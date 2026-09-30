#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_integrity.py — Phase 4C.1-A：**评测完整性**共享库

本模块把 Phase 4C.1-A 的四类校验集中到一处，供门禁 / 测试 / 审计脚本共用：

    A1  human review provenance    `validate_human_review_record` / `baseline_immutability_findings`
    A2  trace integrity            `trace_integrity_findings`
    A3  run manifest hashing       `sha256_file` / `engine_hashes` / `manifest_core`
    A6  lane semantics             `LANE_EXPECTATIONS` / `lane_result`
    A7  structural↔failure 映射     `STRUCTURAL_CLASS_MAP` / `structural_assertion_findings`

设计约束（写死在这里，便于复核）
────────────────────────────────
* **只读**：本模块不写任何 Phase 4C frozen 产物。
* 历史 trace（`research-trace-4b/v1`）中的不一致**不当作新的违规**，而是标为
  `LEGACY_FROZEN`（已冻结的既知缺陷，另行造册）；只有声明 v2 契约的新 trace
  才会被判为 `VIOLATION`。理由：不得为了“让门禁变绿”而改写历史 trace。
* 人工评分只能由**人类**提交；助手只允许「逐字转录」，因此 provenance 必须
  同时说明 `reviewer_type`（human）与 `recorded_by`（谁落盘）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
IDX = os.path.join(VAULT, "_data", "index")
STORE = os.path.join(VAULT, "_data", "passage_store")

# ── A1：人工评审 provenance ────────────────────────────────────────────────
SCORE_DIMS = ("theoretical_coherence", "historical_accuracy",
              "distinction_preservation", "answer_usefulness",
              "overclaiming", "clarity")
SCORE_INT_RANGE = (1, 5)
NA_ALLOWED_DIMS = ("historical_accuracy",)      # 只有这一维允许 N/A
CITATION_SUPPORT = ("PASS", "PARTIAL", "FAIL")
SCHOLARLY_USABLE = ("YES", "WITH_REVISION", "NO")
LEGIT_REVIEWER_TYPES = ("human",)
# 会被视为「不是人类评审者」的标记（大小写无关）
NON_HUMAN_MARKERS = ("gpt", "llm", "claude", "openai", "anthropic", "assistant",
                     "auto", "system", "machine", "model", "script", "bot")
# 允许的落盘者：人类直接提交，或助手逐字转录
ALLOWED_RECORDED_BY = ("human_direct", "assistant_transcription_no_edits")
ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _has_non_human_marker(s) -> bool:
    s = str(s or "").lower()
    # `assistant_transcription_no_edits` 是**记录者**，不是评审者 → 只在
    # reviewer 身份字段上做这个检查时调用者会先排除它
    return any(m in s for m in NON_HUMAN_MARKERS)


def _provenance_assessment(rec, tid) -> tuple:
    """→ (style, problems)；style ∈ {"v2", "legacy_round1", "none"}。

    两种**都合法**、都证明「评分由人类提交、助手只落盘」：

    * `v2`（Phase 4C 后半段起）：`provenance.reviewer_type == "human"` +
      `recorded_by ∈ {human_direct, assistant_transcription_no_edits}`。
    * `legacy_round1`（Phase 4C 评审开头两条）：`submitted_by` 明写人类直接提交 +
      `validated == true` + `written_by` 说明「无系统评分」。
      **这两种形态都不许改写**（冻结基线），因此校验器必须接受历史形态，
      而不是把它们判成伪造 —— 这正是旧 Gate 13 犯的错。
    """
    prov = rec.get("provenance")
    if not isinstance(prov, dict) or not prov:
        return "none", ["%s 缺 provenance（无法证明评分来自人类）" % tid]

    if prov.get("reviewer_type") in LEGIT_REVIEWER_TYPES and prov.get("recorded_by"):
        p = []
        rb = prov.get("recorded_by")
        if rb not in ALLOWED_RECORDED_BY:
            p.append("%s provenance.recorded_by=%r 不在 %s（若确为助手逐字转录请用 "
                     "assistant_transcription_no_edits）" % (tid, rb, ALLOWED_RECORDED_BY))
        if not prov.get("submitted_by"):
            p.append("%s provenance.submitted_by 缺失" % tid)
        if prov.get("reviewer_id") and rec.get("reviewer_id") \
                and prov["reviewer_id"] != rec["reviewer_id"]:
            p.append("%s provenance.reviewer_id != reviewer_id" % tid)
        if prov.get("review_round") and rec.get("review_round") \
                and prov["review_round"] != rec["review_round"]:
            p.append("%s provenance.review_round != review_round" % tid)
        return "v2", p

    sub = str(prov.get("submitted_by") or "")
    if re.search(r"human", sub, re.IGNORECASE) and prov.get("validated") is True \
            and prov.get("written_by"):
        return "legacy_round1", []

    return "none", ["%s provenance 既不是 v2 形态也不是 Phase 4C 第一轮的历史形态" % tid]


def validate_human_review_record(rec) -> dict:
    """provenance-aware 校验一条 `research_human_review.jsonl` 记录。

    → {"state": UNREVIEWED_PLACEHOLDER | REVIEWED_HUMAN | ILLEGITIMATE,
       "problems": [...], "ok": bool, "provenance_style": str}

    `ILLEGITIMATE` 覆盖 Phase 4C 人工评审之前 Gate 13 想抓的东西：
    空占位被自动填分、REVIEWED 但 provenance 不是人类、枚举越界、
    评分维度缺失/类型错误、LLM 冒充 reviewer。
    **合法的真实人工评审（含历史形态）不得被判为违规。**
    """
    p = []
    tid = rec.get("task_id") or "<no-task-id>"
    scores = rec.get("human_scores") or {}
    status = rec.get("review_status")
    cited = rec.get("citation_support")
    usable = rec.get("scholarly_usable")

    if status == "NOT_REVIEWED":
        # 空占位：只允许全空
        for k, v in scores.items():
            if v is not None:
                p.append("%s.%s=%s 但 review_status=NOT_REVIEWED（自动填分）" % (tid, k, v))
        if cited is not None:
            p.append("%s citation_support=%s 但 review_status=NOT_REVIEWED" % (tid, cited))
        if usable is not None:
            p.append("%s scholarly_usable=%s 但 review_status=NOT_REVIEWED" % (tid, usable))
        state = "ILLEGITIMATE" if p else "UNREVIEWED_PLACEHOLDER"
        return {"state": state, "problems": p, "ok": not p, "provenance_style": "none"}

    if status != "REVIEWED":
        return {"state": "ILLEGITIMATE", "provenance_style": "none",
                "problems": ["%s review_status=%r 不在 {NOT_REVIEWED, REVIEWED}"
                             % (tid, status)], "ok": False}

    # ── REVIEWED：必须是人类 provenance + 完整字段 ────────────────────────
    rt = rec.get("reviewer_type")
    if rt not in LEGIT_REVIEWER_TYPES:
        p.append("%s reviewer_type=%r 不是人类评审" % (tid, rt))
    rid = rec.get("reviewer_id")
    if not rid:
        p.append("%s 缺 reviewer_id（可为 not_supplied_by_reviewer，但不得为空）" % tid)
    elif str(rid) != "not_supplied_by_reviewer" and _has_non_human_marker(rid):
        p.append("%s reviewer_id=%r 含非人类标记" % (tid, rid))
    rr = rec.get("review_round")
    if not isinstance(rr, int) or rr < 1:
        p.append("%s review_round=%r 非法" % (tid, rr))
    ts = rec.get("review_timestamp") or rec.get("reviewed_at")
    if not ts or not ISO_TS.match(str(ts)):
        p.append("%s review_timestamp/reviewed_at=%r 不是 ISO-8601 UTC" % (tid, ts))
    if rec.get("reviewed_at") and rec.get("review_timestamp") \
            and rec["reviewed_at"] != rec["review_timestamp"]:
        p.append("%s reviewed_at != review_timestamp" % tid)

    # 评分维度
    for d in SCORE_DIMS:
        if d not in scores:
            p.append("%s 缺评分维度 %s" % (tid, d))
            continue
        v = scores[d]
        if v is None:
            p.append("%s.%s 为 null（REVIEWED 必须已评分）" % (tid, d))
        elif v == "N/A":
            if d not in NA_ALLOWED_DIMS:
                p.append("%s.%s=N/A 但只有 %s 允许 N/A" % (tid, d, NA_ALLOWED_DIMS[0]))
        elif not (isinstance(v, int) and SCORE_INT_RANGE[0] <= v <= SCORE_INT_RANGE[1]):
            p.append("%s.%s=%r 不在 1–5" % (tid, d, v))
    for k, v in scores.items():
        if k not in SCORE_DIMS:
            p.append("%s 出现未知评分维度 %s" % (tid, k))

    if cited not in CITATION_SUPPORT:
        p.append("%s citation_support=%r 不在 %s" % (tid, cited, CITATION_SUPPORT))
    if usable not in SCHOLARLY_USABLE:
        p.append("%s scholarly_usable=%r 不在 %s" % (tid, usable, SCHOLARLY_USABLE))

    rc = rec.get("reviewer_comment")
    if not isinstance(rc, dict) or not (rc.get("raw") or "").strip():
        p.append("%s reviewer_comment.raw 缺失或为空" % tid)
    else:
        for k in ("most_worth_keeping", "most_needing_change"):
            if not (rc.get(k) or "").strip():
                p.append("%s reviewer_comment.%s 为空" % (tid, k))

    style, prov_problems = _provenance_assessment(rec, tid)
    p.extend(prov_problems)

    return {"state": "ILLEGITIMATE" if p else "REVIEWED_HUMAN",
            "problems": p, "ok": not p, "provenance_style": style}


