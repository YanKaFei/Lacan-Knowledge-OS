#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui.server.export_view — Export 的产品适配层（4D.6 §50–§55）

职责：
    * 把 ExportDocument 变成 UI 可直接用的预览（**预览只能是 ExportDocument 的渲染**，
      不允许「临时再生成一份 summary」，§55）；
    * 提供 citation formatter 的**唯一入口**（前端不得自己拼字符串，§54）；
    * 落盘一律经 `export_system.policy`（只写 `_workspace/exports/**`）。
"""
from __future__ import annotations

import os

import export_system as EX

from . import config as C

EXPORT_VIEW_VERSION = "export-view/v1"

FORMAT_LABELS = {"markdown": "Markdown", "json": "JSON", "html": "HTML",
                 "bundle": "Research Bundle"}
EXT = {"markdown": ".md", "json": ".json", "html": ".html"}


def _err(exc):
    if isinstance(exc, EX.ExportError):
        status_hint = {"BIBLIOGRAPHIC_METADATA_INCOMPLETE": 400,
                       "UNSUPPORTED_FORMAT": 400,
                       "EXPORT_POLICY_DENIED": 403,
                       "EXPORT_SOURCE_NOT_FOUND": 404,
                       "EXPORT_SOURCE_MODIFIED": 409,
                       "BROKEN_REFERENCE": 409,
                       "SCHEMA_VALIDATION_FAILED": 400}.get(exc.code, 500)
        return {"kind": "error", "code": exc.code, "title": exc.message,
                "body": str(exc.detail)[:300], "view": "error",
                "status_hint": status_hint}
    return {"kind": "error", "code": "EXPORT_WRITE_FAILED",
            "title": "Export failed.", "body": str(exc)[:300], "view": "error",
            "status_hint": 500}


def menus():
    """UI 菜单只显示**已实现**的格式（§50）。"""
    return {"kind": "export_menu",
            "formats": [{"id": f, "label": FORMAT_LABELS[f]} for f in EX.FORMATS],
            "citation_styles": [
                {"id": s, "label": s, "available": True} for s in EX.INTERNAL_STYLES]
            + [{"id": s, "label": s, "available": False,
                "reason": "requires complete bibliographic metadata"}
               for s in EX.BIBLIOGRAPHIC_STYLES],
            "note": ("Bibliographic styles are advertised but only enabled when the "
                     "metadata really exists.")}


# ─────────────────────────────────────────────────────────── 构造
def build(source_type, source_id=None, *, view=None, project_id=None, run_id=None,
          file_name=None, include_context=0, options=None, include_audit=False):
    opts = dict(options or {})
    if include_context:
        opts["include_context"] = int(include_context)
    # ★ Phase 5A §46：Audit Bundle 需要显式 opt-in；**标准导出默认不含**审计内容。
    if include_audit:
        opts["include_audit"] = True
    if source_type in ("research_run", "final_scholarly_answer", "answer"):
        if view is None:
            raise EX.ExportError("EXPORT_SOURCE_NOT_FOUND",
                                 "an answer view is required for this source type")
        return EX.build_from_answer(view, source_type="research_run",
                                    source_id=source_id, export_options=opts)
    if source_type == "research_note":
        return EX.build_from_history(file_name or source_id, export_options=opts)
    if source_type == "saved_passage":
        return EX.build_from_passage(source_id, include_context=include_context,
                                     export_options=opts)
    if source_type == "research_project":
        if run_id:
            return EX.build_from_project_run(project_id or source_id, run_id,
                                             export_options=opts)
        return EX.build_project_summary(project_id or source_id, export_options=opts)
    raise EX.ExportError("SCHEMA_VALIDATION_FAILED",
                         "unsupported source_type: %r" % source_type,
                         {"allowed": list(EX.SOURCE_TYPES)})


def preview(doc, fmt="markdown"):
    """→ 预览内容（严格来自 ExportDocument）。"""
    fmt = fmt or "markdown"
    if fmt == "markdown":
        text = EX.markdown.render(doc)
    elif fmt == "json":
        text = EX.json_export.render(doc)
    elif fmt == "html":
        text = EX.html_export.render(doc)
    elif fmt == "bundle":
        files, counts = EX.bundle.build_files(
            doc, include_context=int((doc.get("export_options") or {}).get(
                "include_context") or 0))
        text = "\n".join("--- %s (%d bytes) ---" % (rel, len(blob))
                         for rel, blob in files)
        return {"kind": "export_preview", "format": fmt, "text": text,
                "files": [{"path": rel, "bytes": len(blob)} for rel, blob in files],
                "counts": counts, "document": _slim(doc),
                "document_payload_hash": doc.get("export_payload_hash")}
    else:
        raise EX.ExportError("UNSUPPORTED_FORMAT", "unsupported format: %r" % fmt,
                             {"allowed": list(EX.FORMATS)})
    return {"kind": "export_preview", "format": fmt, "text": text,
            "bytes": len(text.encode("utf-8")), "document": _slim(doc),
            "document_payload_hash": doc.get("export_payload_hash")}


def _slim(doc):
    """给 UI 的 ExportDocument 摘要（完整对象仍可经 JSON 导出）。"""
    return {"schema_version": doc.get("schema_version"),
            "export_id": doc.get("export_id"),
            "export_type": doc.get("export_type"),
            "source_type": doc.get("source_type"),
            "source_id": doc.get("source_id"),
            "title": doc.get("title"),
            "question": doc.get("question"),
            "answer_state": doc.get("answer_state"),
            "evidence_role": doc.get("evidence_role"),
            "citation_count": len(doc.get("citations") or []),
            "claim_count": len(doc.get("claims") or []),
            "limitation_count": len(doc.get("limitations") or []),
            "is_abstention": bool(doc.get("abstention")),
            "export_payload_hash": doc.get("export_payload_hash"),
            "content_hash": doc.get("content_hash"),
            "source_answer_hash": doc.get("source_answer_hash"),
            "snapshot_integrity": doc.get("snapshot_integrity")}


# ─────────────────────────────────────────────────────────── 落盘
def run(doc, fmt="markdown", *, root="default"):
    """执行一次导出；返回路径 + manifest（bundle 走 bundle 流程）。"""
    fmt = fmt or "markdown"
    if fmt == "bundle":
        opts_run = dict(doc.get("export_options") or {})
        out = EX.build_bundle(doc, include_context=int(opts_run.get("include_context") or 0),
                              root=root, include_audit=bool(opts_run.get("include_audit")),
                              audit=opts_run.get("audit_payload"))
        return {"kind": "export_result", **out}

    if fmt == "markdown":
        text = EX.markdown.render(doc)
    elif fmt == "json":
        text = EX.json_export.render(doc)
    elif fmt == "html":
        text = EX.html_export.render(doc)
    else:
        raise EX.ExportError("UNSUPPORTED_FORMAT", "unsupported format: %r" % fmt,
                             {"allowed": list(EX.FORMATS)})
    root_dir = EX.export_root(root)
    name = "%s%s" % (EX.safe_name(doc.get("export_id")), EXT[fmt])
    path = os.path.join(root_dir, name)
    try:
        EX.policy.write_file(path, text)
    except Exception as exc:                                              # noqa: BLE001
        EX.audit({"export_id": doc.get("export_id"), "source_type": doc.get("source_type"),
                  "source_id": doc.get("source_id"), "format": fmt, "success": False,
                  "error_code": "EXPORT_WRITE_FAILED", "export_root": root})
        raise _err(exc) if not isinstance(exc, EX.ExportError) else exc
    EX.audit({"export_id": doc.get("export_id"), "source_type": doc.get("source_type"),
              "source_id": doc.get("source_id"), "format": fmt, "success": True,
              "file_count": 1, "bytes": len(text.encode("utf-8")), "export_root": root})
    return {"ok": True, "kind": "export_result", "format": fmt,
            "file": os.path.relpath(path, EX.policy.VAULT),
            "bytes": len(text.encode("utf-8")),
            "export_payload_hash": doc.get("export_payload_hash"),
            "content_hash": doc.get("content_hash"),
            "document": _slim(doc)}


# ─────────────────────────────────────────────────────────── citation / 校验
def citation(passage_id, *, style=None, bibliographic=None):
    """§53/§54：citation 只能由 formatter 生成（前端不得自己拼）。"""
    import browse_api as B                                                # noqa: PLC0415
    p = B.get_passage_view(passage_id)
    if p is None:
        return {"kind": "error", "code": "EXPORT_SOURCE_NOT_FOUND",
                "title": "Passage not found.", "body": str(passage_id)[:120]}
    sem_key = (p.get("seminar") or "").replace("seminar.", "")
    year = None
    try:
        year = (B.store.seminars_index().get(p.get("seminar")) or {}).get("year_from")
    except Exception:                                                     # noqa: BLE001
        pass
    meta = {"seminar_key": sem_key, "seminar": p.get("seminar"),
            "session": p.get("session"), "language": p.get("language"),
            "source_layer": p.get("source_layer"), "witness": p.get("witness"),
            "provenance_status": p.get("provenance_status"), "year": year,
            "position": passage_id.rsplit(".", 1)[-1]}
    rec = EX.citation_record(passage_id, meta=meta, bibliographic=bibliographic)
    out = {"kind": "citation", "record": rec,
           "styles": [{"id": s, "label": s, "text": rec[
               {"internal-short": "internal_short", "internal-full": "internal_full",
                "provenance": "provenance"}[s]],
               "available": True} for s in EX.INTERNAL_STYLES]}
    for s in EX.BIBLIOGRAPHIC_STYLES:
        avail = bool(rec["capabilities"].get(s))
        item = {"id": s, "label": s, "available": avail,
                "text": None, "reason": None}
        if avail:
            try:
                item["text"] = EX.render_citation(rec, s)
            except EX.ExportError as exc:
                item["available"] = False
                item["reason"] = exc.code
        else:
            item["reason"] = "BIBLIOGRAPHIC_METADATA_INCOMPLETE"
        out["styles"].append(item)
    if style:
        out["selected"] = EX.render_citation(rec, style)
    return out


def verify(rel_path, root="default"):
    try:
        p = EX.resolve_export_path(rel_path, root)
    except EX.ExportError as exc:
        return _err(exc)
    if not os.path.exists(p):
        return {"kind": "error", "code": "EXPORT_SOURCE_NOT_FOUND",
                "title": "Export not found.", "body": rel_path}
    out = EX.verify_bundle(p)
    out["kind"] = "export_verify"
    out["path"] = rel_path
    return out
