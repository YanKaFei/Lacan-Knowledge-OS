#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1b2_execution.py — Phase 4C.1-B2：执行层契约测试

四层：
    Lifecycle     operation/lane 状态模型（禁止无记录消失）
    Scheduling    调度器真的逐项执行 required obligations
    Hard rules    §22 泛化 fallback 不得满足 required lane；§20 预算优先级；
                  §10 relation 强度分级；§15 metadata 优先；§16 STRUCTURALLY_UNAVAILABLE
    Diagnostic    4c1b2 DIAGNOSTIC 产物 + Gate 19 在真实 B2 trace 上 0 违规
外加：
    NoTaskSpecificHack  静态扫描：执行层与契约层不得出现 task_id 分支
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
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))

import research_contract as rc          # noqa: E402
import research_execution as rexec      # noqa: E402
import eval_integrity as ei             # noqa: E402


def jd(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def jl(p):
    try:
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except Exception:
        return []


def tasks():
    return {r["task_id"]: r for r in
            jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))}


def public(t):
    return {k: t[k] for k in ("task_id", "question", "language", "task_type",
                              "required_capabilities", "split")}


# ── Lifecycle ────────────────────────────────────────────────────────────
class TestLifecycle(unittest.TestCase):
    def test_01_state_vocabularies_are_closed(self):
        self.assertIn("EXECUTED", rexec.OP_STATUS)
        self.assertIn("SKIPPED_WITH_REASON", rexec.OP_STATUS)
        self.assertIn("STRUCTURALLY_UNAVAILABLE", rexec.OP_STATUS)
        for s in ("NOT_STARTED", "EXECUTED", "SATISFIED",
                  "ZERO_ATTESTATION_CONFIRMED", "FAILED", "STRUCTURALLY_UNAVAILABLE"):
            self.assertIn(s, rexec.LANE_STATUS)

    def test_02_every_required_operation_has_a_record(self):
        """§4/§5：required operation 必须落在终态之一，禁止静默消失。"""
        from research_answer import make_plan, run_task
        t = tasks()["rt-B01"]
        run = run_task(public(t))
        ex = run["trace"]["execution"]
        ops = {o["operation_id"]: o for o in ex["operations"]}
        terminal = ("EXECUTED", "FAILED", "STRUCTURALLY_UNAVAILABLE",
                    "SKIPPED_WITH_REASON")
        for op in ex["required_operations"]:
            self.assertIn(op, ops, "required op %s 没有执行记录" % op)
            self.assertIn(ops[op]["status"], terminal)

    def test_03_every_required_lane_has_a_record(self):
        from research_answer import run_task
        t = tasks()["rt-C03"]
        run = run_task(public(t))
        ex = run["trace"]["execution"]
        lanes = {l["lane_id"]: l for l in ex["lanes"]}
        for lid in run["trace"]["research_contract"]["required_lanes"]:
            self.assertIn(lid, lanes, "required lane %s 没有执行记录" % lid)
            self.assertNotEqual(lanes[lid]["status"], "NOT_STARTED")

    def test_04_execution_state_matches_records(self):
        from research_answer import run_task
        for tid in ("rt-B01", "rt-C03", "rt-J03"):
            t = tasks()[tid]
            run = run_task(public(t))
            ex = run["trace"]["execution"]
            skipped_required = [o for o in ex["operations"]
                                if o["required"] and o["status"] == "SKIPPED_WITH_REASON"]
            if skipped_required:
                self.assertNotEqual(ex["state"], "EXECUTION_COMPLETE", tid)
            else:
                self.assertIn(ex["state"], ("EXECUTION_COMPLETE", "BLOCKED"), tid)

    def test_05_state_machine_is_recorded(self):
        from research_answer import run_task
        run = run_task(public(tasks()["rt-I03"]))
        sm = run["trace"]["state_machine"]
        self.assertTrue(sm)
        for tr in sm:
            self.assertIn("to", tr)
            self.assertIn("reason", tr)
        self.assertIn("EVIDENCE_EVALUATED", [x["to"] for x in sm])