def baseline_immutability_findings(records, baseline=None, results=None) -> list[str]:
    """Phase 4C 冻结人工基线不得被改动。

    基线来源（按优先级）：
      1. `_data/eval/human_review_baseline_v1.json` —— Phase 4C.1-A 新建的**钉住快照**
         （逐任务记下 14 条评分 / citation_support / scholarly_usable / 评语长度）。
         这是唯一可逐字段比对的冻结基线；`human_review_results_v1.json` 里只有聚合，
         没有逐任务行，因此不能单独承担该职责。
      2. `human_review_results_v1.json` 的**聚合计数**（citation_support /
         scholarly_usable）—— 用于交叉核对，抓「改了分但聚合没动」这类不一致。
    """
    out = []
    if baseline is None:
        baseline = jd(os.path.join(EVAL, "human_review_baseline_v1.json"))
    pinned = {}
    if baseline:
        pinned = {t["task_id"]: t for t in (baseline.get("tasks") or [])}
    for rec in records:
        tid = rec.get("task_id")
        base = pinned.get(tid)
        if not base:
            continue
        for key in ("human_scores", "citation_support", "scholarly_usable",
                    "review_status", "review_round"):
            if rec.get(key) != base.get(key):
                out.append("%s 冻结基线被改动：%s 现=%r 基线=%r"
                           % (tid, key, rec.get(key), base.get(key)))

    # 聚合交叉核对（results_v1 只有聚合，没有逐任务行）
    if results is None:
        results = jd(os.path.join(EVAL, "human_review_results_v1.json")) or {}
    if results:
        from collections import Counter
        want_cite = results.get("citation_support") or {}
        want_use = results.get("scholarly_usable") or {}
        if want_cite:
            got = dict(Counter(r.get("citation_support") for r in records
                               if r.get("citation_support") is not None))
            if got != want_cite:
                out.append("citation_support 聚合与冻结汇总不一致：现=%s 基线=%s"
                           % (got, want_cite))
        if want_use:
            got = dict(Counter(r.get("scholarly_usable") for r in records
                               if r.get("scholarly_usable") is not None))
            if got != want_use:
                out.append("scholarly_usable 聚合与冻结汇总不一致：现=%s 基线=%s"
                           % (got, want_use))
    return out


def adjudication_immutability_findings(queue, baseline=None) -> list[str]:
    """3 条人工裁决同样不得被改动（逐字段比对钉住的快照）。"""
    if baseline is None:
        baseline = jd(os.path.join(EVAL, "human_review_baseline_v1.json"))
    pinned = {}
    if baseline:
        pinned = {a["task_id"]: a for a in (baseline.get("adjudications") or [])}
    out = []
    for q in queue:
        tid = q.get("task_id")
        base = pinned.get(tid)
        if not base:
            continue
        for key in ("decision", "status", "adjudicated_by", "adjudicated_at",
                    "agent_state_v4c", "followup_required"):
            if q.get(key) != base.get(key):
                out.append("%s 冻结裁决被改动：%s 现=%r 基线=%r"
                           % (tid, key, q.get(key), base.get(key)))
    return out


# ── A2：trace 完整性 ──────────────────────────────────────────────────────
CONTRACT_SCHEMA = "research-trace/v2"
LEGACY_SCHEMAS = ("research-trace-4b/v1", "research-trace/v1")
_SIGNAL_CLAIM_PATTERNS = ("多分量一致性", "约束满足", "component agreement",
                          "constraint satisfaction")
# 「声称达标」的肯定式措辞（必须出现），以及否定/豁免措辞（出现即不算声称）
_AFFIRM = re.compile(r"达标|均达标|满足|一致|agreement|satisfaction", re.I)
_NEGATED = re.compile(r"不适用|未测量|未测|null|None|无|不达标|不满足|不成立|不参与|"
                      r"not\s+applicable|n/?a\b|missing|absent", re.I)


def _final_state(trace):
    ev = trace.get("evaluation") or {}
    if ev.get("state"):
        return ev["state"]
    return ((trace.get("evidence_pack") or {}).get("evidence_state") or {}).get("final_state") \
        or ((trace.get("answer") or {}).get("evidence_state"))


def _last_step_state(trace):
    st = (trace.get("trace") or {}).get("state_transitions") or []
    return st[-1].get("state") if st else None


def _executed_tools(trace):
    return [c.get("tool") for c in ((trace.get("trace") or {}).get("tool_calls") or [])]


