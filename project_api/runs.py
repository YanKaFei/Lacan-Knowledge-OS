#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_api.runs — Research Run 快照（4D.5 §12–§16/§43/§44/§53/§75/§76/§77）

铁律：
    * 快照 == MCP 返回的 FinalScholarlyAnswer **原样**（§75），Project 层**不摘要**、
      不改写、不补字段；
    * 一次 run **不可变**（§15）：重新研究同一问题 = 新 run，绝不覆盖；
    * `ABSTAIN` 保持 `ABSTAIN`（§76），qualification 原样保留（§49）；
    * Project 内容**永不**进入 EvidencePacket（§44/§74）—— 本模块只写 workspace，
      并且 `context_for_agent()` 明确标 `not_evidence`。
"""
from __future__ import annotations

import hashlib
import json
import os

from . import store as S

# 核心的**全部**真实答案状态（6 态）。
# ⚠️ Phase 4E delta 验证发现（产品缺陷）：这里原来只列 3 态
# （VALIDATED / VALIDATED_WITH_QUALIFICATIONS / ABSTAINED），于是真实 provider 合法返回
# PARTIALLY_SUPPORTED / VALIDATION_FAILED / INSUFFICIENT_EVIDENCE 时，
# `add_research_run` 会抛 `Invalid` —— 用户拿到一个真实答案却**无法加入 Research Project**。
# 4D.7 只修了导出层的同一类问题（`export_system.model.ANSWER_STATES`）；
# mock provider 在这条动线上从不产生这 3 态，所以 4D.5 的测试没有照到。
# 纪律：这里只决定「能否存」，**不**把失败态美化成答案（is_abstention/is_qualified 由视图层
# 各自判定，答案状态原样保存）。
RUN_STATE_OK = ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "PARTIALLY_SUPPORTED",
                "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "ABSTAINED")


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def answer_hash(view):
    """与 4D.3/核心一致的答案身份哈希（对 `raw.scholarly_payload` 规范化后取 sha256）。"""
    payload = ((view or {}).get("raw") or {}).get("scholarly_payload")
    if payload is None:
        payload = ((view or {}).get("raw") or {})
    return hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()


def snapshot_hash(view):
    """对**整个存储视图**取哈希（含 sections / claims / abstention）。

    与 `source_answer_hash` 分工不同（§53/§77）：
        source_answer_hash → 核心答案身份（`raw.scholarly_payload`），跨阶段可比；
        snapshot_hash      → **我们真正存下来的字节**，用于发现快照被改写。
    实测踩过：只校验 source_answer_hash 时，改写 `snapshot.sections[*].text`
    仍然返回 VERIFIED —— 因为那段文本不在核心 payload 里。
    """
    return hashlib.sha256(_canon(view).encode("utf-8")).hexdigest()


def snapshot_path(project_id, run_id):
    return os.path.join(S.project_dir(project_id), "snapshots", "%s.json" % run_id)


def add_research_run(project_id, expected_revision, view, request_meta=None,
                     question=None, run_id=None, project_question_id=None):
    """保存一次研究执行 → 不可变快照。

    `view` 必须是 workspace 视图（即 MCP 返回的 FinalScholarlyAnswer 的呈现），
    **不接受**任何被改写的文本：我们只做「拷贝 + 记录元数据」。
    """
    if not isinstance(view, dict) or view.get("kind") not in (None, "answer"):
        raise S.Invalid("only a scholarly answer view can be stored as a run")
    state = str(view.get("state") or "")
    if state not in RUN_STATE_OK:
        raise S.Invalid("unexpected answer_state: %r" % state)
    q = question or view.get("question") or ""
    q = S.clean_text(q, 2000, "question")
    run_id = run_id or S.new_item_id("run")
    advanced = view.get("advanced") or {}
    hijacked = {
        "project_id": project_id,
    }
    record = {
        "run_id": run_id,
        "project_id": project_id,
        "question": q,
        "created_at": S.now_iso(),
        "mode": (request_meta or {}).get("mode"),
        "provider": advanced.get("provider") or (request_meta or {}).get("provider"),
        "answer_state": state,
        "answer_state_label": view.get("state_label"),
        "task_type": view.get("task_type"),
        "is_abstention": bool(view.get("is_abstention")),
        "is_qualified": bool(view.get("is_qualified")),
        "answer_permission": view.get("answer_permission"),
        "request_id": advanced.get("request_id"),
        "core_freeze_version": advanced.get("core_freeze_version"),
        "api_version": advanced.get("api_version"),
        "mcp_version": advanced.get("mcp_version"),
        "answer_schema_version": advanced.get("answer_schema_version"),
        "source_answer_hash": answer_hash(view),
        "snapshot_hash": snapshot_hash(view),
        "citation_ids": [c.get("passage_id") for c in (view.get("citations") or [])],
        "claim_count": len(view.get("claims") or []),
        "limitations": list(view.get("limitations") or []),
        "warnings": list(view.get("warnings") or []),
        "project_question_id": project_question_id,
        "snapshot": view,                      # ← 原样（含 sections / claims / abstention / raw）
        "hijacked_fields": hijacked,
        "immutable": True,
    }
    # 快照先落盘（不可变文件），再登记进 project.json —— 顺序保证不会出现「登记了但没快照」
    path = snapshot_path(project_id, run_id)
    S._atomic_write_json(path, record)                                        # noqa: SLF001

    def fn(p):
        p["research_runs"].append({
            "run_id": run_id, "question": q, "created_at": record["created_at"],
            "answer_state": state, "is_abstention": record["is_abstention"],
            "is_qualified": record["is_qualified"],
            "task_type": record["task_type"], "provider": record["provider"],
            "mode": record["mode"], "request_id": record["request_id"],
            "source_answer_hash": record["source_answer_hash"],
            "snapshot_hash": record["snapshot_hash"],
            "citation_ids": list(record["citation_ids"]),
            "claim_count": record["claim_count"],
            "snapshot_path": os.path.relpath(path, S.PROJECTS_DIR),
            "project_question_id": project_question_id,
        })
        if project_question_id:
            for qq in p["research_questions"]:
                if qq["question_id"] == project_question_id:
                    qq["status"] = "RESEARCHED"
                    qq["last_run_id"] = run_id
        return True
    project, _ = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "add_run",
                   {"run_id": run_id, "state": state, "revision": project["revision"]})
    return project, record


def get_run(project_id, run_id):
    p = snapshot_path(project_id, run_id)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def list_runs(project_id, limit=200):
    d = os.path.join(S.project_dir(project_id), "snapshots")
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:                                                 # noqa: BLE001
            continue
        out.append({"run_id": rec.get("run_id"), "question": rec.get("question"),
                    "created_at": rec.get("created_at"),
                    "answer_state": rec.get("answer_state"),
                    "is_abstention": rec.get("is_abstention"),
                    "is_qualified": rec.get("is_qualified"),
                    "citation_ids": rec.get("citation_ids") or [],
                    "claim_count": rec.get("claim_count"),
                    "limitations": rec.get("limitations") or [],
                    "source_answer_hash": rec.get("source_answer_hash"),
                    "snapshot_hash": rec.get("snapshot_hash")})
    out.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return out[:limit]


def verify_project_runs(project_id):
    """§77：→ VERIFIED / MODIFIED / BROKEN_REFERENCE（逐 run 判定 + 总体判定）。"""
    p = S.read_project(project_id)
    items = []
    for meta in p.get("research_runs") or []:
        path = snapshot_path(project_id, meta["run_id"])
        if not os.path.isfile(path):
            items.append({"run_id": meta["run_id"], "status": "MISSING_SNAPSHOT"})
            continue
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        view = rec.get("snapshot")
        if not isinstance(view, dict):
            items.append({"run_id": meta["run_id"], "status": "MODIFIED",
                          "detail": "snapshot body missing"})
            continue
        stored = rec.get("source_answer_hash")
        actual = answer_hash(view)
        stored_snap = rec.get("snapshot_hash")
        actual_snap = snapshot_hash(view)
        problems = []
        if stored != actual:
            problems.append("core identity hash mismatch")
        if stored_snap and stored_snap != actual_snap:
            problems.append("stored snapshot body modified")
        status = "VERIFIED" if not problems else "MODIFIED"
        broken = []
        for cid in (rec.get("citation_ids") or []):
            if not cid:
                continue
            from . import projects as P                                    # noqa: PLC0415
            if not P.check_referent("passage", cid)["exists"]:
                broken.append(cid)
                status = "BROKEN_REFERENCE"
        items.append({"run_id": rec.get("run_id"), "status": status,
                      "stored_hash": stored, "recomputed_hash": actual,
                      "stored_snapshot_hash": stored_snap,
                      "recomputed_snapshot_hash": actual_snap,
                      "problems": problems,
                      "broken_citations": broken,
                      "answer_state": rec.get("answer_state")})
    overall = "VERIFIED"
    for it in items:
        if it["status"] != "VERIFIED":
            overall = it["status"] if it["status"] != "MISSING_SNAPSHOT" else "MODIFIED"
            break
    return {"project_id": project_id, "overall": overall, "runs": items,
            "note": ("Snapshot identity is recomputed from the stored body; "
                     "a Project never rewrites a stored FinalScholarlyAnswer.")}


def compare_runs(project_id, run_a, run_b):
    """§16：**结构性** diff，绝不由模型写「理论发生了重大改善」。"""
    a = get_run(project_id, run_a)
    b = get_run(project_id, run_b)
    if not a or not b:
        return None
    sa, sb = set(a.get("citation_ids") or []), set(b.get("citation_ids") or [])
    return {
        "run_a": run_a, "run_b": run_b,
        "answer_state": {"a": a.get("answer_state"), "b": b.get("answer_state"),
                         "changed": a.get("answer_state") != b.get("answer_state")},
        "citation_set": {"only_a": sorted(sa - sb), "only_b": sorted(sb - sa),
                         "common": sorted(sa & sb), "changed": sa != sb},
        "claim_count": {"a": a.get("claim_count"), "b": b.get("claim_count"),
                        "changed": a.get("claim_count") != b.get("claim_count")},
        "limitations": {"a": a.get("limitations") or [], "b": b.get("limitations") or [],
                        "changed": (a.get("limitations") or []) != (b.get("limitations") or [])},
        "citation_count": {"a": len(sa), "b": len(sb), "changed": len(sa) != len(sb)},
        "provider": {"a": a.get("provider"), "b": b.get("provider"),
                     "changed": a.get("provider") != b.get("provider")},
        "core_freeze_version": {"a": a.get("core_freeze_version"),
                                "b": b.get("core_freeze_version"),
                                "changed": a.get("core_freeze_version")
                                != b.get("core_freeze_version")},
        "note": ("Structural diff only. No interpretation is generated here: whether a "
                 "change matters is a scholarly judgement that must come from a new "
                 "research call."),
    }


def context_for_agent(project_id, selected_note_ids=None, selected_run_ids=None,
                      include_current_question=None):
    """§42/§43：Agent 读取 Project 上下文时的**预算与边界**。

    只返回：title / description / 当前问题 / **显式选中**的笔记与历史 run；
    绝不把整个项目历史塞进 prompt；并且**明确标记 not_evidence**（§44/§74）。
    """
    p = S.read_project(project_id)
    # ⚠️ 默认 = **什么都不带**：只有调用方显式点名才进上下文（§42）。
    #    实测踩过：写成「没给选择就全都带上」，等于把整个项目笔记倒进 prompt。
    wanted = set(selected_note_ids or [])
    notes = [n for n in (p.get("notes") or []) if n["note_id"] in wanted]
    runs = []
    for rid in (selected_run_ids or []):
        rec = get_run(project_id, rid)
        if rec:
            runs.append({"run_id": rid, "question": rec.get("question"),
                         "answer_state": rec.get("answer_state"),
                         "answer_text": "\n".join(
                             (s.get("text") or "") for s in
                             ((rec.get("snapshot") or {}).get("sections") or []))})
    return {
        "project_id": project_id,
        "title": p["title"],
        "description": p.get("description"),
        "current_question": include_current_question,
        "selected_notes": [{"note_id": n["note_id"], "title": n.get("title"),
                            "text": n.get("text")} for n in notes],
        "selected_runs": runs,
        "evidence_role": "NOT_EVIDENCE",
        "note": ("Project content may only shape **question interpretation**. It is "
                 "never an EvidencePacket member; every scholarly claim must be "
                 "re-derived from the corpus by a research call."),
    }
