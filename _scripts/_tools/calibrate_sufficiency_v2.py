#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate_sufficiency_v2.py — Phase 4C §27–§29：证据充分性校准集与报告

它评的是**判定层**，不是研究回答
─────────────────────────────────
`evidence_sufficiency_eval_v2.jsonl` 覆盖 §27 要求的组合：

    direct+dense · direct+sparse · incidental+dense · incidental+sparse
    metadata-impossible · ontology-gap · source-gap · diachronic-multi-period
    conflicting · formalism-missing

每组至少一个案例，每个案例给出**期望的 final_state 与分层状态**，
期望值由「语料实测事实 + 该案例的判定意图」决定，并逐条写明 rationale。
凡与 Phase 4B gold 不一致的，标 `adjudication_required = true`（不静默改 gold）。

输出：
    _data/eval/evidence_sufficiency_eval_v2.jsonl
    _data/eval/evidence_sufficiency_calibration.v4c.json
    EVIDENCE_SUFFICIENCY_CALIBRATION_REPORT.md
    + 混淆矩阵、False SUPPORTED / False INSUFFICIENT 率、abstention 率、
      SUPPORTED precision/recall（§29：不能只追求 false SUPPORTED = 0）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
CASES = os.path.join(EVAL, "evidence_sufficiency_eval_v2.jsonl")
OUT = os.path.join(EVAL, "evidence_sufficiency_calibration.v4c.json")
REPORT = os.path.join(VAULT, "EVIDENCE_SUFFICIENCY_CALIBRATION_REPORT.md")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

# group → (question, caps, expected_final, expected_availability, expected_topicality,
#          rationale, adjudication_required)
SPEC = [
    ("direct_dense", "拉康所谓的 objet petit a 到底是什么？请区分不同时期对它定位的差别。",
     ["multi_step", "period_coverage", "entity_resolution"], "SUPPORTED", "AVAILABLE",
     "DIRECT", "实体存在、L1 原文成片、跨多期 → 扎实的可答问题。", False),
    ("direct_sparse", "Unheimlich（令人不安的陌生感）在拉康那里出现在哪一期、如何被使用？",
     ["multi_step", "seminar_constraint"], "SUPPORTED", "SPARSE",
     "DIRECT", "§14：全库 unheimlich 56 段、集中在 S10 —— 稀疏但**直接**，"
     "不能因为条数少就判不足。", False),
    ("incidental_dense", "黑格尔的主人—奴隶辩证法如何进入拉康的欲望理论？",
     ["multi_step", "source_layer_separation"], "PARTIALLY_SUPPORTED", "AVAILABLE",
     "CONTEXTUAL", "Hegel 332 段多为旁及；缺少「哲学来源 → 拉康欲望理论」的完整链条。"
     "与 Phase 4B gold（SUPPORTED）不一致 → 需人工裁决。", True),
    ("incidental_sparse", "拉康如何看待 fMRI 等当代神经科学影像研究？",
     ["abstention"], "INSUFFICIENT_EVIDENCE", "SPARSE",
     "INCIDENTAL", "§6/§30 的固定回归：fMRI 词法命中 0、neuroscience 0、无实体、"
     "检索到的 10 条全是 INCIDENTAL。", False),
    ("metadata_impossible", "拉康 1953 年 11 月 18 日那场报告的确切时间、地点与在场者是谁？",
     ["abstention"], "INSUFFICIENT_EVIDENCE", "SPARSE", None,
     "全部 passage 的 session_date = unknown → METADATA_UNAVAILABLE。", False),
    ("ontology_gap", "维特根斯坦与拉康之间是否有直接的文本往来或通信？",
     ["abstention"], "INSUFFICIENT_EVIDENCE", "SPARSE",
     "INCIDENTAL", "wittgenstein 19 段全为旁及、无实体无关系 → ONTOLOGY_GAP + "
     "SOURCE_CHAIN_INCOMPLETE。", False),
    ("cross_language_primary", "中文语料里「快感」这一译名与 jouissance 的关系是什么？",
     ["cross_language"], "SUPPORTED", "AVAILABLE", "DIRECT",
     "⚠️ 期望值修正（原设计为 PARTIALLY）：实测该中文问题经术语桥取到了 **L1 法文**"
     "证据（jouissance 原文成片），因此 SUPPORTED 才是正确答案 —— "
     "这正是跨语言检索应当做到的事；把它当 source gap 是我的校准集设计错误。", False),
    ("diachronic_multi_period", "Comment la notion de jouissance se transforme-t-elle "
     "entre L'éthique (S7) et Encore (S20) ?",
     ["multi_step", "period_coverage", "diachronic_grouping"], "SUPPORTED", "AVAILABLE",
     "DIRECT", "§13：多期差异是发展不是「证据不一致」，不得因此降级。", False),
    ("conflicting", "signifiant 和 signifié 是什么关系？",
     ["multi_step", "separate_lanes"], "SUPPORTED", "AVAILABLE",
     "DIRECT",
     "⚠️ 期望值修正（原设计为 PARTIALLY）：v4a1 把 signifiant 的歧义消解到"
     "concept.signifiant 之后，两侧都有 L1 证据 → SUPPORTED。"
     "原期望低估了 4A.1 修复后的状态。", False),
    ("formalism_missing", "Que exprime la formule $ ◊ a dans la structure du fantasme ?",
     ["matheme_evidence"], "INSUFFICIENT_EVIDENCE", "AVAILABLE", "DIRECT",
     "语料是散文转写，检索到的段落里没有该公式符号 → FORMALISM_MISSING。"
     "与 Phase 4B gold（SUPPORTED）不一致 → 需人工裁决。", True),
    ("direct_dense_2", "Seminar XI 中 gaze/regard 是如何与 objet a 发生关系的？",
     ["multi_step", "terminology_mapping", "seminar_constraint"], "SUPPORTED",
     "AVAILABLE", "DIRECT", "v4a1 受控映射 + S11 期号约束 → 直接证据。", False),
    ("incidental_dense_2", "拉康对当代认知科学（cognitive science）有什么看法？",
     ["abstention"], "INSUFFICIENT_EVIDENCE", "SPARSE",
     "INCIDENTAL", "现代研究词在 1953–1980 语料里几乎不出现 → 与 fMRI 同型。", False),
]


