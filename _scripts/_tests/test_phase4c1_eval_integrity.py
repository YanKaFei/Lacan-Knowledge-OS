#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1_eval_integrity.py — Phase 4C.1-A（Evaluation Integrity Repair）契约测试

覆盖本轮七项交付：
    A1  Gate 13 provenance-aware（含**负例**：自动填分 / LLM 冒充 / 枚举越界）
    A2  trace integrity 五类检查（含**负例**：人为构造一条坏 v2 trace）
    A3  EvaluationRunManifest 版本绑定（schema + 可复现 + 必填 hash）
    A4  gold normalization 的跨 token 假阳性修复（含 rt-J02 的 URL 真案例）
    A5  三个裁决题的 evaluation truth 规范
    A6  empty lane semantics（rt-I03 的「原乐 = 0」必须 PASS）
    A7  structural unanswerability ↔ failure class 映射（没检到 ≠ 库里没有）
    §12 14 个已评审任务的 regression spec

设计原则：所有测试只读 frozen 产物；负例在内存里构造，不写盘。
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
EVAL = os.path.join(VAULT, "_data", "eval")
IDX = os.path.join(VAULT, "_data", "index")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))

import eval_integrity as ei          # noqa: E402
import gold_normalization as gn      # noqa: E402


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


# ── A4：gold normalization ────────────────────────────────────────────────
class TestGoldNormalization(unittest.TestCase):
    """§A4：标点必须成为 token 边界，而不是删除后拼接。"""

    def test_01_rt_j02_url_false_positive_is_gone(self):
        """rt-J02 的 `frmi` 来自 URL `univ-rennes1.fr/michel` —— v2 必须不命中。"""
        url = "http://perso.univ-rennes1.fr/michel.coste/cindy/affproj.html"
        self.assertFalse(gn.contains_v2(url, "frmi"))
        # v1（冻结）确实会命中 —— 这正是被修复的缺陷，保留为对照
        self.assertIn(gn.squash_v1("frmi"), gn.squash_v1(url))
        d = gn.diagnose_v1_only_hit(url, "frmi")
        self.assertEqual(d["reason"], "url_join")

    def test_02_cross_token_joins_are_rejected(self):
        cases = [
            ("à aucun objet, a fait des mouvements", "objet a"),
            ("le « veau d'or » a une sorte", "dora"),
            ("Est-il dans l'individualité radicale, réelle ?", "le reel"),
            ("et FREUD qui fait des ironies, fait des ironies", "desir"),
        ]
        for text, needle in cases:
            with self.subTest(needle=needle, text=text[:30]):
                self.assertFalse(gn.contains_v2(text, needle))
                self.assertIn(gn.squash_v1(needle), gn.squash_v1(text))   # v1 会命中
                # 机制可以是跨子句 / 跨空白 / 短片段拼接，但都必须落在「可判假阳性」集合里
                self.assertIn(gn.diagnose_v1_only_hit(text, needle)["reason"],
                              gn.FALSE_POSITIVE_REASONS)

    def test_03_legitimate_hits_survive(self):
        """修精度不能把该命中的也砍掉（词形、连字符/空格变体、CJK、elision）。"""
        keep = [
            ("ses désirs, son rapport à son milieu", "désir"),      # 词形
            ("plus-de-jouir", "plus de jouir"),                     # 连字符 ↔ 空格
            ("plus de jouir", "plus-de-jouir"),
            ("l'objet petit a, vous apparaîtra-t-il", "objet petit a"),  # elision
            ("对象a 与 客体小a", "对象 a"),                          # CJK 无空格
            ("莫比乌斯带是一种这样的曲面", "莫比乌斯带"),
            ("Discours du Maître", "maitre"),
            ("（objet (a) 的另一种写法）", "objet a"),
            ("[Pas de sténotypie disponible]", "pas de stenotypie"),
        ]
        for text, needle in keep:
            with self.subTest(needle=needle):
                self.assertTrue(gn.contains_v2(text, needle))

    def test_04_symbolic_needles_keep_their_symbols(self):
        """`◊` 是语义的一部分：`S ◊ a` 绝不能退化成 `s a` 两 token 序列。"""
        self.assertTrue(gn.is_symbolic_needle("◊"))
        self.assertTrue(gn.is_symbolic_needle("S ◊ a"))
        self.assertTrue(gn.is_symbolic_needle("(S ◊ a)"))
        self.assertFalse(gn.is_symbolic_needle("formule"))
        self.assertTrue(gn.contains_v2_symbolic(
            "nous partirons de la formule (S ◊ a) :", "S ◊ a"))
        self.assertFalse(gn.contains_v2_symbolic("les sujets a", "S ◊ a"))
        rx = gn.symbolic_needle_regex("S ◊ a", relaxed=True)
        self.assertTrue(rx.search("S◊a"))
        self.assertFalse(rx.search("les sujets a"))

    def test_05_v1_squash_is_frozen(self):
        """v1 squash 必须保持原样 —— research_tasks_v1.jsonl 靠它复现。"""
        self.assertEqual(gn.squash_v1("l'objet petit a"), "lobjetpetita")
        self.assertEqual(gn.squash_v1("plus-de-jouir"), "plusdejouir")

    def test_06_task_builder_check_still_passes(self):
        """改了归一化实现也不许动 v1 gold（`--check` 必须仍然通过）。"""
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "build_research_tasks_v1.py"), "--check"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


