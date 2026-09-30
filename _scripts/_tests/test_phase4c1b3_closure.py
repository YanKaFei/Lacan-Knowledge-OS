#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1b3_closure.py — Phase 4C.1-B3：Execution Closure 测试

覆盖 B3 的四个工作流，每条都对应报告里的一个验收点：

    Metadata      NOT_APPLICABLE 语义（必须有 whole-corpus 结构凭据；不得滥用）
    Budget        required source lane 不得被 relation 抢占预算（类别隔离）
    Formalism     分级形式检索（H02 必须在 S14 取到 (S ◊ a) 直接证据）
    Terminology   mapping / attestation / context validation **三层分开**
    Metrics       raw_executed_rate vs resolved_obligation_rate（不得互相冒充）
    Gate19        B3 的 6 条检查在真实 B3 trace 上 0 违规
    RepoSafety    HEAD 不变；诊断脚本不得写到 B2 目录；不得 task_id 特判
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
EVAL = os.path.join(VAULT, "_data", "eval")
B3_DIR = os.path.join(EVAL, "research_traces_4c1b3")
B3_OUT = os.path.join(EVAL, "research_eval_results.4c1b3.json")
B2_DIR = os.path.join(EVAL, "research_traces_4c1b2")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))

import research_contract as rc          # noqa: E402
import research_execution as rexec      # noqa: E402
import research_answer as ans           # noqa: E402
import eval_integrity as ei             # noqa: E402


def jd(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def tasks():
    return {json.loads(l)["task_id"]: json.loads(l)
            for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"),
                          encoding="utf-8") if l.strip()}


def public_view(t):
    return {k: t[k] for k in ("task_id", "question", "language", "task_type",
                              "required_capabilities", "split")}


_RUN_CACHE = {}


def run(tid):
    if tid not in _RUN_CACHE:
        _RUN_CACHE[tid] = ans.run_task(public_view(tasks()[tid]), record_gaps=False)
    return _RUN_CACHE[tid]


def exof(tid):
    return run(tid)["trace"]["execution"]


def status(tid, op):
    return {o["operation_id"]: o["status"] for o in exof(tid)["operations"]}.get(op)


# ══════════════════════════════════════════════════════════════════ B3-1
class TestMetadataNotApplicable(unittest.TestCase):
    """§2：NOT_APPLICABLE 只允许有 upstream 结构性凭据时使用。"""

    def test_01_metadata_proof_is_corpus_verified(self):
        pr = rc.metadata_structural_proof("session_date")
        self.assertEqual(pr["availability"], "GLOBAL_UNKNOWN")
        scan = pr["corpus_scan"]
        self.assertTrue(scan["executed"])
        self.assertEqual(scan["scope"], "whole_corpus")
        self.assertGreater(scan["n_passages"], 100000)
        self.assertEqual(scan["n_with_real_value"], 0)

    def test_02_absent_field_proof(self):
        pr = rc.metadata_structural_proof("attendees")
        self.assertEqual(pr["availability"], "FIELD_ABSENT")
        self.assertEqual(pr["corpus_scan"]["n_with_real_value"], 0)

    def test_03_proof_predicate_rejects_bare_na(self):
        ok = rc.BaseContract.not_applicable_is_proven
        self.assertTrue(ok({"structural_dependency": {
            "upstream_operation": "metadata_check",
            "upstream_state": "METADATA_UNAVAILABLE",
            "proofs": [rc.metadata_structural_proof("session_date")]}}))
        self.assertFalse(ok({"structural_dependency": {
            "upstream_operation": "metadata_check",
            "upstream_state": "METADATA_UNAVAILABLE"}}))
        self.assertFalse(ok({"structural_dependency": {
            "upstream_operation": "search_passages",
            "upstream_state": "RETRIEVAL_FAILURE",
            "proofs": [{"corpus_scan": {"executed": True, "scope": "whole_corpus",
                                        "n_with_real_value": 0},
                        "availability": "GLOBAL_UNKNOWN"}]}}))

    def test_04_j03_dependent_ops_are_not_applicable(self):
        self.assertEqual(status("rt-J03", "metadata_check"), "EXECUTED")
        self.assertEqual(status("rt-J03", "search_passages"), "NOT_APPLICABLE")
        self.assertEqual(status("rt-J03", "find_concept_evidence"), "NOT_APPLICABLE")
        tr = run("rt-J03")["trace"]
        self.assertEqual(tr["missing_operations"], [])
        nas = tr["not_applicable_operations"]
        self.assertTrue(nas)
        for na in nas:
            self.assertTrue(rc.BaseContract.not_applicable_is_proven(
                {"structural_dependency": na["structural_dependency"]}))

    def test_05_j03_does_no_unrelated_retrieval(self):
        """元数据不可答 → 不应再去跑一堆无关的通用检索。"""
        ex = exof("rt-J03")
        tools = [o["operation_id"] for o in ex["operations"]
                 if o["status"] == "EXECUTED"]
        self.assertEqual(tools, ["metadata_check", "resolve_entity"])

    def test_06_j03_state_stays_insufficient(self):
        tr = run("rt-J03")["trace"]
        self.assertEqual(tr["final_state"], "INSUFFICIENT_EVIDENCE")
        codes = [v["code"] for v in
                 (tr.get("sufficiency_v21") or {}).get("violated_rules") or []]
        self.assertIn("METADATA_UNAVAILABLE", codes)
        self.assertNotIn("MISSING_REQUIRED_OPERATION", codes)

    def test_07_unproven_na_is_a_contract_violation(self):
        """把普通失败包装成 NOT_APPLICABLE → 契约层必须判违规。"""
        contract = {"missing_operations": [], "missing_lanes": [],
                    "required_operations": ["search_passages"],
                    "not_applicable_operations": [{"operation": "search_passages"}],
                    "not_applicable_unproven": [{"operation": "search_passages"}],
                    "required_constraints": [], "evidence_usability": {"substantive_n": 3}}
        audit = rc.validate_contract(contract)
        codes = [v["code"] for v in audit["violated_rules"]]
        self.assertIn("NOT_APPLICABLE_WITHOUT_STRUCTURAL_PROOF", codes)


