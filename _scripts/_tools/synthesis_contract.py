#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthesis_contract.py — Phase 4C.1-C §2：**Synthesis Boundary Contract**（C0）

为什么需要它
────────────
LLM 不能看 question + corpus 自由回答。进入 synthesis 之前，Research Engine 必须
先把「**允许说什么**」写成一份机器可检查的契约：

    Research Engine → SynthesisInputContract → (mock/LLM) synthesis
                    → StructuredClaim[] → CitationBinding → ScholarlyAnswer

本模块只做**判定**，不生成任何自然语言答案：
  1. `answer_permission`：FULL_SYNTHESIS / QUALIFIED_SYNTHESIS / ABSTAIN / BLOCKED
  2. `claim_permissions`：每类 evidence 能承担什么 claim（media 不得承担理论 claim）
  3. `citation_eligibility`：ELIGIBLE / QUALIFIED / INELIGIBLE（含来源层限制）
  4. `usable_evidence`：证据最小化包（选择理由 / 排除理由 / 多样性记录）
  5. `synthesis_template`：10 种任务特定 templates
  6. `abstention_requirements`：弃权时**必须**给出的机器可读字段

三条硬原则（在代码里可复核）：
    NO EVIDENCE            → NO SCHOLARLY CLAIM
    PARTIAL EVIDENCE       → QUALIFIED CLAIM
    STRUCTURAL UNANSWERABLE→ ABSTENTION
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_contract as rc        # noqa: E402

SCHEMA = "synthesis-input-contract/v1"

ANSWER_PERMISSIONS = ("FULL_SYNTHESIS", "QUALIFIED_SYNTHESIS", "ABSTAIN", "BLOCKED")
CONTRACT_STATUS = ("READY", "BLOCKED")

CLAIM_TYPES = ("DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
               "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY", "FORMALISM",
               "METADATA", "CORPUS_ABSENCE", "LIMITATION")

EPISTEMIC_STATUS = ("DIRECTLY_SUPPORTED", "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE",
                    "QUALIFIED_INFERENCE", "CORPUS_ABSENCE", "UNSUPPORTED")

CITATION_ELIGIBILITY = ("ELIGIBLE", "QUALIFIED", "INELIGIBLE")

# §4：evidence usability → 允许承担哪些 claim
CLAIM_PERMISSION_BY_USABILITY = {
    "SUBSTANTIVE_TEXT": ["substantive", "contextual", "limitation"],
    "FRAGMENT_ONLY": ["contextual", "limitation"],          # 未验证的片段不得承担理论断言
    "EDITORIAL_METADATA": ["metadata", "limitation"],
    "BIBLIOGRAPHY_ONLY": ["bibliographic", "limitation"],
    "MEDIA_ONLY": ["limitation"],                           # `![[image.jpeg]]` 不得承担理论 claim
}

# §23：失败模式（synthesis 层）
FAILURE_MODES = ("SYNTHESIS_NOT_ALLOWED", "SYNTHESIS_SCHEMA_INVALID",
                 "CLAIM_WITHOUT_EVIDENCE", "INVALID_CITATION_REFERENCE",
                 "UNSUPPORTED_QUOTATION", "SOURCE_ROLE_VIOLATION",
                 "ABSTENTION_CONTRACT_VIOLATION", "LLM_PROVIDER_FAILURE")

ABSTENTION_REASON_CODES = ("METADATA_UNAVAILABLE", "TOPIC_NOT_COVERED",
                           "CORPUS_FORMALISM_MISSING", "NO_SUBSTANTIVE_EVIDENCE",
                           "SOURCE_CHAIN_INCOMPLETE", "ONTOLOGY_GAP",
                           "EXECUTION_INCOMPLETE", "CONTRACT_VIOLATION",
                           "RELATION_EVIDENCE_MISSING", "SOURCE_LAYER_MISSING",
                           "DIACHRONIC_ENDPOINT_MISSING")

# 源层 → 措辞（§9：source-aware language；不得把 recovered witness 说成「拉康原文」）
SOURCE_ATTRIBUTION = {
    "L1_ORIGINAL": "在该段（L1 原文见证）中，拉康",
    "L1_TRANSCRIPTION": "在该段（L1 课堂转写）中，拉康",
    "L2_TRANSLATION": "当前收录的译本文本显示（L2 翻译见证，非原文层）",
    "L2_RECOVERED": "当前收录的 recovered 文本显示（L2，来源链不完整）",
    "EDITORIAL": "编者说明（editorial，非拉康论述）",
    "BIBLIOGRAPHY": "书目/出处信息（bibliographic）",
    "MEDIA": "媒体附件（不承担文本论断）",
}