def trace_integrity_findings(trace) -> list[dict]:
    """检查一条 research trace 的五类内部一致性（A2 §1–§5）。

    每条 → {"code", "detail", "severity"}；`severity` ∈
    {"VIOLATION", "LEGACY_FROZEN"}：声明 v2 契约的 trace 出问题算 VIOLATION，
    历史冻结 trace 算 LEGACY_FROZEN（另册记录，不改变历史）。
    """
    out = []
    tid = trace.get("task_id")
    tr = trace.get("trace") or {}
    ev = trace.get("evaluation") or {}
    plan = trace.get("plan") or {}
    # 契约版本可能写在 run 顶层（run schema）或 trace 文档里 —— 两处都认，
    # 否则新 trace 会被当成 legacy 而**静默跳过**契约检查（Gate 19 的假通过）。
    schema = trace.get("schema_version")
    trace_schema = tr.get("schema_version")
    contract = (schema == CONTRACT_SCHEMA) or (trace_schema == CONTRACT_SCHEMA)
    sev = "VIOLATION" if contract else "LEGACY_FROZEN"

    # (1) required operations
    #     v2 契约把字段写在 trace 文档里（run["trace"]），有的实现写在 run 顶层 —— 两处都认。
    req = (trace.get("required_operations") or tr.get("required_operations")
           or ev.get("required_operations"))
    done = trace.get("completed_operations") or tr.get("completed_operations")
    missing = trace.get("missing_operations") or tr.get("missing_operations")
    executed = _executed_tools(trace)
    if contract:
        if not req:
            out.append({"code": "REQUIRED_OPERATIONS_NOT_DECLARED", "severity": sev,
                        "detail": "%s 声明 %s 但缺 required_operations" % (tid, CONTRACT_SCHEMA)})
        else:
            # Phase 4C.1-B3：执行层判为 NOT_APPLICABLE（且有结构凭据）的 required op
            # 视为**已解决**，不算 missing（否则会把结构性不可答记成漏执行）。
            na = set()
            _ex0 = tr.get("execution") or trace.get("execution") or {}
            for o in (_ex0.get("operations") or []):
                if o.get("status") == "NOT_APPLICABLE":
                    dep = o.get("structural_dependency") or {}
                    ok = False
                    for pr in dep.get("proofs") or []:
                        scan = (pr or {}).get("corpus_scan") or {}
                        if (dep.get("upstream_operation") == "metadata_check"
                                and scan.get("executed") is True
                                and scan.get("scope") == "whole_corpus"
                                and int(scan.get("n_with_real_value") or 0) == 0):
                            ok = True
                    if ok:
                        na.add(o.get("operation_id"))
            want_done = [o for o in req if o in executed or o in na]
            want_missing = [o for o in req if o not in executed and o not in na]
            if done is not None and sorted(done) != sorted(want_done):
                out.append({"code": "COMPLETED_OPERATIONS_MISMATCH", "severity": sev,
                            "detail": "%s completed_operations=%s 实际=%s"
                                      % (tid, done, want_done)})
            if missing is not None and sorted(missing) != sorted(want_missing):
                out.append({"code": "MISSING_OPERATIONS_MISMATCH", "severity": sev,
                            "detail": "%s missing_operations=%s 实际=%s"
                                      % (tid, missing, want_missing)})
            if want_missing and _final_state(trace) == "SUPPORTED":
                out.append({"code": "SUPPORTED_WITH_MISSING_REQUIRED_OPERATIONS",
                            "severity": "VIOLATION",
                            "detail": "%s final_state=SUPPORTED 但缺 %s" % (tid, want_missing)})
    else:
        planned = plan.get("planned_operations") or []
        not_run = [o for o in planned if o not in executed]
        if not_run:
            out.append({"code": "PLANNED_OPERATION_NOT_EXECUTED", "severity": sev,
                        "detail": "%s plan 声明但未执行：%s（已执行 %s）"
                                  % (tid, not_run, executed)})
        if not req:
            out.append({"code": "REQUIRED_OPERATIONS_NOT_DECLARED", "severity": sev,
                        "detail": "%s（%s）未声明 required_operations —— 未来 trace 需按 %s "
                                  "补齐，本阶段不回填历史" % (tid, schema, CONTRACT_SCHEMA)})

    # (2) final state 与最后一步状态
    final, last = _final_state(trace), _last_step_state(trace)
    reason = (trace.get("state_transition_reason")
              or tr.get("state_transition_reason")
              or (tr.get("sufficiency_v21") or {}).get("transition_reason")
              or (tr.get("sufficiency_v2") or {}).get("transition_reason")
              or ((trace.get("evidence_pack") or {}).get("evidence_state") or {})
              .get("transition_reason")
              or (ev.get("calibration") or {}).get("transition_reason"))
    if final and last and final != last and not reason:
        out.append({"code": "STATE_TRANSITION_UNEXPLAINED", "severity": sev,
                    "detail": "%s 最后一步=%s 但 final_state=%s，且无 transition_reason"
                              % (tid, last, final)})

    # (3) state explanation 与 signals 一致
    es = (trace.get("evidence_pack") or {}).get("evidence_state") or {}
    sig = es.get("signals") or {}
    reasons = es.get("reasons") or []
    # 只有**肯定式**声称才算「引用不存在的信号」：
    # `多分量一致性：不适用（本次独立检索族 0 个）` 是如实说明，不是借口句。
    claims_component = [r for r in reasons
                        if any(k in r for k in _SIGNAL_CLAIM_PATTERNS)
                        and _AFFIRM.search(r) and not _NEGATED.search(r)]
    null_signals = (sig.get("component_agreement") is None
                    and sig.get("constraint_satisfaction") is None
                    and not sig.get("independent_families_executed"))
    if claims_component and null_signals:
        out.append({"code": "SUFFICIENCY_REASON_CITES_ABSENT_SIGNAL", "severity": sev,
                    "detail": "%s reasons 声称「多分量一致性/约束满足」但 signals 全为 null/空：%r"
                              % (tid, claims_component[0][:60])})

    # (4) context expansion 计数一致
    used = ((trace.get("budget") or {}).get("used") or {}).get("context_expansions")
    listed = tr.get("context_expansions")
    if isinstance(listed, list) and isinstance(used, int) and used != len(listed):
        out.append({"code": "CONTEXT_EXPANSION_COUNT_MISMATCH", "severity": sev,
                    "detail": "%s budget.used.context_expansions=%d 但 trace.context_expansions "
                              "有 %d 项" % (tid, used, len(listed))})

    # ── Phase 4C.1-B2：执行层契约（只在 trace 带 `execution` 段时检查）
    ex = tr.get("execution") or trace.get("execution") or {}
    if isinstance(ex, dict) and ex.get("operations") is not None:
        ops = {o.get("operation_id"): o for o in (ex.get("operations") or [])}
        lanes = {l.get("lane_id"): l for l in (ex.get("lanes") or [])}
        contract = tr.get("research_contract") or {}
        terminal = ("EXECUTED", "FAILED", "STRUCTURALLY_UNAVAILABLE",
                    "SKIPPED_WITH_REASON", "SATISFIED", "ZERO_ATTESTATION_CONFIRMED",
                    "NOT_APPLICABLE")
        # B2-1：required operation 必须有执行记录（且是终态）
        for op in (contract.get("required_operations") or []):
            rec = ops.get(op)
            if rec is None:
                out.append({"code": "B2_REQUIRED_OPERATION_WITHOUT_RECORD",
                            "severity": "VIOLATION",
                            "detail": "%s required operation %s 无执行记录" % (tid, op)})
            elif rec.get("status") not in terminal:
                out.append({"code": "B2_REQUIRED_OPERATION_NOT_TERMINAL",
                            "severity": "VIOLATION",
                            "detail": "%s operation %s status=%s" % (tid, op, rec.get("status"))})
        # B2-2：required lane 必须有执行记录
        for lid in (contract.get("required_lanes") or []):
            lrec = lanes.get(lid)
            if lrec is None:
                out.append({"code": "B2_REQUIRED_LANE_WITHOUT_RECORD",
                            "severity": "VIOLATION",
                            "detail": "%s required lane %s 无执行记录" % (tid, lid)})
            elif lrec.get("status") not in terminal:
                out.append({"code": "B2_REQUIRED_LANE_NOT_TERMINAL",
                            "severity": "VIOLATION",
                            "detail": "%s lane %s status=%s" % (tid, lid, lrec.get("status"))})
        # B2-3：声称 SATISFIED 却没有任何 evidence id
        for lid, lrec in lanes.items():
            if lrec.get("status") in ("SATISFIED", "ZERO_ATTESTATION_CONFIRMED"):
                if lrec.get("status") == "SATISFIED" and not (lrec.get("evidence_ids") or []):
                    out.append({"code": "B2_SATISFIED_LANE_WITHOUT_EVIDENCE",
                                "severity": "VIOLATION",
                                "detail": "%s lane %s 标 SATISFIED 但 evidence_ids 为空"
                                          % (tid, lid)})
        # B2-4：required constraint 必须有 applied 记录
        for c in (contract.get("required_constraints") or []):
            key = "%s=%s" % (c.get("kind"), c.get("value"))
            rec = next((x for x in (ex.get("constraints") or [])
                        if "%s=%s" % (x.get("kind"), x.get("value")) == key), None)
            if rec is None or rec.get("applied") is None:
                out.append({"code": "B2_REQUIRED_CONSTRAINT_NOT_RECORDED",
                            "severity": "VIOLATION",
                            "detail": "%s 约束 %s 无 applied 记录" % (tid, key)})
        # B2-6：generic fallback 不得满足 required lane
        gf = ex.get("generic_fallback") or {}
        if gf.get("satisfied_required_lane_n"):
            out.append({"code": "B2_GENERIC_FALLBACK_SATISFIED_REQUIRED_LANE",
                        "severity": "VIOLATION",
                        "detail": "%s 有 %s 条 required lane 由泛化 fallback 满足"
                                  % (tid, gf.get("satisfied_required_lane_n"))})
        # B2-7：relation required 但未执行却 SUPPORTED
        rel = ex.get("relation") or {}
        if rel.get("required"):
            rel_op = ops.get("find_relation_evidence") or {}
            if rel_op.get("status") not in ("EXECUTED",) and _final_state(trace) == "SUPPORTED":
                out.append({"code": "B2_RELATION_NOT_EXECUTED_BUT_SUPPORTED",
                            "severity": "VIOLATION",
                            "detail": "%s relation_required 但 relation 检索未执行 → SUPPORTED"
                                      % tid})
        # ── Phase 4C.1-B3：执行闭环的 6 条检查 ─────────────────────────────
        # ⚠️ 只对 **research-execution/v2**（B3 起的执行记录）生效：B2/B1 的历史 trace
        #    没有 NOT_APPLICABLE / 类别预算 / 分级 formalism / 术语三层，不能拿新语义去
        #    判旧记录（那就是改写历史）。历史 trace 的不一致另册（见 trace baseline）。
        b3 = str(ex.get("schema_version") or "").startswith("research-execution/v2")
        if b3:
            # B3-1：NOT_APPLICABLE 必须有**机器可验证**的结构依赖凭据
            na_recs = [o for o in (ex.get("operations") or [])
                       if o.get("status") == "NOT_APPLICABLE"]
            for o in na_recs:
                dep = o.get("structural_dependency") or {}
                proofs = dep.get("proofs") or []
                proven = False
                for pr in proofs:
                    scan = (pr or {}).get("corpus_scan") or {}
                    if (scan.get("executed") is True and scan.get("scope") == "whole_corpus"
                            and int(scan.get("n_with_real_value") or 0) == 0
                            and (pr or {}).get("availability") in ("GLOBAL_UNKNOWN",
                                                                   "FIELD_ABSENT")):
                        proven = True
                if not proven:
                    out.append({"code": "B3_NOT_APPLICABLE_WITHOUT_STRUCTURAL_PROOF",
                                "severity": "VIOLATION",
                                "detail": ("%s operation %s 标 NOT_APPLICABLE 但没有 "
                                           "whole-corpus 结构凭据")
                                          % (tid, o.get("operation_id"))})
            # B3-2：普通 retrieval failure 不得伪装成 NOT_APPLICABLE
            #        （凭据必须来自 metadata_check；且不得同时存在「有证据却判 NA」）
            for o in na_recs:
                dep = o.get("structural_dependency") or {}
                if dep.get("upstream_operation") != "metadata_check":
                    out.append({"code": "B3_NOT_APPLICABLE_DISGUISES_RETRIEVAL_FAILURE",
                                "severity": "VIOLATION",
                                "detail": ("%s operation %s 的 NOT_APPLICABLE 上游不是结构性检查"
                                           "（upstream=%s）→ 疑似把检索失败包装成 NA")
                                          % (tid, o.get("operation_id"),
                                             dep.get("upstream_operation"))})
                if o.get("evidence_ids") and o.get("evidence_n"):
                    out.append({"code": "B3_NOT_APPLICABLE_DISGUISES_RETRIEVAL_FAILURE",
                                "severity": "VIOLATION",
                                "detail": ("%s operation %s 标 NOT_APPLICABLE 却带着 %d 条证据"
                                           % (tid, o.get("operation_id"), o.get("evidence_n")))})
            # B3-3：required source lane 不得因预算而缺失/被截断
            for lid, lrec in lanes.items():
                if not str(lid).startswith("source_layer:"):
                    continue
                if not lrec.get("required"):
                    continue
                if lrec.get("status") in ("NOT_STARTED", "SKIPPED_WITH_REASON"):
                    out.append({"code": "B3_REQUIRED_SOURCE_LANE_BUDGET_STARVED",
                                "severity": "VIOLATION",
                                "detail": ("%s required source lane %s status=%s（不得因关系/其它 "
                                           "lane 抢占预算而未执行）" % (tid, lid, lrec.get("status")))})
            # B3-4：formalism 契约要求时必须有一条**形式检索**记录（符号/表达式检索）
            form = contract.get("formalism") or {}
            if form.get("formalism_required"):
                frec = ops.get("formalism_search")
                if frec is None:
                    out.append({"code": "B3_FORMALISM_CONTRACT_WITHOUT_SYMBOL_OPERATION",
                                "severity": "VIOLATION",
                                "detail": "%s formalism_required 但没有 formalism_search 记录" % tid})
                else:
                    eb = (ex.get("formalism") or {})
                    if not (eb.get("query_forms") or eb.get("hits") or eb.get("candidates")):
                        out.append({"code": "B3_FORMALISM_CONTRACT_WITHOUT_SYMBOL_OPERATION",
                                    "severity": "VIOLATION",
                                    "detail": ("%s formalism_search 记录里没有分级检索形式"
                                               "（query_forms/hits/candidates 全空）" % tid)})
            # B3-5：terminology 三层完成语义不得混写
            term = ex.get("terminology") or {}
            for t_, v in (term.get("terms") or {}).items():
                if not isinstance(v, dict):
                    continue
                mapping, att, ctx = (v.get("mapping_completion"), v.get("attestation_completion"),
                                     v.get("context_validation"))
                if not mapping or not att or not ctx:
                    out.append({"code": "B3_TERMINOLOGY_COMPLETION_CONFLATED",
                                "severity": "VIOLATION",
                                "detail": "%s 术语 %r 缺少三层状态（mapping/attestation/context）"
                                          % (tid, t_)})
                    continue
                hits = int(v.get("corpus_hits") or 0)
                if att == "ATTESTED" and hits == 0:
                    out.append({"code": "B3_TERMINOLOGY_COMPLETION_CONFLATED",
                                "severity": "VIOLATION",
                                "detail": "%s 术语 %r 声称 ATTESTED 但 corpus_hits=0" % (tid, t_)})
                if att == "ZERO_ATTESTATION" and hits > 0:
                    out.append({"code": "B3_TERMINOLOGY_COMPLETION_CONFLATED",
                                "severity": "VIOLATION",
                                "detail": "%s 术语 %r 声称 ZERO_ATTESTATION 但 corpus_hits=%d"
                                          % (tid, t_, hits)})
                if att == "ZERO_ATTESTATION" and ctx == "CONTEXT_VALIDATED":
                    out.append({"code": "B3_TERMINOLOGY_COMPLETION_CONFLATED",
                                "severity": "VIOLATION",
                                "detail": ("%s 术语 %r 零见证却声称 CONTEXT_VALIDATED"
                                           "（零见证没有可验证的上下文）" % (tid, t_))})
            # B3-6：EXECUTION_COMPLETE 不得建立在 unresolved required obligation 上
            ec2 = tr.get("execution_completion") or {}
            if ec2.get("complete") is True:
                unresolved = []
                for op in (contract.get("required_operations") or []):
                    st = (ops.get(op) or {}).get("status")
                    if st in (None, "PLANNED", "SCHEDULED", "SKIPPED_WITH_REASON"):
                        unresolved.append("op:%s(%s)" % (op, st))
                for lid, lrec in lanes.items():
                    if lrec.get("required") and lrec.get("status") in ("NOT_STARTED",):
                        unresolved.append("lane:%s" % lid)
                if unresolved:
                    out.append({"code": "B3_EXECUTION_COMPLETE_WITH_UNRESOLVED_OBLIGATION",
                                "severity": "VIOLATION",
                                "detail": "%s 声称 EXECUTION_COMPLETE 但仍有未终态义务：%s"
                                          % (tid, unresolved)})
        # B2-8：execution 未完成却声称 research_completion=true
        ec = tr.get("execution_completion") or {}
        if ec and ec.get("complete") is False and ev.get("research_completion") is True:
            out.append({"code": "B2_INCOMPLETE_EXECUTION_CLAIMED_COMPLETE",
                        "severity": "VIOLATION",
                        "detail": "%s execution=%s 但 research_completion=true"
                                  % (tid, ec.get("state"))})

    # (5) required lanes（若有 trace 端的契约引用）
    applied = (trace.get("applied_contract")
               or tr.get("applied_contract")
               or ((tr.get("research_contract") or {}) if isinstance(
                   tr.get("research_contract"), dict) else {}) or {})
    req_lanes = (applied.get("required_lanes")
                 or trace.get("required_lanes") or tr.get("required_lanes") or [])
    if req_lanes:
        # B2 trace：lane 记录在 execution.lanes（没有 legacy lane_tags）→ 用 B2 语义复核：
        # 判 SUPPORTED 时，每个 required lane 必须**有证据**，relation 若为必需也必须有证据。
        ex = trace.get("execution") or tr.get("execution") or {}
        b2_lanes = ex.get("lanes") or []
        if b2_lanes and _final_state(trace) == "SUPPORTED":
            # 术语 lane 的完成语义是「译名有语料见证」（corpus_hits>0），不是「检索到段落」，
            # 因此不参与「无证据仍判 SUPPORTED」这条；其余 required lane 必须有证据。
            _contract_lanes = set(contract.get("required_lanes") or [])
            noev = [l.get("lane_id") for l in b2_lanes
                    if l.get("required") and not str(l.get("lane_id", "")).startswith("term:")
                    and (l.get("lane_id") in _contract_lanes)
                    and not (l.get("evidence_ids") or l.get("usable_hit_count"))]
            rel = ex.get("relation") or {}
            if rel.get("required") and not (rel.get("relation_evidence_ids")
                                            or rel.get("relation_evidence_n")):
                noev.append("relation")
            if noev:
                out.append({"code": "SUPPORTED_WITH_MISSING_REQUIRED_LANE",
                            "severity": "VIOLATION",
                            "detail": "%s 判 SUPPORTED 但 required lane 无证据：%s"
                                      % (tid, noev)})
            return out
        seen = set(tr.get("lane_tags") or [])
        cov = trace.get("coverage") or (trace.get("evidence_pack") or {}).get("coverage") or {}
        missing_lanes = (trace.get("missing_lanes") or tr.get("missing_lanes") or [])
        if missing_lanes and _final_state(trace) == "SUPPORTED":
            out.append({"code": "SUPPORTED_WITH_MISSING_REQUIRED_LANE",
                        "severity": "VIOLATION",
                        "detail": "%s 契约要求的 lane 缺失 %s 仍判 SUPPORTED"
                                  % (tid, missing_lanes)})
        if len(req_lanes) >= 2 and (cov.get("lane_b_evidence_n") == 0 or len(seen) < 2):
            if _final_state(trace) == "SUPPORTED":
                out.append({"code": "SUPPORTED_WITH_MISSING_REQUIRED_LANE",
                            "severity": "VIOLATION",
                            "detail": "%s 契约要求 lanes=%s 但 lane_tags=%s lane_b_evidence_n=%s "
                                      "仍判 SUPPORTED"
                                      % (tid, req_lanes, sorted(seen), cov.get("lane_b_evidence_n"))})
    return out


