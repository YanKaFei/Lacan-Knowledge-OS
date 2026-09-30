#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_scholarly_regression_v1.py — Phase 4C.1-A §12：14 个已人工评审任务的**回归规格**

为什么不能只存 `expected_state`
───────────────────────────────
Phase 4C 人工评审证明：`expected_state` 单独存在时无法阻止回归 —— 系统可以在
「缺 lane / 缺端点 / 缺关系证据 / 缺 formalism / 缺 metadata」的情况下仍然输出
SUPPORTED（rt-B01、rt-C03、rt-G01、rt-H02 全都是这样）。因此回归规格必须同时保存：

    required_entities / required_operations / required_lanes / required_constraints
    expected_zero_lanes / relation_evidence_required / source_layers_required
    seminar_constraints / period_constraints / formalism_required / metadata_required
    supported_forbidden_conditions
    human_review_baseline / human_adjudication

数据来源（全部为冻结产物，只读）
────────────────────────────────
    research_tasks_v1.jsonl             结构字段（entities / operations / seminars / periods / lanes）
    research_human_review.jsonl         14 条人工评分（冻结基线）
    human_adjudication_queue.jsonl      3 条裁决（冻结）
    evaluation_truth_adjudicated_v1.json 三个裁决题的 gold_v2 规范
    lane_semantics_v1.json              空 lane 语义

`SPEC_OVERLAY` 是**本阶段唯一手写的部分**：每条要求都带 `basis`，指向该要求在
人工评审记录里对应的 issue code（不允许无据添加要求）。

用法
────
    python3 build_scholarly_regression_v1.py             # 写 _data/eval/scholarly_regression_v1.jsonl
    python3 build_scholarly_regression_v1.py --check     # 校验可复现 + 覆盖 14/14
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
OUT = os.path.join(EVAL, "scholarly_regression_v1.jsonl")
sys.path.insert(0, HERE)
import eval_integrity as ei  # noqa: E402

