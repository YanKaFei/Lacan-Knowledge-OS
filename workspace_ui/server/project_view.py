#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui.server.project_view — Research Project 的产品适配层（4D.5 §9/§10/§50）

职责：
    * 把 project_api 的对象转成 UI 视图（含计数、时间线、referent 状态、revision）；
    * 提供「Research from project question」——**仍然走 MCP → 冻结核心**，
      Project 历史绝不作为 evidence 注入（§12/§13/§44）；
    * 提供「Run → Project」「Explorer → Project」「History → Project」三条接入；
    * 错误映射：revision 冲突 → `WORKSPACE_CONFLICT`（HTTP 409）。

写入永远经 project_api（USER_WORKSPACE）；本模块自己不开文件（契约自检守）。
"""
from __future__ import annotations

import project_api as PA

from . import api as A
from . import config as C

PROJECT_VIEW_VERSION = "project-view/v1"

TABS = ("overview", "questions", "research", "evidence", "notes", "questions_open",
        "hypotheses", "bibliography", "activity")
PRIMARY_TABS = (("overview", "Overview"), ("questions", "Questions"),
                ("research", "Research"), ("evidence", "Evidence"),
                ("notes", "Notes"))


def _err(exc):
    if isinstance(exc, PA.Conflict):
        return {"kind": "error", "code": "WORKSPACE_CONFLICT",
                "title": "This project changed while you were editing it.",
                "body": ("Expected revision %s but the project is at %s. Reload the "
                         "project and re-apply your edit; nothing was written."
                         % (exc.expected, exc.actual)),
                "view": "error", "expected_revision": exc.expected,
                "actual_revision": exc.actual}
    if isinstance(exc, PA.NotFound):
        return {"kind": "error", "code": "NOT_FOUND", "title": "Project not found.",
                "body": str(exc)[:200], "view": "error"}
    if isinstance(exc, PA.Invalid):
        return {"kind": "error", "code": "INVALID_REQUEST",
                "title": "The project request is invalid.", "body": str(exc)[:200],
                "view": "error"}
    raise exc


def project_list(status=None, tag=None, query=None, updated_after=None):
    out = PA.list_projects(status=status, tag=tag, query=query,
                           updated_after=updated_after)
    out["kind"] = "project_list"
    out["view"] = "projects"
    out["filters"] = {"status": status, "tag": tag, "query": query,
                      "updated_after": updated_after}
    return out


def project_detail(project_id, tab="overview"):
    try:
        p = PA.get_project(project_id)
    except PA.ProjectError as exc:
        return _err(exc)
    tab = tab if tab in TABS else "overview"
    runs = PA.list_runs(project_id)
    view = {
        "kind": "project",
        "view": "project",
        "project": p,
        "summary": PA.summary(p),
        "tabs": [{"id": t, "label": l, "primary": True} for t, l in PRIMARY_TABS]
        + [{"id": "questions_open", "label": "Open Questions", "primary": False},
           {"id": "hypotheses", "label": "Hypotheses (user objects)", "primary": False},
           {"id": "bibliography", "label": "Bibliography", "primary": False},
           {"id": "activity", "label": "Activity", "primary": False}],
        "active_tab": tab,
        "runs": runs,
        "verify": PA.verify_project_runs(project_id) if runs else
        {"overall": "VERIFIED", "runs": []},
        "timeline": PA.timeline(project_id),
        "broken_references": p.get("broken_references") or [],
        "counts_are_workspace_counts": True,
        "note": ("Counts on this page are workspace counts, not research quality "
                 "scores. Project content is never evidence."),
    }
    try:
        import obsidian_adapter as OA                                  # noqa: PLC0415
        view["obsidian"] = {"note": PA.store.read_project(project_id).get("obsidian_note"),
                            "mapping": OA.project_note_map().get(project_id),
                            "links": OA.research_links_for_project(p)}
    except Exception as exc:                                           # noqa: BLE001
        view["obsidian"] = {"error": str(exc)[:160]}
    # §11/§33：项目书目三组（reviewed 已挂 / 用户自由输入 / 不可挂接的 candidate）
    try:
        from project_api import bibliography as PB                      # noqa: PLC0415
        view["project_bibliography"] = PB.list_bibliography(project_id)
        view["bibliography_candidates_not_linkable"] = _candidate_ids()
    except Exception as exc:                                           # noqa: BLE001
        view["project_bibliography"] = {"project_bibliography_refs": [],
                                        "legacy_user_supplied_refs": [],
                                        "error": str(exc)[:160]}
        view["bibliography_candidates_not_linkable"] = []
    return view


def _candidate_ids():
    """candidate **不得**挂到项目（§12/§33）——这里只列出为什么不可挂。"""
    try:
        import bibliography as B                                       # noqa: PLC0415
        return [{"bibliographic_id": i["bibliographic_id"],
                 "review_status": i.get("review_status"),
                 "reason": "candidate — needs review before it can be referenced"}
                for i in B.registry.items() if i.get("review_status") != "reviewed"]
    except Exception:                                                  # noqa: BLE001
        return []


def project_add_bibliographic_item(project_id, expected_revision, bibliographic_id,
                                   user_note=None):
    from project_api import bibliography as PB                         # noqa: PLC0415
    try:
        return PB.add_bibliographic_item(project_id, expected_revision, bibliographic_id,
                                         user_note=user_note)
    except PA.ProjectError as exc:
        return _err(exc)


def project_link_legacy_ref(project_id, expected_revision, ref_id, bibliographic_id):
    """显式关联（用户确认的动作）；不迁移、不删除 legacy 记录（§46）。"""
    from project_api import bibliography as PB                         # noqa: PLC0415
    try:
        return PB.link_legacy_ref(project_id, expected_revision, ref_id, bibliographic_id)
    except PA.ProjectError as exc:
        return _err(exc)


def project_create(title, description="", tags=None, questions=None):
    try:
        p = PA.create_project(title, description=description, tags=tags,
                              questions=questions)
    except PA.ProjectError as exc:
        return _err(exc)
    return {"kind": "project_created", "view": "project", "project": PA.get_project(
        p["project_id"])}


def project_update(project_id, expected_revision, **fields):
    try:
        p = PA.update_project(project_id, expected_revision,
                              **{k: v for k, v in fields.items() if v is not None})
    except PA.ProjectError as exc:
        return _err(exc)
    return {"kind": "project_updated", "project": PA.summary(p)}


def project_archive(project_id, expected_revision):
    try:
        p = PA.archive_project(project_id, expected_revision)
    except PA.ProjectError as exc:
        return _err(exc)
    return {"kind": "project_archived", "project": PA.summary(p)}


def project_restore(project_id, expected_revision):
    try:
        p = PA.restore_project(project_id, expected_revision)
    except PA.ProjectError as exc:
        return _err(exc)
    return {"kind": "project_restored", "project": PA.summary(p)}


def project_add(project_id, expected_revision, kind, payload):
    """kind ∈ passage/concept/seminar/term/question/note/open_question/hypothesis/bibliography"""
    try:
        if kind in ("passage", "concept", "seminar", "term"):
            p = PA.add_reference(project_id, expected_revision, kind,
                                 payload.get("id") or payload.get("item_id"),
                                 note=payload.get("note"),
                                 source_context=payload.get("source_context"))
        elif kind == "question":
            p = PA.add_question(project_id, expected_revision, payload.get("text"))
        elif kind == "note":
            p = PA.add_note(project_id, expected_revision, payload.get("text"),
                            title=payload.get("title"))
        elif kind == "open_question":
            p = PA.add_open_question(project_id, expected_revision, payload.get("text"),
                                     origin=payload.get("origin") or "user_created",
                                     run_id=payload.get("run_id"),
                                     limitation=payload.get("limitation"))
        elif kind == "hypothesis":
            p = PA.add_hypothesis(project_id, expected_revision, payload.get("text"),
                                  rationale=payload.get("rationale"))
        elif kind == "bibliography":
            p = PA.add_bibliography_ref(project_id, expected_revision,
                                        payload.get("title"), author=payload.get("author"),
                                        year=payload.get("year"),
                                        source_type=payload.get("source_type"),
                                        identifier=payload.get("identifier"),
                                        url_or_reference=payload.get("url_or_reference"),
                                        user_note=payload.get("user_note"))
        else:
            return {"kind": "error", "code": "INVALID_REQUEST",
                    "title": "Unknown project item kind.", "body": str(kind)[:80]}
    except PA.ProjectError as exc:
        return _err(exc)
    return {"kind": "project_added", "item_kind": kind, "project": PA.summary(p)}


def project_remove(project_id, expected_revision, kind, item_id):
    try:
        if kind in ("passage", "concept", "seminar", "term"):
            p = PA.remove_reference(project_id, expected_revision, kind, item_id)
        elif kind == "note":
            p = PA.remove_note(project_id, expected_revision, item_id)
        elif kind == "bibliography":
            p = PA.remove_bibliography_ref(project_id, expected_revision, item_id)
        else:
            return {"kind": "error", "code": "INVALID_REQUEST",
                    "title": "Unknown project item kind.", "body": str(kind)[:80]}
    except PA.ProjectError as exc:
        return _err(exc)
    return {"kind": "project_removed", "project": PA.summary(p)}


def project_add_run(project_id, expected_revision, view, request_meta=None,
                    project_question_id=None):
    """Research → Project：保存的是 MCP 返回答案的**原样**快照（§75）。"""
    try:
        p, rec = PA.add_research_run(project_id, expected_revision, view,
                                     request_meta=request_meta,
                                     project_question_id=project_question_id)
    except PA.ProjectError as exc:
        return _err(exc)
    return {"kind": "project_run_added", "run_id": rec["run_id"],
            "answer_state": rec["answer_state"],
            "source_answer_hash": rec["source_answer_hash"],
            "citation_ids": rec["citation_ids"],
            "is_abstention": rec["is_abstention"],
            "project": PA.summary(p)}


def project_add_history_run(project_id, expected_revision, file_name):
    """§47：把 4D.2 历史快照加入 Project（**不重新调用 LLM**）。"""
    from . import history as H                                     # noqa: PLC0415
    rec = H.get(file_name)
    if not rec:
        return {"kind": "error", "code": "NOT_FOUND",
                "title": "History item not found.", "body": str(file_name)[:120]}
    view = rec.get("answer") or {}
    meta = rec.get("request") or {}
    return project_add_run(project_id, expected_revision, view,
                           request_meta={"mode": meta.get("mode"),
                                         "provider": meta.get("provider"),
                                         "from_history": file_name},
                           project_question_id=None)


def project_research(project_id, expected_revision, question, mode="scholarly",
                     provider=None, language=None, project_question_id=None,
                     save_history=False, store_run=True):
    """§12/§13：项目内发起研究 —— **新 ResearchRequest → MCP → 冻结核心**。

    Project 的历史/笔记只用于『问题解释』，绝不进入 evidence；
    这里把这句话连同一次真实的 research 调用一起返回，便于审计。
    """
    out = A.research(question, mode=mode, provider=provider, language=language,
                     save_history=save_history)
    view = out.get("view") or {}
    result = {"kind": "project_research", "question": question,
              "answer_state": view.get("state"),
              "view": view,
              "request": {"mode": mode, "provider": provider, "language": language},
              "project_context_role": "question interpretation only — NOT evidence"}
    if store_run and view.get("kind") == "answer":
        stored = project_add_run(project_id, expected_revision, view,
                                 request_meta={"mode": mode, "provider": provider},
                                 project_question_id=project_question_id)
        result["stored"] = stored
    return result


def project_compare(project_id, run_a, run_b):
    out = PA.compare_runs(project_id, run_a, run_b)
    if out is None:
        return {"kind": "error", "code": "NOT_FOUND",
                "title": "Run not found.", "body": "Check the run ids."}
    out["kind"] = "project_run_comparison"
    return out


def project_verify(project_id):
    try:
        return {"kind": "project_verify", **PA.verify_project_runs(project_id)}
    except PA.ProjectError as exc:
        return _err(exc)


def project_search(project_id, query):
    try:
        return {"kind": "project_search",
                **PA.search_project(project_id, query)}
    except PA.ProjectError as exc:
        return _err(exc)


def project_obsidian_sync(project_id):
    """§27–§31：Project Hub 同步（经 4D.3 adapter；用户区永不被覆盖）。"""
    try:
        p = PA.get_project(project_id)
        import obsidian_adapter as OA                                  # noqa: PLC0415
        res = OA.save_project_note(p)
    except PA.ProjectError as exc:
        return _err(exc)
    except Exception as exc:                                           # noqa: BLE001
        return {"kind": "error", "code": "INTERNAL_ERROR",
                "title": "Obsidian project sync failed.", "body": str(exc)[:200]}
    if res.get("note"):
        try:                       # 只登记映射结果；不动任何 scholarly 数据
            PA.store.mutate(project_id, None,
                            lambda doc: (doc.__setitem__("obsidian_note", res["note"])
                                         or True))
        except Exception:                                              # noqa: BLE001
            pass
    return {"kind": "project_obsidian", **res}


def export_manifest(project_id):
    """§37：Project manifest JSON（本阶段只做导出，完整 bundle 留 4D.6）。"""
    try:
        p = PA.get_project(project_id)
    except PA.ProjectError as exc:
        return _err(exc)
    runs = PA.list_runs(project_id)
    manifest = {
        "schema_version": "project-manifest/v1",
        "project_api_version": PA.PROJECT_API_VERSION,
        "project_id": p["project_id"],
        "title": p["title"],
        "status": p["status"],
        "revision": p["revision"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "tags": p.get("tags") or [],
        "counts": PA.summary(p)["counts"],
        "research_runs": [{"run_id": r["run_id"], "created_at": r["created_at"],
                           "answer_state": r["answer_state"],
                           "source_answer_hash": r["source_answer_hash"],
                           "citations": len(r["citation_ids"]),
                           "is_abstention": r["is_abstention"]} for r in runs],
        "verify": PA.verify_project_runs(project_id)["overall"] if runs else "VERIFIED",
        "references": {
            "passages": [x["id"] for x in p.get("saved_passages") or []],
            "concepts": [x["id"] for x in p.get("saved_concepts") or []],
            "seminars": [x["id"] for x in p.get("saved_seminars") or []],
            "terms": [x["id"] for x in p.get("saved_terms") or []],
        },
        "evidence_role": "NOT_EVIDENCE",
        "note": ("This manifest describes a USER_WORKSPACE project. It is not a "
                 "scholarly artifact and cannot substitute for corpus evidence."),
    }
    return {"kind": "project_manifest", "manifest": manifest}