# ── A4：lane audit 产物 ───────────────────────────────────────────────────
class TestGoldLaneAudit(unittest.TestCase):
    def test_10_audit_artifact_exists_and_classifies(self):
        rows = jl(os.path.join(EVAL, "gold_lane_audit_v1.jsonl"))
        self.assertGreater(len(rows), 40, "lane 审计应覆盖全部 lane")
        for r in rows:
            self.assertIn(r["classification"],
                          ("SAFE", "LIKELY_FALSE_POSITIVE", "NEEDS_MANUAL_REVIEW"))
            self.assertEqual(r["schema_version"], "gold-lane-audit/v1")
            if r["classification"] == "SAFE":
                self.assertEqual(r["extra_v1_only"], 0)
            else:
                self.assertGreater(r["extra_v1_only"], 0)
                self.assertTrue(r["examples"], "非 SAFE 必须给出可复核例子")

    def test_11_rt_j02_lane_is_flagged_as_false_positive(self):
        rows = jl(os.path.join(EVAL, "gold_lane_audit_v1.jsonl"))
        r = [x for x in rows if x["task_id"] == "rt-J02" and x["lane"] == "zh_frmi"]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["classification"], "LIKELY_FALSE_POSITIVE")
        self.assertEqual(r[0]["v2_hits"], 0)
        self.assertEqual(r[0]["v1_hits"], 3)
        self.assertIn("url_join", r[0]["reasons"])