# ── 手写 overlay：每条要求都注明依据（人工评审的 issue code / requested_changes）──
SPEC_OVERLAY = {
    "rt-A01": {
        "required_lanes": ["fr_core", "zh_core"],
        "required_constraints": ["≥2 个 period（分期定位），且每期给代表性 passage"],
        "partner_checks": ["每一处「阶段变化」陈述都要有 claim → passage 直接支持"],
        "supported_forbidden_conditions": ["只用一期材料就给出「拉康的定义是」"],
        "basis": ["task_decomposition", "evidence_topicality", "answer_contract",
                  "reviewer requested_changes 1–5"],
    },
    "rt-D01": {
        "required_lanes": ["fr_s11_regard", "fr_s11_objet"],
        "required_constraints": ["seminar 约束 S11 必须下推到 retrieval",
                                 "gaze/regard 必须定位到 objet a，不得当作「观看行为」"],
        "supported_forbidden_conditions": ["把 Sartre 的凝视等同于 Lacan 对 gaze 的形式化"],
        "basis": ["answer_contract", "claim_granularity", "本轮唯一 citation_support=PASS 的包"],
    },
    "rt-B01": {
        "required_lanes": ["lane_besoin", "lane_demande", "lane_desir"],
        "required_constraints": ["三条 lane 必须各自独立取证",
                                 "必须检索三者发生直接关系/转换的 passages"],
        "relation_evidence_required": True,
        "if_missing_lane": "SUPPORTED = forbidden",
        "supported_forbidden_conditions": ["任一条 lane 证据不足时仍判 SUPPORTED"],
        "basis": ["research_planning_lane_execution", "evidence_sufficiency_false_supported",
                  "non_substantive_evidence", "generic_lexical_occurrence_as_evidence",
                  "citation_entailment_vs_authenticity", "reviewer requested_changes 1–6"],
    },
    "rt-E01": {
        "required_lanes": ["fr_schreber"],
        "required_constraints": ["案卷材料与理论位置分层",
                                 "psychose 与 névrose / perversion 必须是**并列**关系而非同义别名"],
        "supported_forbidden_conditions": ["用 perversion 材料充当 psychose 的证据"],
        "basis": ["ontology_alias_collapse", "distinction_failure_clinical_structures",
                  "no_substantive_claim", "evidence_sufficiency_relation_hard_rule_missing",
                  "non_substantive_evidence", "query_decomposition_predicate_as_entity"],
    },
    "rt-I02": {
        "required_lanes": ["fr_reel", "fr_realite", "zh_pair"],
        "required_constraints": ["Réel 与 réalité 必须保持区分（概念 vs 术语层）",
                                 "plan 的 planned_operations 必须真执行"],
        "supported_forbidden_conditions": ["把 Réel 与 réalité 当作同一个东西"],
        "basis": ["no_substantive_claim", "ontology_alias_collapse",
                  "evidence_selection_ignores_direct_evidence",
                  "planned_operations_not_executable", "state_model_inconsistency",
                  "evidence_sufficiency_false_positive"],
    },
    "rt-C03": {
        "required_lanes": ["fr_s07", "fr_s20"],
        "required_endpoints": ["seminar.S07", "seminar.S20"],
        "required_constraints": ["历时两端都必须真实进入检索（端点缺失不得判 SUPPORTED）",
                                 "必须产出历时性 substantive claim（而非 Seminar 分布）"],
        "diachronic_claim_required": True,
        "if_endpoint_missing": "SUPPORTED = forbidden",
        "supported_forbidden_conditions": ["端点缺席时仍输出「A→B 的发展」结论"],
        "basis": ["diachronic_endpoint_missing", "scope_constraint_not_pushed_down",
                  "sufficiency_false_supported_diachronic", "no_substantive_diachronic_claim",
                  "evidence_quality_enjoyment_vs_jouissance", "recovered_layer_weight",
                  "trace_auditability_limit", "state_machine_contract_conflict",
                  "sufficiency_explanation_cites_absent_signals"],
    },
    "rt-F01": {
        "required_lanes": ["fr_trieb", "zh_pulsion"],
        "source_layers_required": ["Freud 原始层（Trieb）", "Lacan 重读层（pulsion）"],
        "relation_evidence_required": True,
        "required_constraints": ["source_layer_separation 必须真执行（当前是声明性 metadata）",
                                 "每条「Lacan 重读 Freud」claim 需同时能回到两层证据"],
        "supported_forbidden_conditions": ["Freud primary 层为 0 时判 SUPPORTED"],
        "basis": ["source_layer_separation_not_executed",
                  "required_capability_is_declarative_only", "no_substantive_claim",
                  "non_substantive_evidence_promoted", "evidence_sufficiency_false_positive",
                  "resolution_state_not_unified"],
    },
    "rt-G02": {
        "required_lanes": ["fr_cogito", "fr_descartes"],
        "required_entities": ["concept.sujet", "concept.moi"],
        "required_constraints": ["必须区分 sujet 与 moi（v4a1 新建 concept.moi）",
                                 "expected entities 未解析时不得判 SUPPORTED",
                                 "plan 的 find_concept_evidence / compare_concepts 必须真执行",
                                 "gold lane 必须能衡量 sujet/moi 的理论区分，而非仅词面覆盖"],
        "supported_forbidden_conditions": ["把 cogito 与 sujet 直接等同",
                                          "未解析 expected entities 时判 SUPPORTED"],
        "basis": ["core_research_task_not_completed", "required_distinction_absent",
                  "no_substantive_claim", "citation_support_insufficient",
                  "plan_not_executable_contract", "gold_lane_not_measuring_theoretical_task",
                  "evidence_sufficiency_false_positive", "sufficiency_reason_contradicts_signals"],
    },
    "rt-J02": {
        "required_lanes": ["zh_frmi"],
        "expected_zero_lanes": ["zh_frmi（fMRI 全库 0 段；v1 的 3 条命中是 URL 跨 token 假阳性）"],
        "abstention_contract": ["必须说明为什么不可答（全库 0 命中 + 语料年代范围）",
                                "不得把 degenerate / 无关 passage 当作 evidence 展示",
                                "citation 应支持「为什么不可答」，而不是引用无关材料"],
        "supported_forbidden_conditions": ["把普通「脑/影像」材料综合成 Lacan 对 fMRI 的看法"],
        "basis": ["abstention_rationale_not_surfaced_in_answer",
                  "degenerate_evidence_presented_as_theoretical_development",
                  "citation_contract_unsuited_to_abstention",
                  "gold_lane_normalization_cross_token_false_positive",
                  "gold_lane_false_positives_are_systemic", "state_consistency_defects"],
    },
    "rt-J03": {
        "metadata_required": ["日级日期（canonical store 的 session_date）",
                              "地点", "在场者"],
        "required_constraints": ["metadata 字段全库 unknown → 触发 METADATA_UNAVAILABLE",
                                 "不得进入普通 topical evidence synthesis",
                                 "必须明确指出缺失的具体字段",
                                 "用户问题自身的日期前提无法在库内验证时标记 premise_unverified",
                                 "editorial note 不得计入 Lacan primary evidence"],
        "supported_forbidden_conditions": ["用年份区间冒充确切日期", "编造日期/地点/人名"],
        "basis": ["internal_verdict_not_surfaced_in_answer",
                  "irrelevant_evidence_leaked_into_final_answer",
                  "citation_contract_cannot_support_historical_facts",
                  "editorial_note_counted_as_l1_primary",
                  "text_role_and_authority_level_too_coarse",
                  "question_premise_not_challenged",
                  "structural_unanswerability_not_mapped_to_failure_taxonomy"],
    },
    "rt-H02": {
        "required_lanes": ["fr_fantasme_s14", "fr_objet_s14", "formalism（新增：◊ / S ◊ a）"],
        "formalism_required": ["◊", "S ◊ a", "(S ◊ a)", "poinçon", "formule"],
        "seminar_constraints": ["seminar.S14"],
        "required_entities": ["concept.fantasme", "concept.objet-petit-a"],
        "required_constraints": ["formalism-specific 全库扫描先于 STRUCTURAL 判定",
                                 "RETRIEVED_FORMALISM_MISSING ≠ CORPUS_FORMALISM_MISSING"],
        "retrieval_formalism_missing": "structural_unanswerability = false",
        "supported_forbidden_conditions": ["未经全库 formalism 扫描就断言结构性不可答",
                                          "把 $ ◊ a 翻译成自然语言后当作拉康原话引用"],
        "basis": ["formalism_query_dropped",
                  "retrieval_miss_misclassified_as_structural_unanswerability",
                  "wrong_concept_pair", "gold_evidence_derivation_defect",
                  "no_substantive_matheme_claim", "citation_entailment_failure",
                  "seminar_constraint_not_enforced", "ontology_state_inconsistency",
                  "裁决 GOLD_CORRECT（仅 answerability 标签）"],
    },
    "rt-I03": {
        "terminology_lanes": ["快感", "享受", "原乐"],
        "expected_zero_lanes": ["原乐（ZERO_ATTESTATION：全库 0 段）"],
        "required_lanes": [],
        "required_constraints": ["translation_terminology 必须强制 terminology_lookup",
                                 "用户显式列出的每个译名必须生成独立 lexical lane",
                                 "ontology RESOLVED ≠ corpus attested",
                                 "词面出现 ≠ 目标术语翻译，需 context validation",
                                 "0-hit 术语必须明确报告「当前 corpus 无证据」",
                                 "不得把问题残片送入 compare_concepts"],
        "supported_forbidden_conditions": ["missing required terminology lane 时判 SUPPORTED",
                                          "把「原乐」说成语料中已确立的译名"],
        "basis": ["terminology_task_not_executed", "explicit_translation_terms_ignored",
                  "question_fragment_used_as_concept", "terminology_lookup_not_executed",
                  "ontology_mapping_confused_with_corpus_attestation",
                  "empty_lane_semantics_missing", "retrieval_miss_with_supported_state",
                  "unsupported_state_upgrade", "no_substantive_terminology_claim",
                  "citation_entailment_failure"],
    },
    "rt-J01": {
        "required_lanes": ["zh_moebius（新增：莫比乌斯 / 莫比乌斯带）", "fr_moebius", "relation:sujet_barré"],
        "required_constraints": ["answerability 必须基于跨语言 concept coverage",
                                 "只能 recovered 中文 L2 + 无 L1 时最高 PARTIALLY_SUPPORTED",
                                 "Möbius(topology) 与 Paul Julius Möbius(person) 消歧",
                                 "排除普通英文 strips 的 lexical false positive"],
        "multilingual_concept_required": True,
        "target_answerability": "PARTIALLY_SUPPORTED",
        "supported_forbidden_conditions": ["以单语法文 needle 命中数断言整个知识库不可答",
                                          "only-L2 证据时判 full SUPPORTED"],
        "basis": ["gold_cross_language_coverage_failure", "single_language_answerability_bias",
                  "direct_relation_evidence_not_synthesized", "primary_source_trace_missing",
                  "person_topology_entity_ambiguity", "lexical_strip_false_positive",
                  "no_substantive_claim", "multilingual_concept_entity_missing",
                  "裁决 AGENT_CORRECT"],
    },
    "rt-G01": {
        "required_lanes": ["fr_hegel", "kojeve（新增）", "maitre-esclave relation（新增）",
                           "desire relation（新增）"],
        "relation_evidence_required": True,
        "source_layers_required": ["Hegel 原始哲学来源", "Kojève 的解释/传递层",
                                   "Lacan 对结构的重新使用", "Lacan 自身欲望理论"],
        "required_constraints": ["不得把 Lacan 的 Discours du Maître 等同于黑格尔主奴辩证法",
                                 "不得用问句残片作为 discriminating terms",
                                 "expected_periods 与 expected_seminars 必须一致"],
        "followup_required": True,
        "target_answerability": "UNDETERMINED_PENDING_RELATION_RETRIEVAL",
        "supported_forbidden_conditions": ["缺 relation evidence 时判 SUPPORTED"],
        "basis": ["relation_lane_missing", "desire_only_retrieval", "false_topic_not_covered",
                  "gold_lexical_lane_insufficient", "master_discourse_vs_master_slave_conflation",
                  "source_layer_separation_missing", "query_fragment_as_discriminating_term",
                  "queue_state_inconsistency", "task_metadata_period_seminar_conflict",
                  "citation_entailment_failure", "裁决 NEEDS_MORE_EVIDENCE"],
    },
}