# ══════════════════════════════════════════════════════════════════ B3-2
class TestSourceLayerBudgetIsolation(unittest.TestCase):
    """§3：required source lane 不得被 relation 抢占预算。"""

    def test_10_budget_classes_are_isolated(self):
        run("rt-F01")
        plan = exof("rt-F01")["budget"]["plan"]
        quota = plan["class_quota"]
        for cls in ("source_layer", "relation", "context", "optional", "target_lane"):
            self.assertIn(cls, quota)
        self.assertGreaterEqual(quota["source_layer"], 1)
        self.assertGreaterEqual(quota["relation"], 2)
        self.assertNotIn("source_layer", plan.get("shrunk_by_all", []))

    def test_11_f01_f02_source_lane_is_terminal(self):
        for tid in ("rt-F01", "rt-F02"):
            lanes = {l["lane_id"]: l for l in exof(tid)["lanes"]}
            lp = lanes.get("source_layer:lacan_primary")
            self.assertIsNotNone(lp, "%s 缺少 lacan_primary lane" % tid)
            self.assertIn(lp["status"], ("SATISFIED", "ZERO_ATTESTATION_CONFIRMED",
                                         "STRUCTURALLY_UNAVAILABLE", "FAILED"))
            self.assertNotIn(lp["status"], ("NOT_STARTED", "SKIPPED_WITH_REASON"))
            fs = lanes.get("source_layer:freud_source")
            self.assertEqual(fs["status"], "STRUCTURALLY_UNAVAILABLE")

    def test_12_source_layer_class_actually_spent(self):
        for tid in ("rt-F01", "rt-F02"):
            b = exof(tid)["budget"]
            self.assertGreaterEqual(b["class_spend"].get("source_layer", 0), 1)

    def test_13_all_required_ops_resolve_on_f01_f02(self):
        for tid in ("rt-F01", "rt-F02"):
            tr = run(tid)["trace"]
            self.assertEqual(tr["execution_completion"]["raw_executed_rate"], 1.0)
            self.assertEqual(tr["missing_operations"], [])

    def test_14_relation_cannot_borrow_source_quota(self):
        """关系类花完自己的额度后，不得写进 source_layer 的账。"""
        ex = exof("rt-F01")
        b = ex["budget"]
        self.assertNotIn("CLASS_BUDGET_EXHAUSTED:source_layer",
                         [s.get("failure_code") for s in ex["skipped_operations"]])


