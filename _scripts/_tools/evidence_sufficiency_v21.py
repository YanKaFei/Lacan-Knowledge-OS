#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evidence_sufficiency_v21.py — Phase 4C.1-B §12–§14：Evidence Sufficiency **v2.1**

为什么叫 v2.1 而不是 v3
───────────────────────
v2 的分层（availability / topicality / coverage / source / ontology）是**证据层**判断，保持不变；
v2.1 只在它之上加一层**任务完成层**：题目要求的动作、lane、约束、关系、来源层、
formalism、metadata 是否完成。因此：

    final_state(v2.1) = min( final_state(v2), contract.state_ceiling )

`SUPPORTED` 的含义从「有很多相关 evidence」变成
**「该研究任务规定的必要条件全部满足」**。

同时修掉 §14 的两个问题
───────────────────────
1. **固定模板借口**：v1 会产出「证据量、多分量一致性、session 多样性、约束满足四项均达标」，
   而 v2 把 v1 的 reasons 原样并进来 —— 于是 `component_agreement = null`、
   `constraint_satisfaction = null`、`independent_families_executed = []` 时**仍然声称达标**。
   v2.1 的 `sanitize_reasons()` 会把这类句子**删掉**，并改用真实字段动态生成一句
   「真实信号」说明（每个数都来自本次 run 的字段）。
2. **无解释升格**（§13）：任何 final state 变化都必须带
   `{from, to, reason_code, trigger, evidence, contract_check}`；
   没有 `transition_reason` 时 Gate 19 判 FAIL。

v2 本身**保持冻结**（`evidence_sufficiency_calibration.v4c.json` 必须可复现），
所有修正都在本模块完成。
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_contract as rc      # noqa: E402

ENGINE = "evidence_sufficiency/v2.1"

# 会「凭空声称达标」的句子模式（配合 signals 一起判断）
_CLAIM_PATTERNS = (
    re.compile(r"多分量一致性"),
    re.compile(r"约束满足.{0,6}(达标|满足|均已)"),
    re.compile(r"四项均达标"),
    re.compile(r"component\s+agreement", re.I),
    re.compile(r"constraint\s+satisfaction", re.I),
)


def sanitize_reasons(reasons, signals) -> dict:
    """删除引用**不存在信号**的借口句，并用真实字段生成一句说明。

    → {"reasons": [...], "dropped": [...], "real_signal_line": str}
    """
    sig = signals or {}
    comp = sig.get("component_agreement")
    cons = sig.get("constraint_satisfaction")
    fams = sig.get("independent_families_executed") or []
    comp_applicable = bool(sig.get("component_agreement_applicable"))
    absent = (comp is None and cons is None and not fams)

    kept, dropped = [], []
    for r in reasons or []:
        r = str(r)
        if absent and any(p.search(r) for p in _CLAIM_PATTERNS):
            dropped.append(r)
            continue
        kept.append(r)

    parts = []
    if not comp_applicable or comp is None:
        parts.append("多分量一致性：不适用（本次独立检索族 %d 个）" % len(fams))
    else:
        parts.append("多分量一致性：%s" % comp)
    parts.append("约束满足：%s" % ("未测量（null）" if cons is None else cons))
    parts.append("证据量：%s 条" % (sig.get("passage_count")))
    parts.append("session 多样性：%s" % (sig.get("distinct_session_count")))
    line = "本次真实信号 —— " + "；".join(parts) + "。"
    return {"reasons": kept, "dropped": dropped, "real_signal_line": line}


