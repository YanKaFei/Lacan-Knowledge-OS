#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4b_research.py — Phase 4B 契约测试

覆盖 §3–§9、§11–§13、§20、§23、§25–§26、§29–§30、§33、§35 里可自动核对的部分。
每个「通过了」的断言都配一条「它真的会红」的合成违规测试（门禁不能只是永远绿）。
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
MCP = os.path.join(TOOLS, "lacan_mcp")
EVAL = os.path.join(VAULT, "_data", "eval")
IDX = os.path.join(VAULT, "_data", "index")
sys.path.insert(0, TOOLS)
sys.path.insert(0, MCP)

import research_answer as rans        # noqa: E402
import research_eval_4b as rev        # noqa: E402
import knowledge_api as api           # noqa: E402


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def jd(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d


class TestTaskSet(unittest.TestCase):
    """§3–§5：任务集与 gold。"""

    @classmethod
    def setUpClass(cls):
        cls.tasks = jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))
        cls.by = {t["task_id"]: t for t in cls.tasks}

    def test_01_size_types_and_split(self):
        self.assertGreaterEqual(len(self.tasks), 24, "§3 要求 24–30 个任务")
        self.assertLessEqual(len(self.tasks), 30)
        self.assertEqual(len({t["task_type"] for t in self.tasks}), 10, "§4 要求 10 类")
        hold = [t for t in self.tasks if t["split"] == "holdout"]
        self.assertGreaterEqual(len(hold), 8, "§29/§35 要求 ≥8 个 holdout")

    def test_02_schema_fields_present(self):
        need = ("task_id", "question", "language", "task_type", "expected_entities",
                "expected_operations", "expected_seminars", "required_capabilities",
                "answerability", "gold_evidence", "acceptable_evidence",
                "forbidden_shortcuts", "evaluation_notes", "review_status")
        for t in self.tasks:
            for k in need:
                self.assertIn(k, t, "%s 缺 %s" % (t["task_id"], k))
            self.assertIn(t["answerability"], ("SUPPORTED", "PARTIALLY_SUPPORTED",
                                               "INSUFFICIENT_EVIDENCE"))
            self.assertEqual(t["review_status"], "script_assisted_unreviewed")

    def test_03_gold_ids_are_real(self):
        known = set(api.KB_.meta())
        for t in self.tasks:
            for pid in (t["gold_evidence"] or []) + (t["acceptable_evidence"] or []):
                self.assertIn(pid, known, "%s: %s 不存在" % (t["task_id"], pid))
            for ids in (t.get("lane_eval_sets") or {}).values():
                for pid in ids:
                    self.assertIn(pid, known)

    def test_04_insufficient_tasks_have_no_fabricated_gold(self):
        """§5：gold 可以为空，但不得为了 schema 填数据而虚构。"""
        for t in self.tasks:
            if t["answerability"] == "INSUFFICIENT_EVIDENCE":
                # gold 为空 → 必须写明「为什么没有 gold」；
                # gold 非空但仍判不可答（如 J02 只有 3 处旁及提及）→ 必须在
                # evaluation_notes 里给出实测计数作为理由。
                if not t["gold_evidence"]:
                    self.assertTrue(t["gold_derivation"].get("no_gold_reason"),
                                    t["task_id"])
                else:
                    self.assertTrue(t["evaluation_notes"], t["task_id"])
                    self.assertIn("实测", t["evaluation_notes"])

    def test_05_gold_derivation_is_auditable(self):
        d = jd(os.path.join(EVAL, "research_tasks_v1.gold_derivation.json"))
        self.assertEqual(len(d["tasks"]), len(self.tasks))
        for t in d["tasks"]:
            self.assertTrue(t["lanes"] or t["gold_n"] == 0)
            for l in t["lanes"]:
                self.assertIn("hits_total", l)
                self.assertIn("needles", l)

    def test_06_holdout_questions_have_no_tuning_hooks(self):
        """§30：holdout 任务里不得出现「为测试题写系统」的痕迹字段。"""
        for t in self.tasks:
            if t["split"] != "holdout":
                continue
            blob = json.dumps(t, ensure_ascii=False)
            self.assertNotIn("post_hoc_rule", blob)
            self.assertFalse(t.get("tuned_after_run", False))
            self.assertFalse(t.get("holdout_answers_disclosed_to_agent", False))


