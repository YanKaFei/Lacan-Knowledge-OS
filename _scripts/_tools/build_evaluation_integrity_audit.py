#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_evaluation_integrity_audit.py — Phase 4C.1-A：评测完整性审计（机器可读汇总）

三件事
──────
1. **钉住人工评审基线**（`_data/eval/human_review_baseline_v1.json`）：
   Phase 4C 的 `human_review_results_v1.json` 只有聚合、没有逐任务行，
   无法承担「冻结评分逐字段不可改」的比对职责。因此新建一份**派生快照**：
   逐任务记下评分 / citation_support / scholarly_usable / 评语长度 + 源文件 sha256。
   已存在且源 hash 变化时**拒绝覆盖**（要改必须显式 `--force`，并留下 repinned_from）。
2. **汇总审计**（`_data/eval/evaluation_integrity_audit.json`）：
   Gate 13 旧/新行为、Gate 19 trace 完整性、gold lane 审计分布、
   冻结产物哈希、taxonomy 映射、regression 覆盖、manifest 绑定。
3. 所有结论都可复算：同样的输入 → 同样的输出（时间戳除外）。

用法
────
    python3 build_evaluation_integrity_audit.py            # 写审计（必要时钉基线）
    python3 build_evaluation_integrity_audit.py --force    # 允许重钉基线（记 repinned_from）
    python3 build_evaluation_integrity_audit.py --check    # 只校验，不写
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
IDX = os.path.join(VAULT, "_data", "index")
BASELINE = os.path.join(EVAL, "human_review_baseline_v1.json")
OUT = os.path.join(EVAL, "evaluation_integrity_audit.json")
sys.path.insert(0, HERE)
import eval_integrity as ei  # noqa: E402

FROZEN = {
    "research_human_review.jsonl": "_data/eval/research_human_review.jsonl",
    "human_adjudication_queue.jsonl": "_data/eval/human_adjudication_queue.jsonl",
    "human_review_results_v1.json": "_data/eval/human_review_results_v1.json",
    "HUMAN_REVIEW_RESULTS_V1.md": "HUMAN_REVIEW_RESULTS_V1.md",
    "human_review_set_v1.json": "_data/eval/human_review_set_v1.json",
    "research_eval_results.v4c.json": "_data/eval/research_eval_results.v4c.json",
    "research_eval_results_v1.dev.json": "_data/eval/research_eval_results_v1.dev.json",
    "research_eval_results_v1.holdout.json": "_data/eval/research_eval_results_v1.holdout.json",
    "research_tasks_v1.jsonl": "_data/eval/research_tasks_v1.jsonl",
    "research_tasks_v1.gold_derivation.json": "_data/eval/research_tasks_v1.gold_derivation.json",
}
TRACE_DIR = "_data/eval/research_traces_4b"


def snapshot(records) -> dict:
    tasks = []
    for r in sorted(records, key=lambda x: x["task_id"]):
        rc = r.get("reviewer_comment") or {}
        tasks.append({
            "task_id": r["task_id"],
            "human_scores": r.get("human_scores"),
            "citation_support": r.get("citation_support"),
            "scholarly_usable": r.get("scholarly_usable"),
            "review_status": r.get("review_status"),
            "review_round": r.get("review_round"),
            "reviewed_at": r.get("reviewed_at"),
            "reviewer_id": r.get("reviewer_id"),
            "reviewer_type": r.get("reviewer_type"),
            "comment_raw_len": len(rc.get("raw") or ""),
            "comment_keep_len": len(rc.get("most_worth_keeping") or ""),
            "comment_change_len": len(rc.get("most_needing_change") or ""),
            "requested_changes_n": len(r.get("requested_changes") or []),
            "issue_codes": sorted((i.get("code") or i.get("kind"))
                                  for i in (r.get("reviewer_raised_issues") or [])),
        })
    qpath = os.path.join(EVAL, "human_adjudication_queue.jsonl")
    adjs = [{"task_id": q["task_id"], "decision": q.get("decision"),
             "status": q.get("status"), "adjudicated_by": q.get("adjudicated_by"),
             "adjudicated_at": q.get("adjudicated_at"),
             "agent_state_v4c": q.get("agent_state_v4c"),
             "agent_state_v4c_previous": q.get("agent_state_v4c_previous"),
             "followup_required": q.get("followup_required")}
            for q in sorted(ei.jl(qpath), key=lambda x: x["task_id"])]
    return {
        "schema_version": "human-review-baseline/v1",
        "phase": "Phase 4C — Human Scholarly Review Round 1（冻结）",
        "pinned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": os.path.relpath(os.path.join(EVAL, "research_human_review.jsonl"), VAULT),
        "source_sha256": ei.sha256_file(os.path.join(EVAL, "research_human_review.jsonl")),
        "adjudication_source": os.path.relpath(qpath, VAULT),
        "adjudication_source_sha256": ei.sha256_file(qpath),
        "adjudications": adjs,
        "n_tasks": len(tasks),
        "tasks": tasks,
        "note": ("本文件是**派生快照**，用于证明 14 条人工评分未被改动；"
                 "它不改写任何 Phase 4C 冻结产物。若源文件 hash 变化，"
                 "审计脚本会拒绝覆盖本文件（需显式 --force 并记录 repinned_from）。"),
    }