# ── A6：lane 语义（空 lane 不等于失败） ───────────────────────────────────
LANE_EXPECTATIONS = ("EXPECTED_POSITIVE", "EXPECTED_ZERO", "UNKNOWN_EXPECTATION")
LANE_HIT_STATES = ("ATTESTED", "ZERO_ATTESTATION", "UNKNOWN")
LANE_RESULTS = ("PASS", "FAIL", "REVIEW")


def lane_result(expectation, observed_hits, threshold=0):
    """把 (期望, 实测命中数) 映射成 PASS / FAIL / REVIEW。

    这是 Phase 4C.1-A 的核心修正：`原乐 = 0 hit` 在那个译名任务里是**研究结论**，
    不是 retrieval failure。只有 `UNKNOWN_EXPECTATION` 的 0 命中才需要复核。
    """
    if expectation == "EXPECTED_POSITIVE":
        return "PASS" if observed_hits > threshold else "FAIL"
    if expectation == "EXPECTED_ZERO":
        return "PASS" if observed_hits == 0 else "FAIL"
    if expectation == "UNKNOWN_EXPECTATION":
        return "REVIEW" if observed_hits == 0 else "PASS"
    raise ValueError("未知 lane expectation：%r" % (expectation,))


# ── A7：structural unanswerability ↔ failure class 映射 ───────────────────
# category 说明：CORPUS_STRUCTURAL = 只有**语料层**证据不足时才可断言（真结构性）；
#                RETRIEVAL_OR_EXECUTION = 只能说明本次执行没取到，**不得**当作结构性不可答。
STRUCTURAL_CLASS_MAP = {
    "METADATA_UNAVAILABLE": {
        "category": "CORPUS_STRUCTURAL",
        "maps_to_failure_classes": ["SOURCE_GAP"],
        "requires_corpus_level_check": True,
        "admissible_as_structural_unanswerability": True,
        "note": "字段级缺失（如 session_date 全库 unknown）。必须给出全库字段统计。",
    },
    "TOPIC_NOT_COVERED": {
        "category": "CORPUS_STRUCTURAL",
        "maps_to_failure_classes": ["SOURCE_GAP", "ONTOLOGY_GAP"],
        "requires_corpus_level_check": True,
        "admissible_as_structural_unanswerability": True,
        "note": "先做 corpus 级 needle 计数；若计数来自失败的问句切分则**不得**成立。",
    },
    "SOURCE_CHAIN_INCOMPLETE": {
        "category": "CORPUS_STRUCTURAL",
        "maps_to_failure_classes": ["SOURCE_GAP"],
        "requires_corpus_level_check": True,
        "admissible_as_structural_unanswerability": True,
        "note": "recovered 层与 primary 层之间的缺环，需给出 witness 统计。",
    },
    "ONTOLOGY_GAP": {
        "category": "CORPUS_STRUCTURAL",
        "maps_to_failure_classes": ["ONTOLOGY_GAP", "ENTITY_RESOLUTION_FAILURE"],
        "requires_corpus_level_check": True,
        "admissible_as_structural_unanswerability": True,
        "note": "概念/词表缺口，需给出 alias/spec 层证据。",
    },
    "FORMALISM_MISSING": {
        "category": "RETRIEVAL_OR_EXECUTION",
        "maps_to_failure_classes": ["RETRIEVAL_MISS", "RANKING_FAILURE"],
        "requires_corpus_level_check": True,
        "admissible_as_structural_unanswerability": False,
        "note": ("Phase 4C 人工裁决（拓扑题）：检索集里没有公式符号，只能证明"
                 "**本次检索**没找到；要成为结构性不可答，必须先在 corpus 上做"
                 "formalism-specific 扫描并记录计数（CORPUS_FORMALISM_MISSING）。"),
    },
}