# ══════════════════════════════════════════════════════════════════════ §10 templates
SYNTHESIS_TEMPLATES = {
    "DEFINITION": {
        "task_types": ["concept_definition", "case_research"],
        "sections": ["working_definition", "structural_function", "key_distinctions",
                     "period_source_qualification", "evidence"],
        "required_claim_types": ["DEFINITION", "DISTINCTION"],
        "structure_rule": ("working definition → structural function → key distinctions → "
                           "period/source qualification → evidence；**禁止只列 passage**"),
    },
    "COMPARISON": {
        "task_types": ["concept_relation"],
        "sections": ["term_a", "term_b", "differences", "relations", "why_it_matters"],
        "required_claim_types": ["DISTINCTION", "RELATION"],
        "structure_rule": ("两侧各自 lane + relation evidence；不得把「都有证据」写成"
                           "「两者有理论关系」"),
    },
    "RELATION": {
        "task_types": ["seminar_specific"],
        "sections": ["term_a", "term_b", "relationship", "mechanism_or_position",
                     "direct_evidence"],
        "required_claim_types": ["RELATION"],
        "structure_rule": ("关系必须有同段共现/关系陈述证据（R2 以上）；"
                           "只有两侧各自出现 → QUALIFIED 或 abstain"),
    },
    "DIACHRONIC": {
        "task_types": ["diachronic_development"],
        "sections": ["earlier_endpoint", "later_endpoint", "what_remains",
                     "what_changes", "what_is_reformulated"],
        "required_claim_types": ["DIACHRONIC_CHANGE"],
        "structure_rule": ("端点必须各有证据；不得用「证据分布在 N 个时期」替代理论发展"),
    },
    "FREUD_TO_LACAN": {
        "task_types": ["freud_to_lacan"],
        "sections": ["freud_source", "lacan_source", "lacanian_reinterpretation",
                     "what_cannot_be_verified"],
        "required_claim_types": ["SOURCE_INFLUENCE", "REINTERPRETATION"],
        "structure_rule": ("必须区分 Freud 来源层 / Lacan 来源层 / 拉康的重解；"
                           "Freud L0 不存在时**必须**写明「当前知识库不能直接核验 Freud 原文层」，"
                           "不得用模型记忆补 Freud"),
    },
    "PHILOSOPHY_TO_LACAN": {
        "task_types": ["philosophy_to_lacan"],
        "sections": ["source_philosophy", "intermediary_interpretation",
                     "lacanian_transformation", "what_cannot_be_verified"],
        "required_claim_types": ["SOURCE_INFLUENCE", "REINTERPRETATION"],
        "structure_rule": ("三层分开：哲学来源 / 中介解释（如 Kojève）/ 拉康的改造；"
                           "没有来源层证据就不得写「影响史」"),
    },
    "TRANSLATION_TERMINOLOGY": {
        "task_types": ["translation_terminology"],
        "sections": ["term_mapping", "corpus_attestation", "context_validation",
                     "semantic_implication", "limitations"],
        "required_claim_types": ["TERMINOLOGY"],
        "structure_rule": ("KNOWN_TRANSLATION ≠ CORPUS_ATTESTED ≠ CONTEXT_VALIDATED；"
                           "三层分开陈述"),
    },
    "TOPOLOGY_MATHEME": {
        "task_types": ["topology_matheme"],
        "sections": ["formal_expression", "components", "structural_relation",
                     "lacan_textual_explanation"],
        "required_claim_types": ["FORMALISM"],
        "structure_rule": ("先给语料里的形式表达式（含 raw_matched_form），再给成分与结构关系；"
                           "**不得**把模型自己的自然语言解释冒充拉康原句"),
    },
    "METADATA": {
        "task_types": [],
        "sections": ["answer", "evidence"],
        "required_claim_types": ["METADATA"],
        "structure_rule": "metadata available → 直接给结果；unavailable → 必须 abstain",
    },
    "ABSTENTION": {
        "task_types": ["insufficient_unanswerable"],
        "sections": ["conclusion", "why", "what_can_be_said", "what_would_be_needed"],
        "required_claim_types": ["LIMITATION", "CORPUS_ABSENCE"],
        "structure_rule": ("明确的研究型弃权：结论 / 原因 / 仅能确认什么 / 需要什么材料；"
                           "**不得**输出普通 theoretical development，也不得罗列检索日志"),
    },
}