# ── A1：Gate 13 / provenance ──────────────────────────────────────────────
class TestHumanReviewProvenance(unittest.TestCase):
    def setUp(self):
        self.rows = jl(os.path.join(EVAL, "research_human_review.jsonl"))
        self.assertTrue(self.rows)
        self.sample = copy.deepcopy(self.rows[-1])

    def test_20_frozen_human_reviews_are_legitimate(self):
        for r in self.rows:
            v = ei.validate_human_review_record(r)
            self.assertEqual(v["state"], "REVIEWED_HUMAN", (r["task_id"], v["problems"]))
            self.assertEqual(r["reviewer_type"], "human")
        self.assertEqual(ei.baseline_immutability_findings(self.rows), [])

    def test_21_auto_filled_placeholder_is_illegitimate(self):
        bad = copy.deepcopy(self.sample)
        bad["review_status"] = "NOT_REVIEWED"
        bad["human_scores"] = {k: 3 for k in ei.SCORE_DIMS}
        bad["citation_support"] = "PASS"
        v = ei.validate_human_review_record(bad)
        self.assertEqual(v["state"], "ILLEGITIMATE")
        self.assertTrue(any("NOT_REVIEWED" in p for p in v["problems"]))

    def test_22_llm_reviewer_is_illegitimate(self):
        bad = copy.deepcopy(self.sample)
        bad["reviewer_type"] = "llm"
        bad["provenance"] = {"reviewer_type": "llm", "recorded_by": "auto_script",
                             "submitted_by": "system"}
        v = ei.validate_human_review_record(bad)
        self.assertEqual(v["state"], "ILLEGITIMATE")

    def test_23_out_of_enum_and_range_are_illegitimate(self):
        for mutate in (lambda r: r["human_scores"].__setitem__("clarity", 9),
                       lambda r: r.__setitem__("citation_support", "MAYBE"),
                       lambda r: r.__setitem__("scholarly_usable", "PROBABLY")):
            bad = copy.deepcopy(self.sample)
            mutate(bad)
            self.assertEqual(ei.validate_human_review_record(bad)["state"],
                             "ILLEGITIMATE")

    def test_24_missing_dims_or_comment_are_illegitimate(self):
        bad = copy.deepcopy(self.sample)
        bad["human_scores"].pop("distinction_preservation")
        self.assertEqual(ei.validate_human_review_record(bad)["state"], "ILLEGITIMATE")
        bad2 = copy.deepcopy(self.sample)
        bad2["reviewer_comment"] = {"raw": ""}
        self.assertEqual(ei.validate_human_review_record(bad2)["state"], "ILLEGITIMATE")

    def test_25_baseline_tampering_is_detected(self):
        tampered = copy.deepcopy(self.rows)
        tampered[0]["human_scores"]["theoretical_coherence"] = 5
        problems = ei.baseline_immutability_findings(tampered)
        self.assertTrue(problems)
        self.assertIn("冻结基线被改动", problems[0])

    def test_26b_adjudication_tampering_is_detected(self):
        q = jl(os.path.join(EVAL, "human_adjudication_queue.jsonl"))
        self.assertEqual(ei.adjudication_immutability_findings(q), [])
        bad = copy.deepcopy(q)
        bad[0]["decision"] = "GOLD_CORRECT"
        self.assertTrue(ei.adjudication_immutability_findings(bad))

    def test_26_gate13_reports_zero_on_real_data(self):
        d = jd(os.path.join(IDX, "PHASE4C_HARD_GATES.json"))
        self.assertEqual(d["new_gates"]["13"]["violations"], 0)
        self.assertEqual(d["human_review_legitimate_n"], 14)