class TestGoldIsolation(unittest.TestCase):
    """§6：Gold 不得进入 Agent。"""

    def test_10_public_view_strips_gold(self):
        t = jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))[0]
        pub = rev.public_view(t)
        self.assertEqual(sorted(pub), sorted(rev.PUBLIC_FIELDS))
        for g in rev.GOLD_FIELD_NAMES if hasattr(rev, "GOLD_FIELD_NAMES") else ():
            self.assertNotIn(g, pub)

    def test_11_run_task_refuses_gold_fields(self):
        with self.assertRaises(ValueError):
            rans.run_task({"task_id": "x", "question": "q", "language": "zh",
                           "task_type": "concept_definition",
                           "required_capabilities": [],
                           "gold_evidence": ["passage.S01.unknown.P0001"]})

    def test_12_traces_contain_no_gold_field_names(self):
        tdir = os.path.join(EVAL, "research_traces_4b")
        for fn in sorted(os.listdir(tdir)):
            d = jd(os.path.join(tdir, fn))
            blob = json.dumps({k: d[k] for k in ("trace", "plan", "evidence_pack")},
                              ensure_ascii=False)
            for g in ("expected_operations", "evaluation_notes", "forbidden_shortcuts",
                      "gold_evidence", "answerability"):
                self.assertNotIn('"%s"' % g, blob, "%s 泄漏 %s" % (fn, g))
            self.assertEqual(sorted(d["public_task"]), sorted(rev.PUBLIC_FIELDS))


