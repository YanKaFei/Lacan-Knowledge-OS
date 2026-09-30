#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.builders — 把 source object 转成 ExportDocument（4D.6 §3/§7–§12/§37–§43）

支持的 source：
    final_scholarly_answer / research_run（4D.2 历史快照、4D.5 project run）
    research_project（§10 两种模式：summary / research bundle）
    saved_passage（§23/§27）

铁律：
    * **只搬运，不重写**：sections / claims / citations / limitations / abstention
      逐字复制；§6 的身份断言由 `model.assert_identity` 守住；
    * 用户内容（notes / hypotheses / open questions / bibliography）放在 `user_blocks`，
      并在渲染时**分区**显示（§39/§40/§41/§42）；
    * 缺 passage → `BROKEN_REFERENCE`（§65），不静默删 citation。
"""
from __future__ import annotations

import os

from . import citations as C
from . import provenance as PV
from .model import (ABSTENTION_TITLE, ExportError, finalize_document, make_document,
                    sha256_text)

ADAPTER_FALLBACK = "workspace"


# ─────────────────────────────────────────────────────────── 答案视图
def _advanced(view):
    return (view or {}).get("advanced") or {}


def _passage_meta(passage_id):
    """→ citation 需要的语义元数据（读 canonical store；缺就 None，不猜）。"""
    import browse_api as B                                                # noqa: PLC0415
    p = B.get_passage_view(passage_id)
    if not p:
        return None, None
    sem_key = (p.get("seminar") or "").replace("seminar.", "")
    year = None
    try:
        s = B.store.seminars_index().get(p.get("seminar"))
        year = (s or {}).get("year_from")
    except Exception:                                                     # noqa: BLE001
        year = None
    meta = {"seminar_key": sem_key, "seminar": p.get("seminar"),
            "session": p.get("session"), "language": p.get("language"),
            "source_layer": p.get("source_layer"), "witness": p.get("witness"),
            "provenance_status": p.get("provenance_status"), "year": year,
            "position": (passage_id or "").rsplit(".", 1)[-1]}
    return p, meta


def build_citation_records(view, *, bibliographic=None):
    """→ (records, broken)。缺 passage 的 citation 进 broken（§65），不删。"""
    records, broken = [], []
    for c in (view or {}).get("citations") or []:
        pid = c.get("passage_id")
        passage, meta = _passage_meta(pid)
        if passage is None:
            broken.append({"passage_id": pid, "claim_id": c.get("claim_id"),
                           "error": "BROKEN_REFERENCE"})
            continue
        meta["source_layer"] = meta.get("source_layer") or c.get("source_layer")
        rec = C.citation_record(pid, meta=meta, quoted_span=c.get("quoted_span"),
                                claim_id=c.get("claim_id"),
                                bibliographic=bibliographic)
        rec["citation_status"] = c.get("citation_status")
        rec["label"] = c.get("label")
        records.append(rec)
    return records, broken


def _sections(view, include_audit=False):
    """答案段落**逐字**搬运（不改写任何文本）。

    Phase 5A（P5A-001 / §47）呈现策略变更：
      * **Standard 导出** = 用户可见面（学术内容 + 学术限制）；
        分类为 AUDIT_DIAGNOSTIC 的段落（校验器 reject 日志、验证计量摘要）**不进**标准导出；
      * **Audit Bundle**（`include_audit=True`）= 把那些段落原样带回（另存 audit/ 下），
        审计内容 **100% 保留**，只是不再混进用户可见正文。
    `internal` 标记仍原样写在文档里，便于审计者识别。
    """
    out = []
    for s in (view or {}).get("sections") or []:
        internal = bool(s.get("internal"))
        classification = s.get("classification")
        is_audit = internal or classification == "AUDIT_DIAGNOSTIC"
        if is_audit and not include_audit:
            continue
        out.append({"label": s.get("label"), "text": s.get("text"),
                    "internal": internal})
    return out


def _claims(view):
    out = []
    for c in (view or {}).get("claims") or []:
        out.append({"claim_id": c.get("claim_id"), "claim_text": c.get("claim_text"),
                    "claim_type": c.get("claim_type"),
                    "epistemic_label": c.get("epistemic_label"),
                    "epistemic_status": c.get("epistemic_status"),
                    "evidence_ids": list(c.get("evidence_ids") or [])})
    return out


def _abstention(view):
    if not (view or {}).get("is_abstention"):
        return None
    ab = dict(view.get("abstention") or {})
    ab.setdefault("title", ABSTENTION_TITLE)
    ab["is_abstention"] = True
    return ab


def build_from_answer(view, *, source_type="research_run", source_id=None,
                      title=None, bibliographic=None, export_options=None,
                      snapshot_integrity=None, source_snapshot_hash=None,
                      user_blocks=None, evidence_role_override=None,
                      from_history=None):
    """FinalScholarlyAnswer（或已存快照视图）→ ExportDocument。"""
    # ★ Phase 5A：Audit Bundle 的审计载荷**从 view 取**（viewmodel/audit_view 已算好），
    #   这样 HTTP 层只需开关 `include_audit`，不必自己重组诊断。
    if (export_options or {}).get("include_audit") and "audit_payload" not in (export_options or {}):
        export_options = dict(export_options or {})
        export_options["audit_payload"] = view.get("audit") or {}
    if not isinstance(view, dict) or view.get("kind") not in (None, "answer"):
        raise ExportError("SCHEMA_VALIDATION_FAILED",
                          "only a scholarly answer view can be exported",
                          {"got": type(view).__name__})
    adv = _advanced(view)
    records, broken = build_citation_records(view, bibliographic=bibliographic)
    if broken:
        raise ExportError("BROKEN_REFERENCE",
                          "%d citation(s) point to a passage that does not exist"
                          % len(broken), {"broken": broken})
    question = view.get("question") or ""
    doc = make_document(
        export_type=source_type,
        source_type=source_type,
        source_id=source_id or adv.get("request_id") or sha256_text(question)[:12],
        title=title or ("Research: %s" % (question[:80] or "untitled")),
        created_at=PV.now_iso(),
        question=question,
        answer_state=view.get("state"),
        answer_state_label=view.get("state_label"),
        task_type=view.get("task_type"),
        sections=_sections(view, include_audit=bool((export_options or {}).get("include_audit"))),
        claims=_claims(view),
        citations=records,
        limitations=list(view.get("limitations") or []),
        abstention=_abstention(view),
        provenance=PV.provenance_summary(view, citations=records),
        bibliographic_metadata=(bibliographic or {}),
        source_answer_hash=PV.answer_hash(view),
        source_snapshot_hash=source_snapshot_hash,
        snapshot_integrity=snapshot_integrity,
        core_freeze_version=adv.get("core_freeze_version"),
        product_interface_version=adv.get("workspace_version"),
        export_options=export_options or {},
        extra_blocks=user_blocks or {},
        notes=([{"kind": "history_source", "file": from_history}] if from_history else []),
    )
    doc["task_type_advanced"] = {"request_id": adv.get("request_id"),
                                 "provider": adv.get("provider"),
                                 "mcp_version": adv.get("mcp_version"),
                                 "answer_schema_version": adv.get("answer_schema_version")}
    doc["source_kind"] = "final_scholarly_answer"
    if evidence_role_override:
        doc["evidence_role"] = evidence_role_override
    doc["warnings"] = list(view.get("warnings") or [])
    doc["claim_bindings"] = C.citation_bindings(doc["claims"], doc["citations"])
    return finalize_document(doc)


# ─────────────────────────────────────────────────────────── 历史快照（§37）
def build_from_history(file_name, *, bibliographic=None, export_options=None):
    """4D.2 历史里的旧 run：直接导出快照，**禁止重新执行 research**。"""
    import json                                                           # noqa: PLC0415
    from workspace_ui.server import config as UIC                         # noqa: PLC0415
    path = os.path.join(UIC.HISTORY_DIR, os.path.basename(file_name or ""))
    if not os.path.isfile(path):
        raise ExportError("EXPORT_SOURCE_NOT_FOUND", "history item not found",
                          {"file": file_name})
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    view = rec.get("answer") or {}
    return build_from_answer(view, source_type="research_note",
                             source_id=rec.get("request_id") or file_name,
                             title="Research (history): %s"
                                   % ((rec.get("request") or {}).get("question") or "")[:70],
                             bibliographic=bibliographic,
                             export_options=export_options,
                             from_history=os.path.basename(file_name))


# ─────────────────────────────────────────────────────────── Project run（§38/§75）
def build_from_project_run(project_id, run_id, *, bibliographic=None,
                           export_options=None):
    """4D.5 immutable run：用快照导出，并**验证 snapshot_hash**。"""
    import project_api as PA                                              # noqa: PLC0415
    try:
        rec = PA.get_run(project_id, run_id)
    except PA.ProjectError as exc:
        raise ExportError("EXPORT_SOURCE_NOT_FOUND",
                          "project run source unavailable: %s" % exc,
                          {"project_id": project_id, "run_id": run_id}) from exc
    if not rec:
        raise ExportError("EXPORT_SOURCE_NOT_FOUND", "project run not found",
                          {"project_id": project_id, "run_id": run_id})
    view = rec.get("snapshot") or {}
    check = PA.verify_project_runs(project_id)
    status = next((r["status"] for r in check["runs"] if r["run_id"] == run_id),
                  "UNKNOWN")
    if status == "MODIFIED" and not (export_options or {}).get("allow_modified"):
        raise ExportError("EXPORT_SOURCE_MODIFIED",
                          "the stored snapshot no longer matches its hash; "
                          "export requires explicit confirmation",
                          {"run_id": run_id, "status": status})
    doc = build_from_answer(
        view, source_type="research_run", source_id=run_id,
        title="Project run: %s" % (rec.get("question") or "")[:70],
        bibliographic=bibliographic, export_options=export_options,
        snapshot_integrity=status, source_snapshot_hash=rec.get("snapshot_hash"))
    doc["project"] = {"project_id": project_id}
    return doc


# ─────────────────────────────────────────────────────────── Saved passage（§27）
def build_from_passage(passage_id, *, include_context=None, bibliographic=None,
                       export_options=None, kind="saved_passage"):
    import browse_api as B                                                # noqa: PLC0415
    try:
        p = B.get_passage_view(passage_id)
    except Exception as exc:                                              # noqa: BLE001
        raise ExportError("EXPORT_SOURCE_NOT_FOUND",
                          "passage source unavailable: %s" % exc,
                          {"passage_id": passage_id}) from exc
    if not p:
        raise ExportError("EXPORT_SOURCE_NOT_FOUND", "passage not found",
                          {"passage_id": passage_id})
    passage, meta = _passage_meta(passage_id)
    record = C.citation_record(passage_id, meta=meta, bibliographic=bibliographic)
    trace = B.source_trace(passage_id) or {}
    ctx = []
    if include_context:
        ctx = (B.context(passage_id, include_context, include_context) or {}).get(
            "items") or []
    doc = make_document(
        export_type=kind, source_type=kind, source_id=passage_id,
        title="Passage %s" % C.short_citation(passage_id),
        created_at=PV.now_iso(),
        question=None, answer_state=None,
        sections=[{"label": "Passage", "text": passage.get("text")}],
        claims=[], citations=[record], limitations=[],
        abstention=None,
        provenance=PV.provenance_summary(None, passage=passage, trace=trace,
                                        citations=[record]),
        bibliographic_metadata=(bibliographic or {}),
        source_answer_hash=None,
        export_options=dict(export_options or {},
                            include_context=bool(include_context)),
    )
    doc["passage"] = {"passage_id": passage_id, "text": passage.get("text"),
                      "seminar": passage.get("seminar"), "session": passage.get("session"),
                      "language": passage.get("language"),
                      "source_layer": passage.get("source_layer"),
                      "witness": passage.get("witness"),
                      "provenance_status": passage.get("provenance_status"),
                      "trace_status": trace.get("trace_status"),
                      "trace_incomplete": passage.get("provenance_status")
                      == "SOURCE_TRACE_INCOMPLETE",
                      "witness_note": trace.get("witness_note"),
                      "source_state": trace.get("source_state"),
                      "trace_missing": trace.get("trace_missing") or [],
                      "context": [{"passage_id": c.get("passage_id"),
                                   "text": c.get("text"),
                                   "is_target": c.get("is_target")} for c in ctx],
                      "canonical_store": "passage store (read-only reference)"}
    doc["claim_bindings"] = {"bindings": [], "unbound_citations": [passage_id]}
    return finalize_document(doc)


# ─────────────────────────────────────────────────────────── Project（§10–§12）
def build_project_summary(project_id, *, export_options=None):
    """§11 Project Summary：只整理 workspace 结构（不重写任何学术内容）。"""
    import project_api as PA                                              # noqa: PLC0415
    try:
        p = PA.get_project(project_id)
        runs = PA.list_runs(project_id)
        verify = PA.verify_project_runs(project_id) if runs else {"overall": "VERIFIED"}
    except PA.ProjectError as exc:
        raise ExportError("EXPORT_SOURCE_NOT_FOUND",
                          "project source unavailable: %s" % exc,
                          {"project_id": project_id}) from exc
    user_blocks = {
        "user_hypotheses": [{"id": h["hypothesis_id"], "text": h["text"],
                             "not_validated": True,
                             "label": "USER HYPOTHESIS — NOT VALIDATED",
                             "test_runs": h.get("test_runs") or []}
                            for h in p.get("hypotheses") or []],
        "open_questions": [{"id": q["question_id"], "text": q["text"],
                            "origin": q.get("origin"), "run_id": q.get("run_id"),
                            "is_claim": False} for q in p.get("open_questions") or []],
        "user_notes": [{"id": n["note_id"], "title": n.get("title"),
                        "text": n.get("text"), "is_evidence": False}
                       for n in p.get("notes") or []],
        "bibliography": [dict(b) for b in p.get("bibliography_refs") or []],
    }
    doc = make_document(
        export_type="research_project", source_type="research_project",
        source_id=project_id, title="Project: %s" % p.get("title"),
        created_at=PV.now_iso(),
        question=None, answer_state=None,
        sections=[], claims=[], citations=[], limitations=[], abstention=None,
        provenance={"kind": "project_summary",
                    "evidence_role": "NOT_EVIDENCE",
                    "note": ("A project is USER_WORKSPACE. It organizes references; "
                             "it is never evidence.")},
        source_answer_hash=None,
        export_options=dict(export_options or {}, mode="summary"),
        extra_blocks=user_blocks,
    )
    doc["project"] = {
        "project_id": project_id, "title": p.get("title"),
        "description": p.get("description"), "status": p.get("status"),
        "tags": p.get("tags") or [], "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"), "revision": p.get("revision"),
        "counts": PA.summary(p)["counts"],
        "research_questions": [{"id": q["question_id"], "text": q["text"],
                                "status": q.get("status")}
                               for q in p.get("research_questions") or []],
        "runs_index": [{"run_id": r["run_id"], "question": r["question"],
                        "answer_state": r["answer_state"],
                        "created_at": r["created_at"],
                        "source_answer_hash": r["source_answer_hash"],
                        "is_abstention": r["is_abstention"],
                        "is_qualified": r["is_qualified"],
                        "citations": len(r["citation_ids"])} for r in runs],
        "saved_concepts": [r["id"] for r in p.get("saved_concepts") or []],
        "saved_seminars": [r["id"] for r in p.get("saved_seminars") or []],
        "saved_passages": [r["id"] for r in p.get("saved_passages") or []],
        "saved_terms": [r["id"] for r in p.get("saved_terms") or []],
        "snapshot_verification": verify["overall"],
        "broken_references": p.get("broken_references") or [],
        "evidence_role": "NOT_EVIDENCE",
    }
    doc["claim_bindings"] = {"bindings": [], "unbound_citations": []}
    return finalize_document(doc)