# ── A2：trace integrity ───────────────────────────────────────────────────
class TestTraceIntegrity(unittest.TestCase):
    def _good_v2(self):
        return {
            "schema_version": ei.CONTRACT_SCHEMA,
            "task_id": "rt-FAKE",
            "required_operations": ["resolve_entity", "get_context"],
            "completed_operations": ["resolve_entity", "get_context"],
            "missing_operations": [],
            "state_transition_reason": "证据量充足且 topicality=DIRECT",
            "plan": {"planned_operations": ["resolve_entity", "get_context"]},
            "trace": {"tool_calls": [{"tool": "resolve_entity"}, {"tool": "get_context"}],
                      "state_transitions": [{"step": 1, "state": "SUPPORTED"}],
                      "context_expansions": [{"passage_id": "p1"}]},
            "budget": {"used": {"context_expansions": 1}},
            "evidence_pack": {"evidence_state": {"final_state": "SUPPORTED", "reasons": [],
                                                 "signals": {}}},
            "evaluation": {"state": "SUPPORTED"},
        }

    def test_30_good_v2_trace_has_no_findings(self):
        self.assertEqual(ei.trace_integrity_findings(self._good_v2()), [])

    def test_31_unexplained_state_transition(self):
        t = self._good_v2()
        t["trace"]["state_transitions"] = [{"step": 1, "state": "PARTIALLY_SUPPORTED"}]
        t.pop("state_transition_reason")
        codes = [f["code"] for f in ei.trace_integrity_findings(t)]
        self.assertIn("STATE_TRANSITION_UNEXPLAINED", codes)
        self.assertTrue(all(f["severity"] == "VIOLATION"
                            for f in ei.trace_integrity_findings(t)))

    def test_32_reason_citing_absent_signals(self):
        t = self._good_v2()
        t["evidence_pack"]["evidence_state"]["reasons"] = [
            "证据量、多分量一致性、session 多样性、约束满足四项均达标。"]
        t["evidence_pack"]["evidence_state"]["signals"] = {
            "component_agreement": None, "constraint_satisfaction": None,
            "independent_families_executed": []}
        codes = [f["code"] for f in ei.trace_integrity_findings(t)]
        self.assertIn("SUFFICIENCY_REASON_CITES_ABSENT_SIGNAL", codes)

    def test_33_context_expansion_mismatch(self):
        t = self._good_v2()
        t["budget"]["used"]["context_expansions"] = 3     # trace 里只有 1 项
        codes = [f["code"] for f in ei.trace_integrity_findings(t)]
        self.assertIn("CONTEXT_EXPANSION_COUNT_MISMATCH", codes)

    def test_34_missing_required_operation_with_supported(self):
        t = self._good_v2()
        t["required_operations"] = ["resolve_entity", "get_context", "find_concept_evidence"]
        t["completed_operations"] = ["resolve_entity", "get_context"]
        t["missing_operations"] = ["find_concept_evidence"]
        codes = [f["code"] for f in ei.trace_integrity_findings(t)]
        self.assertIn("SUPPORTED_WITH_MISSING_REQUIRED_OPERATIONS", codes)
        self.assertTrue(all(f["severity"] == "VIOLATION"
                            for f in ei.trace_integrity_findings(t)))

    def test_35_legacy_trace_is_catalogued_not_failed(self):
        """历史冻结 trace 的既知不一致必须是 LEGACY_FROZEN（不判违规、不改历史）。"""
        p = os.path.join(EVAL, "research_traces_4b", "rt-C03.json")
        t = jd(p)
        self.assertIsNotNone(t)
        fs = ei.trace_integrity_findings(t)
        self.assertTrue(fs, "rt-C03 的 trace 有既知不一致")
        self.assertTrue(all(f["severity"] == "LEGACY_FROZEN" for f in fs))

    def test_36_baseline_artifact_records_frozen_findings(self):
        d = jd(os.path.join(EVAL, "trace_integrity_baseline_v1.json"))
        self.assertIsNotNone(d)
        self.assertEqual(d["contract_violations"], 0)
        self.assertGreater(d["legacy_frozen_total"], 0)
        self.assertIn("PLANNED_OPERATION_NOT_EXECUTED", d["legacy_frozen_by_code"])
        self.assertIn("SUFFICIENCY_REASON_CITES_ABSENT_SIGNAL", d["legacy_frozen_by_code"])
        self.assertIn("CONTEXT_EXPANSION_COUNT_MISMATCH", d["legacy_frozen_by_code"])
        self.assertIn("STATE_TRANSITION_UNEXPLAINED", d["legacy_frozen_by_code"])


# ── A3：manifest ─────────────────────────────────────────────────────────
class TestRunManifest(unittest.TestCase):
    def test_40_schema_and_latest_exist(self):
        self.assertTrue(os.path.isfile(os.path.join(EVAL,
                                                    "evaluation_run_manifest.schema.json")))
        m = jd(os.path.join(EVAL, "manifests", "latest.json"))
        self.assertIsNotNone(m)

    def test_41_manifest_binds_everything_required(self):
        m = jd(os.path.join(EVAL, "manifests", "latest.json"))
        for k in ("git_commit", "engine_version", "engine_hashes", "engine_hash",
                  "ontology_version", "passage_store_version", "gold_version",
                  "task_set_version", "schema_versions", "generated_at"):
            self.assertIn(k, m, k)
        for name in ("research_answer", "research_agent", "evidence_sufficiency_v2",
                     "knowledge_api", "gold_normalization", "eval_integrity"):
            self.assertIn(name, m["engine_hashes"])
            self.assertTrue(m["engine_hashes"][name]["sha256"])
        for k in ("engine_hash", "ontology_version", "passage_store_version",
                  "gold_version", "task_set_version"):
            self.assertRegex(m[k], r"^[0-9a-f]{64}$")
        self.assertGreater(m["passage_store"]["passage_store"]["n_lines"], 100000)

    def test_42_manifest_matches_schema(self):
        import jsonschema
        m = jd(os.path.join(EVAL, "manifests", "latest.json"))
        jsonschema.Draft7Validator(
            jd(os.path.join(EVAL, "evaluation_run_manifest.schema.json"))).validate(m)

    def test_43_manifest_is_reproducible(self):
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "build_eval_manifest.py"), "--verify"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


