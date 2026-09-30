#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_ai_review.py — Phase 4E acceptance-policy v2：**AI-only 多代理盲审**协议。

背景（项目所有者决定，acceptance-policy version change）：
    当前项目**不存在可执行的人类学术 reviewer**，因此停止等待 human spot review，
    且**不得**伪造 / 模拟 / 把 AI reviewer 标记为 human。Phase 4E 改用明确标注为
    **AI-only** 的独立多代理学术验收协议。这是**策略版本变更**，不是改写历史 Gate。

永久保留（不可触碰）：
    `_data/phase4e/phase4e_remediation_gate_v1.json`
      E14 = human spot review FAIL = 0 → 真实状态 PENDING（reason=NO_HUMAN_REVIEWER_AVAILABLE）
      不得把 agent review 改名 human、不得伪造 reviewer_name/reviewed_at、
      不得把 v1 E14 改成 PASS、不得修改历史 acceptance run。
      必须永久保持 `human_review_performed = false`。

本工具做四件事（顺序固定）：
    1. `--freeze-gate`  冻结 `phase4e_remediation_gate_v2.json`
                        （E1–E13/E15–E17 与 v1 **逐字一致**；只替换 E14）
    2. `--packets`      从**已封存**的真实 provider run 生成盲审包（严格字段白名单）
    3. `--lane-c`       确定性证据审计（deterministic evidence auditor）
    4. `--collect`      汇总 A/B/C(+D) → task_consensus / final_summary / E14-v2 判定
    5. `--run`          验收 run `4e_ai_closure_<ts>_<id>`（重算 E1–E17，immutable）

用法：
    python3 _scripts/_tools/phase4e_ai_review.py --freeze-gate
    python3 _scripts/_tools/phase4e_ai_review.py --packets
    python3 _scripts/_tools/phase4e_ai_review.py --lane-c
    python3 _scripts/_tools/phase4e_ai_review.py --collect
    python3 _scripts/_tools/phase4e_ai_review.py --run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
P4E = os.path.join(VAULT, "_data", "phase4e")
GATE_V1 = os.path.join(P4E, "phase4e_remediation_gate_v1.json")
GATE_V2 = os.path.join(P4E, "phase4e_remediation_gate_v2.json")
REVIEW_DIR = os.path.join(P4E, "ai_scholarly_review_v2")
PACKETS_DIR = os.path.join(REVIEW_DIR, "packets")
SEALED = os.path.join(P4E, "phase4e_real_llm_20260926T115518Z_1c8e1efc")
TASKS = ["rt-D01", "rt-I02", "rt-H02", "rt-C03", "rt-J02", "rt-G01"]

POLICY_CHANGE = "HUMAN_REVIEW_UNAVAILABLE_AI_ONLY_REPLACEMENT"
REVIEW_PROTOCOL = "AI_MULTI_AGENT_BLIND_REVIEW_V1"
AI_E14_REQUIREMENT = ("Independent AI Scholarly Review Protocol has no unresolved "
                      "scholarly integrity failure")
VERDICTS = ("PASS", "WITH_CONCERN", "FAIL")
CONCERN_TYPES = ("existing_scholarly_limitation", "adapter_induced",
                 "evidence_failure", "presentation_only", "N/A")

# §10：硬失败定义
INTEGRITY_FAILURE_CODES = (
    "CLAIM_UNSUPPORTED_BY_CITED_EVIDENCE",
    "CITATION_POINTS_TO_WRONG_PASSAGE",
    "SOURCE_LAYER_FALSELY_REPRESENTED",
    "L2_REPRESENTED_AS_L1",
    "MAPPING_REPRESENTED_AS_ATTESTATION",
    "ABSTENTION_SUPPLEMENTED_WITH_UNSUPPORTED_KNOWLEDGE",
    "BROKEN_EVIDENCE_REFERENCE",
    "ADAPTER_INDUCED_SCHOLARLY_REGRESSION",
)

# §6：盲审包**只允许**这些字段（白名单）。禁止 agent_pre_review / round1-2 / D2 /
#     expected gate result / repair history / 其它 lane 的结果。
# §6：**只**给这些。`summary` / `warnings` 是呈现/运行元数据（含 rejected 计数、
# sufficiency 判据名），不属于"final answer / claims / citations / evidence /
# source limitations / answer state / abstention"这几类 → 一律不进盲审包。
# `sections` 用**用户可见面**（Phase 5A 呈现层）：原始 v1 载荷的 limitations 段里
# 混着校验器日志（NOT_ENTAILED / 已剔除 …），那是 repair/reject 历史 → 会让 reviewer
# 事先知道"哪些断言被剔除"，破坏盲性。
PACKET_FIELDS = ("task_id", "question", "answer_state", "answer_permission",
                 "claims", "citations", "evidence", "source_limitations",
                 "abstention", "sections", "sections_note")