TASK_TYPE_TO_TEMPLATE = {
    "concept_definition": "DEFINITION",
    "concept_relation": "COMPARISON",
    "diachronic_development": "DIACHRONIC",
    "seminar_specific": "RELATION",
    "case_research": "DEFINITION",
    "freud_to_lacan": "FREUD_TO_LACAN",
    "philosophy_to_lacan": "PHILOSOPHY_TO_LACAN",
    "topology_matheme": "TOPOLOGY_MATHEME",
    "translation_terminology": "TRANSLATION_TERMINOLOGY",
    "insufficient_unanswerable": "ABSTENTION",
}


def synthesis_template(task_type, contract=None):
    """任务类型 → synthesis template（metadata 义务优先，其次任务类型）。"""
    meta = (contract or {}).get("metadata") or {}
    if (meta.get("metadata_required") or []) and \
            meta.get("metadata_state") == "METADATA_UNAVAILABLE":
        name = "METADATA"
    else:
        name = TASK_TYPE_TO_TEMPLATE.get(task_type or "", "DEFINITION")
    tpl = dict(SYNTHESIS_TEMPLATES[name])
    tpl["template"] = name
    return tpl


# ══════════════════════════════════════════════════════════════════════ §8 eligibility
_TRACE_OK = ("COMPLETE", "PARTIAL", None)


def citation_eligibility(ev, contract=None):
    """→ {"eligibility", "reasons", "source_layer", "attribution"}（§8 引用资格）。"""
    usab = rc.classify_evidence_usability(ev)
    cls = usab["usability_class"]
    reasons = list(usab["reasons"])
    trace = ev.get("trace_status")
    role = str(ev.get("text_role") or "")
    auth = str(ev.get("authority_level") or "")
    if cls in ("MEDIA_ONLY", "BIBLIOGRAPHY_ONLY", "EDITORIAL_METADATA",
               "FRAGMENT_ONLY"):
        return {"eligibility": "INELIGIBLE",
                "reasons": reasons + ["%s 不得支持 substantive theoretical claim" % cls],
                "usability_class": cls, "source_layer": _source_layer(ev),
                "attribution": _attribution(ev)}
    if trace and str(trace).startswith("SOURCE_TRACE_INCOMPLETE"):
        return {"eligibility": "QUALIFIED",
                "reasons": reasons + ["SOURCE_TRACE_INCOMPLETE：可引用，但须附来源限制"],
                "usability_class": cls, "source_layer": _source_layer(ev),
                "attribution": _attribution(ev)}
    if auth == "L2" or role in ("translation", "recovered", "reconstruction"):
        return {"eligibility": "QUALIFIED",
                "reasons": reasons + ["L2 / %s：非原文层，须标明归属" % (role or "translation")],
                "usability_class": cls, "source_layer": _source_layer(ev),
                "attribution": _attribution(ev)}
    return {"eligibility": "ELIGIBLE", "reasons": reasons,
            "usability_class": cls, "source_layer": _source_layer(ev),
            "attribution": _attribution(ev)}


def _source_layer(ev):
    auth = str(ev.get("authority_level") or "")
    role = str(ev.get("text_role") or "")
    trace = str(ev.get("trace_status") or "")
    if auth == "L1" and role in ("transcription", "seminar", "écrit", "ecrit"):
        return "L1_TRANSCRIPTION"
    if auth == "L1":
        return "L1_ORIGINAL"
    if auth == "L2" and trace.startswith("SOURCE_TRACE_INCOMPLETE"):
        return "L2_RECOVERED"
    if auth == "L2":
        return "L2_TRANSLATION"
    if str(ev.get("authority_level") or "") in ("L3", "L4"):
        return "EDITORIAL"
    return "L2_TRANSLATION"


def _attribution(ev):
    return SOURCE_ATTRIBUTION.get(_source_layer(ev),
                                  "当前收录文本显示（来源层未定）")


def claim_permissions(usability_class, eligibility):
    """该类证据能承担哪些 claim（§4）。INELIGIBLE → 只能进 limitation。"""
    perms = list(CLAIM_PERMISSION_BY_USABILITY.get(usability_class, ["limitation"]))
    if eligibility == "INELIGIBLE":
        perms = ["limitation"]
    return perms