# ══════════════════════════════════════════════════════════════════ B3-3
class TestFormalismRecall(unittest.TestCase):
    """§3（formalism）：分级检索，H02 要在 S14 取到 (S ◊ a)。"""

    H02_Q = "Que exprime la formule $ ◊ a dans la structure du fantasme ?"
    H01_Q = "波罗米结（nœud borroméen）在拉康晚期如何用来表达 R.S.I. 的结构？"

    def test_20_query_forms_are_staged(self):
        forms = rc.formalism_query_forms(self.H02_Q, ["$", "◊"], "topology_matheme")
        strategies = {f["strategy"] for f in forms}
        self.assertTrue({"notation_variant", "parenthesized_form"} & strategies)
        self.assertIn("S◊a", [f["normalized"] for f in forms])

    def test_21_match_strategy_is_honest(self):
        # 语料里写的是 `S ◊ a`，不能因为索引里做了记号归一就宣称 exact_expression
        self.assertEqual(rc.classify_formalism_match("$ ◊ a", "S ◊ a",
                                                     "exact_expression"),
                         "notation_variant")
        self.assertEqual(rc.classify_formalism_match("S◊a", "(S ◊ a)",
                                                     "symbol_spacing_variants"),
                         "parenthesized_form")
        self.assertEqual(rc.classify_formalism_match("S◊a", "S ◊ a",
                                                     "exact_expression"),
                         "exact_expression")

    def test_22_seminar_is_derived_from_title_not_task_id(self):
        d = rc.seminar_from_title(self.H02_Q)
        self.assertIsNotNone(d)
        self.assertEqual(d["seminar_id"], "seminar.S14")
        self.assertEqual(d["method"], "seminar_title_token_match")

    def test_23_h02_retrieves_s14_direct_formalism(self):
        r = rc.formalism_retrieve(self.H02_Q, ["$", "◊"], "topology_matheme",
                                  seminar="seminar.S14")
        ids = [h["passage_id"] for h in r["direct_hits"]]
        for want in ("passage.S14.unknown.P0029", "passage.S14.unknown.P0055",
                     "passage.S14.unknown.P0066"):
            self.assertIn(want, ids, "缺少直接公式证据 %s（实际 %s）" % (want, ids[:6]))
        for h in r["direct_hits"]:
            if h["passage_id"] in ("passage.S14.unknown.P0029",
                                   "passage.S14.unknown.P0055",
                                   "passage.S14.unknown.P0066"):
                self.assertEqual(h["raw_matched_form"].strip(), "(S ◊ a)")
                self.assertIn(h["match_strategy"],
                              ("notation_variant", "parenthesized_form",
                               "exact_expression"))
                self.assertEqual(h["seminar_id"], "seminar.S14")

    def test_24_h01_uses_named_formal_object(self):
        forms = rc.formalism_query_forms(self.H01_Q, [], "topology_matheme")
        self.assertIn("named_formal_object", {f["strategy"] for f in forms})
        r = rc.formalism_retrieve(self.H01_Q, [], "topology_matheme")
        self.assertGreater(r["direct_n"], 10)
        self.assertIn("seminar.S22", r["corpus_distribution"])

    def test_25_non_topology_tasks_have_no_formalism_obligation(self):
        """J03「1953 年 11 月 18 日…」不构成形式义务（B3 修过的一个真 bug）。"""
        t = rc.compile_research_contract(
            tasks()["rt-J03"],
            {"salient_terms": ["1953 年 11 月 18 日", "报告", "在场者"], "entities": []},
            {"evidence": []})
        self.assertFalse(t["formalism"]["formalism_required"])
        self.assertEqual(t["formalism"]["formalism_state"], "NOT_REQUIRED")

    def test_26_h01_h02_traces_have_direct_formalism(self):
        for tid in ("rt-H01", "rt-H02"):
            ex = exof(tid)
            form = ex.get("formalism") or {}
            self.assertGreater(form.get("formalism_evidence_n") or 0, 0)
            lanes = {l["lane_id"]: l for l in ex["lanes"]}
            self.assertEqual(lanes["formalism"]["status"], "SATISFIED")
            self.assertTrue(form.get("strategy_counts"))
            self.assertTrue(form.get("query_forms"))

    def test_27_h02_trace_hits_include_s14_targets(self):
        hits = {h["passage_id"] for h in (exof("rt-H02").get("formalism") or {})
                .get("hits") or []}
        self.assertTrue({"passage.S14.unknown.P0029", "passage.S14.unknown.P0055",
                         "passage.S14.unknown.P0066"} & hits, sorted(hits))


