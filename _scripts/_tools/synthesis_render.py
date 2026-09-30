#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthesis_render.py — Phase 4C.1-C §13/§12：**ScholarlyAnswer** 与 Markdown 渲染

answer 结构（不同 task type 可省略不适用字段）：

    answer_state / brief_answer / main_analysis / key_distinctions /
    diachronic_analysis(optional) / source_notes / limitations / claims[] / citations[]

渲染纪律（§12）：
* **不得**把 research trace 泄漏进答案主体（tool calls / lane / budget / vector /
  evidence 计数都不是学术答案）；
* 来源限制必须转成人类可读的学术说明（`source_notes` / `limitations`）。
"""
from __future__ import annotations

import re

ANSWER_SCHEMA = "scholarly-answer/v1"

ANSWER_STATES = ("FULL_SYNTHESIS", "QUALIFIED_SYNTHESIS", "ABSTAINED", "BLOCKED")

# 不得出现在答案主体里的 pipeline 内部词（§12）
TRACE_LEAK_PATTERNS = (
    r"tool[_ ]?calls?", r"\blane\b", r"\bbudget\b", r"vector[_ ]unavailable",
    r"execution_state", r"evidence_n\s*=", r"\bretrieval route\b",
    r"research[_ ]trace", r"scheduler", r"\bmax_tool_calls\b",
    r"\bclass_quota\b", r"passage_store",
)

_LEAK_RE = re.compile("|".join(TRACE_LEAK_PATTERNS), re.I)


def build_answer(contract, claims, sections, abstention=None, citations=None):
    """把 claims + 分节文本组装成 ScholarlyAnswer。"""
    perm = contract.get("answer_permission")
    state = {"FULL_SYNTHESIS": "FULL_SYNTHESIS",
             "QUALIFIED_SYNTHESIS": "QUALIFIED_SYNTHESIS",
             "ABSTAIN": "ABSTAINED",
             "BLOCKED": "BLOCKED"}.get(perm, "BLOCKED")
    _SEC_ORDER = ["conclusion", "why", "what_can_be_said", "what_would_be_needed",
                  "working_definition", "structural_function", "key_distinctions",
                  "period_source_qualification", "evidence",
                  "term_a", "term_b", "differences", "relations", "why_it_matters",
                  "relationship", "mechanism_or_position", "direct_evidence",
                  "earlier_endpoint", "later_endpoint", "what_remains",
                  "what_changes", "what_is_reformulated",
                  "freud_source", "lacan_source", "lacanian_reinterpretation",
                  "what_cannot_be_verified",
                  "source_philosophy", "intermediary_interpretation",
                  "lacanian_transformation",
                  "term_mapping", "corpus_attestation", "context_validation",
                  "semantic_implication",
                  "formal_expression", "components", "structural_relation",
                  "lacan_textual_explanation",
                  "answer", "limitations", "source_notes"]
    ordered = [(k, sections[k]) for k in _SEC_ORDER if sections.get(k)]
    for k, v in (sections or {}).items():
        if k not in _SEC_ORDER and v:
            ordered.append((k, v))
    answer = {
        "schema_version": ANSWER_SCHEMA,
        "task_id": contract.get("task_id"),
        "question": contract.get("question"),
        "task_type": contract.get("task_type"),
        "synthesis_template": (contract.get("synthesis_template") or {}).get("template"),
        "answer_state": state,
        "answer_permission": perm,
        "brief_answer": sections.get("brief_answer") or "",
        "sections": [{"id": k, "text": v} for k, v in ordered],
        "main_analysis": sections.get("main_analysis") or "",
        "key_distinctions": sections.get("key_distinctions") or "",
        "diachronic_analysis": sections.get("diachronic_analysis"),
        "source_notes": sections.get("source_notes") or "",
        "limitations": sections.get("limitations") or "",
        "claims": claims or [],
        "citations": citations if citations is not None else _citations(contract, claims),
        "abstention": abstention,
        "evidence_state": contract.get("evidence_state"),
        "execution_state": contract.get("execution_state"),
        "warnings": contract.get("warnings") or [],
        "no_hidden_reasoning": True,
    }
    return answer


def _citations(contract, claims):
    """§7：claim → evidence → passage → source 的绑定（每条 claim 单独成组）。"""
    usable = {e["passage_id"]: e for e in contract.get("usable_evidence") or []}
    out = []
    for c in claims or []:
        ids = list(c.get("evidence_ids") or [])
        if not ids:
            continue
        out.append({
            "claim_id": c.get("claim_id"),
            "evidence_ids": ids,
            "passages": [{
                "passage_id": pid,
                "seminar_id": (usable.get(pid) or {}).get("seminar_id"),
                "language": (usable.get(pid) or {}).get("language"),
                "source_layer": (usable.get(pid) or {}).get("source_layer"),
                "authority_level": (usable.get(pid) or {}).get("authority_level"),
                "text_role": (usable.get(pid) or {}).get("text_role"),
                "trace_status": (usable.get(pid) or {}).get("trace_status"),
                "citation_eligibility": (usable.get(pid) or {}).get(
                    "citation_eligibility"),
                "attribution": (usable.get(pid) or {}).get("attribution"),
            } for pid in ids],
        })
    return out


def validate_answer(answer, contract) -> dict:
    """schema + abstention contract + 引用一致性 + trace 泄漏。"""
    out = []
    state = answer.get("answer_state")
    if state not in ANSWER_STATES:
        out.append({"code": "SYNTHESIS_SCHEMA_INVALID", "severity": "VIOLATION",
                    "detail": "answer_state=%r 非法" % state})
    if answer.get("answer_state") == "BLOCKED" and answer.get("claims"):
        out.append({"code": "SYNTHESIS_NOT_ALLOWED", "severity": "VIOLATION",
                    "detail": "BLOCKED 的答案不得带 claims"})
    # abstention contract（§11）：只要带了 abstention 块就必须完整（含限定性弃权）
    if state == "ABSTAINED" or answer.get("abstention"):
        ab = answer.get("abstention") or {}
        if not ab:
            out.append({"code": "ABSTENTION_CONTRACT_VIOLATION", "severity": "VIOLATION",
                        "detail": "ABSTAINED 但缺 abstention 块"})
        else:
            for f in ("abstention_reason_codes", "missing_information",
                      "available_partial_information", "next_required_sources"):
                if not ab.get(f):
                    out.append({"code": "ABSTENTION_CONTRACT_VIOLATION",
                                "severity": "VIOLATION",
                                "detail": "abstention 缺字段 %s" % f})
        if not any((s.get("id") in ("conclusion", "why", "what_can_be_said",
                                    "what_would_be_needed"))
                   for s in answer.get("sections") or []):
            out.append({"code": "ABSTENTION_CONTRACT_VIOLATION", "severity": "VIOLATION",
                        "detail": "abstention 答案缺四段结构（conclusion/why/"
                                  "what_can_be_said/what_would_be_needed）"})
    # 引用一致性：citations 必须与 claims 对齐
    cids = {c.get("claim_id") for c in answer.get("claims") or []}
    for group in answer.get("citations") or []:
        if group.get("claim_id") not in cids:
            out.append({"code": "INVALID_CITATION_REFERENCE", "severity": "VIOLATION",
                        "detail": "citation 指向不存在的 claim %s" % group.get("claim_id")})
    # trace 泄漏（§12）
    leak = trace_leaks(answer)
    for tok in leak:
        out.append({"code": "SYNTHESIS_SCHEMA_INVALID", "severity": "VIOLATION",
                    "detail": "答案主体泄漏 pipeline 内部信息：%r" % tok})
    by_code = {}
    for f in out:
        by_code[f["code"]] = by_code.get(f["code"], 0) + 1
    return {"findings": out, "violations": [f for f in out if f["severity"] == "VIOLATION"],
            "failure_counts": by_code}


def trace_leaks(answer) -> list:
    """答案主体（不含 citations 元数据）里出现的 pipeline 内部词。"""
    texts = [answer.get("brief_answer") or "", answer.get("main_analysis") or "",
             answer.get("limitations") or "", answer.get("source_notes") or "",
             answer.get("key_distinctions") or ""]
    texts += [s.get("text") or "" for s in answer.get("sections") or []]
    texts += [c.get("claim_text") or "" for c in answer.get("claims") or []]
    hits = []
    for t in texts:
        for m in _LEAK_RE.finditer(str(t)):
            tok = m.group(0)
            if tok not in hits:
                hits.append(tok)
    return hits


def render_markdown(answer) -> str:
    """把 ScholarlyAnswer 渲染成人读的 Markdown（不泄漏 trace）。"""
    L = []
    L.append("## 研究回答（%s）" % answer.get("answer_state"))
    if answer.get("brief_answer"):
        L.append("")
        L.append(answer["brief_answer"])
    for sec in answer.get("sections") or []:
        if not sec.get("text"):
            continue
        L.append("")
        L.append("### %s" % _section_title(sec["id"]))
        L.append("")
        L.append(sec["text"])
    if answer.get("claims"):
        L.append("")
        L.append("### 论断与引用绑定")
        L.append("")
        for c in answer["claims"]:
            cites = ("、".join(c.get("evidence_ids") or [])) or "（无引用：%s）" % \
                    c.get("claim_type")
            L.append("- **[%s / %s]** %s → %s" % (c.get("claim_id"), c.get("claim_type"),
                                                  c.get("claim_text"), cites))
    if answer.get("limitations"):
        L.append("")
        L.append("### 限制")
        L.append("")
        L.append(answer["limitations"])
    if answer.get("source_notes"):
        L.append("")
        L.append("### 来源说明")
        L.append("")
        L.append(answer["source_notes"])
    md = "\n".join(L)
    return md


_SECTION_TITLES = {
    "conclusion": "结论", "why": "为什么无法回答", "what_can_be_said": "仅能确认",
    "what_would_be_needed": "需要什么材料",
    "working_definition": "工作定义", "structural_function": "结构功能",
    "key_distinctions": "关键区分", "period_source_qualification": "时期与来源限定",
    "evidence": "证据", "term_a": "A 侧", "term_b": "B 侧", "differences": "差异",
    "relations": "关系", "why_it_matters": "这一区分为何重要",
    "relationship": "关系", "mechanism_or_position": "机制 / 结构位置",
    "direct_evidence": "直接证据", "earlier_endpoint": "早期端点",
    "later_endpoint": "晚期端点", "what_remains": "保持不变的部分",
    "what_changes": "发生变化的部分", "what_is_reformulated": "被重新表述的部分",
    "freud_source": "弗洛伊德来源层", "lacan_source": "拉康来源层",
    "lacanian_reinterpretation": "拉康的重解", "what_cannot_be_verified": "无法核验的部分",
    "source_philosophy": "哲学来源", "intermediary_interpretation": "中介解释",
    "lacanian_transformation": "拉康的改造",
    "term_mapping": "术语映射", "corpus_attestation": "语料见证",
    "context_validation": "上下文验证", "semantic_implication": "语义含义",
    "formal_expression": "形式表达式", "components": "成分",
    "structural_relation": "结构关系", "lacan_textual_explanation": "拉康文本解释",
    "answer": "结果", "limitations": "限制", "source_notes": "来源说明",
}


def _section_title(sid):
    return _SECTION_TITLES.get(sid, sid)


def answer_metrics(answer) -> dict:
    claims = answer.get("claims") or []
    cites = answer.get("citations") or []
    quotes = [c.get("quotation") for c in claims if c.get("quotation")]
    return {
        "claims_total": len(claims),
        "claims_with_evidence": len([c for c in claims if c.get("evidence_ids")]),
        "claims_without_evidence": len([c for c in claims
                                        if not c.get("evidence_ids")]),
        "citation_groups": len(cites),
        "eligible_citations": len({p.get("passage_id") for g in cites
                                   for p in (g.get("passages") or [])
                                   if p.get("citation_eligibility") == "ELIGIBLE"}),
        "qualified_citations": len({p.get("passage_id") for g in cites
                                    for p in (g.get("passages") or [])
                                    if p.get("citation_eligibility") == "QUALIFIED"}),
        "ineligible_citations_used": len({p.get("passage_id") for g in cites
                                          for p in (g.get("passages") or [])
                                          if p.get("citation_eligibility") ==
                                          "INELIGIBLE"}),
        "direct_quotes_total": len(quotes),
        "quotes_with_exact_span": len([q for q in quotes
                                       if q.get("kind") == "CORPUS_QUOTE"
                                       and q.get("exact_span")]),
        "quotes_paraphrase": len([q for q in quotes if q.get("kind") == "PARAPHRASE"]),
        "quotes_model_translation": len([q for q in quotes
                                         if q.get("kind") == "MODEL_TRANSLATION"]),
    }


__all__ = ["ANSWER_SCHEMA", "ANSWER_STATES", "build_answer", "validate_answer",
           "render_markdown", "answer_metrics", "trace_leaks", "TRACE_LEAK_PATTERNS"]