# ══════════════════════════════════════════════════════════════════════ §15 packet
def _reason_for_selection(ev, ctx):
    """为什么这条证据进 synthesis 包（可复核）。"""
    why = []
    if ev["citation_eligibility"] == "ELIGIBLE":
        why.append("ELIGIBLE（可直接引用）")
    elif ev["citation_eligibility"] == "QUALIFIED":
        why.append("QUALIFIED（须附来源限制）")
    if ev["usability_class"] == "SUBSTANTIVE_TEXT":
        why.append("SUBSTANTIVE_TEXT（可承担理论断言）")
    if ev.get("rank") is not None and int(ev["rank"] or 99) <= 5:
        why.append("检索排名 ≤5")
    if ev.get("component_contribution"):
        why.append("component=%s" % ev["component_contribution"])
    return why or ["进入最终证据集"]


# 义务类别优先级：越小越先占位（§15：required 证据不得被 token 预算挤掉）
EVIDENCE_CLASS_PRIORITY = {"relation": 0, "formalism": 1, "source_layer": 2,
                           "endpoint": 3, "terminology": 4, "entity": 5,
                           "seminar": 6}


def required_evidence_classes(contract):
    """→ {passage_id: 优先级}（取该证据所属**最重要**的义务类别）。"""
    out = {}

    def add(pid, cls):
        if not pid:
            return
        out[pid] = min(out.get(pid, 99), EVIDENCE_CLASS_PRIORITY.get(cls, 9))

    # 每类保留前 N 条（契约顺序即确定顺序）；entity/seminar lane 证据**不算 must**
    # （它们数量多且可互相替代，按 ELIGIBLE+SUBSTANTIVE+rank 自然排前即可）
    CAP = {"relation": 6, "formalism": 6, "source_layer": 6, "endpoint": 4,
           "terminology": 6}

    def add_capped(pids, cls):
        for pid in list(pids)[:CAP.get(cls, 6)]:
            add(pid, cls)

    add_capped((contract.get("relation_evidence") or {}).get("ids") or [], "relation")
    add_capped([h.get("passage_id") for h in
                ((contract.get("formalism_evidence") or {}).get("hits") or [])],
               "formalism")
    # 术语：**每个术语**各留 2 条（不能因为第一个术语证据多就把后面的术语挤掉）
    for t_, v in (contract.get("terminology_evidence") or {}).items():
        add_capped((v.get("evidence_ids") or [])[:2], "terminology")
    src_ids = []
    for lane in (contract.get("execution_lanes") or []):
        lid = str(lane.get("lane_id") or "")
        if lid.startswith("source_layer:"):
            src_ids += list(lane.get("evidence_ids") or [])
    add_capped(src_ids, "source_layer")
    ep_ids = []
    for ep in ((contract.get("diachronic") or {}).get("endpoints") or []):
        ep_ids += list(ep.get("evidence_ids") or [])
    add_capped(ep_ids, "endpoint")
    return out


def required_evidence_ids(contract):
    """**必须**进入 synthesis 包的证据 id（§15：不得为了 token 预算删除唯一关键证据）。

    来源：relation 证据、formalism 命中、terminology lane、source-layer lane、
    历时端点 lane、entity lane —— 它们都是 required obligation 的直接产物。
    """
    cls = required_evidence_classes(contract)
    return sorted(cls, key=lambda p: (cls[p], p))