def structural_assertion_findings(structural_classes, corpus_checks=None) -> list[str]:
    """断言结构性不可答时，是否满足「先扫语料、再下结论」的契约。

    `corpus_checks` → {class_name: {"executed": bool, "scope": str, ...}}

    规则：
      * 未知类 → 违规（五类是封闭集）；
      * 需要 corpus 级检查但没有 `executed: True` → 违规（没检到 ≠ 库里没有）；
      * 属 RETRIEVAL_OR_EXECUTION 的类（如 `FORMALISM_MISSING`）只有在做了
        `scope == "whole_corpus"` 的专项扫描后才可能成立 —— 也就是说必须把
        `RETRIEVED_FORMALISM_MISSING` 与 `CORPUS_FORMALISM_MISSING` 分开；
        只扫检索集就断言结构性不可答 → 违规。
    """
    corpus_checks = corpus_checks or {}
    out = []
    for c in structural_classes or []:
        spec = STRUCTURAL_CLASS_MAP.get(c)
        if not spec:
            out.append("未知 structural class：%s（不在五类封闭集内）" % c)
            continue
        chk = corpus_checks.get(c) or {}
        if spec["requires_corpus_level_check"] and not chk.get("executed"):
            out.append("%s 需要 corpus 级检查但未见记录（没检到 ≠ 库里没有）" % c)
            continue
        if not spec["admissible_as_structural_unanswerability"] \
                and chk.get("scope") != "whole_corpus":
            out.append("%s 属 %s：只有做过 whole_corpus 专项扫描"
                       "（CORPUS_FORMALISM_MISSING）才可能成立，当前 scope=%r"
                       % (c, spec["category"], chk.get("scope")))
    return out