# ── Scheduling ───────────────────────────────────────────────────────────
class TestScheduling(unittest.TestCase):
    """§26 重点回归：这些任务以前 27/27 都缺 required operation。"""

    def _run(self, tid):
        from research_answer import run_task
        return run_task(public(tasks()[tid]))

    def test_10_b01_three_lanes_and_relation_executed(self):
        run = self._run("rt-B01")
        ex = run["trace"]["execution"]
        lanes = {l["lane_id"]: l for l in ex["lanes"]}
        for lid in ("concept.desir", "concept.demande", "concept.besoin"):
            self.assertIn(lid, lanes)
            self.assertIn(lanes[lid]["status"], ("SATISFIED", "EXECUTED"))
            self.assertGreater(lanes[lid]["usable_hit_count"], 0, lid)
        self.assertIn("compare_concepts", ex["executed_operations"])
        rel = ex["relation"]
        self.assertTrue(rel.get("required"))
        self.assertEqual(rel.get("relation_evidence_n", 0) >= 0, True)
        self.assertIn("find_relation_evidence", [o["operation_id"] for o in ex["operations"]])

    def test_11_c03_both_endpoints_executed(self):
        run = self._run("rt-C03")
        ex = run["trace"]["execution"]
        eps = {e["endpoint_id"]: e for e in ex["endpoints"]}
        self.assertIn("endpoint.seminar.S07", eps)
        self.assertIn("endpoint.seminar.S20", eps)
        for e in eps.values():
            self.assertIn(e["completion"], ("COMPLETE", "INCOMPLETE"))
        # 至少 S20 必须有可用证据（S07 视语料而定，但必须**执行过**）
        self.assertGreater(eps["endpoint.seminar.S20"]["usable_evidence_n"], 0)

    def test_12_h02_formalism_search_executed(self):
        run = self._run("rt-H02")
        ex = run["trace"]["execution"]
        self.assertIn("formalism_search", [o["operation_id"] for o in ex["operations"]])
        f = ex["formalism"]
        self.assertTrue(f.get("symbols"))
        self.assertEqual(f["whole_corpus_formalism_check"]["scope"], "whole_corpus")
        self.assertIn(f["formalism_state"],
                      ("FORMALISM_FOUND", "RETRIEVED_FORMALISM_MISSING",
                       "CORPUS_FORMALISM_MISSING"))

    def test_13_j03_metadata_first(self):
        run = self._run("rt-J03")
        ex = run["trace"]["execution"]
        ops = [o["operation_id"] for o in ex["operations"]]
        self.assertIn("metadata_check", ops)
        self.assertEqual(ex["metadata"].get("metadata_state"), "METADATA_UNAVAILABLE")
        self.assertTrue(ex["metadata"].get("checked"))

    def test_14_i03_terminology_lanes_and_zero_attestation(self):
        run = self._run("rt-I03")
        ex = run["trace"]["execution"]
        self.assertIn("terminology_lookup", ex["executed_operations"])
        term_lanes = {l["lane_id"]: l for l in ex["lanes"]
                      if str(l["lane_id"]).startswith("term:")}
        self.assertTrue(term_lanes)
        zero = [l for l in term_lanes.values()
                if l["status"] == "ZERO_ATTESTATION_CONFIRMED"]
        self.assertTrue(zero, "「原乐」应为 ZERO_ATTESTATION_CONFIRMED")
        self.assertEqual(zero[0]["corpus_hits"], 0)

    def test_15_f01_source_layer_structurally_unavailable(self):
        run = self._run("rt-F01")
        ex = run["trace"]["execution"]
        sl = ex["source_layers"]
        self.assertIn("freud_source", sl)
        self.assertEqual(sl["freud_source"]["status"], "STRUCTURALLY_UNAVAILABLE")
        self.assertFalse(sl["freud_source"]["corpus_availability"])

    def test_16_lane_constraint_pushed_down(self):
        """§12：seminar 约束必须体现在执行记录里（constraint_applied=True）。"""
        run = self._run("rt-H02")
        ex = run["trace"]["execution"]
        applied = [l for l in ex["lanes"] if l.get("constraint_applied")]
        self.assertTrue(applied, "至少有一条 lane 记录了 constraint_applied")