def select_synthesis_evidence(evidence, contract, max_n=12):
    """§15：证据最小化（**不得**为了 token 预算删掉唯一关键证据）。

    优先级：required lane 覆盖 > relation 证据 > 来源权威 > topicality > usability >
    去冗余（同一 session 相邻 passage 只留最强一条）。
    """
    rel_ids = set(contract.get("relation_evidence_ids") or [])
    must_cls = required_evidence_classes(contract)
    must_ids = set(must_cls)
    usable, excluded = [], []
    seen_session_bucket = {}
    for ev in evidence:
        el = citation_eligibility(ev)
        item = {
            "passage_id": ev.get("passage_id"), "seminar_id": ev.get("seminar_id"),
            "session_id": ev.get("session_id"), "language": ev.get("language"),
            "authority_level": ev.get("authority_level"),
            "text_role": ev.get("text_role"), "trace_status": ev.get("trace_status"),
            "canonical": ev.get("canonical"), "witness_id": ev.get("witness_id"),
            "review_status": ev.get("review_status"),
            "period": ev.get("period"), "period_label": ev.get("period_label"),
            "text": ev.get("text") or "", "rank": ev.get("rank"),
            "usability_class": el["usability_class"],
            "citation_eligibility": el["eligibility"],
            "eligibility_reasons": el["reasons"],
            "source_layer": el["source_layer"],
            "attribution": el["attribution"],
            "claim_permissions": claim_permissions(el["usability_class"],
                                                   el["eligibility"]),
            "is_relation_evidence": ev.get("passage_id") in rel_ids,
        }
        item["selection_reason"] = _reason_for_selection(item, contract)
        if el["eligibility"] == "INELIGIBLE":
            item["excluded_reason"] = "INELIGIBLE：%s" % "；".join(el["reasons"][:2])
            excluded.append(item)
            continue
        # 去冗余：同一 session 的相邻段落只保留排名最高的一条（不删关系证据）
        bucket = item["session_id"]
        if bucket and not item["is_relation_evidence"] and item["usability_class"] != "SUBSTANTIVE_TEXT":
            seen_session_bucket.setdefault(bucket, item)
        usable.append(item)
    # 排序：**required 义务证据** > 关系证据 > ELIGIBLE+SUBSTANTIVE > 其余；同级按 rank
    def _key(it):
        return (must_cls.get(it["passage_id"], 99),
                0 if it["passage_id"] in must_ids else 1,
                0 if it["is_relation_evidence"] else 1,
                0 if it["citation_eligibility"] == "ELIGIBLE" else 1,
                0 if it["usability_class"] == "SUBSTANTIVE_TEXT" else 1,
                int(it.get("rank") or 99))
    usable.sort(key=_key)
    for it in usable:
        if it["passage_id"] in must_ids and "required obligation 证据" not in it[
                "selection_reason"]:
            it["selection_reason"] = it["selection_reason"] + ["required obligation 证据"]
    selected = usable[:max_n]
    for it in usable[max_n:]:
        it = dict(it)
        it["excluded_reason"] = "超出 synthesis token 预算（max_n=%d）" % max_n
        excluded.append(it)
    return selected, excluded


def truncated_required_evidence(excluded):
    """被 token 预算挤掉的 required 证据（必须进 warnings）。"""
    return [e["passage_id"] for e in (excluded or [])
            if "required" in " ".join(e.get("selection_reason") or []) or
            "required obligation" in " ".join(e.get("selection_reason") or [])]


def evidence_diversity(selected):
    """§16：多样性记账（**不是**硬目的；直接高质量证据优先）。"""
    def _n(k):
        return len({str(x.get(k)) for x in selected if x.get(k)})
    return {"seminar_diversity": _n("seminar_id"), "session_diversity": _n("session_id"),
            "source_layer_diversity": _n("source_layer"),
            "language_diversity": _n("language"),
            "n_selected": len(selected),
            "note": "多样性只做记账；直接高质量证据优先于机械多样性"}


# ══════════════════════════════════════════════════════════════════════ permissions
def _structural_reason_codes(tr):
    codes = []
    s21 = tr.get("sufficiency_v21") or {}
    for v in s21.get("violated_rules") or []:
        codes.append(v.get("code"))
    for c in (tr.get("final_state_reason_codes") or []):
        codes.append(c)
    return [c for c in dict.fromkeys(codes) if c]


def _structural_classes(struct):
    """v2 的 structural_unanswerability 可能是 [{class,message}] 或 [str]。"""
    out = set()
    for x in (struct or []):
        if isinstance(x, dict):
            if x.get("class"):
                out.add(x["class"])
        elif x:
            out.add(str(x))
    return out


