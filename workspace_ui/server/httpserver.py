#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui.server.httpserver — 4D.2 Workspace HTTP 服务（stdlib，无额外依赖）

路由
────
    GET  /                       → 静态 UI（index.html）
    GET  /static/*               → 静态资源（防目录穿越）
    GET  /api/status             → MCP 连接 + core freeze 状态
    POST /api/research           → {question, mode, provider, language}
    GET  /api/passage            → Evidence Inspector 面板（passage+context+provenance）
    GET  /api/context            → 上下文窗口（可调 ±，上限由服务端夹紧）
    GET  /api/search             → Advanced 简易检索
    GET  /api/history            → 历史列表（lazy）
    GET  /api/history/item       → 单条历史（含答案快照）
    GET  /api/help/content       → Help Center 的编译文档（结构 + i18n key，不含正文）
    GET  /help, /help/<slug>     → 产品 SPA 路由（真实 URL，可分享/可新标签打开）
    GET  /research /explore /projects /bibliography /persons /cases /zotero → SPA 路由
    GET  /api/provider/settings  → 真实 provider 的生效设置（密钥只报"有没有"）
    POST /api/provider/settings  → 保存 model / base_url（**不接受密钥**）
    POST /api/provider/test      → 真发一次极小 chat/completions 的连通性自检
    POST /api/research/job       → 长研究请求的作业化提交（返回 202 + job_id）
    GET  /api/research/job?id=   → 作业进度（只报真实耗时与状态，不编百分比）

安全（§37）：静态路径规范化并限制在 static/ 内；请求体限长；所有错误统一走
ViewModel 的用户文案，**绝不返回 traceback**。
"""
from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import api as A
from . import config as C
import export_system as EX

from . import bibliography as BIB
from . import entities as ENT
from . import explorer as X
from . import export_view as EV
from . import help_view as HV
from . import jobs as JB
from . import project_view as PV
from . import provider_view as PROVIDER
from . import viewmodel as VM


def _safe_static_path(rel):
    """→ 绝对路径（必须落在 static/ 内），否则 None。"""
    raw = unquote(rel or "")
    # 显式拒绝绝对路径与任何 ".." 段（纵深防御；不能只靠 normpath 兜底）
    if raw.startswith("/") or ".." in raw.replace("\\", "/").split("/"):
        return None
    rel = raw.lstrip("/")
    if not rel:
        rel = "index.html"
    p = os.path.normpath(os.path.join(C.STATIC_DIR, rel))
    if not p.startswith(os.path.normpath(C.STATIC_DIR) + os.sep) and p != os.path.normpath(
            os.path.join(C.STATIC_DIR, "index.html")):
        return None
    return p


def _explore_filters(q):
    """→ browse filters（只提取白名单键；值在 browse_api 里再校验一次）。"""
    keys = ("seminar", "session", "lesson", "language", "source_layer",
            "provenance", "text_role", "year_from", "year_to", "concept",
            "formalism")
    return {k: q.get(k) for k in keys if q.get(k) not in (None, "")}


CONTENT_TYPES = {".html": "text/html; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".json": "application/json; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png",
                 ".woff2": "font/woff2", ".map": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "LacanWorkspace/1.0"
    protocol_version = "HTTP/1.1"

    # ── 工具
    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj, ensure_ascii=False))

    def _query(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def log_message(self, fmt, *args):                    # 日志走 stderr，且不噪音化
        if os.environ.get("LACAN_UI_HTTP_LOG") == "1":
            BaseHTTPRequestHandler.log_message(self, fmt, *args)

    # ── Explorer（只读浏览；参数白名单化，非法值显式报错）
    EXPLORE_ROUTES = {
        "/api/explore/availability": lambda q: X.availability(),
        "/api/explore/concepts": lambda q: X.concept_list(
            q.get("query"), q.get("status"), q.get("layer"), q.get("cursor"),
            q.get("limit")),
        "/api/explore/concept": lambda q: X.concept_detail(q.get("id")),
        "/api/explore/graph": lambda q: X.concept_graph_detail(q.get("id")),
        "/api/explore/passages": lambda q: X.passage_search(_explore_filters(q), q.get("cursor"),
                                                            q.get("limit")),
        "/api/explore/passage": lambda q: X.passage_detail(q.get("id"), q.get("before"),
                                                           q.get("after")),
        "/api/explore/context": lambda q: X.context_window(q.get("id"), q.get("before"),
                                                           q.get("after")),
        "/api/explore/sessions": lambda q: X.sessions(q.get("seminar")),
        "/api/explore/session": lambda q: X.session_reading(q.get("id"), q.get("cursor"),
                                                            q.get("limit")),
        "/api/explore/seminars": lambda q: X.seminar_list(q.get("cursor"), q.get("limit"),
                                                          q.get("query"), q.get("year_from"),
                                                          q.get("year_to")),
        "/api/explore/seminar": lambda q: X.seminar_detail(q.get("id")),
        # ── Phase 5B：Person / Case Explorer（只读、分页、只有提及证据）
        "/api/explore/entities/availability": lambda q: ENT.availability(),
        "/api/explore/persons": lambda q: ENT.persons(q.get("cursor"), q.get("limit")),
        "/api/explore/person": lambda q: ENT.person(q.get("id")),
        "/api/explore/cases": lambda q: ENT.cases(q.get("cursor"), q.get("limit")),
        "/api/explore/case": lambda q: ENT.case(q.get("id")),
        "/api/explore/mentions": lambda q: ENT.mentions(q.get("id"), q.get("cursor"),
                                                        q.get("limit")),
        "/api/explore/entity_search": lambda q: ENT.search(q.get("q"), q.get("kind"),
                                                           q.get("cursor"), q.get("limit")),
        # ── Phase 5C：Bibliography Explorer（只读；唯一 CitationRenderer）
        "/api/explore/bibliography": lambda q: BIB.list_items(
            q.get("q"), q.get("author"), q.get("year"), q.get("language"),
            q.get("item_type"), q.get("review_status"), q.get("cursor"),
            q.get("limit")),
        "/api/explore/bibliography_item": lambda q: BIB.item(q.get("id")),
        "/api/explore/bibliography_capabilities": lambda q: BIB.capabilities(
            q.get("id"), q.get("passage_id")),
        "/api/explore/bibliography_citation": lambda q: BIB.citation(
            q.get("id"), q.get("style"), q.get("passage_id")),
        "/api/explore/bibliography_chain": lambda q: BIB.chain(q.get("witness_id")),
        "/api/explore/bibliography_availability": lambda q: BIB.availability(),
        "/api/explore/bibliography_health": lambda q: BIB.registry_health(),
        "/api/explore/citation_availability": lambda q: BIB.citation_availability(
            q.get("id")),
        "/api/explore/bibliography_imports": lambda q: BIB.imported_candidates(
            int(q.get("limit") or 100)),
        "/api/explore/bibliography_conflicts": lambda q: BIB.conflicts(
            int(q.get("limit") or 100)),
        "/api/explore/terminology": lambda q: X.terminology_list(q.get("query"),
                                                                 q.get("cursor"),
                                                                 q.get("limit")),
        "/api/explore/term": lambda q: X.terminology_control() if q.get("control") ==
            "reel_realite" else X.terminology_detail(
                q.get("term"), (q.get("forms") or "").split(",") if q.get("forms") else None),
        "/api/explore/research_requests": lambda q: X.research_requests(),
    }

    def _explore(self, path, q):
        fn = self.EXPLORE_ROUTES.get(path)
        if fn is None:
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INVALID_REQUEST",
                                        "message": "unknown explore route"}}), 404)
        try:
            out = fn(q)
        except ValueError as exc:                      # 白名单/游标/上限类错误
            return self._json({"kind": "error", "code": "INVALID_REQUEST",
                               "title": "The browse request is invalid.",
                               "body": str(exc)[:200], "view": "error"}, 400)
        except Exception as exc:                       # noqa: BLE001
            code = type(exc).__name__
            if code in ("ImportError_", "ValueError") and "/api/bibliography/import" in \
                    str(getattr(self, "path", "")):
                return self._json({"kind": "error", "code": "IMPORT_REJECTED",
                                   "title": "Import rejected",
                                   "body": str(exc)[:300], "view": "error"}, 400)
            if code == "InferenceNotSupported":
                return self._json({"kind": "error",
                                   "code": "INFERENCE_NOT_SUPPORTED",
                                   "title": "This browse layer exposes mention evidence only.",
                                   "body": str(exc)[:300],
                                   "view": "error"}, 400)
            if code == "BrowseUnavailable":
                return self._json({"kind": "error", "code": "INDEX_UNAVAILABLE",
                                   "title": C.ERROR_UX["INDEX_UNAVAILABLE"]["title"],
                                   "body": C.ERROR_UX["INDEX_UNAVAILABLE"]["body"],
                                   "view": "error"}, 503)
            raise
        if out is None:
            return self._json({"kind": "error", "code": "NOT_FOUND",
                               "title": "Not found.",
                               "body": "That id does not exist in the browse layer.",
                               "view": "error"}, 404)
        return self._json(out)

    # ── GET
    def do_GET(self):                                     # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/status":
                return self._json(A.status())
            if path == "/api/passage":
                q = self._query()
                if not q.get("id"):
                    return self._json(VM.error_view(
                        {"ok": False, "error": {"code": "INVALID_REQUEST",
                                                "message": "missing passage id"}}), 400)
                return self._json(A.passage_panel(q["id"],
                                                  q.get("before", C.DEFAULT_CONTEXT),
                                                  q.get("after", C.DEFAULT_CONTEXT),
                                                  q.get("span")))
            if path == "/api/context":
                q = self._query()
                if not q.get("id"):
                    return self._json(VM.error_view(
                        {"ok": False, "error": {"code": "INVALID_REQUEST",
                                                "message": "missing passage id"}}), 400)
                return self._json(A.context_window(q["id"], q.get("before"),
                                                   q.get("after")))
            if path == "/api/search":
                q = self._query()
                if not q.get("q"):
                    return self._json({"kind": "search", "results": [], "n": 0})
                try:
                    limit = int(q.get("limit", "10"))
                except ValueError:
                    limit = 10
                return self._json(A.search(q["q"], max(1, min(limit, 50))))
            if path == "/api/obsidian/status":
                return self._json(A.obsidian_status())
            if path == "/api/obsidian/list":
                return self._json(A.obsidian_list())
            if path.startswith("/api/explore/"):
                return self._explore(path, self._query())
            if path.startswith("/api/export"):
                return self._export(path, self._query())
            if path.startswith("/api/projects"):
                return self._projects(path, self._query())
            if path == "/api/history":
                q = self._query()
                return self._json(A.history_list(limit=int(q.get("limit", "50")),
                                                 offset=int(q.get("offset", "0"))))
            if path == "/api/history/item":
                q = self._query()
                return self._json(A.history_get(q.get("file", "")))
            if path == "/api/help/content":
                return self._json(HV.content())
            if path == "/api/provider/settings":
                return self._json(PROVIDER.effective())
            if path == "/api/research/job":
                q = self._query()
                return self._json(JB.progress(q.get("id", ""),
                                              include_result=bool(q.get("result"))))
            # ── 产品 SPA 路由（P5D-005）：真实 URL，交给前端 router 解释。
            #    * 必须在所有 /api 与 /static 之后，**不得**吞掉未知 API 路径；
            #    * 不是"通配回退"：只有 help_view 声明的产品路由才走这里。
            if path.startswith("/api/"):
                return self._json(VM.error_view(
                    {"ok": False, "error": {"code": "INVALID_REQUEST",
                                            "message": "unknown route"}}), 404)
            if HV.spa_route_ok(path):
                return self._static("index.html")
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INVALID_REQUEST",
                                        "message": "unknown route"}}), 404)
        except Exception as exc:                          # noqa: BLE001
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                        "message": type(exc).__name__,
                                        "detail": {"where": "GET %s" % path}}}), 500)

    # ── POST
    def do_POST(self):                                    # noqa: N802
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > C.MAX_PAYLOAD_BYTES:
                return self._json(VM.error_view(
                    {"ok": False, "error": {"code": "INVALID_REQUEST",
                                            "message": "payload too large"}}), 413)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:                             # noqa: BLE001
                return self._json(VM.error_view(
                    {"ok": False, "error": {"code": "INVALID_REQUEST",
                                            "message": "body is not JSON"}}), 400)
            if path == "/api/obsidian/save_research":
                return self._json(A.obsidian_save_research(
                    body.get("question"), body.get("mode") or "scholarly",
                    body.get("provider"), body.get("language")))
            if path == "/api/obsidian/save_passage":
                pid = body.get("passage_id")
                if not pid:
                    return self._json(VM.error_view(
                        {"ok": False, "error": {"code": "INVALID_REQUEST",
                                                "message": "missing passage_id"}}), 400)
                return self._json(A.obsidian_save_passage(pid))
            if path.startswith("/api/export"):
                return self._export_post(path, body)
            if path.startswith("/api/projects/"):
                return self._projects_post(path, body)
            if path == "/api/explore/obsidian_create":
                et = body.get("entity_type")
                eid = body.get("entity_id")
                if et not in ("concept", "seminar", "passage") or not eid:
                    return self._json(VM.error_view(
                        {"ok": False, "error": {"code": "INVALID_REQUEST",
                                                "message": "entity_type/entity_id required"}}),
                        400)
                return self._json(X.obsidian_create(et, eid))
            if path == "/api/bibliography/import":
                body = json.loads(raw or "{}")
                mode = body.get("mode") or "preview"
                text = body.get("text") or ""
                source = body.get("source") or "csl-json"
                if len(text.encode("utf-8")) > 8 * 1024 * 1024:
                    return self._json({"kind": "error", "code": "IMPORT_TOO_LARGE",
                                       "title": "Import rejected",
                                       "body": "file exceeds the 8 MiB import cap",
                                       "view": "error"}, 413)
                if mode == "commit":
                    return self._json(BIB.import_commit(text, source))
                return self._json(BIB.import_preview(text, source))
            if path == "/api/research":
                return self._json(A.research(body.get("question"),
                                             body.get("mode") or "scholarly",
                                             body.get("provider"),
                                             body.get("language"),
                                             save_history=bool(
                                                 body.get("save_history", True)),
                                             use_cache=not bool(body.get("fresh"))))
            if path == "/api/research/job":
                # 长研究请求（真实 LLM）走作业：HTTP 不再挂 60s+ 无反馈。
                q_text = (body.get("question") or "").strip()
                prov = body.get("provider")
                mode = body.get("mode") or "scholarly"
                lang = body.get("language")
                fresh = bool(body.get("fresh"))
                jid = JB.start(q_text, lambda: A.research(
                    q_text, mode, prov, lang, save_history=True, use_cache=not fresh))
                return self._json({"kind": "job", "view": "job", "job_id": jid,
                                   "status": "RUNNING", "elapsed_ms": 0}, 202)
            if path == "/api/provider/settings":
                ok, out = PROVIDER.save(body)
                return self._json(out, 200 if ok else 400)
            if path == "/api/provider/test":
                return self._json(PROVIDER.test_connection(body))
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INVALID_REQUEST",
                                        "message": "unknown route"}}), 404)
        except Exception as exc:                          # noqa: BLE001
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                        "message": type(exc).__name__,
                                        "detail": {"where": "POST %s" % path}}}), 500)

    # ── Export（4D.6）：只读 source；只写 _workspace/exports/**
    EXPORT_GET = {
        "/api/export/menu": lambda q: EV.menus(),
        "/api/export/citation": lambda q: EV.citation(q.get("id"), style=q.get("style")),
        "/api/export/verify": lambda q: EV.verify(q.get("path"), q.get("root") or "default"),
        "/api/export/list": lambda q: {"kind": "export_list",
                                       **EX.list_exports(q.get("root") or "default")},
        "/api/export/audit": lambda q: {"kind": "export_audit",
                                        "items": EX.read_audit(int(q.get("limit") or 50))},
    }

    def _export(self, path, q):
        fn = self.EXPORT_GET.get(path)
        if fn is None:
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INVALID_REQUEST",
                                        "message": "unknown export route"}}), 404)
        try:
            out = fn(q)
        except EX.ExportError as exc:
            return self._json(EV._err(exc), exc.as_dict() and 400)  # noqa: SLF001
        except Exception as exc:                               # noqa: BLE001
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                        "message": type(exc).__name__,
                                        "detail": {"where": "GET %s" % path}}}), 500)
        return self._json(out)

    def _export_post(self, path, body):
        try:
            if path == "/api/export/preview":
                doc = EV.build(body.get("source_type"), body.get("source_id"),
                               view=body.get("view"), project_id=body.get("project_id"),
                               run_id=body.get("run_id"), file_name=body.get("file"),
                               include_context=body.get("include_context") or 0,
                               options=body.get("options"),
                               include_audit=bool(body.get("include_audit")))
                return self._json(EV.preview(doc, body.get("format") or "markdown"))
            if path == "/api/export/run":
                doc = EV.build(body.get("source_type"), body.get("source_id"),
                               view=body.get("view"), project_id=body.get("project_id"),
                               run_id=body.get("run_id"), file_name=body.get("file"),
                               include_context=body.get("include_context") or 0,
                               options=body.get("options"),
                               include_audit=bool(body.get("include_audit")))
                return self._json(EV.run(doc, body.get("format") or "markdown",
                                         root=body.get("root") or "default"))
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INVALID_REQUEST",
                                        "message": "unknown export route"}}), 404)
        except EX.ExportError as exc:
            out = EV._err(exc)                                  # noqa: SLF001
            return self._json(out, out.get("status_hint") or 400)
        except Exception as exc:                               # noqa: BLE001
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                        "message": type(exc).__name__,
                                        "detail": {"where": "POST %s" % path}}}), 500)

    # ── Projects（Research Project；写入只经 project_api → USER_WORKSPACE）
    PROJECTS_GET = {
        "/api/projects": lambda q: PV.project_list(
            q.get("status"), q.get("tag"), q.get("query"), q.get("updated_after")),
        "/api/projects/detail": lambda q: PV.project_detail(q.get("id"),
                                                            q.get("tab") or "overview"),
        "/api/projects/verify": lambda q: PV.project_verify(q.get("id")),
        "/api/projects/search": lambda q: PV.project_search(q.get("id"), q.get("query")),
        "/api/projects/compare": lambda q: PV.project_compare(q.get("id"), q.get("a"),
                                                              q.get("b")),
        "/api/projects/manifest": lambda q: PV.export_manifest(q.get("id")),
    }

    def _projects(self, path, q):
        fn = self.PROJECTS_GET.get(path)
        if fn is None:
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INVALID_REQUEST",
                                        "message": "unknown project route"}}), 404)
        try:
            out = fn(q)
        except Exception as exc:                           # noqa: BLE001
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                        "message": type(exc).__name__,
                                        "detail": {"where": "GET %s" % path}}}), 500)
        if out is None:
            return self._json({"kind": "error", "code": "NOT_FOUND",
                               "title": "Project not found.", "view": "error"}, 404)
        status = 409 if out.get("code") == "WORKSPACE_CONFLICT" else (
            400 if out.get("kind") == "error" else 200)
        return self._json(out, status)

    def _projects_post(self, path, body):
        rid = body.get("project_id")
        rev = body.get("expected_revision")
        try:
            if path == "/api/projects/create":
                out = PV.project_create(body.get("title"), body.get("description") or "",
                                        body.get("tags") or [], body.get("questions") or [])
            elif path == "/api/projects/update":
                out = PV.project_update(rid, rev, title=body.get("title"),
                                        description=body.get("description"),
                                        tags=body.get("tags"), status=body.get("status"))
            elif path == "/api/projects/archive":
                out = PV.project_archive(rid, rev)
            elif path == "/api/projects/restore":
                out = PV.project_restore(rid, rev)
            elif path == "/api/projects/add":
                out = PV.project_add(rid, rev, body.get("kind"), body.get("payload") or {})
            elif path == "/api/projects/remove":
                out = PV.project_remove(rid, rev, body.get("kind"), body.get("item_id"))
            elif path == "/api/projects/add_bibliographic_item":
                out = PV.project_add_bibliographic_item(
                    rid, rev, body.get("bibliographic_id"), body.get("user_note"))
            elif path == "/api/projects/link_legacy_ref":
                out = PV.project_link_legacy_ref(
                    rid, rev, body.get("ref_id"), body.get("bibliographic_id"))
            elif path == "/api/projects/add_run":
                out = PV.project_add_run(rid, rev, body.get("view") or {},
                                         body.get("request_meta"),
                                         body.get("project_question_id"))
            elif path == "/api/projects/add_history_run":
                out = PV.project_add_history_run(rid, rev, body.get("file"))
            elif path == "/api/projects/research":
                out = PV.project_research(rid, rev, body.get("question"),
                                          body.get("mode") or "scholarly",
                                          body.get("provider"), body.get("language"),
                                          body.get("project_question_id"),
                                          store_run=bool(body.get("store_run", True)))
            elif path == "/api/projects/obsidian_sync":
                out = PV.project_obsidian_sync(rid)
            else:
                return self._json(VM.error_view(
                    {"ok": False, "error": {"code": "INVALID_REQUEST",
                                            "message": "unknown project route"}}), 404)
        except Exception as exc:                           # noqa: BLE001
            return self._json(VM.error_view(
                {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                        "message": type(exc).__name__,
                                        "detail": {"where": "POST %s" % path}}}), 500)
        status = 409 if out.get("code") == "WORKSPACE_CONFLICT" else (
            400 if out.get("kind") == "error" else 200)
        return self._json(out, status)

    # ── 静态
    def _static(self, rel):
        p = _safe_static_path(rel)
        if p is None or not os.path.isfile(p):
            return self._send(404, "not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(p)[1].lower()
        with open(p, "rb") as f:
            self._send(200, f.read(), CONTENT_TYPES.get(ext, "application/octet-stream"))


def make_server(host=None, port=None):
    host = host or C.DEFAULT_HOST
    port = C.DEFAULT_PORT if port is None else port
    # ★ 启动即应用持久化的 provider 设置（只写 model / base_url，不碰密钥），
    #    这样 MCP 子进程 spawn 时就能继承；失败不影响服务启动。
    try:
        PROVIDER.apply_persisted()
    except Exception as exc:                                              # noqa: BLE001
        print("provider settings not applied: %s" % type(exc).__name__, flush=True)
    return ThreadingHTTPServer((host, port), Handler)


def serve_forever(host=None, port=None):
    srv = make_server(host, port)
    print("Lacan Research Workspace → http://%s:%d" % srv.server_address[:2],
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