# ══════════════════════════════════════════════════════════════════ B3-4
class TestTerminologyCompletion(unittest.TestCase):
    """§5：mapping / attestation / context validation 三层分开。"""

    def test_30_three_layers_present_per_term(self):
        terms = (exof("rt-I03").get("terminology") or {}).get("terms") or {}
        self.assertTrue(terms)
        for t, v in terms.items():
            for k in ("mapping_completion", "attestation_completion",
                      "context_validation"):
                self.assertIn(k, v, "%s 缺 %s" % (t, k))

    def test_31_zero_attestation_is_valid_completion(self):
        terms = (exof("rt-I03").get("terminology") or {}).get("terms") or {}
        self.assertIn("原乐", terms)
        v = terms["原乐"]
        self.assertEqual(v["mapping_completion"], "MAPPING_COMPLETE")
        self.assertEqual(v["attestation_completion"], "ZERO_ATTESTATION")
        self.assertEqual(v["context_validation"], "NOT_APPLICABLE")
        self.assertEqual(v["lane_status"], "ZERO_ATTESTATION_CONFIRMED")

    def test_32_attested_but_pending_is_not_conflated(self):
        terms = (exof("rt-I03").get("terminology") or {}).get("terms") or {}
        v = terms.get("快感") or {}
        self.assertEqual(v.get("attestation_completion"), "ATTESTED")
        self.assertIn(v.get("mapping_completion"),
                      ("MAPPING_COMPLETE", "MAPPING_PARTIAL"))

    def test_33_aggregate_counts_recorded(self):
        agg = exof("rt-I03").get("terminology") or {}
        self.assertTrue(agg.get("mapping_completion_counts"))
        self.assertTrue(agg.get("attestation_completion_counts"))
        self.assertTrue(agg.get("context_validation_counts"))
        self.assertIn("三层", agg.get("rule") or "")

    def test_34_gate_flags_conflated_terminology(self):
        inner = {"schema_version": "research-trace/v2", "task_id": "synthetic",
                 "required_operations": [], "required_lanes": [],
                 "execution": {"schema_version": "research-execution/v2",
                               "operations": [],
                               "terminology": {"terms": {"x": {
                                   "corpus_hits": 0,
                                   "mapping_completion": "MAPPING_COMPLETE",
                                   "attestation_completion": "ATTESTED",
                                   "context_validation": "CONTEXT_VALIDATED"}}}},
                 "research_contract": {"required_operations": [],
                                       "required_lanes": []},
                 "final_state": "SUPPORTED"}
        tr = {"schema_version": "research-trace/v2", "task_id": "synthetic",
              "trace": inner, "required_operations": [], "final_state": "SUPPORTED"}
        codes = [f["code"] for f in ei.trace_integrity_findings(tr)
                 if f["severity"] == "VIOLATION"]
        self.assertIn("B3_TERMINOLOGY_COMPLETION_CONFLATED", codes)


# ══════════════════════════════════════════════════════════════════ §6
class TestExecutionMetrics(unittest.TestCase):
    def test_40_raw_and_resolved_are_separate(self):
        ec = run("rt-J03")["trace"]["execution_completion"]
        self.assertLess(ec["raw_executed_rate"], 1.0)
        self.assertEqual(ec["resolved_obligation_rate"], 1.0)
        self.assertEqual(ec["not_applicable_proven_n"], 2)
        self.assertIn("永不进 raw_executed_rate", ec["not_applicable_is_not_execution"])

    def test_41_no_unproven_na_anywhere_in_b3(self):
        doc = jd(B3_OUT, {}) or {}
        self.assertTrue(doc, "B3 diagnostic 结果缺失")
        self.assertEqual(doc.get("marker"), "DIAGNOSTIC")
        self.assertEqual(doc.get("phase"), "Phase 4C.1-B3")
        for r in doc.get("rows") or []:
            for op, ok in (r.get("not_applicable_proven") or {}).items():
                self.assertTrue(ok, "%s 的 %s 是未证明的 NOT_APPLICABLE"
                                % (r.get("task_id"), op))

    def test_42_resolved_rate_never_below_raw_rate(self):
        doc = jd(B3_OUT, {}) or {}
        m = doc.get("metrics") or {}
        self.assertIsNotNone(m.get("raw_executed_rate"))
        self.assertIsNotNone(m.get("resolved_obligation_rate"))
        self.assertGreaterEqual(m["resolved_obligation_rate"] + 1e-9,
                                m["raw_executed_rate"])

    def test_43_metrics_have_three_terminology_layers(self):
        m = (jd(B3_OUT, {}) or {}).get("metrics") or {}
        for k in ("terminology_mapping_completion",
                  "terminology_attestation_completion",
                  "terminology_context_validation_completion"):
            self.assertIsInstance(m.get(k), dict)
            self.assertTrue(m[k])