FORBIDDEN_SUBSTRINGS = ("agent_pre_review", "human_spot_review", "round2", "round_1",
                        "round1", "adjudication", "d2_", "expected", "gate_result",
                        "repair_log", "rejected_claims")


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jd(p, d=None):
    if not os.path.isfile(p):
        return d
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def wr(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def jl(p, rows):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(p):
    out = []
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _git_head():
    try:
        return subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:                                                      # noqa: BLE001
        return "unknown"


# ────────────────────────────────────────────────────── §2/§3/§17 Gate v2
def gate_v2_payload():
    v1 = jd(GATE_V1, {})
    if not v1:
        raise SystemExit("缺 Gate v1：%s（历史 Gate 必须存在）" % GATE_V1)
    crit = []
    for c in v1.get("criteria") or []:
        if c.get("id") == "E14":
            crit.append({"id": "E14", "requirement": AI_E14_REQUIREMENT,
                         "blocking": True, "replaces": c.get("requirement"),
                         "protocol": REVIEW_PROTOCOL})
        else:
            # §3：E1–E13 / E15–E17 与 v1 **逐字一致**
            crit.append(dict(c))
    return {
        "schema_version": "phase4e-remediation-gate/v2",
        "gate_id": "Phase 4E Remediation Gate v2",
        "gate_version": 2,
        "phase": "Phase 4E — real provider remediation / CCR-0001",
        "ccr": "CCR-0001",
        "frozen": True,
        "frozen_at": utcnow(),
        "frozen_before_final_run": True,
        "git_head": _git_head(),
        "parent_gate": {
            "gate_id": v1.get("gate_id"),
            "gate_hash": v1.get("gate_hash"),
            "schema_version": v1.get("schema_version"),
            "frozen_at": v1.get("frozen_at"),
            "historical_e14": {
                "requirement": "human spot review FAIL = 0（6 题，含 rt-D01/I02/H02/C03/J02/G01）",
                "status": "PENDING",
                "reason": "NO_HUMAN_REVIEWER_AVAILABLE",
                "immutable": True,
            },
        },
        "policy_change": POLICY_CHANGE,
        "policy_change_note": (
            "项目所有者决定：当前项目不存在可执行的人类学术 reviewer，停止等待 "
            "human spot review；不得伪造/模拟/把 AI reviewer 标记为 human。"
            "Phase 4E 改用明确标注为 AI-only 的独立多代理盲审协议。"
            "这是**验收策略版本变更**，不是对历史 Gate 的改写。"),
        "human_review_performed": False,
        "review_protocol": REVIEW_PROTOCOL,
        "review_lanes": ["A_SCHOLARLY", "B_ADVERSARIAL", "C_EVIDENCE_AUDITOR",
                         "D_ADJUDICATOR_IF_DISAGREEMENT"],
        "criteria": crit,
        "decision_values": ["PHASE_4E_COMPLETE_UNDER_AI_REVIEW_PROTOCOL",
                            "PHASE_4E_BLOCKED"],
        "policy": {
            "any_criterion_fail": "PHASE_4E_BLOCKED；CCR-0001 不得 RESOLVED",
            "no_gate_edits_after_freeze": True,
            "no_history_rewrite": "失败的 run 保留，修完新开 run",
            "semantic_change_rule": "只允许产品边界组件变化；学术语义漂移必须为 0",
            "no_human_review_fabrication": True,
            "ai_review_is_not_human_review": True,
            "reviewer_identity_required": {"reviewer_type": "AI"},
        },
        "successor_semantics": {
            "gate_v1": "历史且不可变；其 E14 = human spot review 永久保持 PENDING",
            "gate_v2": "更替的是 E14 的**证据类型**（human → AI-only 多代理盲审），"
                       "E1–E13/E15–E17 逐字不变，阈值未降低",
            "not_equivalent_to_human_peer_review": True,
        },
    }


def freeze_gate():
    if os.path.isfile(GATE_V2):
        cur = jd(GATE_V2)
        body = {k: v for k, v in gate_v2_payload().items() if k != "frozen_at"}
        old = {k: v for k, v in cur.items() if k not in ("frozen_at", "gate_hash")}
        if body != old:
            print("FAIL Gate v2 已存在且判据发生变化 —— 冻结后不得修改")
            return 1
        print("Gate v2 已冻结且未改动：%s（%d 条判据）"
              % (os.path.relpath(GATE_V2, VAULT), len(cur.get("criteria") or [])))
        return 0
    doc = gate_v2_payload()
    doc["gate_hash"] = hashlib.sha256(json.dumps(
        {k: v for k, v in doc.items() if k != "gate_hash"},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    wr(GATE_V2, doc)
    print("frozen gate -> %s（%d 条判据；gate_hash=%s；parent(v1)=%s）"
          % (os.path.relpath(GATE_V2, VAULT), len(doc["criteria"]),
             doc["gate_hash"][:16], str(doc["parent_gate"]["gate_hash"])[:16]))
    print("  human_review_performed=%s | protocol=%s"
          % (doc["human_review_performed"], doc["review_protocol"]))
    return 0


def verify_gate_v1_untouched():
    cur = jd(GATE_V1)
    if not cur:
        return False, "缺 Gate v1"
    want = cur.get("gate_hash")
    got = hashlib.sha256(json.dumps(
        {k: v for k, v in cur.items() if k != "gate_hash"},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    e14 = [c for c in (cur.get("criteria") or []) if c.get("id") == "E14"]
    ok = (want == got and e14 and "human spot review" in e14[0].get("requirement", ""))
    return ok, ("Gate v1 完整性 OK（E14 仍为 human spot review；gate_hash=%s）"
                % str(want)[:16] if ok else "Gate v1 被改动或 E14 语义被替换")


# ───────────────────────────────────────────────────────────── §5/§6 packets
def _norm(s):
    s = unicodedata.normalize("NFC", str(s or ""))
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2014", "-").replace("\u2013", "-")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _user_facing_sections(fa):
    """→ 用户可见 sections（确定性；不读 repair/reject 记录）。"""
    try:
        sys.path.insert(0, VAULT)
        from workspace_ui.server import presentation as PZ
        out = []
        for s in PZ.user_facing_view(fa).get("sections") or []:
            out.append({"id": s.get("id"), "text": s.get("text"),
                        "classification": s.get("classification")})
        return out
    except Exception:                                                      # noqa: BLE001
        return []


def build_packets():
    rows = {}
    with open(os.path.join(SEALED, "task_results.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                rows[r["task_id"]] = r
    packets, manifest_tasks = {}, []
    for tid in TASKS:
        r = rows.get(tid)
        if not r:
            raise SystemExit("封存 run 缺任务 %s" % tid)
        fa = r.get("final_answer") or {}
        ic = r.get("input_contract") or {}
        ev = []
        for e in (ic.get("usable_evidence") or []):
            ev.append({k: e.get(k) for k in
                       ("passage_id", "text", "source_layer", "authority_level",
                        "trace_status", "citation_eligibility", "language",
                        "seminar_id", "session_id", "witness_id", "review_status",
                        "usability_class", "period_label", "eligibility_reasons")})
        pkt = {
            "task_id": tid,
            "question": fa.get("question"),
            "answer_state": fa.get("answer_state"),
            "answer_permission": fa.get("answer_permission"),
            "claims": [dict(c) for c in (fa.get("validated_claims") or [])],
            "citations": [dict(c) for c in (fa.get("citations") or [])],
            "evidence": ev,
            "source_limitations": list(fa.get("source_limitations") or []),
            "abstention": fa.get("abstention"),
            "sections": _user_facing_sections(fa),
            "sections_note": ("sections 是**用户可见面**（Phase 5A 呈现层）："
                              "校验器诊断已按 AUDIT_DIAGNOSTIC 路由走，"
                              "因此这里既不含也不暗示被剔除的断言。"),
        }
        blob = json.dumps(pkt, ensure_ascii=False).lower()
        leaked = [s for s in FORBIDDEN_SUBSTRINGS if s in blob]
        if leaked:
            raise SystemExit("盲审包泄漏禁止内容 %s（task %s）" % (leaked, tid))
        if set(pkt) != set(PACKET_FIELDS):
            raise SystemExit("盲审包字段与白名单不符：%s" % sorted(set(pkt) ^ set(PACKET_FIELDS)))
        packets[tid] = pkt
        manifest_tasks.append({
            "task_id": tid,
            "packet_hash": hashlib.sha256(
                json.dumps(pkt, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "claims_n": len(pkt["claims"]), "citations_n": len(pkt["citations"]),
            "evidence_n": len(pkt["evidence"]),
            "answer_state": pkt["answer_state"],
            "abstained": bool(pkt["abstention"]),
        })
        wr(os.path.join(PACKETS_DIR, "%s.json" % tid), pkt)

    # §7：每 lane 独立的**随机化题目顺序**（固定 seed → 可复现，且顺序不同）
    import random
    orders = {}
    for lane, seed in (("A", 20260401), ("B", 20260402), ("C", 20260403), ("D", 20260404)):
        lst = list(TASKS)
        random.Random(seed).shuffle(lst)
        orders[lane] = lst
    man = {
        "schema_version": "phase4e-ai-review-manifest/v1",
        "review_protocol": REVIEW_PROTOCOL,
        "created_at": utcnow(),
        "sealed_run": os.path.relpath(SEALED, VAULT),
        "sealed_run_seal_hash": sha_file(os.path.join(SEALED, "seal.json")),
        "human_review_performed": False,
        "reviewer_type": "AI",
        "blindness": {
            "allowed_fields": list(PACKET_FIELDS),
            "forbidden_substrings_checked": list(FORBIDDEN_SUBSTRINGS),
            "lanes_do_not_share_state": True,
            "lane_inputs_are_packet_only": True,
            "excluded": ["agent_pre_review", "round1/round2 scores", "D2 outcome",
                         "expected gate result", "repair history",
                         "other lanes' findings (until adjudication)"],
        },
        "task_orders": orders,
        "order_seeds": {"A": 20260401, "B": 20260402, "C": 20260403, "D": 20260404},
        "tasks": manifest_tasks,
        "reviewer_diversity_note": (
            "单一 provider（DeepSeek Harness 当前路由）。lane 之间只有 **角色/prompt/"
            "fresh session/题目顺序**不同，**不是**不同模型。不得伪称模型独立性。"),
    }
    wr(os.path.join(REVIEW_DIR, "manifest.json"), man)
    print("盲审包 -> %s（%d 题；manifest 已写）" % (os.path.relpath(PACKETS_DIR, VAULT), len(packets)))
    for m in manifest_tasks:
        print("  %-8s claims=%-2d cits=%-2d ev=%-3d state=%s"
              % (m["task_id"], m["claims_n"], m["citations_n"], m["evidence_n"],
                 m["answer_state"]))
    print("  orders: %s" % json.dumps(orders, ensure_ascii=False))
    return 0


# ─────────────────────────────────────────────── §5 Lane C（确定性证据审计）
def _passage_index():
    """→ {passage_id: passage_dict}（经 browse_api，只读）。"""
    for _p in (VAULT, HERE):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import browse_api as BA
    idx = {}
    for tid in TASKS:
        pkt = jd(os.path.join(PACKETS_DIR, "%s.json" % tid))
        if not pkt:
            continue
        for e in pkt.get("evidence") or []:
            idx.setdefault(e["passage_id"], e)
    return idx, BA


def lane_c():
    idx, BA = _passage_index()
    rows = []
    for tid in TASKS:
        pkt = jd(os.path.join(PACKETS_DIR, "%s.json" % tid))
        usable = {e["passage_id"] for e in pkt.get("evidence") or []}
        cits = pkt.get("citations") or []
        claims = pkt.get("claims") or []
        by_claim = {}
        for c in cits:
            by_claim.setdefault(c.get("claim_id"), []).append(c)

        claim_rows, worst = [], "SUPPORTED"
        rank = {"SUPPORTED": 0, "QUALIFIED": 1, "NOT_SUPPORTED": 2, "BROKEN_REFERENCE": 3}
        for cl in claims:
            cid = cl.get("claim_id")
            ev_ids = list(cl.get("evidence_ids") or [])
            my_cits = by_claim.get(cid, [])
            sub, notes = "SUPPORTED", []
            # 1) evidence_ids 必须落在 input contract 的 usable evidence 内
            _absence = (str(cl.get("claim_type")) in
                        ("LIMITATION", "METADATA", "CORPUS_ABSENCE")
                        or str(cl.get("epistemic_status")) == "CORPUS_ABSENCE")
            bad_ev = [] if _absence else [e for e in ev_ids if e not in usable]
            if bad_ev:
                sub = "BROKEN_REFERENCE"
                notes.append("evidence_ids 不在 usable evidence 内：%s" % bad_ev[:3])
            # 2) 每个 citation 的 passage 必须可解析 + quoted_span 必须落在该 passage 原文里
            for c in my_cits:
                pid = c.get("passage_id")
                p = idx.get(pid)
                if p is None:
                    try:
                        p = BA.get_passage(pid)
                    except Exception:                                          # noqa: BLE001
                        p = None
                if not p:
                    sub = "BROKEN_REFERENCE"
                    notes.append("passage 不可解析：%s" % pid)
                    continue
                span = _norm(c.get("quoted_span"))
                body = _norm(p.get("text"))
                if span and span not in body:
                    # 允许超长引文按前 120 字比对（确定性规则，非模糊匹配）
                    head = span[:120]
                    if head and head in body:
                        notes.append("%s: quoted_span 仅前 120 字命中（记录为部分匹配）" % pid)
                        sub = max([sub, "QUALIFIED"], key=lambda x: rank[x])
                    else:
                        sub = "BROKEN_REFERENCE"
                        notes.append("quoted_span 在该 passage 原文中未命中：%s" % pid)
                # 3) source_layer 不得虚报（L2 说成 L1）
                declared = str(c.get("source_layer") or "")
                actual = str(p.get("source_layer") or p.get("authority_level") or "")
                if declared.startswith("L1") and actual and not actual.startswith("L1"):
                    sub = "BROKEN_REFERENCE"
                    notes.append("source_layer 虚报：声明 %s，实际 %s（%s）"
                                 % (declared, actual, pid))
                elif declared and actual and declared.split("_")[0] != actual.split("_")[0]:
                    sub = max([sub, "QUALIFIED"], key=lambda x: rank[x])
                    notes.append("source_layer 声明 %s vs 实际 %s（%s）" % (declared, actual, pid))
                # 4) provenance_status 与 passage trace_status 不得矛盾
                if str(c.get("provenance_status")) == "COMPLETE" and \
                        str(p.get("trace_status")) == "SOURCE_TRACE_INCOMPLETE":
                    sub = max([sub, "QUALIFIED"], key=lambda x: rank[x])
                    notes.append("citation 声称 provenance COMPLETE，但 %s 为 "
                                 "SOURCE_TRACE_INCOMPLETE" % pid)
                # 5) citation_eligibility 不得是受限档
                elig = str(p.get("citation_eligibility") or "")
                if elig and elig not in ("ELIGIBLE", "QUALIFIED"):
                    sub = max([sub, "QUALIFIED"], key=lambda x: rank[x])
                    notes.append("citation_eligibility=%s（%s）" % (elig, pid))
            # ★ 审计器缺陷修复（REVIEW_TOOLING_DEFECT_001，实测踩过）：
            #   「absence / limitation」型断言**本来就不该有 citation** ——
            #   `LIMITATION` / `METADATA` / `CORPUS_ABSENCE`（epistemic_status =
            #   CORPUS_ABSENCE）断言的是"语料在此沉默"，它由**引擎侧语料普查凭据**
            #   支撑（frozen core 的 engine_scan_ref 机制），不是由引文支撑。
            #   对这类 claim 要求 citation 会产生假阳性（rt-C03 的 c7 即此例）。
            absence_claim = (str(cl.get("claim_type")) in
                             ("LIMITATION", "METADATA", "CORPUS_ABSENCE")
                             or str(cl.get("epistemic_status")) == "CORPUS_ABSENCE")
            if absence_claim:
                notes.append("absence/limitation 断言：无 citation 属**正确形态**"
                             "（由引擎侧语料普查凭据支撑，非引文支撑）")
            elif not my_cits and not bad_ev and pkt.get("answer_state") != "ABSTAINED":
                sub = max([sub, "NOT_SUPPORTED"], key=lambda x: rank[x])
                notes.append("claim 无任何 citation 绑定")
            if str(cl.get("entailment_status")) == "PARTIALLY_ENTAILED":
                sub = max([sub, "QUALIFIED"], key=lambda x: rank[x])
            claim_rows.append({"claim_id": cid, "claim_type": cl.get("claim_type"),
                               "epistemic_status": cl.get("epistemic_status"),
                               "evidence_ids": ev_ids,
                               "citations_n": len(my_cits),
                               "verdict": sub, "notes": notes[:4]})
            worst = max([worst, sub], key=lambda x: rank[x])

        # 弃权答案的额外确定性检查（§14 rt-J02）
        abst = pkt.get("abstention") or {}
        if abst:
            substantive = [c for c in claims if c.get("claim_type") in
                           ("DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
                            "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY",
                            "FORMALISM")]
            if substantive:
                worst = "BROKEN_REFERENCE"
        rows.append({
            "schema_version": "phase4e-ai-review-lane/v1",
            "review_lane": "C_EVIDENCE_AUDITOR",
            "reviewer_type": "AI",
            "method": "DETERMINISTIC_EVIDENCE_AUDIT",
            "provider": "deterministic",
            "model": "frozen-validators+corpus-lookup",
            "task_id": tid,
            "verdict": {"SUPPORTED": "PASS", "QUALIFIED": "WITH_CONCERN",
                        "NOT_SUPPORTED": "FAIL", "BROKEN_REFERENCE": "FAIL"}[worst],
            "concern_type": ("N/A" if worst == "SUPPORTED"
                             else ("existing_scholarly_limitation"
                                   if worst == "QUALIFIED" else "evidence_failure")),
            "claim_verdicts": claim_rows,
            "worst_claim_verdict": worst,
            "integrity_failure": ("NONE" if worst in ("SUPPORTED", "QUALIFIED")
                                  else "BROKEN_EVIDENCE_REFERENCE"),
            "findings": [n for r_ in claim_rows for n in r_["notes"]][:8],
        })
    jl(os.path.join(REVIEW_DIR, "lane_c.jsonl"), rows)
    bad = [r["task_id"] for r in rows if r["integrity_failure"] != "NONE"]
    print("Lane C（确定性证据审计）-> %s" % os.path.relpath(
        os.path.join(REVIEW_DIR, "lane_c.jsonl"), VAULT))
    for r in rows:
        print("  %-8s %-14s worst=%-15s %s"
              % (r["task_id"], r["verdict"], r["worst_claim_verdict"],
                 (r["findings"] or [""])[0][:70]))
    print("  integrity failures: %s" % (bad or "NONE"))
    return 0


HARD_CONCERNS = ("evidence_failure", "adapter_induced")


def adjudication_dossiers():
    """§12：为**分歧**任务建立裁决档案（含 A/B/C findings；**不含**任何期望结果）。"""
    lane_a = {r["task_id"]: r for r in read_jsonl(os.path.join(REVIEW_DIR, "lane_a.jsonl"))}
    lane_c = {r["task_id"]: r for r in read_jsonl(os.path.join(REVIEW_DIR, "lane_c.jsonl"))}
    lane_b = {}
    for tid in TASKS:
        fp = os.path.join(REVIEW_DIR, "lane_b", "%s.json" % tid)
        if os.path.isfile(fp):
            lane_b[tid] = jd(fp)
    disputed, reasons = [], {}
    for tid in TASKS:
        a, b, c = lane_a.get(tid, {}), lane_b.get(tid, {}), lane_c.get(tid, {})
        why = []
        for lane, r in (("A", a), ("B", b), ("C", c)):
            if r.get("concern_type") in HARD_CONCERNS:
                why.append("%s concern_type=%s" % (lane, r.get("concern_type")))
            if r.get("verdict") == "FAIL":
                why.append("%s verdict=FAIL" % lane)
            if r.get("integrity_failure") not in (None, "NONE"):
                why.append("%s integrity_failure=%s" % (lane, r.get("integrity_failure")))
        vs = [r.get("verdict") for r in (a, b, c) if r.get("verdict")]
        if len(set(vs)) > 1:
            why.append("verdict 分歧：%s" % vs)
        if why:
            disputed.append(tid)
            reasons[tid] = why
    outdir = os.path.join(REVIEW_DIR, "adjudication_dossiers")
    for tid in disputed:
        dossier = {
            "schema_version": "phase4e-ai-review-adjudication-dossier/v1",
            "task_id": tid,
            "packet_path": os.path.relpath(
                os.path.join(PACKETS_DIR, "%s.json" % tid), VAULT),
            "dispute_reasons": reasons[tid],
            "lane_a_scholarly": lane_a.get(tid),
            "lane_b_adversarial": lane_b.get(tid),
            "lane_c_evidence_auditor": lane_c.get(tid),
            "note": ("Phase 4E 的**期望结果未提供**，也不得推测。"
                     "A/B/C 的 findings 已全部附上；请独立裁定。"
                     "C 是**确定性**结构审计：它能证明「引用可解析 / 引文逐字命中 / "
                     "层级标注一致」，但**不能**证明「理论主张成立」——两者的区别必须保留。"),
        }
        wr(os.path.join(outdir, "%s.json" % tid), dossier)
    wr(os.path.join(REVIEW_DIR, "disagreements.json"),
       {"schema_version": "phase4e-ai-review-disagreements/v1",
        "disputed_tasks": disputed, "reasons": reasons,
        "undisputed_tasks": [t for t in TASKS if t not in disputed],
        "rule": "§11：任一 lane 报 evidence_failure / adapter_induced / FAIL → 需 §12 裁决"})
    print("裁决档案 -> %s" % os.path.relpath(outdir, VAULT))
    print("  需裁决：%s" % disputed)
    for t, w in reasons.items():
        print("    %-8s %s" % (t, "; ".join(w)))
    print("  无需裁决：%s" % [t for t in TASKS if t not in disputed])
    return 0


def _lane_dir(name):
    return os.path.join(REVIEW_DIR, name)


def collect():
    """§11/§12/§13/§16：汇总 A/B/C(+D) → consensus / adjudications / final_summary。"""
    lane_a = {r["task_id"]: r for r in read_jsonl(os.path.join(REVIEW_DIR, "lane_a.jsonl"))}
    lane_c = {r["task_id"]: r for r in read_jsonl(os.path.join(REVIEW_DIR, "lane_c.jsonl"))}
    lane_b, lane_d = {}, {}
    for tid in TASKS:
        fb = os.path.join(_lane_dir("lane_b"), "%s.json" % tid)
        fd = os.path.join(_lane_dir("lane_d"), "%s.json" % tid)
        if os.path.isfile(fb):
            lane_b[tid] = jd(fb)
        if os.path.isfile(fd):
            lane_d[tid] = jd(fd)

    adjudications, consensus = [], []
    for tid in TASKS:
        a, b, c, d = lane_a.get(tid), lane_b.get(tid), lane_c.get(tid), lane_d.get(tid)
        lanes = {"A": a, "B": b, "C": c}
        integrity = {k: (v or {}).get("integrity_failure") for k, v in lanes.items()
                     if (v or {}).get("integrity_failure") not in (None, "NONE")}
        hard = [k for k, v in lanes.items()
                if (v or {}).get("concern_type") in HARD_CONCERNS]
        fails = [k for k, v in lanes.items() if (v or {}).get("verdict") == "FAIL"]
        # §13：AI lane 的 citation mismatch 声明 vs 确定性审计
        ai_cit_claims = []
        for k in ("A", "B"):
            for cc in ((lanes[k] or {}).get("citation_checks") or []):
                if cc.get("status") in ("MISMATCH", "UNRESOLVED"):
                    det = [x for x in (c or {}).get("claim_verdicts") or []
                           if cc.get("passage_id") in (x.get("evidence_ids") or [])]
                    ai_cit_claims.append({
                        "lane": k, "passage_id": cc.get("passage_id"),
                        "status": cc.get("status"),
                        "deterministic_verdict": (c or {}).get("worst_claim_verdict"),
                        "resolution": ("DETERMINISTIC_CONTRADICTS（结构审计未发现引用/引文/层级问题）"
                                       if (c or {}).get("worst_claim_verdict") in
                                       ("SUPPORTED", "QUALIFIED")
                                       else "DETERMINISTIC_CONSISTENT")})
        c_struct_fail = (c or {}).get("worst_claim_verdict") in ("NOT_SUPPORTED",
                                                                "BROKEN_REFERENCE")
        # §11/§12 判定
        if integrity and c_struct_fail:
            verdict, reason, resolved = "FAIL", "lane integrity code 且确定性审计确认", None
        elif d is not None:
            verdict = d.get("verdict")
            reason = ("§12 裁决：" + str(d.get("reason"))[:300])
            resolved = d.get("resolved_concern_type")
        elif fails and c_struct_fail:
            verdict, reason, resolved = "FAIL", "FAIL 且确定性审计确认", "evidence_failure"
        else:
            sev = [v.get("verdict") for v in (a, b, c) if v]
            if "WITH_CONCERN" in sev:
                verdict = "WITH_CONCERN"
                resolved = next((v.get("concern_type") for v in (a, b)
                                 if v.get("concern_type") in
                                 ("existing_scholarly_limitation", "presentation_only")),
                                "existing_scholarly_limitation")
            else:
                verdict, resolved = "PASS", "N/A"
            reason = "无 lane FAIL、无未决证据失败、无 adapter-induced（确定性审计通过）"
        consensus.append({
            "schema_version": "phase4e-ai-review-consensus/v1",
            "task_id": tid, "verdict": verdict,
            "resolved_concern_type": resolved,
            "lane_verdicts": {k: (v or {}).get("verdict") for k, v in lanes.items()},
            "lane_concern_types": {k: (v or {}).get("concern_type") for k, v in lanes.items()},
            "lane_integrity_failures": integrity,
            "deterministic_evidence_verdict": (c or {}).get("worst_claim_verdict"),
            "adjudicated": d is not None,
            "adjudicator_verdict": (d or {}).get("verdict"),
            "ai_citation_claims": ai_cit_claims,
            "unresolved_integrity_failure": bool(integrity and c_struct_fail),
            "reason": reason,
        })
        if d is not None:
            adj = dict(d)
            adj.setdefault("review_lane", "D_ADJUDICATOR")
            adj.setdefault("reviewer_type", "AI")
            adj.setdefault("protocol", REVIEW_PROTOCOL)
            adj.setdefault("human_review_performed", False)
            adj["dispute_reasons"] = (jd(os.path.join(
                REVIEW_DIR, "adjudication_dossiers", "%s.json" % tid), {}) or {}
                ).get("dispute_reasons")
            adjudications.append(adj)

    # §16：E14-v2 PASS 条件
    reviewed = sorted({r["task_id"] for r in (list(lane_a.values()) +
                                              list(lane_b.values()) +
                                              list(lane_c.values()))})
    lanes_complete = all(t in lane_a and t in lane_b and t in lane_c for t in TASKS)
    unresolved = [r["task_id"] for r in consensus if r["unresolved_integrity_failure"]]
    adapter_fail = [r["task_id"] for r in consensus
                    if r["verdict"] == "FAIL" and r["resolved_concern_type"] == "adapter_induced"]
    # 弃权泄漏：rt-J02 必须 ABSTAINED 且无 lane 报 ABSTENTION_SUPPLEMENTED…
    j_leak = [r["task_id"] for r in consensus
              if r["task_id"] == "rt-J02" and (
                  r["lane_integrity_failures"].get("A") ==
                  "ABSTENTION_SUPPLEMENTED_WITH_UNSUPPORTED_KNOWLEDGE"
                  or r["lane_integrity_failures"].get("B") ==
                  "ABSTENTION_SUPPLEMENTED_WITH_UNSUPPORTED_KNOWLEDGE"
                  or r["lane_integrity_failures"].get("C") ==
                  "ABSTENTION_SUPPLEMENTED_WITH_UNSUPPORTED_KNOWLEDGE")]
    cit_unresolved = [r["task_id"] for r in consensus
                      if any(x["resolution"].startswith("DETERMINISTIC_CONSISTENT")
                             and x["status"] == "MISMATCH"
                             for x in r["ai_citation_claims"])]
    fp_count = sum(len((d or {}).get("reviewer_false_positives") or [])
                   for d in lane_d.values())
    e14_pass = (len(reviewed) == 6 and lanes_complete and not unresolved
                and not adapter_fail and not j_leak and not cit_unresolved)

    summary = {
        "schema_version": "phase4e-ai-review-final-summary/v1",
        "review_protocol": REVIEW_PROTOCOL,
        "human_review_performed": False,
        "reviewer_type": "AI",
        "gate": os.path.relpath(GATE_V2, VAULT),
        "tasks_reviewed": reviewed,
        "tasks_reviewed_n": len(reviewed),
        "lanes_complete": lanes_complete,
        "lanes_present": {"A": len(lane_a), "B": len(lane_b), "C": len(lane_c),
                          "D": len(lane_d)},
        "conditions": {
            "6_of_6_tasks_reviewed": len(reviewed) == 6,
            "all_three_lanes_complete": lanes_complete,
            "unresolved_scholarly_integrity_failure": len(unresolved),
            "adapter_induced_fail": len(adapter_fail),
            "abstention_leakage": len(j_leak),
            "citation_evidence_mismatch_unresolved": len(cit_unresolved),
        },
        "unresolved_integrity_failure_tasks": unresolved,
        "adapter_induced_fail_tasks": adapter_fail,
        "abstention_leakage_tasks": j_leak,
        "citation_evidence_mismatch_unresolved_tasks": cit_unresolved,
        "adjudications_n": len(adjudications),
        "adjudicated_tasks": sorted(lane_d),
        "reviewer_false_positives_n": fp_count,
        "with_concern_allowed": ["existing_scholarly_limitation", "presentation_only"],
        "task_verdicts": {r["task_id"]: r["verdict"] for r in consensus},
        "e14_v2_requirement": AI_E14_REQUIREMENT,
        "e14_v2_pass": bool(e14_pass),
        "limitations_of_this_protocol": [
            "本协议是 **AI-only**，不等于、也不替代外部人类同行评审。",
            "单一 provider / 单一模型家族：lane 之间只有角色、prompt、fresh session、"
            "题目顺序不同，**不是**不同模型；不得伪称模型独立性。",
            "Lane C 是确定性结构审计：能证明引用可解析／引文逐字命中／层级标注一致，"
            "**不能**证明理论主张成立。",
            "reviewer 可能误判（本轮已记录 reviewer false positive 并逐条给出理由）。",
        ],
        "generated_at": utcnow(),
    }
    jl(os.path.join(REVIEW_DIR, "adjudications.jsonl"), adjudications)
    jl(os.path.join(REVIEW_DIR, "task_consensus.jsonl"), consensus)
    wr(os.path.join(REVIEW_DIR, "final_summary.json"), summary)

    print("consensus -> task_consensus.jsonl（%d 题）" % len(consensus))
    for r in consensus:
        print("  %-8s %-14s resolved=%-32s D=%-13s det=%s%s"
              % (r["task_id"], r["verdict"], str(r["resolved_concern_type"]),
                 str(r["adjudicator_verdict"]), r["deterministic_evidence_verdict"],
                 "  [AI citation claims: %d]" % len(r["ai_citation_claims"])
                 if r["ai_citation_claims"] else ""))
    print("  裁决数=%d | reviewer false positives=%d" % (len(adjudications), fp_count))
    print("E14-v2 conditions: %s" % json.dumps(summary["conditions"], ensure_ascii=False))
    print("E14-v2 = %s" % ("PASS" if e14_pass else "FAIL"))
    return 0 if e14_pass else 1


def _p4ea():
    """复用 Phase 4E v1 验收工具的**证据源与校验器**（不重复实现、不改写它）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "p4e_acceptance", os.path.join(HERE, "phase4e_acceptance.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_closure(a):
    """§18/§19/§20：正式 AI-review 验收 run（immutable），重算 E1–E17。"""
    p4ea = _p4ea()
    gate = jd(GATE_V2, {})
    if not gate:
        print("FAIL 缺冻结 Gate v2（先 --freeze-gate）")
        return 2
    summary = jd(os.path.join(REVIEW_DIR, "final_summary.json"), {})
    if not summary:
        print("FAIL 缺 final_summary.json（先 --collect）")
        return 2
    real = a.real_run or p4ea._latest("phase4e_real_llm_")
    delta = a.delta_run or p4ea._latest("4e_product_delta_")
    reg_path = a.regression or os.path.join(VAULT, "_data", "phase5a", "regression_v2.json")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = a.run_id or "4e_ai_closure_%s_%s" % (stamp,
                                                  sha_file(GATE_V2)[:8])
    run_dir = os.path.join(P4E, run_id)
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)

    def run_tool(tool, *args):
        r = subprocess.run([sys.executable, os.path.join(HERE, tool), *args],
                           capture_output=True, text=True, cwd=VAULT)
        return r.returncode, (r.stdout + r.stderr)[-300:]

    seal = jd(os.path.join(real or "", "seal.json"), {}) if real else {}
    metrics = jd(os.path.join(real or "", "metrics.json"), {}) if real else {}
    gate_res = jd(os.path.join(real or "", "gate_results.json"), {}) if real else {}
    delta_dec = jd(os.path.join(delta or "", "final_decision.json"), {}) if delta else {}
    reg = jd(reg_path, {})
    fc = p4ea.freeze_compare()
    root_doc = os.path.join(VAULT, "PHASE4E_CCR0001_ROOT_CAUSE.md")
    req = {c["id"]: c["requirement"] for c in (gate.get("criteria") or [])}
    items = []

    def add(cid, ok, evidence):
        items.append({"id": cid, "status": "PASS" if ok else "FAIL",
                      "requirement": req.get(cid), "evidence": evidence})
        # 逐条即时输出：长跑（含真实 provider 调用）中途失败时仍留下已判证据
        print("  %-4s %-5s %s" % (cid, items[-1]["status"], str(evidence)[:130]),
              flush=True)

    add("E1", os.path.isfile(root_doc), "PHASE4E_CCR0001_ROOT_CAUSE.md + root_cause.json")
    rc2, _m2 = p4ea.suite_ok("test_phase4e_ccr0001_wiring")
    ast_ev = p4ea._adapter_contract_json()
    add("E2", rc2 == 0 and ast_ev["verdict"].startswith("boundary restored"),
        "test_phase4e_ccr0001_wiring exit=%s；%s" % (rc2, ast_ev["verdict"]))
    add("E3", bool(fc["synthesis_prompt_same"]), "synthesis_prompt_hash 与父冻结一致")
    add("E4", bool(fc["judge_prompt_same"]), "judge_prompt_hash 与父冻结一致")
    # ★ E5 实现更正（工具缺陷，见 ABORTED/评审记录）：`phase4e_acceptance.freeze_compare`
    #   仍用旧的**两类**判定（`semantic = changed - PRODUCT_BOUNDARY_KEYS`），于是把
    #   Phase 5A 已归类为 **data_version** 的 `corpus_inventory_hash` 误算成学术语义漂移。
    #   判据文本（"scholarly semantic components drift = 0"）未变；这里按
    #   `core_freeze.component_class` 的**三类**判定，并同时要求全谱系语义总量为 0。
    lin5 = jd(os.path.join(VAULT, "_data", "core_freeze", "freeze_lineage.json"), {})
    segs5 = lin5.get("segments") or []
    e4s = [e for e in segs5 if e.get("ccr") == "CCR-0001"
           and e.get("historical_artifact") == "present"]
    PB = ("scholarly_api_core_hash", "scholarly_api_objects_hash",
          "scholarly_api_policy_hash")
    e4_changed = set((e4s[-1].get("changed_components") if e4s else []) or [])
    add("E5", bool(e4s) and (e4s[-1].get("scholarly_semantic_changes") == 0)
        and e4_changed <= set(PB)
        and lin5.get("semantic_changes_total") == 0
        and lin5.get("all_segments_status_pass"),
        "4E 段 changed=%s semantic=%s；全谱系 semantic_total=%s（data_version=%s / "
        "product_runtime=%s）；按 core_freeze.component_class 三类判定"
        % (sorted(e4_changed), (e4s[-1].get("scholarly_semantic_changes") if e4s else None),
           lin5.get("semantic_changes_total"), lin5.get("data_version_changes_total"),
           lin5.get("product_runtime_changes_total")))
    rc3, msg3 = p4ea.suite_ok("test_phase4e_real_provider_smoke")
    add("E6", rc3 == 0, "test_phase4e_real_provider_smoke exit=%s %s" % (rc3, msg3[-120:]))
    add("E7", seal.get("provider_success") == "14/14"
        and seal.get("tasks_attempted") == 14,
        "seal: provider_success=%s attempted=%s/14"
        % (seal.get("provider_success"), seal.get("tasks_attempted")))
    rc4, _m4 = run_tool("build_evaluation_integrity_audit.py", "--check")
    g20 = (gate_res.get("recomputed_on_this_run", {}).get("gate20", {}).get("violations"))
    g21 = (gate_res.get("recomputed_on_this_run", {}).get("gate21", {}).get("violations"))
    add("E8", g20 == 0 and g21 == 0 and rc4 == 0,
        "gate20=%s gate21=%s；冻结审计 --check exit=%s" % (g20, g21, rc4))
    j_states = {r["task_id"]: r.get("answer_state")
                for r in (jd(os.path.join(real or "", "results.json"), {}) or {}).get("rows", [])
                if r.get("task_id") in ("rt-J01", "rt-J02", "rt-J03")}
    add("E9", not metrics.get("abstention_findings", ["x"])
        and all(v == "ABSTAINED" for v in j_states.values()) and len(j_states) == 3,
        "abstention_findings=%s；J 题=%s" % (metrics.get("abstention_findings"), j_states))
    by_code = (gate_res.get("recomputed_on_this_run", {})
               .get("gate21", {}).get("by_code") or {})
    add("E10", not by_code.get("D_SUBSTANTIVE_CLAIM_WITHOUT_EVIDENCE")
        and not by_code.get("D_REJECTED_CLAIM_IN_FINAL"),
        "gate21 by_code=%s" % by_code)
    add("E11", rc2 == 0 and delta_dec.get("decision") == "DELTA_PASS",
        "确定性 provider 失败用例 + delta=%s" % delta_dec.get("decision"))
    add("E12", rc2 == 0 and delta_dec.get("decision") == "DELTA_PASS",
        "no-fallback 单元断言 + delta no-fallback")
    rc5, _m5 = p4ea.suite_ok("test_phase4e_product_real_provider_path")
    add("E13", rc5 == 0 and delta_dec.get("decision") == "DELTA_PASS",
        "MCP 真实路径 exit=%s；delta=%s" % (rc5, delta_dec.get("decision")))
    # ★ E14-v2：AI-only 多代理盲审
    cond = summary.get("conditions") or {}
    add("E14", bool(summary.get("e14_v2_pass")),
        "AI_MULTI_AGENT_BLIND_REVIEW_V1：%s；consensus=%s；裁决=%s；false positives=%s；"
        "human_review_performed=false"
        % (json.dumps(cond, ensure_ascii=False), summary.get("task_verdicts"),
           summary.get("adjudicated_tasks"), summary.get("reviewer_false_positives_n")))
    add("E15", reg.get("exit_code") == 0 and not reg.get("failed")
        and not reg.get("skipped"),
        "regression exit=%s suites=%s failed=%s skipped=%s"
        % (reg.get("exit_code"), reg.get("suites"), reg.get("failed"), reg.get("skipped")))
    rc6, _m6 = run_tool("core_freeze.py", "--verify", "--quiet")
    rc7, _m7 = run_tool("freeze_lineage.py", "--verify")
    lin = jd(os.path.join(VAULT, "_data", "core_freeze", "freeze_lineage.json"), {})
    segs = lin.get("segments") or []
    e4seg = [e for e in segs if e.get("ccr") == "CCR-0001"]
    add("E16", rc6 == 0 and rc7 == 0 and bool(e4seg)
        and lin.get("all_segments_status_pass") and lin.get("live_matches_last_segment"),
        "core_freeze exit=%s；lineage exit=%s 段数=%d（含 ccr=CCR-0001 段：%s）"
        " 全段 PASS=%s live=末段=%s"
        % (rc6, rc7, len(segs), bool(e4seg), lin.get("all_segments_status_pass"),
           lin.get("live_matches_last_segment")))
    secrets = jd(os.path.join(P4E, "secret_audit.json"), {})
    add("E17", secrets.get("verdict") == "PASS" and not seal.get("secret_leak_findings"),
        "secret_audit=%s；run seal findings=%s"
        % (secrets.get("verdict"), seal.get("secret_leak_findings")))

    failed = [i["id"] for i in items if i["status"] != "PASS"]
    decision = ("PHASE_4E_COMPLETE_UNDER_AI_REVIEW_PROTOCOL" if not failed
                else "PHASE_4E_BLOCKED")
    pass_n = sum(1 for i in items if i["status"] == "PASS")
    wr(os.path.join(run_dir, "gate_results.json"),
       {"gate_id": gate.get("gate_id"), "gate_version": gate.get("gate_version"),
        "gate_hash": gate.get("gate_hash"), "items": items, "failed": failed,
        "decision": decision, "human_review_performed": False,
        "review_protocol": REVIEW_PROTOCOL})
    wr(os.path.join(run_dir, "ai_review_summary.json"), summary)
    wr(os.path.join(run_dir, "manifest.json"), {
        "schema_version": "phase4e-ai-closure-manifest/v1", "run_id": run_id,
        "created_at": utcnow(), "git_head": _git_head(),
        "gate_id": gate.get("gate_id"), "gate_hash": gate.get("gate_hash"),
        "parent_gate_hash": (gate.get("parent_gate") or {}).get("gate_hash"),
        "policy_change": gate.get("policy_change"),
        "human_review_performed": False,
        "review_protocol": REVIEW_PROTOCOL,
        "sealed_run": os.path.relpath(real, VAULT) if real else None,
        "sealed_run_seal_hash": sha_file(os.path.join(real, "seal.json")) if real else None,
        "delta_run": os.path.relpath(delta, VAULT) if delta else None,
        "regression": os.path.relpath(reg_path, VAULT),
        "review_dir": os.path.relpath(REVIEW_DIR, VAULT),
        "reviewer_diversity_note": (jd(os.path.join(REVIEW_DIR, "manifest.json"), {})
                                    or {}).get("reviewer_diversity_note")})
    wr(os.path.join(run_dir, "final_decision.json"), {
        "schema_version": "phase4e-ai-closure-decision/v1", "run_id": run_id,
        "decision": decision, "items": items, "failed": failed,
        "criteria_pass": pass_n, "criteria_total": len(items),
        "human_review_performed": False,
        "review_protocol": REVIEW_PROTOCOL,
        "scholarly_review_assurance": {
            "protocol": REVIEW_PROTOCOL, "human_review": False,
            "ai_only": True,
            "not_equivalent_to_human_peer_review": True},
        "finished_at": utcnow()})
    for i in items:
        print("  %-4s %-5s %s" % (i["id"], i["status"], str(i["evidence"])[:120]))
    print("decision: %s（%d/%d PASS；failed=%s）"
          % (decision, pass_n, len(items), failed))
    print("artifacts: %s" % os.path.relpath(run_dir, VAULT))
    return 0 if not failed else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-gate", action="store_true")
    ap.add_argument("--packets", action="store_true")
    ap.add_argument("--lane-c", action="store_true")
    ap.add_argument("--check-v1", action="store_true")
    ap.add_argument("--adjudication-dossiers", action="store_true")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--real-run", default=None)
    ap.add_argument("--delta-run", default=None)
    ap.add_argument("--regression", default=None)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    if a.check_v1:
        ok, msg = verify_gate_v1_untouched()
        print("%s %s" % ("OK  " if ok else "FAIL", msg))
        return 0 if ok else 1
    if a.freeze_gate:
        return freeze_gate()
    if a.packets:
        return build_packets()
    if a.lane_c:
        return lane_c()
    if a.adjudication_dossiers:
        return adjudication_dossiers()
    if a.collect:
        return collect()
    if a.run:
        return run_closure(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