def category_of_structural_class(c) -> str:
    return (STRUCTURAL_CLASS_MAP.get(c) or {}).get("category", "UNKNOWN")


# ══════════════════════════════════════════════════════════════════════════
# Gate 20（Phase 4C.1-C）：synthesis 契约检查
# ══════════════════════════════════════════════════════════════════════════
SYNTHESIS_FAILURE_CODES = ("SYNTHESIS_NOT_ALLOWED", "SYNTHESIS_SCHEMA_INVALID",
                           "CLAIM_WITHOUT_EVIDENCE", "INVALID_CITATION_REFERENCE",
                           "UNSUPPORTED_QUOTATION", "SOURCE_ROLE_VIOLATION",
                           "ABSTENTION_CONTRACT_VIOLATION", "LLM_PROVIDER_FAILURE")


def synthesis_result_findings(row) -> list[dict]:
    """一条 synthesis 结果 → Gate 20 findings（每条 {"code","detail","severity"}）。

    只做**结构与引用绑定**层面的检查（C 阶段范围）；「citation 是否 entail claim」
    属于 Phase 4C.1-D，这里**不假装**已经证明。
    """
    out = []
    tid = row.get("task_id")
    contract = row.get("input_contract") or {}
    claims = row.get("claims") or []
    answer = row.get("answer") or {}
    perm = row.get("answer_permission") or contract.get("answer_permission")
    status = row.get("contract_status") or contract.get("status")

    def bad(code, detail):
        out.append({"code": code, "severity": "VIOLATION", "detail": detail})

    # ① 没有 READY 契约就不得有 claims / answer
    if not contract:
        bad("SYNTHESIS_NOT_ALLOWED", "%s 没有 SynthesisInputContract" % tid)
    elif status != "READY" and (claims or answer.get("claims")):
        bad("SYNTHESIS_NOT_ALLOWED",
            "%s contract status=%s 却产生了 claims（%d 条）" % (tid, status, len(claims)))
    if perm == "BLOCKED" and (claims or answer.get("claims")):
        bad("SYNTHESIS_NOT_ALLOWED", "%s BLOCKED 却带 claims" % tid)
    # ② schema：claim 结构必须合法
    for v in ((row.get("validation") or {}).get("claim_violations") or []):
        bad(v.get("code") or "SYNTHESIS_SCHEMA_INVALID", "%s %s" % (tid, v.get("detail")))
    for v in ((row.get("validation") or {}).get("answer_violations") or []):
        bad(v.get("code") or "SYNTHESIS_SCHEMA_INVALID", "%s %s" % (tid, v.get("detail")))
    # ③ 硬规则复算（不依赖 adapter 自报）
    usable = {e.get("passage_id"): e for e in (contract.get("usable_evidence") or [])}
    substantive = ("DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
                   "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY", "FORMALISM")
    for c in claims:
        ctype, cid = c.get("claim_type"), c.get("claim_id")
        ids = c.get("evidence_ids") or []
        if ctype in substantive and not ids:
            bad("CLAIM_WITHOUT_EVIDENCE", "%s claim %s(%s) 无 evidence" % (tid, cid, ctype))
        if c.get("epistemic_status") == "UNSUPPORTED":
            bad("CLAIM_WITHOUT_EVIDENCE", "%s claim %s 状态 UNSUPPORTED" % (tid, cid))
        for eid in ids:
            ev = usable.get(eid)
            if ev is None:
                bad("INVALID_CITATION_REFERENCE",
                    "%s claim %s 引用了包外 passage %s" % (tid, cid, eid))
                continue
            if ev.get("citation_eligibility") == "INELIGIBLE":
                bad("SOURCE_ROLE_VIOLATION",
                    "%s claim %s 引用 INELIGIBLE 证据 %s" % (tid, cid, eid))
            elif ctype in substantive and "substantive" not in (ev.get("claim_permissions")
                                                                or []):
                bad("SOURCE_ROLE_VIOLATION",
                    "%s claim %s 用了不能承担 substantive 的 %s" % (tid, cid, eid))
        q = c.get("quotation")
        if q and q.get("kind") == "CORPUS_QUOTE":
            pid, span = q.get("passage_id"), q.get("exact_span")
            ev = usable.get(pid)
            if not (pid and span and q.get("language") and q.get("source_layer")):
                bad("UNSUPPORTED_QUOTATION",
                    "%s claim %s 的引用缺 passage/exact_span/language/source_layer"
                    % (tid, cid))
            elif ev and span not in str(ev.get("text") or ""):
                bad("UNSUPPORTED_QUOTATION",
                    "%s claim %s 的 exact_span 不在 %s 里" % (tid, cid, pid))
    # ④ abstention contract
    if perm == "ABSTAIN":
        ab = answer.get("abstention") or {}
        for f in ("abstention_reason_codes", "missing_information",
                  "available_partial_information", "next_required_sources"):
            if not ab.get(f):
                bad("ABSTENTION_CONTRACT_VIOLATION", "%s abstention 缺 %s" % (tid, f))
    # ⑤ trace 泄漏
    for tok in ((row.get("validation") or {}).get("trace_leaks") or []):
        bad("SYNTHESIS_SCHEMA_INVALID", "%s 答案主体泄漏 pipeline 词 %r" % (tid, tok))
    # ⑥ DIAGNOSTIC 不得声称已人工验证
    if row.get("marker") == "DIAGNOSTIC" and row.get("human_validated"):
        bad("SYNTHESIS_SCHEMA_INVALID", "%s DIAGNOSTIC 却声称 human_validated" % tid)
    return out