# ── A5：adjudicated evaluation truth ─────────────────────────────────────
class TestAdjudicatedTruth(unittest.TestCase):
    def setUp(self):
        self.d = jd(os.path.join(EVAL, "evaluation_truth_adjudicated_v1.json"))
        self.assertTrue(self.d)

    def test_50_three_adjudications_are_encoded(self):
        self.assertEqual(self.d["status"], "SPEC_ONLY_NOT_APPLIED")
        t = self.d["tasks"]
        self.assertEqual(t["rt-J01"]["adjudication_decision"], "AGENT_CORRECT")
        self.assertEqual(t["rt-H02"]["adjudication_decision"], "GOLD_CORRECT")
        self.assertEqual(t["rt-G01"]["adjudication_decision"], "NEEDS_MORE_EVIDENCE")

    def test_51_targets_and_constraints(self):
        t = self.d["tasks"]
        self.assertEqual(t["rt-J01"]["target_answerability"], "PARTIALLY_SUPPORTED")
        self.assertEqual(t["rt-H02"]["target_answerability"], "SUPPORTED")
        self.assertEqual(t["rt-H02"]["adjudication_scope"],
                         "只认可 answerability 标签（SUPPORTED）；gold evidence 构造不合格")
        self.assertTrue(t["rt-G01"]["followup_required"])
        for k, v in t.items():
            self.assertTrue(v["gold_v2_required_changes"], k)
            self.assertTrue(v["supported_forbidden_conditions"], k)

    def test_52_corpus_evidence_is_real(self):
        """裁决所依据的计数来自语料实扫，必须与独立复算一致。"""
        ev = self.d["tasks"]["rt-J01"]["corpus_evidence"]
        self.assertEqual(ev["莫比乌斯"]["hits"], 270)
        self.assertEqual(ev["莫比乌斯带"]["hits"], 241)
        self.assertEqual(ev["moebius"]["hits"], 1)
        self.assertEqual(ev["bande de moebius"]["hits"], 0)
        ev2 = self.d["tasks"]["rt-H02"]["corpus_evidence"]
        self.assertEqual(ev2["diamond"]["hits"], 289)
        self.assertEqual(ev2["(S_diamond_a)"]["hits"], 5)
        ev3 = self.d["tasks"]["rt-G01"]["corpus_evidence"]
        self.assertGreater(ev3["hegel"]["hits"], 300)
        self.assertGreater(ev3["maitre"]["hits"], 800)

    def test_53_truth_matches_frozen_queue(self):
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "build_adjudicated_truth.py"), "--check"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_54_v1_gold_is_untouched(self):
        """v1 任务集里不得出现任何裁决痕迹（§A5 约束）。"""
        rows = jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))
        blob = json.dumps(rows, ensure_ascii=False)
        for marker in ("adjudicat", "gold_v2", "AGENT_CORRECT", "GOLD_CORRECT",
                       "NEEDS_MORE_EVIDENCE"):
            self.assertNotIn(marker, blob)


# ── A6：empty lane semantics ─────────────────────────────────────────────
class TestEmptyLaneSemantics(unittest.TestCase):
    def test_60_lane_result_semantics(self):
        self.assertEqual(ei.lane_result("EXPECTED_ZERO", 0), "PASS")
        self.assertEqual(ei.lane_result("EXPECTED_ZERO", 3), "FAIL")
        self.assertEqual(ei.lane_result("EXPECTED_POSITIVE", 5), "PASS")
        self.assertEqual(ei.lane_result("EXPECTED_POSITIVE", 0), "FAIL")
        self.assertEqual(ei.lane_result("UNKNOWN_EXPECTATION", 0), "REVIEW")
        self.assertEqual(ei.lane_result("UNKNOWN_EXPECTATION", 1), "PASS")

    def test_61_yuan_le_zero_hits_is_a_pass(self):
        rows = jl(os.path.join(EVAL, "scholarly_regression_v1.jsonl"))
        r = [x for x in rows if x["task_id"] == "rt-I03"][0]
        yuan = [l for l in r["lane_semantics"] if l["lane"] == "zh_yuan"]
        self.assertTrue(yuan)
        self.assertEqual(yuan[0]["expectation"], "EXPECTED_ZERO")
        self.assertEqual(yuan[0]["observed_hits"], 0)
        self.assertEqual(yuan[0]["result"], "PASS")
        self.assertIn("原乐", r["expected_zero_lanes"][0])

    def test_62_semantics_spec_declares_three_expectations(self):
        d = jd(os.path.join(EVAL, "lane_semantics_v1.json"))
        for k in ("EXPECTED_POSITIVE", "EXPECTED_ZERO", "UNKNOWN_EXPECTATION"):
            self.assertIn(k, d["expectations"])
        self.assertIn("empty_lane_is_not_failure", d["reporting_contract"])