def evaluate_v21(v2res, contract, question=None, executed_operations=None) -> dict:
    """v2 分层 + 契约 → v2.1 分层 + final_state + 可解释 transition。"""
    audit = rc.validate_contract(contract)
    v2_state = v2res.get("final_state")
    ceiling = audit["state_ceiling"]
    final = rc.cap_state(v2_state, ceiling)

    sig = (v2res.get("signals") or {})
    san = sanitize_reasons(v2res.get("reasons") or [], sig)

    layers = {
        "task_completion": audit["completion_state"],
        "operation_completion": ("COMPLETE" if not contract.get("missing_operations")
                                 else "INCOMPLETE"),
        "lane_completion": ("COMPLETE" if not contract.get("missing_lanes")
                            else "INCOMPLETE"),
        "constraint_completion": ("COMPLETE" if not contract.get("failed_constraints")
                                  else "INCOMPLETE"),
        "relation_completion": (
            "NOT_REQUIRED" if not contract.get("relation_evidence_required")
            else ("COMPLETE" if contract.get("relation_evidence_n") else "MISSING")),
        "source_layer_completion": ("COMPLETE" if not contract.get("missing_source_layers")
                                    else "MISSING"),
        "formalism_completion": (contract.get("formalism") or {}).get("formalism_state"),
        "metadata_completion": (contract.get("metadata") or {}).get("metadata_state"),
        "evidence_usability": ("SUBSTANTIVE_AVAILABLE"
                               if (contract.get("evidence_usability") or {})
                               .get("substantive_n") else "NO_SUBSTANTIVE_EVIDENCE"),
    }

    reason_codes = list(audit["completion_reasons"])
    reasons = list(san["reasons"])
    if reason_codes:
        reasons.append("契约未完成（%s）：%s" % (audit["completion_state"],
                                            "；".join(
                                                "%s → %s" % (v["code"], v["detail"])
                                                for v in audit["violated_rules"])))
    reasons.append(san["real_signal_line"])

    transition = None
    if final != v2_state:
        transition = {
            "from": v2_state,
            "to": final,
            "reason_code": reason_codes[0] if reason_codes else "CONTRACT_CEILING",
            "trigger": "research_contract.state_ceiling",
            "evidence": {"violated_rules": audit["violated_rules"]},
            "contract_check": {"completion_state": audit["completion_state"],
                               "supported_allowed": audit["supported_allowed"]},
        }
    transition_reason = ("%s：%s" % (transition["reason_code"],
                                     "; ".join(v["detail"] for v in
                                               audit["violated_rules"])[:240])
                         if transition else None)

    return {
        "engine": ENGINE,
        "v2_final_state": v2_state,
        "final_state": final,
        "state_ceiling": ceiling,
        "layers": layers,
        "violated_rules": audit["violated_rules"],
        "completion_state": audit["completion_state"],
        "completion_reasons": audit["completion_reasons"],
        "supported_allowed": audit["supported_allowed"],
        "transition": transition,
        "transition_reason": transition_reason,
        "reasons": reasons,
        "dropped_reasons": san["dropped"],
        "real_signal_line": san["real_signal_line"],
        "no_hidden_reasoning": True,
    }


def apply_v21(evp, v21, contract) -> dict:
    """把 v2.1 结果写回 evidence_pack（**只改状态层与解释**，不动证据本身）。"""
    es = evp.setdefault("evidence_state", {})
    es["engine_v21"] = v21["engine"]
    es["state_before_contract"] = v21["v2_final_state"]
    es["final_state"] = v21["final_state"]
    es["state"] = v21["final_state"]
    es["state_ceiling"] = v21["state_ceiling"]
    es["task_completion"] = v21["layers"]
    es["completion_state"] = v21["completion_state"]
    es["completion_reasons"] = v21["completion_reasons"]
    es["violated_rules"] = v21["violated_rules"]
    es["reasons"] = v21["reasons"]
    es["dropped_reasons"] = v21["dropped_reasons"]
    es["transition"] = v21["transition"]
    es["transition_reason"] = v21["transition_reason"]
    es["contract_ref"] = {"contract_type": contract.get("contract_type"),
                          "required_lanes": contract.get("required_lanes"),
                          "missing_lanes": contract.get("missing_lanes"),
                          "missing_operations": contract.get("missing_operations"),
                          "failed_constraints": contract.get("failed_constraints")}
    return evp


__all__ = ["ENGINE", "sanitize_reasons", "evaluate_v21", "apply_v21"]