def answer_permission(run):
    """→ (permission, reasons[], status)。只有 READY 才允许进入 synthesis。"""
    tr = run.get("trace") or {}
    ex = tr.get("execution") or {}
    ec = tr.get("execution_completion") or {}
    contract = tr.get("research_contract") or {}
    evp = run.get("evidence_pack") or {}
    state = tr.get("final_state") or (evp.get("evidence_state") or {}).get("final_state")
    reasons, block = [], []

    # ① BLOCKED：执行没闭环 / 契约违规 / trace 不完整 —— 一律不得调 synthesis
    if not contract:
        block.append("MISSING_RESEARCH_CONTRACT")
    if ex.get("state") not in ("EXECUTION_COMPLETE",):
        block.append("EXECUTION_NOT_COMPLETE:%s" % ex.get("state"))
    if ec and ec.get("complete") is False:
        block.append("EXECUTION_COMPLETION_FALSE")
    if (contract.get("missing_operations") or []):
        block.append("MISSING_REQUIRED_OPERATION:%s" % contract["missing_operations"])
    if (contract.get("not_applicable_unproven") or []):
        block.append("UNPROVEN_NOT_APPLICABLE")
    if block:
        return "BLOCKED", block, "BLOCKED"

    # ② ABSTAIN：结构性不可答（不是「证据少」，而是「不可能答」）
    meta = contract.get("metadata") or {}
    form = contract.get("formalism") or {}
    s21 = tr.get("sufficiency_v21") or {}
    v2 = tr.get("sufficiency_v2") or {}
    struct = _structural_classes(v2.get("structural_unanswerability"))
    usab = contract.get("evidence_usability") or {}
    abstain = []
    if meta.get("metadata_state") == "METADATA_UNAVAILABLE":
        abstain.append("METADATA_UNAVAILABLE")
    if "TOPIC_NOT_COVERED" in struct:
        abstain.append("TOPIC_NOT_COVERED")
    if "ONTOLOGY_GAP" in struct and not usab.get("substantive_n"):
        abstain.append("ONTOLOGY_GAP")
    if form.get("formalism_state") == "CORPUS_FORMALISM_MISSING":
        abstain.append("CORPUS_FORMALISM_MISSING")
    if not usab.get("substantive_n"):
        abstain.append("NO_SUBSTANTIVE_EVIDENCE")
    if state == "INSUFFICIENT_EVIDENCE" and abstain:
        return "ABSTAIN", abstain, "READY"
    if abstain and state != "SUPPORTED":
        return "ABSTAIN", abstain, "READY"

    # ③ QUALIFIED：有上限/有缺口，但可以带限定地回答
    qual = []
    if state == "PARTIALLY_SUPPORTED":
        qual.append("EVIDENCE_STATE_PARTIALLY_SUPPORTED")
    if (contract.get("missing_lanes") or []):
        qual.append("MISSING_REQUIRED_LANE:%s" % contract["missing_lanes"])
    if contract.get("relation_evidence_required") and not contract.get("relation_evidence_n"):
        qual.append("RELATION_EVIDENCE_MISSING")
    if (contract.get("missing_source_layers") or []):
        qual.append("SOURCE_LAYER_MISSING:%s" % contract["missing_source_layers"])
    if (contract.get("failed_constraints") or []):
        qual.append("REQUIRED_CONSTRAINT_NOT_SATISFIED")
    if s21.get("violated_rules"):
        qual.append("CONTRACT_CEILING:%s" % ",".join(
            v.get("code") for v in s21["violated_rules"]))
    if qual:
        return "QUALIFIED_SYNTHESIS", qual, "READY"

    # ④ FULL：证据层 SUPPORTED、执行闭环、契约无违规
    if state == "SUPPORTED":
        return "FULL_SYNTHESIS", ["EVIDENCE_STATE_SUPPORTED", "EXECUTION_COMPLETE"], "READY"
    return "QUALIFIED_SYNTHESIS", ["FINAL_STATE=%s" % state], "READY"