def synthesis_run_findings(doc) -> list[dict]:
    """整份 synthesis 结果文档 → findings（含 hard target 复算）。"""
    out = []
    rows = (doc or {}).get("rows") or []
    for r in rows:
        out.extend(synthesis_result_findings(r))
    m = (doc or {}).get("metrics") or {}
    for k in ("claims_without_evidence", "ineligible_citations_used",
              "source_role_violations", "abstention_contract_violations"):
        if m.get(k):
            out.append({"code": "SYNTHESIS_HARD_TARGET_VIOLATED", "severity": "VIOLATION",
                        "detail": "hard target %s = %s（必须为 0）" % (k, m.get(k))})
    return out


# ══════════════════════════════════════════════════════════════════════════
# Gate 21（Phase 4C.1-D）：Claim–Evidence Entailment Integrity
# ══════════════════════════════════════════════════════════════════════════
D_REJECTION = ("NOT_ENTAILED", "CONTRADICTED", "SOURCE_ROLE_MISMATCH")
D_SUBSTANTIVE = ("DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
                 "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY", "FORMALISM")


def synthesis_entailment_findings(doc) -> list[dict]:
    """Gate 21：10 条检查（§36）。只针对 **最终答案里的 claim** 与 entailment 记录。"""
    out = []
    for row in (doc or {}).get("rows") or []:
        tid = row.get("task_id")
        answer = row.get("answer") or {}
        final_claims = answer.get("claims") or []
        results = ((row.get("entailment") or {}).get("results") or [])
        by_cid = {r.get("final_claim_id") or r.get("claim_id"): r for r in results}
        rejected_ids = {r.get("claim_id") for r in
                        ((row.get("entailment") or {}).get("rejected") or [])}

        def bad(code, detail):
            out.append({"code": code, "severity": "VIOLATION",
                        "detail": "%s %s" % (tid, detail)})

        for c in final_claims:
            cid = c.get("claim_id")
            ctype = c.get("claim_type")
            ids = c.get("evidence_ids") or []
            # 1 substantive claim 必须有 evidence（或普查凭据）
            if ctype in D_SUBSTANTIVE and not ids and not c.get("corpus_scan_ref"):
                bad("D_SUBSTANTIVE_CLAIM_WITHOUT_EVIDENCE",
                    "最终答案的 claim %s(%s) 没有证据" % (cid, ctype))
            # 2/3 evidence 必须存在且资格足够（用 input contract 复算）
            contract = row.get("input_contract") or {}
            usable = {e.get("passage_id"): e for e in
                      (contract.get("usable_evidence") or [])}
            for eid in ids:
                ev = usable.get(eid)
                if ev is None:
                    bad("D_INVALID_CITATION_IN_FINAL",
                        "claim %s 引用了包外 passage %s" % (cid, eid))
                elif ev.get("citation_eligibility") == "INELIGIBLE":
                    bad("D_INVALID_CITATION_IN_FINAL",
                        "claim %s 引用了 INELIGIBLE 证据 %s" % (cid, eid))
            # 4 entailment 状态不得是 rejection 状态
            st = (by_cid.get(cid) or {}).get("status")
            if st in D_REJECTION:
                bad("D_REJECTED_CLAIM_IN_FINAL",
                    "claim %s 的 entailment=%s 却出现在最终答案" % (cid, st))
            # 5 quote 必须可核（exact_span 存在）
            q = c.get("quotation")
            if q and q.get("kind") == "CORPUS_QUOTE":
                if not q.get("exact_span"):
                    bad("D_INVALID_QUOTE_IN_FINAL", "claim %s 的引用缺 exact_span" % cid)
                else:
                    ev = usable.get(q.get("passage_id"))
                    if ev and q["exact_span"] not in str(ev.get("text") or "") and \
                            q.get("quotation_dropped") is None:
                        bad("D_INVALID_QUOTE_IN_FINAL",
                            "claim %s 的 exact_span 不在 %s 里"
                            % (cid, q.get("passage_id")))
            # 6 source role：只引 L2/recovered 不得用「原文」措辞
            text = str(c.get("claim_text") or "")
            if re.search(r"拉康原文|法文原文|原文说|原文写道|Lacan\s+dit", text, re.I) \
                    and ids:
                layers = {usable.get(i, {}).get("source_layer") for i in ids}
                if layers and not (layers & {"L1_ORIGINAL", "L1_TRANSCRIPTION"}):
                    bad("D_SOURCE_ROLE_VIOLATION_IN_FINAL",
                        "claim %s 只有 %s 却用「原文」措辞" % (cid, sorted(layers)))
        # 7 rejected claim 不得进入最终答案
        for cid in rejected_ids:
            if cid in {c.get("claim_id") for c in final_claims}:
                bad("D_REJECTED_CLAIM_IN_FINAL", "被 reject 的 %s 出现在最终答案" % cid)
        # 8 abstention 答案不得含 substantive claim
        if (row.get("answer_permission") == "ABSTAIN") and \
                (answer.get("answer_state") == "ABSTAINED"):
            for c in final_claims:
                if c.get("claim_type") in D_SUBSTANTIVE:
                    bad("D_ABSTENTION_CONTAINS_SUBSTANTIVE_CLAIM",
                        "弃权答案里出现 substantive claim %s" % c.get("claim_id"))
        # 9 validated answer 只能由 validated claim set 渲染
        validated_ids = {c.get("claim_id") for c in (row.get("validated_claims") or [])}
        for c in final_claims:
            if c.get("claim_id") not in validated_ids and not c.get("corpus_scan_ref"):
                bad("D_FINAL_CLAIM_NOT_IN_VALIDATED_SET",
                    "最终答案的 claim %s 不在 validated claim set 里" % c.get("claim_id"))
        # 10 corpus absence / metadata claim 必须有普查凭据
        for c in final_claims:
            if c.get("claim_type") in ("CORPUS_ABSENCE", "METADATA") and \
                    not c.get("corpus_scan_ref"):
                bad("D_ABSENCE_CLAIM_WITHOUT_SCAN_PROVENANCE",
                    "claim %s(%s) 没有 corpus_scan_ref" % (c.get("claim_id"),
                                                           c.get("claim_type")))
    return out