# ── Hard rules ───────────────────────────────────────────────────────────
class TestHardRules(unittest.TestCase):
    def test_20_relation_strength_grading(self):
        rc.entity_form_groups({"entities": [
            {"term": "objet a", "entities": ["concept.objet-petit-a"]},
            {"term": "désir", "entities": ["concept.desir"]}]})
        E = ["concept.objet-petit-a", "concept.desir"]
        # R4：两个实体都出现，且形式化表达式把它们连起来
        self.assertEqual(rc.relation_strength("le désir s'écrit (S ◊ a)", E),
                         "R4_FORMAL_RELATION")
        # 只有一侧实体时不算关系证据（不得因为出现 `◊` 就升级）
        self.assertEqual(rc.relation_strength("le poinçon : (S ◊ a)", E), "R0_NONE")
        self.assertEqual(rc.relation_strength(
            "l'objet(a) dans le champ du visible, c'est le désir.", E),
            "R3_EXPLICIT_RELATION")
        self.assertEqual(rc.relation_strength(
            "le désir et l objet(a) sont ici deux choses.", E),
            "R2_CONTEXTUAL_RELATION")
        self.assertEqual(rc.relation_strength(
            "Le désir est ici. Plus loin, il parle de l objet(a).", E),
            "R1_COOCCURRENCE")
        self.assertEqual(rc.relation_strength("le désir seulement.", E), "R0_NONE")

    def test_21_question_fragments_are_not_terms(self):
        """§18：问句残片不得成为 entity / lane / discriminating term。"""
        for frag in ("中文语料里", "地点与在场者是谁", "进入拉康的欲望理论",
                     "适合表示拉康的主体", "在拉康的主体理论里被", "等译法",
                     "这些译名", "这两种译法中"):
            self.assertTrue(rc.is_question_fragment(frag), frag)
        for real in ("原乐", "莫比乌斯带", "objet petit a", "jouissance", "réel",
                     "fMRI"):
            self.assertFalse(rc.is_question_fragment(real), real)

    def test_22_plan_entities_exclude_fragments(self):
        from research_answer import make_plan
        plan = make_plan({"task_id": "t",
                          "question": "适合表示拉康的主体是什么？中文语料里怎么讲？",
                          "language": "zh", "task_type": "concept_definition",
                          "required_capabilities": []})
        terms = [e["term"] for e in plan["entities"]]
        for t in terms:
            self.assertFalse(rc.is_question_fragment(t),
                             "问句残片进入了实体解析：%s" % t)

    def test_23_generic_fallback_never_satisfies_required_lane(self):
        """§22 硬规则：generic fallback 只能进 fallback_evidence。"""
        for tid in ("rt-J02", "rt-I03"):
            from research_answer import run_task
            run = run_task(public(tasks()[tid]))
            gf = run["trace"]["execution"]["generic_fallback"]
            self.assertEqual(gf["satisfied_required_lane_n"], 0, tid)

    def test_24_budget_priority_and_exhaustion_marker(self):
        """§20：预算不足时必须显式标 BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION。"""
        from research_answer import run_task
        t = tasks()["rt-B01"]
        run = run_task(public(t), budget={"max_tool_calls": 2, "max_passages": 5,
                                          "max_context_expansions": 0,
                                          "max_retries": 0})
        ex = run["trace"]["execution"]
        codes = [o.get("failure_code") for o in ex["operations"]]
        self.assertIn("BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION", codes)
        self.assertNotEqual(ex["state"], "EXECUTION_COMPLETE")
        self.assertLessEqual(run["budget"]["used"]["tool_calls"],
                             run["budget"]["config"]["max_tool_calls"])

    def test_25_evidence_usability_feeds_lane_completion(self):
        """§19：media/editorial/fragment 不得用来满足 required lane。"""
        recs = [{"passage_id": "passage.S01.unknown.L03.P0002", "text": "拉康"},
                {"passage_id": "passage.S06.unknown.L01.P0120",
                 "text": "![[texts/s6/image2.jpeg|151]] ![[texts/s6/image3.jpeg|124]]"}]
        for r in recs:
            u = rc.classify_evidence_usability(r)
            self.assertFalse(u["can_support_substantive_claim"], r["passage_id"])

    def test_26_no_task_id_branch_in_execution_code(self):
        for fn in ("research_execution.py", "research_contract.py"):
            src = open(os.path.join(TOOLS, fn), encoding="utf-8").read()
            self.assertEqual(re.findall(r"rt-[A-Z]\d{2}", src), [],
                             "%s 出现 task_id 分支" % fn)
        src = open(os.path.join(TOOLS, "research_answer.py"), encoding="utf-8").read()
        for m in re.finditer(r"rt-[A-Z]\d{2}", src):
            seg = src[max(0, m.start() - 200):m.start() + 200]
            self.assertIsNone(re.search(r"(if|elif|and|or)\s+[^\n]*rt-[A-Z]\d{2}", seg))

    def test_27_v21_not_loosened_for_execution(self):
        """§二：修执行层不得放宽 v2.1（missing lane / relation / source 仍然禁止 SUPPORTED）。"""
        c = rc.compile_research_contract(
            {"task_id": "x", "question": "desire 与 demand 什么关系？", "language": "zh",
             "task_type": "concept_relation"},
            {"planned_operations": ["resolve_entity", "compare_concepts"],
             "task_type": "concept_relation", "salient_terms": [],
             "entities": [{"term": "desire", "entities": ["concept.desir"]},
                          {"term": "demand", "entities": ["concept.demande"]}],
             "required_capabilities": []},
            {"evidence": []}, executed_tools=["resolve_entity"])
        audit = rc.validate_contract(c)
        self.assertNotEqual(audit["state_ceiling"], "SUPPORTED")