# ── A7：structural ↔ failure 映射 ────────────────────────────────────────
class TestStructuralFailureMapping(unittest.TestCase):
    def test_70_mapping_covers_both_closed_sets(self):
        d = jd(os.path.join(EVAL, "failure_class_mapping_v1.json"))
        self.assertEqual(d["axes"]["structural_unanswerability"]["count"], 5)
        self.assertEqual(d["axes"]["failure_classes"]["count"], 11)
        for c in d["axes"]["structural_unanswerability"]["values"]:
            self.assertIn(c, d["mapping"])
            self.assertIn("category", d["mapping"][c])
            self.assertTrue(d["mapping"][c]["maps_to_failure_classes"], c)
        self.assertEqual(set(d["axes"]["structural_unanswerability"]["values"]),
                         set(ei.STRUCTURAL_CLASS_MAP))

    def test_71_formalism_missing_is_not_structural(self):
        d = jd(os.path.join(EVAL, "failure_class_mapping_v1.json"))
        f = d["mapping"]["FORMALISM_MISSING"]
        self.assertEqual(f["category"], "RETRIEVAL_OR_EXECUTION")
        self.assertFalse(f["admissible_as_structural_unanswerability"])
        self.assertIn("RETRIEVAL_MISS", f["maps_to_failure_classes"])
        self.assertIn("two_level_contract", f)

    def test_72_metadata_unavailable_is_mapped_not_lost(self):
        d = jd(os.path.join(EVAL, "failure_class_mapping_v1.json"))
        m = d["mapping"]["METADATA_UNAVAILABLE"]
        self.assertEqual(m["category"], "CORPUS_STRUCTURAL")
        self.assertTrue(m["admissible_as_structural_unanswerability"])
        self.assertIn("SOURCE_GAP", m["maps_to_failure_classes"])

    def test_73_retrieval_absence_is_not_corpus_absence(self):
        # 未做 corpus 扫描就断言结构性不可答 → 必须被拒
        problems = ei.structural_assertion_findings(["FORMALISM_MISSING"], {})
        self.assertTrue(problems)
        # 做过 corpus 扫描、且属 RETRIEVAL 类 → 仍不得作为结构性不可答
        problems2 = ei.structural_assertion_findings(
            ["FORMALISM_MISSING"], {"FORMALISM_MISSING": {"executed": True}})
        self.assertTrue(problems2)
        # 真结构性 + 有 corpus 扫描 → 通过
        self.assertEqual(ei.structural_assertion_findings(
            ["METADATA_UNAVAILABLE"], {"METADATA_UNAVAILABLE": {"executed": True}}), [])
        # FORMATISM 类：只有 whole_corpus 专项扫描后才可能成立
        self.assertTrue(ei.structural_assertion_findings(
            ["FORMALISM_MISSING"],
            {"FORMALISM_MISSING": {"executed": True, "scope": "retrieved_set"}}))
        self.assertEqual(ei.structural_assertion_findings(
            ["FORMALISM_MISSING"],
            {"FORMALISM_MISSING": {"executed": True, "scope": "whole_corpus"}}), [])
        self.assertEqual(ei.category_of_structural_class("FORMALISM_MISSING"),
                         "RETRIEVAL_OR_EXECUTION")