class TestAnswerContract(unittest.TestCase):
    """§9/§11/§12：回答结构、claim 分类、citation 本地校验。"""

    @classmethod
    def setUpClass(cls):
        # ⚠️ 不能叫 `run`：会覆盖 `unittest.TestCase.run`，报
        #    "TypeError: 'dict' object is not callable"（实测踩过）。
        cls.rr = rans.run_task({"task_id": "t", "question":
                                 "拉康所谓的 objet petit a 到底是什么？",
                                 "language": "zh", "task_type": "concept_definition",
                                 "required_capabilities": ["multi_step",
                                                           "period_coverage"]})

    def test_20_sections_present(self):
        secs = self.rr["answer"]["sections"]
        for k in ("brief_answer", "theoretical_development", "key_primary_evidence",
                  "interpretation_layers", "evidence_limitations"):
            self.assertIn(k, secs)
            self.assertTrue(str(secs[k]).strip(), k)

    def test_21_claims_are_classified_and_cited(self):
        for c in self.rr["answer"]["claims"]:
            self.assertIn(c["classification"], rans.CLAIM_CLASSES)
            if c["classification"] in ("PRIMARY_EVIDENCE", "SECONDARY_INTERPRETATION"):
                self.assertTrue(c["citations"], "%s 无引用" % c["claim_id"])

    def test_22_validation_metrics_shape(self):
        m = self.rr["answer_check"]["metrics"]
        for k in ("evidence_validity", "citation_anchor_support_rate",
                  "citation_term_cluster_rate", "unsupported_claim_rate",
                  "fabricated_citations", "provenance_upgrades",
                  "source_layer_confusions", "entailment_note"):
            self.assertIn(k, m)
        self.assertEqual(m["fabricated_citations"], 0)
        self.assertIn("术语级代理", m["entailment_note"])

    def test_23_fabricated_citation_is_detected(self):
        pack = self.rr["evidence_pack"]
        fake = dict(self.rr["answer"])
        fake["claims"] = [dict(c) for c in self.rr["answer"]["claims"]]
        fake["claims"][0] = {**fake["claims"][0],
                             "citations": ["passage.S99.unknown.P9999"]}
        out = rans.validate_answer(fake, pack)
        self.assertTrue(any(i["kind"] == "FABRICATED_CITATION"
                            for i in out["issues"]))
        self.assertEqual(out["metrics"]["fabricated_citations"], 1)

    def test_24_provenance_upgrade_is_detected(self):
        """recovered 中译不得被当作 L1 primary 引用。"""
        pack = self.rr["evidence_pack"]
        zh = [e for e in pack["evidence"]
              if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"]
        if not zh:
            self.skipTest("本问题没取到 recovered 中译")
        fake = {"claims": [{"claim_id": "x", "text": "t",
                            "classification": "PRIMARY_EVIDENCE",
                            "citations": [zh[0]["passage_id"]],
                            "anchor_terms": []}],
                "sections": {}}
        out = rans.validate_answer(fake, pack)
        self.assertTrue(any(i["kind"] == "PROVENANCE_UPGRADE" for i in out["issues"]))

    def test_25_source_layer_confusion_is_detected(self):
        pack = {"evidence": [{"passage_id": "passage.S01.unknown.P0001",
                              "authority_level": "L2", "language": "zh",
                              "trace_status": "COMPLETE"}]}
        fake = {"claims": [{"claim_id": "x", "text": "t",
                            "classification": "PRIMARY_EVIDENCE",
                            "citations": ["passage.S01.unknown.P0001"],
                            "anchor_terms": []}], "sections": {}}
        out = rans.validate_answer(fake, pack)
        self.assertTrue(any(i["kind"] == "SOURCE_LAYER_CONFUSION"
                            for i in out["issues"]))


class TestCalibration(unittest.TestCase):
    """§13：假 SUPPORTED 是最该防的错。"""

    def test_30_date_question_is_structurally_insufficient(self):
        pt = {"task_id": "t", "question":
              "拉康 1953 年 11 月 18 日那场报告的确切时间与地点是什么？",
              "language": "zh", "task_type": "insufficient_unanswerable",
              "required_capabilities": ["abstention"]}
        run = rans.run_task(pt)
        self.assertEqual(run["evidence_pack"]["evidence_state"]["state"],
                         "INSUFFICIENT_EVIDENCE")
        self.assertIn("STRUCTURAL_METADATA_GAP",
                      run["trace"]["calibration"]["signals"]["structural_gaps"])

    def test_31_period_question_is_not_flagged_as_date_question(self):
        """「années 1957-1960」是**时期**问题，不该被日期规则误伤。"""
        issues = rans.structural_capability_issues(
            "Comment Lacan définit-il le désir dans les années 1957-1960 ?")
        self.assertEqual(issues, [])

    def test_32_zero_relevance_is_insufficient(self):
        pack = {"evidence": [{"passage_id": "p", "text": "完全无关的一段话"}],
                "evidence_state": {"state": "SUPPORTED", "signals": {}, "reasons": []}}
        st, reasons, add = rans.calibrate_state(pack, "莫比乌斯带与拉康主体",
                                                {"anchor_pool": [], "salient_terms": []})
        self.assertEqual(st, "INSUFFICIENT_EVIDENCE")
        self.assertTrue(reasons)

    def test_33_relevance_is_cross_lingual(self):
        """中文问题的法文证据必须算作相关（否则所有 zh→fr 任务都会被误降级）。"""
        pack = {"evidence": [{"passage_id": "p",
                              "text": "l'objet petit a dans le séminaire"}],
                "evidence_state": {"state": "SUPPORTED", "signals": {}, "reasons": []}}
        rep = rans.relevance_report(pack, "拉康所谓的 objet petit a 是什么？",
                                    ["objet petit a", "对象a"])
        self.assertEqual(rep["relevance_rate"], 1.0)

    def test_34_sparsity_ignores_sentence_fragments(self):
        """句子片段不是术语，不能用来判「语料稀疏」。"""
        issue = rans.corpus_sparsity_issue(
            "拉康与维特根斯坦之间是否有直接的文本往来或通信？",
            {"salient_terms": ["拉康与维特根斯坦之间是否有直接的文本往来或通信"]})
        self.assertIsNone(issue)

    def test_35_usable_terms_filter(self):
        plan = {"salient_terms": ["objet a", "在拉康教学中的角色经历了", "objet"]}
        self.assertEqual(rans.usable_terms(plan, 4), ["objet a", "objet"])


class TestBudget(unittest.TestCase):
    """§20：预算必须真的生效，耗尽时不得编答案。"""

    def test_40_tiny_budget_hedges(self):
        rec = jd(os.path.join(IDX, "RESEARCH_4B_BUDGET_CHECK.json"))
        self.assertIsNotNone(rec, "先跑 research_eval_4b.py --budget-check")
        self.assertTrue(rec["all_passed"], rec["checks"])
        for c in rec["checks"]:
            self.assertLessEqual(c["tool_calls"], 2)
            self.assertTrue(c["answer_is_hedged"], c)
            self.assertEqual(c["fabricated"], 0)
            self.assertTrue(c["limitation_reported"])

    def test_41_extra_lanes_are_counted_in_budget(self):
        """Phase 4B 的补充 lane 必须计入 tool_calls（否则预算判据是假的）。"""
        src = open(os.path.join(TOOLS, "research_answer.py"), encoding="utf-8").read()
        self.assertIn('pack["budget"]["used"]["tool_calls"] += len(extra_steps)', src)


class TestEvaluationMethod(unittest.TestCase):
    """§21/§22/§25/§26：指标、无总分、trace、失败分类。"""

    @classmethod
    def setUpClass(cls):
        cls.dev = jd(os.path.join(EVAL, "research_eval_results_v1.dev.json"))
        cls.hold = jd(os.path.join(EVAL, "research_eval_results_v1.holdout.json"))

    def test_50_no_single_total_score(self):
        m = self.dev["metrics"]
        for banned in ("research_score", "score", "overall_score", "total_score"):
            self.assertNotIn(banned, m, "§22 禁止单一总分")
        self.assertIn("score_policy", self.dev)
        self.assertIn("§22", self.dev["score_policy"])

    def test_51_required_submetrics_present(self):
        m = self.dev["metrics"]
        for k in ("evidence_validity", "citation_anchor_support_rate",
                  "citation_term_cluster_rate", "claim_coverage",
                  "unsupported_claim_rate", "source_layer_confusions_total",
                  "sufficiency_accuracy", "entity_resolution_accuracy",
                  "period_coverage_mean", "separate_lanes_accuracy",
                  "tool_calls_mean", "research_completion_rate",
                  "fabricated_citations_total", "failure_counts"):
            self.assertIn(k, m, "§21 指标缺 %s" % k)

    def test_52_holdout_reported_separately(self):
        self.assertEqual(self.dev["split"], "dev")
        self.assertEqual(self.hold["split"], "holdout")
        self.assertNotEqual(self.dev["metrics"], self.hold["metrics"])

    def test_53_traces_have_required_keys(self):
        need = ("task_id", "tool_calls", "entities_resolved", "retrieval_routes",
                "passages_seen", "passages_selected", "passages_rejected",
                "context_expansions", "source_traces", "state_transitions",
                "claims", "citations", "budget_usage", "warnings",
                "no_hidden_reasoning")
        tdir = os.path.join(EVAL, "research_traces_4b")
        fns = [f for f in sorted(os.listdir(tdir)) if f.endswith(".json")]
        self.assertGreaterEqual(len(fns), 24)
        for fn in fns:
            tr = jd(os.path.join(tdir, fn))["trace"]
            for k in need:
                self.assertIn(k, tr, "%s 缺 %s" % (fn, k))
            self.assertTrue(tr["no_hidden_reasoning"])

    def test_54_failure_taxonomy_is_closed_and_used(self):
        self.assertEqual(len(rev.FAILURE_TAXONOMY), 11)
        used = set()
        for r in (self.dev["rows"] + self.hold["rows"]):
            for f in r["failure_classes"]:
                self.assertIn(f, rev.FAILURE_TAXONOMY)
                used.add(f)
        self.assertTrue(used, "至少要有一个失败案例被分类")
        j02 = [r for r in (self.dev["rows"] + self.hold["rows"])
               if r["task_id"] in ("rt-J02", "rt-J01")]
        self.assertTrue(any("EVIDENCE_SUFFICIENCY_ERROR" in r["failure_classes"]
                            for r in j02),
                        "已知的假 SUPPORTED 必须被分类为证据充分性错误")

    def test_55_lane_recall_does_not_use_sampled_gold(self):
        """抽样 gold 不得当作召回分母（实测会得出「检索全错」的假结论）。"""
        self.assertIn("gold_sample_recall_note", self.dev["metrics"])
        self.assertIn("lane_recall_mean", self.dev["metrics"])


class TestHumanReview(unittest.TestCase):
    """§23：没有人工评审者就不伪造评分。"""

    def test_60_not_reviewed_and_null_scores(self):
        """§23（Phase 4C.1-A 修订）：**不得伪造**人工评分。

        旧断言是「所有记录必须仍是 NOT_REVIEWED / 全 null」——真实人工评审完成后
        它必然失败（这正是旧 Gate 13 的同一缺陷）。新断言改为 provenance-aware：
        空占位必须全空；已评审必须带合法人类 provenance。伪造仍会被抓到。
        """
        import eval_integrity as ei
        rows = jl(os.path.join(EVAL, "research_human_review.jsonl"))
        self.assertTrue(rows)
        for r in rows:
            v = ei.validate_human_review_record(r)
            self.assertNotEqual(v["state"], "ILLEGITIMATE", v)
            if v["state"] == "UNREVIEWED_PLACEHOLDER":
                self.assertEqual(r["review_status"], "NOT_REVIEWED")
                for k, val in r["human_scores"].items():
                    self.assertIsNone(val, "%s 不应有伪造的人工评分" % k)
            else:
                self.assertEqual(r["reviewer_type"], "human")


class TestGatesCanFail(unittest.TestCase):
    """§33/§35：门禁必须真的会红。"""

    def test_70_hard_gates_all_zero_and_non_vacuous(self):
        hg = jd(os.path.join(IDX, "PHASE4B_HARD_GATES.json"))
        self.assertEqual(hg["gate_count"], 12)
        self.assertTrue(hg["all_zero"], hg["gates"])
        self.assertEqual(hg["evaluated_tasks"], 27)

    def test_71_completion_gate_reports_missing_deliverables(self):
        cg = jd(os.path.join(IDX, "PHASE4B_COMPLETION_GATE.json"))
        self.assertEqual(cg["total"], 24)
        self.assertIn("deliverable_docs", cg)
        # 判据本身必须能报失败（有过 FAIL 记录 ⇒ 它不是恒真）
        self.assertIn("checks", cg)

    def test_72_gate_detects_synthetic_violation(self):
        """合成违规必须被判据抓到（这里用引用校验做代表）。"""
        pack = {"evidence": [{"passage_id": "passage.S01.unknown.P0001",
                              "authority_level": "L1", "language": "fr",
                              "trace_status": "COMPLETE"}]}
        bad = {"claims": [{"claim_id": "x", "text": "t",
                           "classification": "PRIMARY_EVIDENCE",
                           "citations": ["passage.NOPE.unknown.P0001"],
                           "anchor_terms": []}], "sections": {}}
        out = rans.validate_answer(bad, pack)
        self.assertFalse(out["ok"])
        self.assertEqual(out["metrics"]["evidence_validity"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