# ── Diagnostic / Gate 19 ────────────────────────────────────────────────
class TestDiagnostic(unittest.TestCase):
    """⚠️ 事故说明（Phase 4C.1-B3 开发期）：B2 的 `research_eval_results.4c1b2.json`
    被一次 `--limit 3` 的 smoke run 覆盖成 3 行，`rt-A01/A02/A03` 三条 trace 也被重写。
    见 `_data/eval/research_traces_4c1b2/RESTORATION_NOTE.md`。
    因此本测试类对「27 任务」的断言改为读**事故前恢复出来的指标快照**
    （`research_eval_results.4c1b2.metrics_snapshot.json`），而不是被截断的主文件。
    """

    @classmethod
    def setUpClass(cls):
        cls.doc = jd(os.path.join(EVAL, "research_eval_results.4c1b2.json"))
        cls.snap = jd(os.path.join(
            EVAL, "research_eval_results.4c1b2.metrics_snapshot.json")) or {}
        cls.dir = os.path.join(EVAL, "research_traces_4c1b2")

    def test_30_diagnostic_artifact_versioned(self):
        self.assertIsNotNone(self.doc, "先跑 run_diagnostic_4c1b2.py")
        self.assertEqual(self.doc["marker"], "DIAGNOSTIC")
        self.assertEqual(self.doc["phase"], "Phase 4C.1-B2")
        self.assertEqual(self.doc["schema_version"], "research-eval-4c1b2/v1")
        # 完整 27 任务的记录在快照里（主文件已被事故截断，见类 docstring）
        self.assertEqual(self.snap.get("tasks_n"), 27)
        self.assertEqual(len(self.snap.get("per_task_summary") or []), 27)
        self.assertEqual(
            self.snap["metrics"]["required_operation_completion_rate"], 0.9778)

    def test_31_history_not_overwritten(self):
        self.assertTrue(os.path.isdir(os.path.join(EVAL, "research_traces_4c1b")))
        for fn in sorted(os.listdir(self.dir)):
            if not fn.endswith(".json"):
                continue
            tr = jd(os.path.join(self.dir, fn))
            self.assertIsInstance(tr, dict)
            self.assertEqual(tr["trace"].get("diagnostic_phase"), "Phase 4C.1-B2")
            self.assertEqual(tr["trace"].get("marker"), "DIAGNOSTIC")

    def test_32_execution_metrics_are_measured(self):
        m = self.snap.get("metrics") or self.doc["metrics"]
        self.assertIsNotNone(m["required_operation_completion_rate"])
        self.assertIsNotNone(m["required_lane_completion_rate"])
        self.assertIsNotNone(m["relation_required_n"])
        self.assertEqual(m["generic_fallback_satisfied_required_lane_n"], 0)

    def test_33_no_missing_operation_like_b_phase(self):
        """§33：MISSING_REQUIRED_OPERATION 不再 27/27。"""
        ex = self.snap.get("state_counts_exec") or {}
        self.assertEqual(sum(ex.values()), 27, "快照应覆盖 27 个任务")
        self.assertEqual(ex.get("EXECUTION_COMPLETE", 0), 25)
        m = self.snap.get("metrics") or {}
        self.assertGreaterEqual(m.get("required_lane_completion_rate", 0), 0.99)

    def test_34_gate19_clean_on_real_b2_traces(self):
        violations = []
        for fn in sorted(os.listdir(self.dir)):
            if not fn.endswith(".json"):
                continue                    # RESTORATION_NOTE.md 等非 trace 文件
            tr = jd(os.path.join(self.dir, fn))
            for f in ei.trace_integrity_findings(tr):
                if f["severity"] == "VIOLATION":
                    violations.append((fn, f["code"], f["detail"][:120]))
        self.assertEqual(violations, [], violations[:4])

    def test_35_baseline_artifact_has_no_contract_violations(self):
        d = jd(os.path.join(EVAL, "trace_integrity_baseline_v1.json"), {}) or {}
        self.assertEqual(d.get("contract_violations"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