# ── §12：scholarly regression spec ───────────────────────────────────────
class TestScholarlyRegression(unittest.TestCase):
    def setUp(self):
        self.rows = jl(os.path.join(EVAL, "scholarly_regression_v1.jsonl"))
        self.review_set = [it["task_id"] for it in
                           (jd(os.path.join(EVAL, "human_review_set_v1.json")) or {})
                           .get("items", [])]

    def test_80_all_fourteen_tasks_present(self):
        self.assertEqual(len(self.rows), 14)
        self.assertEqual({r["task_id"] for r in self.rows}, set(self.review_set))

    def test_81_required_fields_present(self):
        need = ("task_id", "task_type", "required_entities", "required_operations",
                "required_lanes", "required_constraints", "expected_zero_lanes",
                "relation_evidence_required", "source_layers_required",
                "seminar_constraints", "period_constraints", "formalism_required",
                "metadata_required", "supported_forbidden_conditions",
                "human_review_baseline", "human_adjudication")
        for r in self.rows:
            for k in need:
                self.assertIn(k, r, (r["task_id"], k))

    def test_82_human_baseline_is_embedded_verbatim(self):
        reviews = {r["task_id"]: r for r in
                   jl(os.path.join(EVAL, "research_human_review.jsonl"))}
        for r in self.rows:
            b = r["human_review_baseline"]
            src = reviews[r["task_id"]]
            self.assertEqual(b["scores"], src["human_scores"], r["task_id"])
            self.assertEqual(b["citation_support"], src["citation_support"])
            self.assertEqual(b["scholarly_usable"], src["scholarly_usable"])

    def test_83_adjudicated_tasks_carry_decisions(self):
        adj = {r["task_id"]: r for r in
               jl(os.path.join(EVAL, "human_adjudication_queue.jsonl"))}
        for r in self.rows:
            if r["task_id"] in adj:
                self.assertIsNotNone(r["human_adjudication"])
                self.assertEqual(r["human_adjudication"]["decision"],
                                 adj[r["task_id"]]["decision"])
                self.assertTrue(r["gold_v2_spec"])
            else:
                self.assertIsNone(r["human_adjudication"])

    def test_84_specific_regression_contracts(self):
        by = {r["task_id"]: r for r in self.rows}
        # rt-B01：三条 lane + 关系证据 + 缺 lane 时禁止 SUPPORTED
        b01 = by["rt-B01"]
        self.assertEqual(b01["required_lanes"],
                         ["lane_besoin", "lane_demande", "lane_desir"])
        self.assertTrue(b01["relation_evidence_required"])
        self.assertEqual(b01["if_missing_lane"], "SUPPORTED = forbidden")
        # rt-C03：两端点 + 端点缺失禁止 SUPPORTED
        c03 = by["rt-C03"]
        self.assertEqual(c03["required_endpoints"], ["seminar.S07", "seminar.S20"])
        self.assertEqual(c03["if_endpoint_missing"], "SUPPORTED = forbidden")
        # rt-H02：formalism + S14 + retrieval_formalism_missing ≠ structural
        h02 = by["rt-H02"]
        for f in ("◊", "S ◊ a"):
            self.assertIn(f, h02["formalism_required"])
        self.assertIn("seminar.S14", h02["seminar_constraints"])
        # rt-I03：terminology lanes + expected zero
        i03 = by["rt-I03"]
        self.assertEqual(i03["terminology_lanes"], ["快感", "享受", "原乐"])
        self.assertTrue(any("原乐" in z for z in i03["expected_zero_lanes"]))
        # rt-F01 / rt-G01：source layer separation
        self.assertTrue(by["rt-F01"]["source_layers_required"])
        self.assertTrue(by["rt-G01"]["source_layers_required"])
        self.assertTrue(by["rt-G01"]["followup_required"])

    def test_85_spec_is_reproducible(self):
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "build_scholarly_regression_v1.py"),
                            "--check"], capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_86_spec_basis_cites_human_review_codes(self):
        """手写要求必须给出依据，且依据至少能对上一条人工评审 issue code。"""
        reviews = {r["task_id"]: r for r in
                   jl(os.path.join(EVAL, "research_human_review.jsonl"))}
        for r in self.rows:
            codes = {(i.get("code") or i.get("kind"))
                     for i in reviews[r["task_id"]].get("reviewer_raised_issues", [])}
            if r["required_lanes"] or r["formalism_required"] \
                    or r["metadata_required"] or r["terminology_lanes"]:
                self.assertTrue(r["spec_basis"], r["task_id"])
                joined = " ".join(r["spec_basis"])
                self.assertTrue(
                    any(c in joined for c in codes)
                    or "reviewer requested_changes" in joined
                    or "裁决" in joined or "本轮" in joined,
                    (r["task_id"], r["spec_basis"], sorted(codes)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