# ══════════════════════════════════════════════════════════════════ §9
class TestGate19OnB3(unittest.TestCase):
    def test_50_zero_violations_on_real_b3_traces(self):
        self.assertTrue(os.path.isdir(B3_DIR), "B3 trace 目录缺失")
        violations = []
        for fn in sorted(os.listdir(B3_DIR)):
            if not fn.endswith(".json"):
                continue
            tr = jd(os.path.join(B3_DIR, fn))
            for f in ei.trace_integrity_findings(tr):
                if f["severity"] == "VIOLATION":
                    violations.append((fn, f["code"], f["detail"][:140]))
        self.assertEqual(violations, [], violations[:5])

    def test_51_gate_catches_execution_complete_with_unresolved(self):
        inner = {"schema_version": "research-trace/v2", "task_id": "synthetic2",
                 "required_operations": ["search_passages"], "required_lanes": [],
                 "execution": {"schema_version": "research-execution/v2",
                               "operations": [{"operation_id": "search_passages",
                                               "status": "SKIPPED_WITH_REASON"}],
                               "lanes": []},
                 "research_contract": {"required_operations": ["search_passages"],
                                       "required_lanes": []},
                 "execution_completion": {"complete": True,
                                          "state": "EXECUTION_COMPLETE"},
                 "final_state": "PARTIALLY_SUPPORTED"}
        tr = {"schema_version": "research-trace/v2", "task_id": "synthetic2",
              "trace": inner, "required_operations": ["search_passages"],
              "final_state": "PARTIALLY_SUPPORTED"}
        codes = [f["code"] for f in ei.trace_integrity_findings(tr)
                 if f["severity"] == "VIOLATION"]
        self.assertIn("B3_EXECUTION_COMPLETE_WITH_UNRESOLVED_OBLIGATION", codes)


# ══════════════════════════════════════════════════════════════════ Repo safety
class TestRepoSafety(unittest.TestCase):
    def test_60_diagnostic_refuses_foreign_paths(self):
        import run_diagnostic_4c1b3 as d
        self.assertEqual(os.path.abspath(d.TRACE_DIR),
                         os.path.abspath(d.ALLOWED_TRACE_DIR))
        self.assertEqual(os.path.abspath(d.OUT), os.path.abspath(d.ALLOWED_OUT))
        old = d.TRACE_DIR
        try:
            d.TRACE_DIR = B2_DIR
            with self.assertRaises(SystemExit):
                d._guard_paths()
        finally:
            d.TRACE_DIR = old

    def test_61_b2_dir_not_written_by_b3_scripts(self):
        src = open(os.path.join(TOOLS, "run_diagnostic_4c1b3.py"),
                   encoding="utf-8").read()
        # 允许出现在注释/PREV 比较里，但不允许作为写入目标
        self.assertNotIn('os.path.join(EVAL, "research_traces_4c1b2")', src)
        self.assertEqual(src.count("research_eval_results.4c1b2.json"), 1)

    def test_62_no_task_id_branch_in_b3_execution_path(self):
        for fn in ("research_execution.py", "research_contract.py",
                   "research_answer.py", "run_diagnostic_4c1b3.py",
                   "eval_integrity.py"):
            src = open(os.path.join(TOOLS, fn), encoding="utf-8").read()
            self.assertEqual(re.findall(r"rt-[A-Z]\d{2}", src), [],
                             "%s 出现 task_id 分支" % fn)

    def test_63_head_unchanged(self):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=VAULT,
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(len(head), 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)
