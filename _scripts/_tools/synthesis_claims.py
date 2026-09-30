#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthesis_claims.py — Phase 4C.1-C §5/§6/§7/§17/§18/§19：**StructuredClaim**

synthesis 的输出不是一段 prose，而是先有 claims，再有 answer：

    StructuredClaim[]  →  CitationBinding  →  Draft Scholarly Answer

本模块只做**结构与引用绑定**层面的检查（C 阶段范围内）：

  ① claim_type / epistemic_status 合法；
  ② substantive claim 必须有 evidence_ids（§17 硬规则）；
  ③ 每个 evidence_id 必须真的在 synthesis 包里（§7 Citation Binding）；
  ④ 引用的证据必须**有资格**承担该 claim（§8/§4 source role）；
  ⑤ direct quote 必须给 passage_id + exact_span + language + source_layer，
     且 span **真的出现在**该段文本里（§18，禁止 LLM 重构原文）；
  ⑥ 措辞必须符合 source layer（§9）：L2/recovered 证据不得写成「拉康原文说」；
  ⑦ 输出里**不得**出现 UNSUPPORTED（§6）。

⚠️ 本阶段**不判断** citation 是否真的 entail claim —— 那是 Phase 4C.1-D。
这里只保证「有引用、引用存在、引用有资格、来源角色相容」。
"""
from __future__ import annotations

import re

SCHEMA = "synthesis-claim/v1"

CLAIM_TYPES = ("DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
               "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY", "FORMALISM",
               "METADATA", "CORPUS_ABSENCE", "LIMITATION")

EPISTEMIC_STATUS = ("DIRECTLY_SUPPORTED", "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE",
                    "QUALIFIED_INFERENCE", "CORPUS_ABSENCE", "UNSUPPORTED")

# 需要证据的 claim 类型（substantive）
SUBSTANTIVE_CLAIM_TYPES = ("DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
                           "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY",
                           "FORMALISM")
# 断言「不存在/受限」的 claim：证据来自全库普查，允许 evidence_ids 为空但必须有 corpus_scan_ref
ABSENCE_CLAIM_TYPES = ("CORPUS_ABSENCE", "LIMITATION")

QUOTE_KINDS = ("CORPUS_QUOTE", "PARAPHRASE", "EXISTING_TRANSLATION",
               "MODEL_TRANSLATION")
FAILURE_MODES = ("SYNTHESIS_NOT_ALLOWED", "SYNTHESIS_SCHEMA_INVALID",
                 "CLAIM_WITHOUT_EVIDENCE", "INVALID_CITATION_REFERENCE",
                 "UNSUPPORTED_QUOTATION", "SOURCE_ROLE_VIOLATION",
                 "ABSTENTION_CONTRACT_VIOLATION", "LLM_PROVIDER_FAILURE")

# 把 L2/recovered 证据说成原文的措辞（source role violation）
_ORIGINAL_CLAIM_PHRASES = re.compile(
    r"拉康原文|法文原文|原文说|原文写道|拉康说|拉康写道|"
    r"Lacan\s+dit|texte\s+original|in the original|原文即", re.I)


def make_claim(claim_id, claim_type, claim_text, epistemic_status, evidence_ids=None,
               source_layer=None, directness=None, scope=None, citation_required=None,
               quotation=None, corpus_scan_ref=None, claim_permissions_used=None):
    """构造一条 StructuredClaim（字段即 schema，缺项显式给 None，便于 Gate 检查）。"""
    substantive = claim_type in SUBSTANTIVE_CLAIM_TYPES
    return {
        "schema_version": SCHEMA,
        "claim_id": claim_id,
        "claim_type": claim_type,
        "claim_text": claim_text,
        "epistemic_status": epistemic_status,
        "evidence_ids": list(evidence_ids or []),
        "source_layer": source_layer,
        "directness": directness or ("DIRECT" if substantive else "META"),
        "scope": scope or "claim-level",
        "citation_required": substantive if citation_required is None else citation_required,
        "quotation": quotation,
        "corpus_scan_ref": corpus_scan_ref,
        "claim_permissions_used": list(claim_permissions_used or []),
        "no_hidden_reasoning": True,
    }


def validate_claim(claim, contract) -> list[dict]:
    """→ findings（每条 {"code","detail","severity"}；severity ∈ VIOLATION/REPAIRABLE）。"""
    out = []
    cid = (claim or {}).get("claim_id")
    ctype = (claim or {}).get("claim_type")
    est = (claim or {}).get("epistemic_status")
    ev_ids = list((claim or {}).get("evidence_ids") or [])
    usable = {e["passage_id"]: e for e in (contract or {}).get("usable_evidence") or []}

    if ctype not in CLAIM_TYPES:
        out.append({"code": "SYNTHESIS_SCHEMA_INVALID", "severity": "VIOLATION",
                    "detail": "claim %s 的 claim_type=%r 不在允许集合" % (cid, ctype)})
    if est not in EPISTEMIC_STATUS:
        out.append({"code": "SYNTHESIS_SCHEMA_INVALID", "severity": "VIOLATION",
                    "detail": "claim %s 的 epistemic_status=%r 不在允许集合" % (cid, est)})
    if est == "UNSUPPORTED":
        out.append({"code": "CLAIM_WITHOUT_EVIDENCE", "severity": "VIOLATION",
                    "detail": "claim %s 状态为 UNSUPPORTED —— 正常输出不得包含" % cid})

    # §17：substantive claim 无证据 = INVALID
    if ctype in SUBSTANTIVE_CLAIM_TYPES and not ev_ids:
        out.append({"code": "CLAIM_WITHOUT_EVIDENCE", "severity": "VIOLATION",
                    "detail": "substantive claim %s（%s）没有 evidence_ids" % (cid, ctype)})
    # 断言「不存在」必须给全库普查凭据
    if ctype in ABSENCE_CLAIM_TYPES and not ev_ids and not (claim or {}).get(
            "corpus_scan_ref"):
        out.append({"code": "ABSTENTION_CONTRACT_VIOLATION", "severity": "VIOLATION",
                    "detail": "claim %s（%s）断言缺失/受限但没有 corpus_scan_ref"
                              % (cid, ctype)})

    # §7：引用必须存在，且引用资格足够
    for eid in ev_ids:
        ev = usable.get(eid)
        if ev is None:
            out.append({"code": "INVALID_CITATION_REFERENCE", "severity": "VIOLATION",
                        "detail": "claim %s 引用了不在 synthesis 包里的 passage %s"
                                  % (cid, eid)})
            continue
        if ev.get("citation_eligibility") == "INELIGIBLE":
            out.append({"code": "SOURCE_ROLE_VIOLATION", "severity": "VIOLATION",
                        "detail": "claim %s 引用了 INELIGIBLE 证据 %s（%s）"
                                  % (cid, eid, ev.get("usability_class"))})
            continue
        if ctype in SUBSTANTIVE_CLAIM_TYPES and \
                "substantive" not in (ev.get("claim_permissions") or []):
            out.append({"code": "SOURCE_ROLE_VIOLATION", "severity": "VIOLATION",
                        "detail": "claim %s（%s）用了不能承担 substantive 的证据 %s（%s）"
                                  % (cid, ctype, eid, ev.get("usability_class"))})
        # §9：只有 L2/recovered 证据时不得用「原文」措辞
        if ctype in SUBSTANTIVE_CLAIM_TYPES and \
                ev.get("citation_eligibility") == "QUALIFIED":
            text = str((claim or {}).get("claim_text") or "")
            if _ORIGINAL_CLAIM_PHRASES.search(text):
                out.append({"code": "SOURCE_ROLE_VIOLATION", "severity": "VIOLATION",
                            "detail": "claim %s 只引用了 QUALIFIED（L2/recovered）证据，"
                                      "却使用「原文/拉康说」措辞" % cid})

    # §18：直接引用必须可核（passage + exact_span + language + source_layer）
    q = (claim or {}).get("quotation")
    if q:
        if q.get("kind") not in QUOTE_KINDS:
            out.append({"code": "SYNTHESIS_SCHEMA_INVALID", "severity": "VIOLATION",
                        "detail": "claim %s 的 quotation.kind=%r 非法" % (cid, q.get("kind"))})
        if q.get("kind") == "CORPUS_QUOTE":
            for f in ("passage_id", "exact_span", "language", "source_layer"):
                if not q.get(f):
                    out.append({"code": "UNSUPPORTED_QUOTATION", "severity": "VIOLATION",
                                "detail": "claim %s 的直接引用缺 %s" % (cid, f)})
            span = str(q.get("exact_span") or "")
            pid = q.get("passage_id")
            ev = usable.get(pid)
            if ev and span:
                if span not in str(ev.get("text") or ""):
                    out.append({"code": "UNSUPPORTED_QUOTATION", "severity": "VIOLATION",
                                "detail": "claim %s 的 exact_span 不在 %s 的文本里（禁止重构原文）"
                                          % (cid, pid)})
            elif span and not ev:
                out.append({"code": "UNSUPPORTED_QUOTATION", "severity": "VIOLATION",
                            "detail": "claim %s 的引用段落 %s 不在 synthesis 包里" % (cid, pid)})
        if q.get("kind") == "MODEL_TRANSLATION" and q.get("presented_as") == "CORPUS_WITNESS":
            out.append({"code": "SOURCE_ROLE_VIOLATION", "severity": "VIOLATION",
                        "detail": "claim %s 把 MODEL_TRANSLATION 冒充 corpus witness" % cid})
    return out


def validate_claims(claims, contract) -> dict:
    findings = []
    for c in claims or []:
        findings.extend(validate_claim(c, contract))
    by_code = {}
    for f in findings:
        by_code[f["code"]] = by_code.get(f["code"], 0) + 1
    substantive = [c for c in (claims or []) if c.get("claim_type") in
                   SUBSTANTIVE_CLAIM_TYPES]
    ev_ids = {e for c in (claims or []) for e in (c.get("evidence_ids") or [])}
    return {
        "findings": findings,
        "violations": [f for f in findings if f["severity"] == "VIOLATION"],
        "failure_counts": by_code,
        "metrics": {
            "claims_total": len(claims or []),
            "claims_substantive": len(substantive),
            "claims_with_evidence": len([c for c in (claims or [])
                                         if c.get("evidence_ids")]),
            "claims_without_evidence": len([c for c in substantive
                                            if not c.get("evidence_ids")]),
            "distinct_evidence_cited": len(ev_ids),
            "claims_with_quotation": len([c for c in (claims or [])
                                          if c.get("quotation")]),
            "claims_unsupported_status": len([c for c in (claims or [])
                                              if c.get("epistemic_status") == "UNSUPPORTED"]),
        },
    }


__all__ = ["SCHEMA", "CLAIM_TYPES", "EPISTEMIC_STATUS", "SUBSTANTIVE_CLAIM_TYPES",
           "ABSENCE_CLAIM_TYPES", "QUOTE_KINDS", "FAILURE_MODES",
           "make_claim", "validate_claim", "validate_claims"]