def pin_baseline(force=False):
    src = os.path.join(EVAL, "research_human_review.jsonl")
    want = ei.sha256_file(src)
    have = ei.jd(BASELINE)
    if have and have.get("source_sha256") == want and not force:
        return have, "unchanged"
    if have and not force:
        raise SystemExit("人工评审源文件已变（%s → %s）；"
                         "如确需重钉基线请显式 --force（会记录 repinned_from）"
                         % (have.get("source_sha256", "")[:16], want[:16]))
    doc = snapshot(ei.jl(src))
    if have and force:
        doc["repinned_from"] = {"pinned_at": have.get("pinned_at"),
                                "source_sha256": have.get("source_sha256")}
    json.dump(doc, open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return doc, "pinned" if not have else "repinned"



def _gate20_section():
    """Gate 20（4C.1-C synthesis）复算：读聚合指针 + run 目录里的完整结果。"""
    agg_p = os.path.join(EVAL, "research_synthesis_results.4c1c.json")
    if not os.path.isfile(agg_p):
        return {"status": "not_run", "note": "尚无 4C.1-C synthesis run"}
    agg = ei.jd(agg_p) or {}
    run_dir = agg.get("run_dir")
    full_p = os.path.join(VAULT, run_dir, "synthesis_results.json") if run_dir else None
    if not full_p or not os.path.isfile(full_p):
        return {"status": "missing_run_artifacts", "run_dir": run_dir}
    doc = ei.jd(full_p) or {}
    findings = ei.synthesis_run_findings(doc)
    m = agg.get("metrics") or {}
    hard = {k: m.get(k) for k in ("claims_without_evidence", "ineligible_citations_used",
                                  "source_role_violations",
                                  "abstention_contract_violations")}
    by_code = {}
    for f in findings:
        by_code[f["code"]] = by_code.get(f["code"], 0) + 1
    return {
        "status": "ok",
        "run_id": agg.get("run_id"), "run_dir": run_dir,
        "marker": agg.get("marker"), "human_validated": agg.get("human_validated"),
        "tasks_n": len(doc.get("rows") or []),
        "adapter": agg.get("adapter"),
        "violations": len(findings),
        "violations_by_code": by_code,
        "hard_targets": hard,
        "hard_targets_ok": all(v == 0 for v in hard.values()),
        "metrics": {k: m.get(k) for k in
                    ("synthesis_allowed_n", "full_synthesis_n",
                     "qualified_synthesis_n", "abstention_n", "blocked_n",
                     "claims_total", "claims_with_evidence", "direct_quotes_total",
                     "quotes_with_exact_span", "schema_valid_rate")},
        "note": ("Gate 20 只检查 claim 有引用 / 引用存在 / 引用有资格 / 来源角色相容；"
                 "citation 是否 entail claim 属 Phase 4C.1-D"),
    }



def _gate21_section():
    """Gate 21（4C.1-D entailment）复算：读 4C.1-D run 的完整结果。"""
    agg_p = os.path.join(EVAL, "research_synthesis_results.4c1d.json")
    if not os.path.isfile(agg_p):
        return {"status": "not_run", "note": "尚无 4C.1-D run"}
    agg = ei.jd(agg_p) or {}
    run_dir = agg.get("run_dir")
    full_p = os.path.join(VAULT, run_dir, "results.json") if run_dir else None
    if not full_p or not os.path.isfile(full_p):
        return {"status": "missing_run_artifacts", "run_dir": run_dir}
    doc = ei.jd(full_p) or {}
    if not doc.get("rows"):
        return {"status": "not_task_mode", "mode": doc.get("mode"),
                "run_id": agg.get("run_id")}
    findings = ei.synthesis_entailment_findings(doc)
    by_code = {}
    for f in findings:
        by_code[f["code"]] = by_code.get(f["code"], 0) + 1
    final_claims = [c for r in doc["rows"] for c in
                    ((r.get("answer") or {}).get("claims") or [])]
    hard = {
        "claims_without_evidence_in_final": len(
            [c for c in final_claims if c.get("claim_type") in ei.D_SUBSTANTIVE
             and not c.get("evidence_ids") and not c.get("corpus_scan_ref")]),
        "invalid_citations_in_final": by_code.get("D_INVALID_CITATION_IN_FINAL", 0),
        "invalid_quotes_in_final": by_code.get("D_INVALID_QUOTE_IN_FINAL", 0),
        "source_role_violations_in_final":
            by_code.get("D_SOURCE_ROLE_VIOLATION_IN_FINAL", 0),
        "rejected_claims_in_final": by_code.get("D_REJECTED_CLAIM_IN_FINAL", 0),
    }
    return {
        "status": "ok", "run_id": agg.get("run_id"), "run_dir": run_dir,
        "mode": doc.get("mode"), "marker": doc.get("marker"),
        "human_validated": doc.get("human_validated"),
        "tasks_n": len(doc.get("rows") or []),
        "provider": agg.get("provider"), "model": agg.get("model"),
        "judge_enabled": agg.get("judge_enabled"),
        "violations": len(findings), "violations_by_code": by_code,
        "hard_targets": hard, "hard_targets_ok": all(v == 0 for v in hard.values()),
        "metrics": {k: (agg.get("metrics") or {}).get(k) for k in
                    ("generated_claims", "validated_claims", "repaired_claims",
                     "rejected_claims", "claim_validation_rate",
                     "direct_entailment_rate", "source_role_violations_in_final")},
        "note": ("Gate 21 只检查「claim–evidence 绑定 + 蕴含状态 + 引文 + 来源角色 + "
                 "reject 不进最终答案」；生成阶段出现 NOT_ENTAILED 是**允许**的"
                 "（被拦下即成功），硬目标只约束**最终答案**"),
    }


def build_audit():
    records = ei.jl(os.path.join(EVAL, "research_human_review.jsonl"))
    queue = ei.jl(os.path.join(EVAL, "human_adjudication_queue.jsonl"))
    verdicts = [ei.validate_human_review_record(r) for r in records]
    gates = ei.jd(os.path.join(IDX, "PHASE4C_HARD_GATES.json"), {}) or {}
    lane_sum = ei.jd(os.path.join(EVAL, "gold_lane_audit_v1.summary.json"), {}) or {}
    lane_rows = ei.jl(os.path.join(EVAL, "gold_lane_audit_v1.jsonl"))
    trace_base = ei.jd(os.path.join(EVAL, "trace_integrity_baseline_v1.json"), {}) or {}
    reg = ei.jl(os.path.join(EVAL, "scholarly_regression_v1.jsonl"))
    truth = ei.jd(os.path.join(EVAL, "evaluation_truth_adjudicated_v1.json"), {}) or {}
    mapping = ei.jd(os.path.join(EVAL, "failure_class_mapping_v1.json"), {}) or {}
    man = ei.jd(os.path.join(EVAL, "manifests", "latest.json"), {}) or {}

    lane_counts = dict(Counter(r["classification"] for r in lane_rows))
    return {
        "schema_version": "evaluation-integrity-audit/v1",
        "phase": "Phase 4C.1-A — Evaluation Integrity Repair",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gate13": {
            "old_behaviour": ("review_status != NOT_REVIEWED / human_scores 非 null / "
                              "citation_support 非 null 一律计为『伪造人工评分』"),
            "old_result_on_real_data": "14 条真实人工评审全部被误判为违规（≈112 条）",
            "new_behaviour": ("provenance-aware：空占位必须全空；REVIEWED 必须带人类 provenance"
                              "（reviewer_type/review_round/时间戳/枚举/评语/provenance）+ "
                              "冻结基线逐字段不可改"),
            "new_result_on_real_data": {
                "reviewed_human": sum(1 for v in verdicts if v["state"] == "REVIEWED_HUMAN"),
                "unreviewed_placeholder": sum(1 for v in verdicts
                                              if v["state"] == "UNREVIEWED_PLACEHOLDER"),
                "illegitimate": sum(1 for v in verdicts if v["state"] == "ILLEGITIMATE"),
                "provenance_styles": dict(Counter(v["provenance_style"] for v in verdicts)),
                "gate13_violations": (gates.get("new_gates", {}).get("13", {})
                                      or {}).get("violations"),
            },
            "negative_cases_still_caught": [
                "空占位被自动填分（review_status=NOT_REVIEWED + 非 null 评分）",
                "LLM/脚本冒充 reviewer（reviewer_type/provenance 非人类）",
                "枚举越界（citation_support / scholarly_usable 非法值）",
                "评分维度缺失或超出 1–5",
                "评语缺失",
                "冻结基线被改动（逐字段 + 聚合交叉核对）",
            ],
        },
        "gate19_trace_integrity": {
            "checks": ["required/completed/missing operations",
                       "final_state vs 最后一步（需 transition_reason）",
                       "state explanation 与 signals 一致性",
                       "context expansion 计数一致性",
                       "v2 契约下 missing required operations / lanes 仍判 SUPPORTED"],
            "contract_schema": ei.CONTRACT_SCHEMA,
            "contract_violations": trace_base.get("contract_violations"),
            "legacy_frozen_total": trace_base.get("legacy_frozen_total"),
            "legacy_frozen_by_code": trace_base.get("legacy_frozen_by_code"),
            "traces_scanned": trace_base.get("traces_scanned"),
            "policy": trace_base.get("policy"),
        },
        "gate20_synthesis": _gate20_section(),
        "gate21_entailment": _gate21_section(),
        "frozen_artifacts": {
            k: {"path": v, "sha256": ei.sha256_file(os.path.join(VAULT, v)),
                "size": os.path.getsize(os.path.join(VAULT, v))}
            for k, v in FROZEN.items() if os.path.isfile(os.path.join(VAULT, v))},
        "frozen_traces": {
            "dir": TRACE_DIR,
            "n": len([f for f in os.listdir(os.path.join(VAULT, TRACE_DIR))
                      if f.endswith(".json")]),
            "dir_digest": ei.combined_digest(
                {f: {"sha256": ei.sha256_file(os.path.join(VAULT, TRACE_DIR, f))}
                 for f in sorted(os.listdir(os.path.join(VAULT, TRACE_DIR)))
                 if f.endswith(".json")}),
            "note": "历史 trace 逐字节未改（见 gate 19 的 LEGACY_FROZEN 造册）。",
        },
        "gold_lane_audit": {
            "lanes_audited": len(lane_rows),
            "classification": lane_counts,
            "reasons": dict(Counter(x for r in lane_rows for x in r["reasons"])),
            "flagged_tasks": sorted({r["task_id"] for r in lane_rows
                                     if r["classification"] != "SAFE"}),
            "output": "_data/eval/gold_lane_audit_v1.jsonl",
            "normalization_fix": {
                "v1": "squash()：删标点后去空白 → 跨 token 拼接（rt-J02 的 frmi 来自 URL）",
                "v2": "gold_normalization.contains_v2：标点作 token 边界；"
                      "单 token needle 不得跨 token；多 token needle 不得跨子句；"
                      "CJK 允许同子句内连写；含符号 needle 保留符号字面",
            },
        },
        "adjudicated_truth": {
            "file": "_data/eval/evaluation_truth_adjudicated_v1.json",
            "status": truth.get("status"),
            "tasks": {t: {"decision": d["adjudication_decision"],
                          "target": d["target_answerability"]}
                      for t, d in (truth.get("tasks") or {}).items()},
            "v1_untouched": True,
        },
        "structural_failure_mapping": {
            "file": "_data/eval/failure_class_mapping_v1.json",
            "core_rule": (mapping.get("core_rule") or {}).get("statement"),
            "categories": {c: mapping.get("mapping", {}).get(c, {}).get("category")
                           for c in (mapping.get("mapping") or {})},
            "formalism_two_level": bool((mapping.get("mapping", {})
                                         .get("FORMALISM_MISSING") or {})
                                        .get("two_level_contract")),
        },
        "scholarly_regression": {
            "file": "_data/eval/scholarly_regression_v1.jsonl",
            "tasks": len(reg),
            "required_lanes": sum(1 for r in reg if r["required_lanes"]),
            "relation_evidence_required": sum(1 for r in reg
                                              if r["relation_evidence_required"]),
            "formalism_required": sum(1 for r in reg if r["formalism_required"]),
            "metadata_required": sum(1 for r in reg if r["metadata_required"]),
            "expected_zero_lanes": sum(1 for r in reg if r["expected_zero_lanes"]),
            "supported_forbidden_conditions": sum(
                1 for r in reg if r["supported_forbidden_conditions"]),
            "with_human_baseline": sum(1 for r in reg if r["human_review_baseline"]["scores"]),
            "with_adjudication": sum(1 for r in reg if r["human_adjudication"]),
        },
        "version_pinning": {
            "manifest": "_data/eval/manifests/latest.json",
            "schema": "_data/eval/evaluation_run_manifest.schema.json",
            "engine_version": man.get("engine_version"),
            "git_commit": man.get("git_commit"),
            "git_dirty": man.get("git_dirty"),
            "engine_hash": man.get("engine_hash"),
            "gold_version": man.get("gold_version"),
            "ontology_version": man.get("ontology_version"),
            "passage_store_version": man.get("passage_store_version"),
            "task_set_version": man.get("task_set_version"),
        },
        "adjudication_immutability": ei.adjudication_immutability_findings(queue),
        "human_adjudications": [
            {"task_id": q["task_id"], "decision": q.get("decision"),
             "status": q.get("status"),
             "agent_state_v4c": q.get("agent_state_v4c"),
             "agent_state_v4c_previous": q.get("agent_state_v4c_previous"),
             "followup_required": q.get("followup_required")}
            for q in queue],
        "scope_statement": {
            "did_not_touch": ["14 条人工评分", "3 条裁决", "历史 trace",
                              "历史 eval results", "v1 gold / task set",
                              "passage IDs", "canonical corpus"],
            "added_new_versioned_artifacts": True,
            "no_research_agent_behaviour_change": True,
            "no_llm_synthesis": True,
            "no_evidence_sufficiency_v3": True,
        },
    }


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        doc = ei.jd(OUT)
        if not doc:
            print("缺 %s" % os.path.relpath(OUT, VAULT))
            return 1
        live = build_audit()
        # `frozen_artifacts` 里既有**冻结输入**也有**每次运行都会重算的派生产物**
        # （PHASE4C_HARD_GATES.json / *_COMPLETION_GATE.json / TEST_RUN*.json …）。
        # 后者在跑完套件后必然变哈希 —— 因此这里只比对冻结输入子集，
        # 派生产物单独报告（否则会出现「跑一次套件 → audit 假红」）。
        VOLATILE_FROZEN = {"PHASE4C_HARD_GATES.json", "TEST_RUN.json",
                           "READONLY_GATE.json", "TEST_RUN.suites.json"}
        def stable(sub):
            return {k: v for k, v in (sub or {}).items() if k not in VOLATILE_FROZEN}
        same = all(doc.get(k) == live.get(k) for k in
                   ("gate13", "gate19_trace_integrity", "gate20_synthesis",
                    "gate21_entailment",
                    "gold_lane_audit", "adjudicated_truth", "scholarly_regression",
                    "structural_failure_mapping"))
        same = same and stable(doc.get("frozen_artifacts")) == \
            stable(live.get("frozen_artifacts"))
        print("audit 一致" if same else "audit 与当前状态不一致（重跑）")
        return 0 if same else 1
    _, how = pin_baseline(force=a.force)
    doc = build_audit()
    doc["human_review_baseline"] = {
        "file": "_data/eval/human_review_baseline_v1.json",
        "pin_action": how,
        "source_sha256": ei.sha256_file(os.path.join(EVAL, "research_human_review.jsonl")),
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("baseline pin: %s" % how)
        print("gate13: 真实人工评审 %d 条合法 / 违规 %d"
              % (doc["gate13"]["new_result_on_real_data"]["reviewed_human"],
                 doc["gate13"]["new_result_on_real_data"]["gate13_violations"]))
        print("gate19: 契约违规 %s；历史冻结既知不一致 %s"
              % (doc["gate19_trace_integrity"]["contract_violations"],
                 doc["gate19_trace_integrity"]["legacy_frozen_total"]))
        g20 = doc.get("gate20_synthesis") or {}
        if g20.get("status") == "ok":
            print("gate20: synthesis 违规 %s（%s 题；hard targets %s）"
                  % (g20.get("violations"), g20.get("tasks_n"),
                     g20.get("hard_targets_ok")))
        else:
            print("gate20: %s" % g20.get("status"))
        g21 = doc.get("gate21_entailment") or {}
        if g21.get("status") == "ok":
            print("gate21: entailment 违规 %s（%s 题；hard target %s）"
                  % (g21.get("violations"), g21.get("tasks_n"),
                     g21.get("hard_targets_ok")))
        else:
            print("gate21: %s" % g21.get("status"))
        print("gold lanes: %s" % doc["gold_lane_audit"]["classification"])
        print("regression: %d 个任务" % doc["scholarly_regression"]["tasks"])
        print("-> %s" % os.path.relpath(OUT, VAULT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