# ══════════════════════════════════════════════════════════════════════ contract
def _structured_extras(run, contract):
    """从 Research Engine 的产物里抽出 synthesis 需要的结构化补充（**不是新证据**）。

    包括：实体形式、执行 lane（含 evidence_ids）、历时端点、术语三层 + lane 证据、
    relation 证据对（用于点名两侧）。
    """
    tr = run.get("trace") or {}
    ex = tr.get("execution") or {}
    plan = run.get("plan") if isinstance(run.get("plan"), dict) else {}
    form_groups = rc.entity_form_groups(plan) if plan else {}
    rel_pairs = []
    for l in (ex.get("lanes") or []):
        lid = str(l.get("lane_id") or "")
        if lid.startswith("relation:") and "+" in lid:
            a, b = lid.split(":", 1)[1].split("+", 1)
            rel_pairs.append([a, b])
    ex_lanes = [{"lane_id": l.get("lane_id"), "lane_type": l.get("lane_type"),
                 "status": l.get("status"), "required": l.get("required"),
                 "evidence_ids": l.get("evidence_ids") or [],
                 "usable_hit_count": l.get("usable_hit_count"),
                 "note": l.get("note")}
                for l in (ex.get("lanes") or [])]
    lane_ev = {l["lane_id"]: (l.get("evidence_ids") or []) for l in ex_lanes}
    diachronic = {"endpoints": [
        {"endpoint_id": (e.get("endpoint_id") or ""),
         "seminar": e.get("seminar"),
         "evidence_ids": lane_ev.get(e.get("endpoint_id"), []),
         "usable_evidence_n": e.get("usable_evidence_n"),
         "completion": e.get("completion")}
        for e in (ex.get("endpoints") or [])]}
    term_evidence = {}
    for t_, v in ((ex.get("terminology") or {}).get("terms") or {}).items():
        v = dict(v)
        v["evidence_ids"] = lane_ev.get("term:%s" % t_, [])
        term_evidence[t_] = v
    # relation 两侧：优先 lane 解析；否则用实体形式在关系证据段落里的在场情况推导
    if not rel_pairs:
        rel_ids = list(contract.get("relation_evidence_ids") or [])
        for e in (run.get("evidence_pack") or {}).get("evidence") or []:
            if e.get("passage_id") not in rel_ids:
                continue
            import gold_normalization as gn
            text = str(e.get("text") or "")
            present = [eid for eid, forms in form_groups.items()
                       if any(gn.contains_v2(text, f) for f in (forms or []) if f)]
            if len(present) >= 2:
                rel_pairs.append(sorted(present)[:2])
                break
    return {
        "entities": {"ids": contract.get("required_entities") or [],
                     "form_groups": form_groups},
        "execution_lanes": ex_lanes,
        "diachronic": diachronic,
        "terminology_evidence": term_evidence,
        "formalism_evidence": {
            "required": (contract.get("formalism") or {}).get("formalism_required"),
            "state": (contract.get("formalism") or {}).get("formalism_state"),
            "kind": (contract.get("formalism") or {}).get("formalism_evidence_kind"),
            "symbols": (contract.get("formalism") or {}).get("symbols"),
            "seminar": (contract.get("formalism") or {}).get("formalism_seminar"),
            "hits": (ex.get("formalism") or {}).get("hits") or [],
            "strategy_counts": (ex.get("formalism") or {}).get("strategy_counts") or {},
        },
        "relation_pairs": rel_pairs,
    }