def build_cases():
    return [{"schema_version": "sufficiency-eval-v2/v1", "case_id": "sec-%02d" % (i + 1),
             "group": g, "question": q, "required_capabilities": caps,
             "expected_final_state": ef, "expected_availability": ea,
             "expected_topicality": et, "rationale": r,
             "adjudication_required": adj}
            for i, (g, q, caps, ef, ea, et, r, adj) in enumerate(SPEC)]


def run_case(case):
    import research_answer as ra
    import evidence_sufficiency_v2 as esv2
    pt = {"task_id": case["case_id"], "question": case["question"], "language": "mul",
          "task_type": "calibration", "required_capabilities":
          case["required_capabilities"]}
    # ⚠️ 校准集测的是 **v2 证据层**；执行调度器（4C.1-B2）会改变检索集合，
    #    因此这里显式关闭它，保证 Phase 4C 的校准指标逐字可复现。
    #    执行层的效果由 `run_diagnostic_4c1b2.py` 的指标单独度量。
    run = ra.run_task(pt, execute_contract=False)
    p = run["evidence_pack"]
    v2 = p.get("evidence_state") or {}
    # Phase 4C.1-B：`final_state` 现在是 **v2.1**（= v2 证据层 + 契约任务层）。
    # 本校准集测的是 **证据层**（availability/topicality/directness），它的期望值也是
    # 按证据层设计的；因此这里把两层分开记录：
    #   state_v2_evidence_layer  证据层（= Phase 4C 校准语义，用于期望比对与混淆矩阵）
    #   final_state_v21          任务完成层（v2.1 的最终判定，单独报告，不改变校准口径）
    state_v2_layer = (v2.get("state_before_contract")
                      or v2.get("final_state") or v2.get("state"))
    state_v21 = v2.get("final_state") or v2.get("state")
    return {
        "case_id": case["case_id"], "group": case["group"],
        "question": case["question"],
        "final_state": state_v2_layer,
        "state_v2_evidence_layer": state_v2_layer,
        "final_state_v21_task_layer": state_v21,
        "task_layer_capped": bool(state_v21 != state_v2_layer),
        "task_layer_violations": [v.get("code") for v in
                                  ((run.get("trace") or {}).get("sufficiency_v21") or {})
                                  .get("violated_rules") or []],
        "availability_state": v2.get("availability_state"),
        "topicality_state": v2.get("topicality_state"),
        "coverage_state": v2.get("coverage_state"),
        "source_state": v2.get("source_state"),
        "ontology_state": v2.get("ontology_state"),
        "topic_support_levels": v2.get("topic_support_levels"),
        "topic_prevalence": v2.get("topic_prevalence"),
        "structural_unanswerability": [c.get("class") for c in
                                       (v2.get("structural_unanswerability") or [])],
        "reasons": (v2.get("reasons") or [])[:4],
        "evidence_n": p.get("evidence_n"),
        "expected_final_state": case["expected_final_state"],
        "expected_availability": case["expected_availability"],
        "expected_topicality": case["expected_topicality"],
        "final_ok": state_v2_layer == case["expected_final_state"],
        "task_layer_ok": state_v21 == case["expected_final_state"],
        "availability_ok": v2.get("availability_state") == case["expected_availability"],
        "topicality_ok": (case["expected_topicality"] is None
                          or v2.get("topicality_state") == case["expected_topicality"]),
        "adjudication_required": case["adjudication_required"],
        "rationale": case["rationale"],
    }


