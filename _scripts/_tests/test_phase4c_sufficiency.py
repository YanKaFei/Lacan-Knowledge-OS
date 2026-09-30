#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase4c_sufficiency.py — Phase 4C §38 的契约测试（判定层 + 人工评审基础设施）。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools"); MCP = os.path.join(TOOLS, "lacan_mcp")
EVAL = os.path.join(VAULT, "_data", "eval"); IDX = os.path.join(VAULT, "_data", "index")
sys.path.insert(0, TOOLS); sys.path.insert(0, MCP)
import evidence_sufficiency_v2 as v2      # noqa: E402
import research_answer as ra              # noqa: E402


def jd(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d


def jl(p):
    try: return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except Exception: return []


class TestLayering(unittest.TestCase):
    def test_01_six_layers_present(self):
        cal = jd(os.path.join(EVAL, "evidence_sufficiency_calibration.v4c.json"))
        r = cal["rows"][0]
        for k in ("final_state", "availability_state", "topicality_state",
                  "coverage_state", "source_state", "ontology_state"):
            self.assertTrue(r.get(k), k)

    def test_02_no_mystery_confidence(self):
        # 「不含 cosine 阈值」的正确检查是**没有阈值表达式**，
        # 而不是源文件里不出现这个词（文档字符串里必须能说「禁止 cosine」）。
        import re
        src = open(os.path.join(MCP, "evidence_sufficiency_v2.py"), encoding="utf-8").read()
        self.assertIn("structural_only_no_cosine_threshold", src)
        self.assertIsNone(re.search(r"cosine\s*[<>]=?\s*[0-9.]", src, re.I))
        self.assertNotIn("confidence", re.findall(r'"[a-z_]*confidence[a-z_]*"', src))

    def test_03_all_four_topic_levels_reachable(self):
        lv = set()
        for p in ("evidence_sufficiency_calibration.v4c.json",):
            for r in jd(os.path.join(EVAL, p))["rows"]:
                lv |= set((r.get("topic_support_levels") or {}).keys())
        for r in jd(os.path.join(EVAL, "research_eval_results.v4c.json"))["rows"]:
            lv |= set((r.get("calibration") or {}).get("topic_support_levels") or {})
        self.assertTrue({"DIRECT", "SUBSTANTIAL", "CONTEXTUAL", "INCIDENTAL"} <= lv, lv)

    def test_04_availability_states(self):
        states = {r["availability_state"] for r in
                  jd(os.path.join(EVAL, "evidence_sufficiency_calibration.v4c.json"))["rows"]}
        self.assertTrue(states <= {"AVAILABLE", "SPARSE", "NONE"}, states)
        self.assertIn("SPARSE", states)


class TestCalibrationCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cal = jd(os.path.join(EVAL, "evidence_sufficiency_calibration.v4c.json"))
        cls.by = {r["case_id"]: r for r in cls.cal["rows"]}

    def test_10_all_ten_groups_covered(self):
        need = {"direct_dense", "direct_sparse", "incidental_dense", "incidental_sparse",
                "metadata_impossible", "ontology_gap", "diachronic_multi_period",
                "conflicting", "formalism_missing"}
        self.assertTrue(need <= set(self.cal["metrics"]["groups_covered"]))

    def test_11_incidental_dense_not_plainly_accepted(self):
        """旁及为主 + 证据很多：不得直接当成扎实支持（本案例标了需裁决）。"""
        r = next(r for r in self.cal["rows"] if r["group"] == "incidental_dense")
        self.assertTrue(r["adjudication_required"])

    def test_12_incidental_sparse_is_insufficient(self):
        r = next(r for r in self.cal["rows"] if r["group"] == "incidental_sparse")
        self.assertEqual(r["final_state"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["topicality_state"], "INCIDENTAL")
        self.assertIn("TOPIC_NOT_COVERED", r["structural_unanswerability"])

    def test_13_direct_sparse_is_supported(self):
        """§14：directness > raw count。"""
        r = next(r for r in self.cal["rows"] if r["group"] == "direct_sparse")
        self.assertEqual(r["final_state"], "SUPPORTED")

    def test_14_metadata_impossible(self):
        r = next(r for r in self.cal["rows"] if r["group"] == "metadata_impossible")
        self.assertEqual(r["final_state"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("METADATA_UNAVAILABLE", r["structural_unanswerability"])

    def test_15_diachronic_not_penalised(self):
        r = next(r for r in self.cal["rows"] if r["group"] == "diachronic_multi_period")
        self.assertEqual(r["final_state"], "SUPPORTED")

    def test_16_formalism_missing(self):
        r = next(r for r in self.cal["rows"] if r["group"] == "formalism_missing")
        self.assertIn("FORMALISM_MISSING", r["structural_unanswerability"])

    def test_17_confusion_matrix_and_rates(self):
        m = self.cal["metrics"]
        self.assertTrue(m["confusion_matrix"])
        for k in ("false_supported_rate", "false_insufficient_rate",
                  "supported_precision", "supported_recall", "abstention_rate"):
            self.assertIsNotNone(m[k], k)

    def test_18_false_supported_disclosed_not_hidden(self):
        m = self.cal["metrics"]
        self.assertEqual(m["false_supported_cases"] or [],
                         [c for c in m["false_supported_cases"] if c])
        self.assertTrue(all(c.startswith("sec-") for c in m["false_supported_cases"]))

    def test_19_disputed_case_keeps_expectation(self):
        """§31 精神：分歧案例不得为了让指标变绿而改期望。"""
        src = open(os.path.join(TOOLS, "calibrate_sufficiency_v2.py"), encoding="utf-8").read()
        self.assertIn("adjudication_required", src)
        r = next(r for r in self.cal["rows"] if r["group"] == "incidental_dense")
        self.assertEqual(r["expected_final_state"], "PARTIALLY_SUPPORTED")


class TestNoTaskSpecificHack(unittest.TestCase):
    def test_20_no_fmri_condition_in_rules(self):
        import re
        src = open(os.path.join(MCP, "evidence_sufficiency_v2.py"), encoding="utf-8").read()
        for pat in ("fMRI", "frmi", "neuroscience", "莫比乌斯", "moebius"):
            self.assertIsNone(re.search(r"(if|elif|and|or)[^\n]*%s" % pat, src), pat)

    def test_21_prevalence_uses_tightest_variant(self):
        src = open(os.path.join(MCP, "evidence_sufficiency_v2.py"), encoding="utf-8").read()
        self.assertIn("syntax_variants(t, lang)[:1]", src)


class TestResearchIntegration(unittest.TestCase):
    def test_30_agent_uses_v2(self):
        src = open(os.path.join(TOOLS, "research_answer.py"), encoding="utf-8").read()
        self.assertIn("evidence_sufficiency_v2", src)
        self.assertIn("esv2.evaluate_v2", src)

    def test_31_v4c_not_overwriting_v1(self):
        for p in ("research_eval_results.v4c.json",
                  "research_eval_results_v1.dev.json",
                  "research_eval_results_v1.holdout.json"):
            self.assertTrue(os.path.isfile(os.path.join(EVAL, p)), p)
        v1 = jd(os.path.join(EVAL, "research_eval_results_v1.dev.json"))
        self.assertIsNone(v1.get("sufficiency_engine"))

    def test_32_j02_regression(self):
        rows = jd(os.path.join(EVAL, "research_eval_results.v4c.json"))["rows"]
        j02 = next(r for r in rows if r["task_id"] == "rt-J02")
        self.assertNotEqual(j02["state"], "SUPPORTED")
        self.assertEqual(j02["state"], "INSUFFICIENT_EVIDENCE")

    def test_33_claim_restriction_under_incidental(self):
        """§34：旁及时不得产出强断言式 substantive claim。"""
        pack = {"evidence": [{"passage_id": "p", "text": "只提到 fMRI 一次",
                             "authority_level": "L2"}],
                "evidence_state": {"final_state": "INSUFFICIENT_EVIDENCE",
                                   "topicality_state": "INCIDENTAL", "signals": {},
                                   "reasons": []}}
        ans = ra.compose_answer(pack, {"anchor_pool": [], "salient_terms": ["fMRI"]})
        joined = json.dumps(ans["sections"], ensure_ascii=False)
        self.assertTrue("没有取得任何证据" in joined or "证据" in joined)
        self.assertNotIn("拉康认为", joined)


class TestHumanReviewInfrastructure(unittest.TestCase):
    def test_40_packets_generated(self):
        pk = os.path.join(EVAL, "human_review_packets")
        files = [f for f in os.listdir(pk) if f.endswith(".json")]
        self.assertGreaterEqual(len(files), 12)
        d = jd(os.path.join(pk, files[0]))
        for k in ("question", "final_answer_sections", "claims", "citations",
                  "passage_excerpts", "source_levels", "trace_summary",
                  "evidence_sufficiency_state", "warnings"):
            self.assertIn(k, d, k)
        self.assertTrue(d["no_hidden_reasoning"])

    def test_41_review_set_buckets_and_required_cases(self):
        s = jd(os.path.join(EVAL, "human_review_set_v1.json"))
        from collections import Counter
        b = Counter(i["bucket"] for i in s["items"])
        self.assertGreaterEqual(b["strong_success"], 4)
        self.assertGreaterEqual(b["borderline"], 4)
        self.assertGreaterEqual(b["insufficient"], 2)
        self.assertGreaterEqual(b["failure_or_disagreement"], 2)
        ids = {i["task_id"] for i in s["items"]}
        for t in ("rt-J02", "rt-G01", "rt-D01"):
            self.assertIn(t, ids)
        self.assertEqual(s["reviewer_status"], "SINGLE_REVIEWER")

    def test_42_review_records_are_provenance_legal(self):
        """Phase 4C.1-A：真实人工评审完成后，"必须全为 null" 不再是合法判据。

        新判据：每条记录要么是**空占位**（全空），要么是带**合法人类 provenance**
        的已完成评审；任何其它形态（自动填分 / LLM 冒充 / 枚举越界）才算违规。
        """
        import eval_integrity as ei
        rows = jl(os.path.join(EVAL, "research_human_review.jsonl"))
        self.assertTrue(rows)
        for r in rows:
            v = ei.validate_human_review_record(r)
            self.assertIn(v["state"], ("UNREVIEWED_PLACEHOLDER", "REVIEWED_HUMAN"), v)
            if v["state"] == "UNREVIEWED_PLACEHOLDER":
                for k, val in r["human_scores"].items():
                    self.assertIsNone(val, k)
                self.assertIsNone(r["citation_support"])
            else:
                self.assertEqual(r["review_status"], "REVIEWED")
                self.assertEqual(r["reviewer_type"], "human")
                self.assertIn(v["provenance_style"], ("v2", "legacy_round1"))
        # 冻结基线逐字段不可改
        self.assertEqual(ei.baseline_immutability_findings(rows), [])

    def test_43_adjudication_queue_versioned_and_decided(self):
        """ADR 队列：PENDING 不得带 decision；ADJUDICATED 必须带裁决人与决定。

        Phase 4C.1-A：3 条已由人类裁决，因此不再断言「必须仍是 PENDING」；
        rt-G01 的 NEEDS_MORE_EVIDENCE 必须同时留下 followup_required。
        """
        rows = jl(os.path.join(EVAL, "human_adjudication_queue.jsonl"))
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["status"], ("PENDING", "ADJUDICATED"))
            if r["status"] == "PENDING":
                self.assertIsNone(r.get("decision"))
                self.assertIsNone(r.get("adjudicated_by"))
            else:
                self.assertTrue(r.get("decision"), r["task_id"])
                self.assertTrue(r.get("adjudicated_by"), r["task_id"])
        g01 = [r for r in rows if r["task_id"] == "rt-G01"][0]
        self.assertEqual(g01["decision"], "NEEDS_MORE_EVIDENCE")
        self.assertTrue(g01.get("followup_required"))
        self.assertEqual(g01["agent_state_v4c"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(g01.get("agent_state_v4c_previous"), "SUPPORTED")


class TestGates(unittest.TestCase):
    def test_50_hard_gates_all_zero(self):
        d = jd(os.path.join(IDX, "PHASE4C_HARD_GATES.json"))
        self.assertEqual(d["total_violations"], 0, d)
        self.assertTrue(d["all_zero"])
        self.assertEqual(d["inherited_phase4b"]["gate_count"], 12)
        # Phase 4C.1-A：新增 Gate 19（trace integrity），共 7 项新门禁
        self.assertEqual(d.get("gate_count_new"), 7)
        for i in range(13, 20):
            self.assertIn(str(i), d["new_gates"])
        self.assertEqual(d["new_gates"]["13"]["violations"], 0)
        self.assertEqual(d["new_gates"]["19"]["violations"], 0)
        # 14 条真实人工评审必须被认成合法，而不是「伪造」
        self.assertEqual(d.get("human_review_legitimate_n"), 14)
        for state in (d.get("human_review_states") or {}).values():
            self.assertEqual(state, "REVIEWED_HUMAN")

    def test_51_completion_gate_two_states(self):
        d = jd(os.path.join(IDX, "PHASE4C_COMPLETION_GATE.json"))
        self.assertEqual(d["total"], 24)
        self.assertIn("engineering_complete", d)
        self.assertIn("scholarly_review_complete", d)
        # 学术状态必须与**记录事实**一致（§41）：没有合法人工评审 = false；有 = true。
        import eval_integrity as ei
        rows = jl(os.path.join(EVAL, "research_human_review.jsonl"))
        legs = [r for r in rows
                if ei.validate_human_review_record(r)["state"] == "REVIEWED_HUMAN"]
        self.assertEqual(d["human_reviewed_n"], len(legs))
        self.assertEqual(d["scholarly_review_complete"],
                         bool(legs) and d["engineering_complete"]
                         and all(a.get("status") == "ADJUDICATED"
                                 for a in jl(os.path.join(EVAL, "human_adjudication_queue.jsonl"))))
        # 只有「工程也完成」时才要求 True —— 否则该字段会与 engineering_complete
        # 互相锁死（套件先跑、完成门后跑），形成自引用假红。
        if legs and d["engineering_complete"]:
            self.assertTrue(d["scholarly_review_complete"])

    def test_52_calibration_set_is_reproducible(self):
        import subprocess
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "calibrate_sufficiency_v2.py"), "--check"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