def build_synthesis_input_contract(run, max_evidence=12):
    """Research Engine 的产物 → SynthesisInputContract（§2 的字段表）。"""
    tr = run.get("trace") or {}
    evp = run.get("evidence_pack") or {}
    ex = tr.get("execution") or {}
    contract = tr.get("research_contract") or {}
    permission, reasons, status = answer_permission(run)
    extras = _structured_extras(run, contract)
    sel_contract = dict(contract)
    sel_contract.update(extras)
    selected, excluded = select_synthesis_evidence(
        evp.get("evidence") or [], sel_contract, max_n=max_evidence)
    tpl = synthesis_template(run.get("plan", {}).get("task_type")
                             if isinstance(run.get("plan"), dict) else
                             (run.get("trace") or {}).get("task_type"),
                             contract)
    abstention = {
        "required": permission in ("ABSTAIN",),
        "must_include": ["abstention_reason_codes", "missing_information",
                         "available_partial_information", "next_required_sources"],
        # 只有真的 ABSTAIN 才填 reason_codes；QUALIFIED 的原因另列，避免把「限定」说成「弃权」
        "reason_codes": ([r for r in reasons if r in ABSTENTION_REASON_CODES]
                         or ["NO_SUBSTANTIVE_EVIDENCE"]) if permission == "ABSTAIN" else [],
        "qualified_reasons": [r for r in reasons if r not in ("EVIDENCE_STATE_SUPPORTED",
                                                              "EXECUTION_COMPLETE")] if
        permission == "QUALIFIED_SYNTHESIS" else [],
        "forbidden": ["theoretical_development_without_evidence",
                      "pipeline_log_as_answer"],
    }
    citation_policy = {
        "claim_level_binding": True,
        "rule": "每条 substantive claim 必须绑定 evidence_id[]；段落末尾堆引用不算",
        "chain": ["claim", "evidence_id", "passage_id", "source_layer"],
        "eligibility_required": ["ELIGIBLE", "QUALIFIED"],
        "ineligible_use": "只允许进 limitation，不得支持 substantive claim",
        "quote_policy": {
            "direct_quote_requires": ["passage_id", "exact_span", "language",
                                      "source_layer"],
            "paraphrase_marker": "PARAPHRASE",
            "model_translation_marker": "MODEL_TRANSLATION",
            "forbidden": ["LLM 自行重构原文", "把 model translation 冒充 corpus witness"],
        },
    }
    return {
        "schema_version": SCHEMA,
        "task_id": run.get("task_id") or tr.get("task_id"),
        "question": run.get("question"),
        "task_type": (run.get("plan") or {}).get("task_type") if isinstance(
            run.get("plan"), dict) else tr.get("task_type"),
        "status": status,
        "answer_permission": permission,
        "permission_reasons": reasons,
        "evidence_state": tr.get("final_state"),
        "execution_state": ex.get("state"),
        "research_contract_summary": {
            "contract_type": contract.get("contract_type"),
            "required_operations": contract.get("required_operations"),
            "resolved_operations": contract.get("resolved_operations"),
            "missing_operations": contract.get("missing_operations"),
            "required_lanes": contract.get("required_lanes"),
            "missing_lanes": contract.get("missing_lanes"),
            "required_constraints": contract.get("required_constraints"),
            "failed_constraints": contract.get("failed_constraints"),
            "state_ceiling": (tr.get("sufficiency_v21") or {}).get("state_ceiling"),
            "violated_rules": [v.get("code") for v in
                               ((tr.get("sufficiency_v21") or {}).get("violated_rules")
                                or [])],
        },
        "answer_permissions": {
            "allowed": permission,
            "may_write_theoretical_claims": permission in ("FULL_SYNTHESIS",
                                                           "QUALIFIED_SYNTHESIS"),
            "may_write_certainty": permission == "FULL_SYNTHESIS",
            "must_qualify": permission == "QUALIFIED_SYNTHESIS",
            "must_abstain": permission == "ABSTAIN",
        },
        "claim_permissions": {
            "by_usability": CLAIM_PERMISSION_BY_USABILITY,
            "by_eligibility": {"ELIGIBLE": ["substantive"],
                               "QUALIFIED": ["substantive", "contextual"],
                               "INELIGIBLE": ["limitation"]},
            "hard_rules": [
                "substantive claim 的 evidence 至少要有一条 citation_eligibility ∈ {ELIGIBLE, QUALIFIED}",
                "MEDIA_ONLY / BIBLIOGRAPHY_ONLY 不得支持 theoretical claim",
                "EDITORIAL_METADATA 只能支持 metadata/history claim",
                "FRAGMENT_ONLY 只能作 contextual support",
            ],
        },
        "abstention_requirements": abstention,
        "usable_evidence": selected,
        "excluded_evidence": excluded,
        "evidence_diversity": evidence_diversity(selected),
        "relation_evidence": {
            "required": bool(contract.get("relation_evidence_required")),
            "n": contract.get("relation_evidence_n"),
            "ids": contract.get("relation_evidence_ids") or [],
            "strength": contract.get("relation_strength"),
            "kinds": contract.get("relation_kinds"),
            "pairs": extras["relation_pairs"],
        },
        "source_layers": {
            "required": contract.get("required_source_layers"),
            "available": contract.get("available_source_layers"),
            "missing": contract.get("missing_source_layers"),
            "corpus": contract.get("source_layer_corpus"),
            "execution": ex.get("source_layers") or {},
        },
        "formalism_evidence": extras["formalism_evidence"],
        "terminology_evidence": extras["terminology_evidence"],
        "entities": extras["entities"],
        "execution_lanes": extras["execution_lanes"],
        "diachronic": extras["diachronic"],
        "metadata_evidence": contract.get("metadata") or {},
        "warnings": _warnings(tr, evp) + (
            ["REQUIRED_EVIDENCE_TRUNCATED_IN_SYNTHESIS_PACKET"]
            if truncated_required_evidence(excluded) else []),
        "citation_policy": citation_policy,
        "synthesis_template": tpl,
        "failure_modes": list(FAILURE_MODES),
        "no_hidden_reasoning": True,
    }


def _warnings(tr, evp):
    out = []
    for w in (evp.get("warnings") or []):
        if isinstance(w, dict) and w.get("code"):
            out.append(w["code"])
    if (tr.get("research_contract") or {}).get("not_applicable_operations"):
        out.append("NOT_APPLICABLE_OPERATIONS_PRESENT")
    if (evp.get("provenance") or {}).get("trace_incomplete_n"):
        out.append("SOURCE_TRACE_INCOMPLETE_PRESENT")
    return sorted(set(out))


__all__ = ["SCHEMA", "ANSWER_PERMISSIONS", "CLAIM_TYPES", "EPISTEMIC_STATUS",
           "CITATION_ELIGIBILITY", "FAILURE_MODES", "ABSTENTION_REASON_CODES",
           "SYNTHESIS_TEMPLATES", "build_synthesis_input_contract",
           "answer_permission", "citation_eligibility", "claim_permissions",
           "select_synthesis_evidence", "evidence_diversity", "synthesis_template",
           "SOURCE_ATTRIBUTION"]