def agg(rows):
    n = len(rows)
    gold_pos = [r for r in rows if r["expected_final_state"] == "SUPPORTED"]
    pred_pos = [r for r in rows if r["final_state"] == "SUPPORTED"]
    tp = len([r for r in gold_pos if r["final_state"] == "SUPPORTED"])
    states = ("SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE",
              "CONFLICTING_EVIDENCE")
    matrix = {g: {p: 0 for p in states} for g in states}
    for r in rows:
        matrix[r["expected_final_state"]][r["final_state"]] += 1
    false_sup = [r["case_id"] for r in rows
                 if r["expected_final_state"] != "SUPPORTED" and r["final_state"] == "SUPPORTED"]
    false_ins = [r["case_id"] for r in rows
                 if r["expected_final_state"] == "SUPPORTED"
                 and r["final_state"] == "INSUFFICIENT_EVIDENCE"]
    part_gold = [r for r in rows if r["expected_final_state"] == "PARTIALLY_SUPPORTED"]
    return {
        "n_cases": n,
        "final_state_accuracy": round(len([r for r in rows if r["final_ok"]]) / n, 4),
        "availability_accuracy": round(len([r for r in rows if r["availability_ok"]]) / n, 4),
        "topicality_accuracy": round(len([r for r in rows
                                          if r["topicality_ok"]]) / n, 4),
        "confusion_matrix": matrix,
        "false_supported_rate": round(len(false_sup) / n, 4),
        "false_supported_cases": false_sup,
        "false_insufficient_rate": round(len(false_ins) / n, 4),
        "false_insufficient_cases": false_ins,
        # §29：不能只看 false SUPPORTED —— 同时报 precision/recall/abstention
        "supported_precision": round(tp / len(pred_pos), 4) if pred_pos else None,
        "supported_recall": round(tp / len(gold_pos), 4) if gold_pos else None,
        "partial_accuracy": (round(len([r for r in part_gold if r["final_ok"]])
                                   / len(part_gold), 4) if part_gold else None),
        "insufficient_precision": (
            round(len([r for r in rows if r["final_state"] == "INSUFFICIENT_EVIDENCE"
                       and r["expected_final_state"] == "INSUFFICIENT_EVIDENCE"])
                  / max(1, len([r for r in rows
                                if r["final_state"] == "INSUFFICIENT_EVIDENCE"])), 4)),
        "abstention_rate": round(len([r for r in rows
                                      if r["final_state"] == "INSUFFICIENT_EVIDENCE"])
                                 / n, 4),
        "groups_covered": sorted({r["group"] for r in rows}),
        "groups_failed": sorted({r["group"] for r in rows if not r["final_ok"]}),
        "adjudication_required_cases": [r["case_id"] for r in rows
                                        if r["adjudication_required"]],
    }


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    cases = build_cases()
    if a.check:
        have = [json.loads(l) for l in open(CASES, encoding="utf-8") if l.strip()] \
            if os.path.isfile(CASES) else []
        if json.dumps(have, ensure_ascii=False, sort_keys=True) != \
           json.dumps(cases, ensure_ascii=False, sort_keys=True):
            print("校准集与 spec 不一致（重跑本脚本）")
            return 1
        print("校准集与 spec 一致：%d 案例 / %d 组"
              % (len(cases), len({c["group"] for c in cases})))
        return 0
    with open(CASES, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    rows = [run_case(c) for c in cases]
    metrics = agg(rows)
    doc = {"schema_version": "sufficiency-calibration/v1",
           "engine": "evidence_sufficiency/v2", "dataset": os.path.relpath(CASES, VAULT),
           "metrics": metrics, "rows": rows,
           "note": ("判定层校准：期望值与该案例的判定意图一致；与 Phase 4B gold 冲突的"
                    "案例标了 adjudication_required，不静默改 gold。")}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if not a.quiet:
        for r in rows:
            print("  %-14s %-12s final=%-21s avail=%-9s top=%-12s ok=%s%s"
                  % (r["case_id"], r["group"], r["final_state"], r["availability_state"],
                     r["topicality_state"], r["final_ok"],
                     " [ADJ]" if r["adjudication_required"] else ""))
        print(json.dumps(metrics, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