def build():
    tasks = {r["task_id"]: r for r in ei.jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))}
    reviews = {r["task_id"]: r for r in ei.jl(os.path.join(EVAL, "research_human_review.jsonl"))}
    queue = {r["task_id"]: r for r in ei.jl(os.path.join(EVAL, "human_adjudication_queue.jsonl"))}
    truth = ei.jd(os.path.join(EVAL, "evaluation_truth_adjudicated_v1.json"), {}) or {}
    lane_sem = ei.jd(os.path.join(EVAL, "lane_semantics_v1.json"), {}) or {}
    order = [it["task_id"] for it in
             (ei.jd(os.path.join(EVAL, "human_review_set_v1.json"), {}) or {}).get("items", [])]
    rows = []
    for tid in order:
        t, rv = tasks[tid], reviews[tid]
        ov = SPEC_OVERLAY.get(tid, {})
        lanes = []
        zero_hint = " ".join(ov.get("expected_zero_lanes") or [])
        pos_hint = " ".join((ov.get("required_lanes") or []) + (ov.get("terminology_lanes") or []))
        for lane in (t.get("gold_derivation", {}).get("lanes") or []):
            ndl = " ".join(lane.get("needles") or [])
            exp = "UNKNOWN_EXPECTATION"
            if ndl and ndl in zero_hint:
                exp = "EXPECTED_ZERO"
            elif lane["lane"] in (ov.get("required_lanes") or []) or (ndl and ndl in pos_hint):
                exp = "EXPECTED_POSITIVE"
            lanes.append({"lane": lane["lane"], "needles": lane["needles"],
                          "language": lane.get("language"), "seminar": lane.get("seminar"),
                          "expectation": exp, "observed_hits": lane.get("hits_total"),
                          "hit_state": "ATTESTED" if (lane.get("hits_total") or 0) > 0
                                       else "ZERO_ATTESTATION",
                          "result": ei.lane_result(exp, lane.get("hits_total") or 0)})
        for z in (ov.get("expected_zero_lanes") or []):
            name = z.split("（")[0]
            lanes.append({"lane": name, "needles": [], "language": None, "seminar": None,
                          "expectation": "EXPECTED_ZERO", "observed_hits": 0,
                          "hit_state": "ZERO_ATTESTATION", "result": "PASS", "note": z})
        row = {
            "schema_version": "scholarly-regression/v1",
            "task_id": tid,
            "task_type": t["task_type"],
            "question": t["question"],
            "split": t.get("split"),
            "gold_answerability_v1": t["answerability"],
            "required_entities": t.get("expected_entities") or [],
            "desirable_entities": t.get("desirable_entities") or [],
            "required_operations": t.get("expected_operations") or [],
            "required_lanes": ov.get("required_lanes") or [],
            "required_constraints": ov.get("required_constraints") or [],
            "required_endpoints": ov.get("required_endpoints") or [],
            "expected_zero_lanes": ov.get("expected_zero_lanes") or [],
            "relation_evidence_required": bool(ov.get("relation_evidence_required")),
            "source_layers_required": ov.get("source_layers_required") or [],
            "seminar_constraints": ov.get("seminar_constraints") or t.get("expected_seminars") or [],
            "period_constraints": t.get("expected_periods") or [],
            "formalism_required": ov.get("formalism_required") or [],
            "metadata_required": ov.get("metadata_required") or [],
            "terminology_lanes": ov.get("terminology_lanes") or [],
            "multilingual_concept_required": bool(ov.get("multilingual_concept_required")),
            "supported_forbidden_conditions": ov.get("supported_forbidden_conditions") or [],
            "abstention_contract": ov.get("abstention_contract") or [],
            "lane_semantics": lanes,
            "lane_semantics_schema": lane_sem.get("schema_version"),
            "if_missing_lane": ov.get("if_missing_lane"),
            "if_endpoint_missing": ov.get("if_endpoint_missing"),
            "followup_required": bool(ov.get("followup_required")),
            "gold_v1_evidence_n": len(t.get("gold_evidence") or []),
            "gold_v1_lane_needles": [l["needles"] for l in
                                     (t.get("gold_derivation", {}).get("lanes") or [])],
            "gold_v2_spec": (truth.get("tasks", {}).get(tid) or {}).get("gold_v2_required_changes"),
            "gold_v2_target_answerability": (truth.get("tasks", {}).get(tid) or {}).get("target_answerability"),
            "human_review_baseline": {
                "scores": rv["human_scores"],
                "citation_support": rv["citation_support"],
                "scholarly_usable": rv["scholarly_usable"],
                "reviewed_at": rv.get("reviewed_at"),
                "reviewer_id": rv.get("reviewer_id"),
                "issue_codes": [(i.get("code") or i.get("kind"))
                                for i in rv.get("reviewer_raised_issues", [])],
                "requested_changes_n": len(rv.get("requested_changes") or []),
            },
            "human_adjudication": (
                {"decision": queue[tid].get("decision"),
                 "status": queue[tid].get("status"),
                 "adjudicated_at": queue[tid].get("adjudicated_at"),
                 "followup_required": queue[tid].get("followup_required")}
                if tid in queue else None),
            "spec_basis": ov.get("basis") or [],
            "auto_metrics_v4c": rv.get("auto_metrics"),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": ("本行 = 该任务的回归规格。`expected_state` 单独存在不足以防回归："
                     "缺 lane / 端点的 endpoint / 关系证据 / formalism / metadata 时判 SUPPORTED "
                     "必须被 `supported_forbidden_conditions` 拦下。"),
        }
        rows.append(row)
    return rows


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = sorted(build(), key=lambda r: r["task_id"])
    if a.check:
        have = ei.jl(OUT)
        key = lambda rs: json.dumps([{k: v for k, v in r.items() if k != "generated_at"}
                                     for r in rs], ensure_ascii=False, sort_keys=True)
        problems = []
        if len(have) != len(rows):
            problems.append("行数不符：%d vs %d" % (len(have), len(rows)))
        elif key(have) != key(rows):
            problems.append("内容与输入不一致（重跑本脚本）")
        ids = {r["task_id"] for r in have}
        if len(ids) != 14:
            problems.append("未覆盖 14 个已评审任务：%d" % len(ids))
        for p in problems:
            print("  FAIL", p)
        return 1 if problems else 0
    rows_sorted = rows
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows_sorted:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print("wrote %s（%d 个任务）" % (os.path.relpath(OUT, VAULT), len(rows_sorted)))
    n_req = sum(1 for r in rows if r["required_lanes"])
    n_rel = sum(1 for r in rows if r["relation_evidence_required"])
    n_for = sum(1 for r in rows if r["formalism_required"])
    n_meta = sum(1 for r in rows if r["metadata_required"])
    n_zero = sum(1 for r in rows if r["expected_zero_lanes"])
    n_adj = sum(1 for r in rows if r["human_adjudication"])
    print("  required_lanes=%d  relation_evidence=%d  formalism=%d  metadata=%d  "
          "expected_zero=%d  adjudicated=%d" % (n_req, n_rel, n_for, n_meta, n_zero, n_adj))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