# ── A3：manifest 哈希 ─────────────────────────────────────────────────────
ENGINE_FILES = {
    "research_answer": "_scripts/_tools/research_answer.py",
    "research_agent": "_scripts/_tools/lacan_mcp/research_agent.py",
    "evidence_sufficiency_v2": "_scripts/_tools/lacan_mcp/evidence_sufficiency_v2.py",
    "evidence_sufficiency_v1": "_scripts/_tools/lacan_mcp/evidence_sufficiency.py",
    "knowledge_api": "_scripts/_tools/lacan_mcp/knowledge_api.py",
    "ontology_gaps": "_scripts/_tools/lacan_mcp/ontology_gaps.py",
    "citations": "_scripts/_tools/lacan_mcp/citations.py",
    "gold_normalization": "_scripts/_tools/gold_normalization.py",
    "eval_integrity": "_scripts/_tools/eval_integrity.py",
    # Phase 4C.1-B：契约层与 v2.1 充分性层也是「引擎」——必须一起绑定版本
    "research_contract": "_scripts/_tools/research_contract.py",
    "evidence_sufficiency_v21": "_scripts/_tools/evidence_sufficiency_v21.py",
    "run_diagnostic_4c1b": "_scripts/_tools/run_diagnostic_4c1b.py",
    "build_gold_v2": "_scripts/_tools/build_gold_v2.py",
    # Phase 4C.1-B2：执行层也是引擎的一部分（required operation 真的进执行层这件事
    # 由 research_execution.py 决定，必须与版本绑定）
    "research_execution": "_scripts/_tools/research_execution.py",
    "run_diagnostic_4c1b2": "_scripts/_tools/run_diagnostic_4c1b2.py",
    # Phase 4C.1-B3：执行闭环诊断器也是引擎的一部分
    "run_diagnostic_4c1b3": "_scripts/_tools/run_diagnostic_4c1b3.py",
    # Phase 4C.1-C：synthesis 边界契约 / claim schema / renderer / adapter / run 工具
    "synthesis_contract": "_scripts/_tools/synthesis_contract.py",
    "synthesis_claims": "_scripts/_tools/synthesis_claims.py",
    "synthesis_render": "_scripts/_tools/synthesis_render.py",
    "synthesis_adapters": "_scripts/_tools/synthesis_adapters.py",
    "run_synthesis_4c1c": "_scripts/_tools/run_synthesis_4c1c.py",
    # Phase 4C.1-D：蕴含验证 + 流水线 + 对抗/校准 + 真实 LLM 诊断器
    "synthesis_entailment": "_scripts/_tools/synthesis_entailment.py",
    "synthesis_validation": "_scripts/_tools/synthesis_validation.py",
    "synthesis_adversarial": "_scripts/_tools/synthesis_adversarial.py",
    "run_synthesis_4c1d": "_scripts/_tools/run_synthesis_4c1d.py",
    "build_entailment_calibration": "_scripts/_tools/build_entailment_calibration.py",
}
DATA_FILES = {
    "research_tasks_v1": "_data/eval/research_tasks_v1.jsonl",
    "gold_derivation_v1": "_data/eval/research_tasks_v1.gold_derivation.json",
    "research_eval_results_v4c": "_data/eval/research_eval_results.v4c.json",
    "human_review_records": "_data/eval/research_human_review.jsonl",
    "human_adjudication_queue": "_data/eval/human_adjudication_queue.jsonl",
    "human_review_results_v1": "_data/eval/human_review_results_v1.json",
    "seminars": "_data/passage_store/seminars.jsonl",
    "ontology_entities_v4a1": "_data/ontology/v4a1/entities.jsonl",
    "ontology_term_mappings_v4a1": "_data/ontology/v4a1/term_mappings.jsonl",
    "alias_index": "_data/index/alias_index.jsonl",
    "terminology_bridge": "_data/terminology_bridge.jsonl",
    # Phase 4C.1-B 产物（版本化新文件，不覆盖 v1）
    "gold_v2_tasks": "_data/eval/gold_v2/research_tasks_v2.jsonl",
    "gold_v2_overrides": "_data/eval/gold_v2/lane_overrides_v1.json",
    "scholarly_regression": "_data/eval/scholarly_regression_v1.jsonl",
    "gold_lane_audit": "_data/eval/gold_lane_audit_v1.jsonl",
    "research_contract_schema": "_data/eval/research_contract.schema.json",
    "evaluation_run_manifest_schema": "_data/eval/evaluation_run_manifest.schema.json",
    # B2 事故恢复快照（B3 §13 记录在案；不得被当作可重算产物）
    "b2_metrics_snapshot": "_data/eval/research_eval_results.4c1b2.metrics_snapshot.json",
    # Phase 4C.1-D 校准集
    "entailment_calibration": "_data/eval/claim_entailment_calibration_v1.jsonl",
}
# **派生视图**（含 generated_at，每次生成都会变）——记录但不参与「内容可复现」比对，
# 否则「跑一次套件 → 派生文件被重写 → manifest 假红」。
DERIVED_FILES = {
    "manual_review_lanes": "_data/eval/gold_v2/manual_review_lanes_v1.json",
    "trace_integrity_baseline": "_data/eval/trace_integrity_baseline_v1.json",
    "diagnostic_results_4c1b": "_data/eval/research_eval_results.4c1b.json",
    # Phase 4C.1-B2 派生视图（含 generated_at）
    "diagnostic_results_4c1b2": "_data/eval/research_eval_results.4c1b2.json",
    "research_traces_4c1b2": "_data/eval/research_traces_4c1b2",
    # Phase 4C.1-B3 派生视图 + 事故恢复快照
    "diagnostic_results_4c1b3": "_data/eval/research_eval_results.4c1b3.json",
    "research_traces_4c1b3": "_data/eval/research_traces_4c1b3",
    # Phase 4C.1-C：synthesis 输入契约模板（任务无关的数据）——
    # 逐次 run 的产物在 _data/eval/runs/<run_id>/ 下，由 run manifest 自己钉住
    "research_synthesis_results_4c1c": "_data/eval/research_synthesis_results.4c1c.json",
    "synthesis_runs_dir": "_data/eval/runs",
}


def derived_hashes() -> dict:
    return _digest_map(DERIVED_FILES)


# 大文件单独记录（hashing 仍需读一遍，但只记 digest + size + n_lines）
HEAVY_FILES = {"passage_store": "_data/passage_store/passages.jsonl"}


def sha256_file(path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def dir_digest(path):
    """目录 → 内容摘要（逐文件 sha256 排序后合并）。用于 trace/runs 目录级绑定。"""
    h = hashlib.sha256()
    n = 0
    for root, _dirs, names in os.walk(path):
        for fn in sorted(names):
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, path)
            h.update(rel.encode("utf-8"))
            h.update(sha256_file(fp).encode("utf-8"))
            n += 1
    return h.hexdigest(), n


def _digest_map(files) -> dict:
    out = {}
    for name, rel in files.items():
        p = os.path.join(VAULT, rel)
        if os.path.isdir(p):
            dig, n = dir_digest(p)
            out[name] = {"path": rel, "sha256": dig, "kind": "dir", "n_files": n}
        elif os.path.isfile(p):
            out[name] = {"path": rel, "sha256": sha256_file(p),
                         "size": os.path.getsize(p)}
        else:
            out[name] = {"path": rel, "sha256": None, "size": None,
                         "missing": True}
    return out


def engine_hashes() -> dict:
    return _digest_map(ENGINE_FILES)


def data_hashes() -> dict:
    return _digest_map(DATA_FILES)


def passage_store_digest() -> dict:
    out = {}
    for name, rel in HEAVY_FILES.items():
        p = os.path.join(VAULT, rel)
        if not os.path.isfile(p):
            out[name] = {"path": rel, "sha256": None, "missing": True}
            continue
        n = 0
        with open(p, "rb") as f:
            for _ in f:
                n += 1
        out[name] = {"path": rel, "sha256": sha256_file(p),
                     "size": os.path.getsize(p), "n_lines": n}
    return out


def combined_digest(d: dict) -> str:
    """对一组 {name: {sha256}} 做确定性合并摘要（用于 *_version 字段）。"""
    items = sorted((k, (v or {}).get("sha256") or "missing")
                   for k, v in (d or {}).items())
    h = hashlib.sha256()
    for k, v in items:
        h.update(("%s=%s\n" % (k, v)).encode("utf-8"))
    return h.hexdigest()


def git_commit() -> str:
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=VAULT,
                           capture_output=True, text=True)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def git_dirty() -> bool:
    import subprocess
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=VAULT,
                           capture_output=True, text=True)
        return bool(r.stdout.strip())
    except Exception:
        return True


def jd(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def jl(p):
    try:
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except Exception:
        return []


__all__ = [n for n in dir() if not n.startswith("_")]
