#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthesis_validation.py — Phase 4C.1-D §23–§29：验证流水线

    LLM / Mock draft
      → 预清洗（丢无证据 / 包外引用；引文不可核只丢引文）
      → C 阶段结构验证（synthesis_claims）
      → D 阶段 entailment（synthesis_entailment，Hybrid）
      → Repair / Downgrade / Reject
      → **只由 validated claims 重新渲染**（不是把 LLM 散文原样返回）
      → Validated Scholarly Answer + metrics v2

最后一步是本系统最重要的安全边界：最终答案里的每一句 substantive 内容都来自
通过验证的 claim，LLM 的原始散文**不进入**最终产物。
"""
from __future__ import annotations

import re
import sys

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
sys.path.insert(0, HERE)

import synthesis_claims as scl          # noqa: E402
import synthesis_entailment as se       # noqa: E402
import synthesis_render as sr           # noqa: E402

VALIDATED_ANSWER_STATES = ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "ABSTAINED",
                           "BLOCKED", "VALIDATION_FAILED")

MAX_REPAIR_ATTEMPTS = 2

_UNIVERSAL_FIX = re.compile(r"总是|始终|一律|从来|永远|必然|绝对|完全|"
                            r"always|never|necessarily|absolutely", re.I)
_SCOPE_HINT = "（就该段而言）"


# ══════════════════════════════════════════════════════════════════════ repair
def narrow_claim(claim, verdict, contract):
    """§23 NARROW_CLAIM（确定性）：只保留**被蕴含的原子**，并去掉全称措辞。"""
    atoms = verdict.get("atoms") or []
    good = [a for a in atoms
            if a["status"] in ("ENTAILED", "PARTIALLY_ENTAILED")]
    if not good:
        return None
    # 从 claim_text 里挑出**被蕴含的原子**对应的片段（按文本包含关系，而不是位置）
    parts = [p.strip() for p in re.split(r"[；;，,。]", str(claim.get("claim_text") or ""))
             if p.strip()]
    entailed_texts = [str(a.get("atom_text") or "") for a in good]
    keep = [p for p in parts
            if any(p and (p in et or et in p) for et in entailed_texts)]
    if not keep:
        keep = [et for et in entailed_texts if et][:1]
    if not keep:
        return None
    new_text = "；".join(keep)
    new_text = _UNIVERSAL_FIX.sub("", new_text)
    if "该段" not in new_text and "语料" not in new_text:
        new_text = new_text + _SCOPE_HINT
    new = dict(claim)
    new["claim_text"] = new_text
    new["parent_claim_id"] = claim.get("claim_id")
    new["repaired_from"] = claim.get("claim_id")
    new["repair_kind"] = "NARROW_CLAIM"
    if new.get("epistemic_status") == "DIRECTLY_SUPPORTED":
        new["epistemic_status"] = "QUALIFIED_INFERENCE"      # §24 downgrade
        new["downgraded"] = "DIRECTLY_SUPPORTED→QUALIFIED_INFERENCE"
    return new


def validate_and_repair(claims, contract, judge=None, question=None,
                        max_attempts=MAX_REPAIR_ATTEMPTS):
    """逐 claim：验证 → repair/downgrade → 再验证（最多 max_attempts）→ reject。"""
    results, validated, rejected, repaired = [], [], [], []
    for c in claims:
        attempt = 0
        cur = c
        verdict = se.validate_claim(cur, contract, judge=judge, question=question)
        # substantive claim 若停在 INSUFFICIENT_CONTEXT，同样不接受（防御纵深）
        if verdict["status"] == "INSUFFICIENT_CONTEXT" and \
                verdict["claim_type"] in se.SUBSTANTIVE_CLAIM_TYPES:
            verdict = dict(verdict)
            verdict["reject"] = True
        # §23：PARTIALLY_ENTAILED 必须**先尝试 NARROW_CLAIM**（而不是直接放过或 reject）
        while (verdict["reject"] or verdict["status"] == "PARTIALLY_ENTAILED") \
                and attempt < max_attempts:
            attempt += 1
            fixed = narrow_claim(cur, verdict, contract)
            if fixed is None:
                break
            cur = fixed
            verdict = se.validate_claim(cur, contract, judge=judge,
                                        question=question)
        entry = {"claim_id": c.get("claim_id"),
                 "final_claim_id": cur.get("claim_id"),
                 "status": verdict["status"], "strength": verdict["strength"],
                 "attempts": attempt,
                 "repaired": bool(cur.get("repaired_from")),
                 "disagreement": verdict["disagreement"],
                 "composite": verdict["composite"],
                 "composite_kind": verdict["composite_kind"],
                 "atoms": verdict["atoms"],
                 "reject_reason": verdict.get("reason") if verdict["reject"] else None}
        results.append(entry)
        if verdict["reject"]:
            rejected.append({"claim": cur, "verdict": verdict,
                             "original_claim_id": c.get("claim_id")})
        else:
            if cur.get("repaired_from"):
                repaired.append({"original_claim_id": c.get("claim_id"),
                                 "repaired_claim": cur, "attempts": attempt})
            validated.append(cur)
    return {"results": results, "validated": validated, "rejected": rejected,
            "repaired": repaired}


# ══════════════════════════════════════════════════════════════════════ re-render
_SECTION_BY_TYPE = {
    "DEFINITION": "working_definition", "DISTINCTION": "key_distinctions",
    "RELATION": "relationship", "DIACHRONIC_CHANGE": "diachronic_analysis",
    "SOURCE_INFLUENCE": "source_philosophy", "REINTERPRETATION": "lacanian_reinterpretation",
    "TERMINOLOGY": "term_mapping", "FORMALISM": "formal_expression",
    "METADATA": "answer", "CORPUS_ABSENCE": "corpus_attestation",
    "LIMITATION": "limitations",
}


def engine_scan_ref(contract, claim):
    """引擎侧普查事实（**不是**模型编的）：给 absence/metadata 断言注入真实凭据。

    来源：术语桥 ZERO_ATTESTATION / metadata scan / 来源层全库普查。
    找不到任何事实 → 返回 None（调用方必须**丢掉**该断言，不得凭空写「不存在」）。
    """
    text = str(claim.get("claim_text") or "")
    for t_, v in (contract.get("terminology_evidence") or {}).items():
        if t_ and t_ in text and v.get("attestation_completion") == "ZERO_ATTESTATION":
            return {"scope": "whole_corpus", "term": t_,
                    "corpus_hits": int(v.get("corpus_hits") or 0),
                    "source": "terminology_lane", "injected_by": "engine"}
    meta = contract.get("metadata_evidence") or {}
    if meta.get("metadata_state") == "METADATA_UNAVAILABLE":
        return {"scope": "whole_corpus",
                "fields": meta.get("metadata_missing_fields") or [],
                "n_with_real_value": 0, "source": "metadata_scan",
                "injected_by": "engine"}
    corpus = (contract.get("source_layers") or {}).get("corpus") or {}
    for layer, avail in corpus.items():
        if avail is False and (layer.split("_")[0].lower() in text.lower()):
            return {"scope": "whole_corpus", "missing_layer": layer,
                    "corpus_availability": False, "source": "source_layer_corpus",
                    "injected_by": "engine"}
    return None


def render_validated_answer(contract, validated, rejected, abstention=None,
                            extra_limitations=None):
    """只由 validated claims 渲染最终答案（§26：LLM 散文不进最终产物）。"""
    sections = {}
    for c in validated:
        sec = _SECTION_BY_TYPE.get(c.get("claim_type"), "evidence")
        cite = "、".join(c.get("evidence_ids") or [])
        line = "- %s%s" % (c.get("claim_text"),
                           ("（%s）" % cite) if cite else "（普查凭据）")
        sections[sec] = (sections.get(sec, "") + "\n" + line).strip()
    lim = []
    for r in rejected:
        lim.append("- 已剔除未通过蕴含验证的断言：%s（%s）"
                   % (str(r["claim"].get("claim_text"))[:80], r["verdict"]["status"]))
    for x in (extra_limitations or []):
        lim.append("- %s" % x)
    if lim:
        sections["limitations"] = (sections.get("limitations", "") + "\n" +
                                   "\n".join(lim)).strip()
    n_ok = len([c for c in validated
                if c.get("epistemic_status") == "DIRECTLY_SUPPORTED"])
    sections["brief_answer"] = (
        "本回答由 %d 条通过蕴含验证的断言构成（其中 %d 条为直接支持）；"
        "%d 条断言因未通过验证被剔除。" % (len(validated), n_ok, len(rejected)))
    answer = sr.build_answer(contract, validated, sections,
                             abstention=abstention)
    if not validated and not abstention:
        answer["answer_state"] = "VALIDATION_FAILED"
    elif rejected or any(c.get("epistemic_status") != "DIRECTLY_SUPPORTED"
                         for c in validated):
        answer["answer_state"] = "VALIDATED_WITH_QUALIFICATIONS"
    else:
        answer["answer_state"] = "VALIDATED"
    if abstention:
        answer["answer_state"] = "ABSTAINED"
    if contract.get("answer_permission") == "BLOCKED":
        answer["answer_state"] = "BLOCKED"
    answer["rejected_claims"] = [
        {"claim_id": r["claim"].get("claim_id"),
         "claim_text": r["claim"].get("claim_text"),
         "status": r["verdict"]["status"],
         "reason": r["verdict"].get("reason")} for r in rejected]
    return answer


# ══════════════════════════════════════════════════════════════════════ pipeline
def run_validation_pipeline(run, contract, draft, judge=None, question=None):
    """完整 D 流水线：预清洗 → C 验证 → entailment → repair/reject → re-render。"""
    claims = list(draft.get("claims") or [])
    kept, dropped, quote_fixes = se.sanitize_claims(claims, contract)
    # 引擎侧普查凭据注入（§18/§19）：注入不了就丢掉该断言
    _after = []
    for c in kept:
        if c.pop("_needs_scan_ref", False):
            ref = engine_scan_ref(contract, c)
            if ref is None:
                dropped.append({"claim_id": c.get("claim_id"),
                                "code": "ABSENCE_WITHOUT_SCAN_PROVENANCE",
                                "claim_text": str(c.get("claim_text"))[:120]})
                continue
            c["corpus_scan_ref"] = ref
            c["scan_ref_injected"] = True
        _after.append(c)
    kept = _after
    crep = scl.validate_claims(kept, contract)
    # C 阶段仍违规的 claim 不进 entailment
    bad_ids = {v["detail"].split()[1] if False else None for v in []}
    violators = set()
    for v in crep["violations"]:
        m = re.search(r"claim (\S+)", v.get("detail") or "")
        if m:
            violators.add(m.group(1))
    survivors = [c for c in kept if c.get("claim_id") not in violators]
    _by_cid = {}
    for v in crep["violations"]:
        m = re.search(r"claim (\S+)", v.get("detail") or "")
        if m:
            _by_cid.setdefault(m.group(1), []).append(v["code"])
    c_dropped = [{"claim_id": c.get("claim_id"),
                  "claim_text": str(c.get("claim_text"))[:120],
                  "code": (_by_cid.get(c.get("claim_id")) or ["SYNTHESIS_SCHEMA_INVALID"])[0],
                  "codes": _by_cid.get(c.get("claim_id")) or []}
                 for c in kept if c.get("claim_id") in violators]
    vres = validate_and_repair(survivors, contract, judge=judge, question=question)
    answer = render_validated_answer(
        contract, vres["validated"], vres["rejected"],
        abstention=draft.get("abstention"))
    return {
        "generated_claims": len(claims),
        "prevalidation_dropped": dropped,
        "quote_fixes": quote_fixes,
        "c_validation": crep,
        "c_dropped": c_dropped,
        "entailment": {"results": vres["results"],
                       "repaired": [{"original_claim_id": r["original_claim_id"],
                                     "repaired_claim_id":
                                         r["repaired_claim"].get("claim_id"),
                                     "attempts": r["attempts"]}
                                    for r in vres["repaired"]],
                       "rejected": [{"claim_id": r["claim"].get("claim_id"),
                                     "claim_text": str(r["claim"].get("claim_text"))[:200],
                                     "status": r["verdict"]["status"],
                                     "reason": r["verdict"].get("reason")}
                                    for r in vres["rejected"]]},
        "validated_claims": vres["validated"],
        "answer": answer,
        "markdown": sr.render_markdown(answer),
        "answer_state": answer.get("answer_state"),
    }


# ══════════════════════════════════════════════════════════════════════ metrics v2
def entailment_metrics(rows):
    """§28/§29/§40：entailment 与 citation 指标（v2）。"""
    def _n(pred, seq):
        return len([x for x in seq if pred(x)])

    all_results = [r for row in rows for r in
                   ((row.get("entailment") or {}).get("results") or [])]
    validated = [c for row in rows for c in (row.get("validated_claims") or [])]
    rejected = [r for row in rows
                for r in ((row.get("entailment") or {}).get("rejected") or [])]
    repaired = [r for row in rows
                for r in ((row.get("entailment") or {}).get("repaired") or [])]
    atoms = [a for r in all_results for a in (r.get("atoms") or [])]
    finals = [row.get("answer") or {} for row in rows]
    final_claims = [c for a in finals for c in (a.get("claims") or [])]
    final_quote_bad = 0
    for a in finals:
        for c in a.get("claims") or []:
            q = c.get("quotation")
            if q and q.get("kind") == "CORPUS_QUOTE" and not q.get("exact_span"):
                final_quote_bad += 1
    gen = sum(int(row.get("generated_claims") or 0) for row in rows)
    status_counts = {s: _n(lambda r: r.get("status") == s, all_results)
                     for s in se.ENTAILMENT_STATUS}
    strength_counts = {s: _n(lambda a: a.get("strength") == s, atoms)
                       for s in se.ENTAILMENT_STRENGTH}
    eligible_final = _n(lambda c: True, final_claims)
    return {
        "tasks_n": len(rows),
        "generated_claims": gen,
        "validated_claims": len(validated),
        "repaired_claims": len(repaired),
        "rejected_claims": len(rejected),
        "atom_n": len(atoms),
        "claims_without_evidence_in_final": _n(
            lambda c: c.get("claim_type") in se.SUBSTANTIVE_CLAIM_TYPES
            and not c.get("evidence_ids"), final_claims),
        "invalid_citations_in_final": 0,          # 由 Gate 21 复算，这里占位
        "invalid_quotes_in_final": final_quote_bad,
        "source_role_violations_generated": _n(
            lambda r: r.get("status") == "SOURCE_ROLE_MISMATCH", all_results),
        "source_role_violations_in_final": _n(
            lambda c: any(
                (r.get("final_claim_id") or r.get("claim_id")) == c.get("claim_id")
                and r.get("status") == "SOURCE_ROLE_MISMATCH"
                for r in all_results), final_claims),
        "NOT_ENTAILED_generated": status_counts["NOT_ENTAILED"],
        "CONTRADICTED_generated": status_counts["CONTRADICTED"],
        "NOT_ENTAILED_in_final": _n(
            lambda c: c.get("entailment_status") == "NOT_ENTAILED", final_claims),
        "CONTRADICTED_in_final": _n(
            lambda c: c.get("entailment_status") == "CONTRADICTED", final_claims),
        "entailment_status_counts": status_counts,
        "entailment_strength_counts": strength_counts,
        "claim_validation_rate": _round(len(validated), gen),
        "direct_entailment_rate": _round(status_counts["ENTAILED"], len(all_results)),
        "partial_entailment_rate": _round(status_counts["PARTIALLY_ENTAILED"],
                                          len(all_results)),
        "rejected_claim_rate": _round(len(rejected), gen),
        "claim_citation_binding_rate": _round(
            _n(lambda c: c.get("evidence_ids") or c.get("corpus_scan_ref"),
               validated + [r["claim"] for r in []]), len(validated)),
        "entailed_citation_rate": _round(
            _n(lambda r: r.get("status") == "ENTAILED", all_results), len(all_results)),
        "source_role_valid_rate": _round(
            len(all_results) - status_counts["SOURCE_ROLE_MISMATCH"], len(all_results)),
        "quote_validation_rate": _round(
            _n(lambda a: a.get("quote_ok") is not False, atoms), len(atoms)),
        "composite_entailment_success_rate": _round(
            _n(lambda r: r.get("composite") and r.get("status") == "ENTAILED",
               all_results),
            _n(lambda r: r.get("composite"), all_results)),
        "disagreement_n": _n(lambda r: r.get("disagreement"), all_results),
        "legacy_metrics": {
            "status": "LEGACY_DIAGNOSTIC_ONLY",
            "note": ("Phase 4C 已证明旧的 citation_anchor_support_rate 与人工判断反向，"
                     "不得再当 scholarly quality proxy；此处仅作历史兼容。"),
            "citation_anchor_support_rate": None,
        },
    }


def _round(n, d):
    return round(n / d, 4) if d else None


__all__ = ["VALIDATED_ANSWER_STATES", "MAX_REPAIR_ATTEMPTS", "narrow_claim",
           "validate_and_repair", "render_validated_answer", "run_validation_pipeline",
           "entailment_metrics"]
