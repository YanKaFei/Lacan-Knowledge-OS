#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1b_contracts.py — Phase 4C.1-B 契约测试

三层：
    Unit          每类 contract 的字段与判定
    Negative      §19 的五类反例（缺 lane / 缺 relation / formalism / metadata / EXPECTED_ZERO）
    Regression    14 个已评审任务的 contract **编译**（§15/§21：只要求编译与检查正确，
                  不要求答案正确）
外加：
    NoTaskSpecificHack  静态扫描：规则不得出现 task_id 分支（§20）
    TraceSchemaV2       §18 新 trace 字段齐全 + Gate 19 能验证真实 v2 trace → trace.jsonl
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
EVAL = os.path.join(VAULT, "_data", "eval")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))

import research_contract as rc          # noqa: E402
import evidence_sufficiency_v21 as v21  # noqa: E402
import eval_integrity as ei             # noqa: E402


def jl(p):
    try:
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except Exception:
        return []


def jd(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def compile_for(task_type, question, *, language="zh", caps=(), executed=("resolve_entity",),
                entities=(), evidence=(), pack=None):
    """不跑真实检索，直接构造 plan/pack 编译契约 —— 便于构造**反例**。"""
    plan = {
        "planned_operations": ["resolve_entity", "find_concept_evidence",
                               "search_passages", "get_context"],
        "task_type": task_type, "salient_terms": [], "question_language": language,
        "entities": [{"term": t, "status": "RESOLVED", "entities": [e],
                      "context_required": False} for t, e in entities],
        "required_capabilities": list(caps), "anchor_pool": [],
    }
    pk = {"evidence": list(evidence), "resolution": {"entities": []},
          "coverage": {"evidence_n": len(evidence)}}
    if pack:
        pk.update(pack)
    return rc.compile_research_contract(
        {"task_id": "unit", "question": question, "language": language,
         "task_type": task_type, "required_capabilities": list(caps)},
        plan, pk, executed_tools=list(executed))


def ev(pid, text, **kw):
    d = {"passage_id": pid, "text": text, "authority_level": "L1",
         "seminar_id": "seminar." + pid.split(".")[1], "trace_status": "COMPLETE"}
    d.update(kw)
    return d


# ── Unit：十类契约 ────────────────────────────────────────────────────────
class TestContractTypes(unittest.TestCase):
    def test_01_ten_task_types_have_a_contract(self):
        need = ["concept_definition", "concept_relation", "diachronic_development",
                "seminar_specific", "case_research", "freud_to_lacan",
                "philosophy_to_lacan", "topology_matheme", "translation_terminology",
                "insufficient_unanswerable"]
        for tt in need:
            self.assertIn(tt, rc.CONTRACTS, tt)
        self.assertEqual(len(rc.CONTRACTS), 10)

    def test_02_definition_contract_shape(self):
        c = compile_for("concept_definition", "拉康所谓的 objet petit a 是什么？",
                        entities=[("objet petit a", "concept.objet-petit-a")],
                        evidence=[ev("passage.S10.unknown.P0001",
                                     "le objet petit a est le reste de l'opération.")],
                        executed=("resolve_entity", "find_concept_evidence", "get_context"))
        self.assertEqual(c["contract_type"], "DefinitionResearchContract")
        self.assertIn("find_concept_evidence", c["required_operations"])
        self.assertIn("concept.objet-petit-a", c["required_lanes"])
        self.assertEqual(c["missing_operations"], [])
        self.assertIn("schema_version", c)

    def test_03_comparison_requires_one_lane_per_entity(self):
        c = compile_for("concept_relation", "desire、demand、need 三者是什么关系？",
                        entities=[("desire", "concept.desir"),
                                  ("demand", "concept.demande"),
                                  ("need", "concept.besoin")],
                        evidence=[ev("passage.S05.unknown.P0001",
                                     "le désir et la demande se distinguent.")],
                        executed=("resolve_entity", "compare_concepts", "get_context"))
        self.assertEqual(c["contract_type"], "ComparisonResearchContract")
        self.assertEqual(len(c["required_lanes"]), 3)
        self.assertIn("concept.besoin", c["missing_lanes"])
        audit = rc.validate_contract(c)
        self.assertNotEqual(audit["state_ceiling"], "SUPPORTED")

    def test_04_diachronic_endpoints(self):
        c = compile_for("diachronic_development",
                        "jouissance 从 Seminar VII 到 Seminar XX 的历时变化？",
                        entities=[("jouissance", "concept.jouissance")],
                        executed=("resolve_entity", "trace_concept"))
        self.assertEqual(c["contract_type"], "DiachronicResearchContract")
        self.assertIn("seminar.S07", c["required_endpoints"])
        self.assertIn("seminar.S20", c["required_endpoints"])
        self.assertTrue(c["diachronic_relation_required"])

    def test_05_freud_contract_requires_source_layers(self):
        c = compile_for("freud_to_lacan",
                        "Comment Lacan réinterprète-t-il la pulsion (Trieb) freudienne ?",
                        language="fr", entities=[("pulsion", "concept.pulsion")])
        self.assertEqual(c["contract_type"], "FreudToLacanResearchContract")
        self.assertIn("freud_source", c["required_source_layers"])
        self.assertIn("freud_source", c["missing_source_layers"])

    def test_06_philosophy_contract_requires_source_layers(self):
        c = compile_for("philosophy_to_lacan",
                        "黑格尔的主人—奴隶辩证法如何进入拉康的欲望理论？",
                        entities=[("désir", "concept.desir")])
        self.assertIn("philosophy_source", c["required_source_layers"])

    def test_07_translation_contract_terms_and_zero(self):
        c = compile_for("translation_terminology",
                        "中文语料里 jouissance 有「快感」「原乐」等译法，这些译名差异意味着什么？")
        self.assertEqual(c["contract_type"], "TranslationTerminologyResearchContract")
        self.assertIn("terminology_lookup", c["required_operations"])
        terms = c["terminology"]["explicit_terms"]
        self.assertIn("快感", terms)
        self.assertIn("原乐", terms)
        # 语料有命中的译名 → 不是 EXPECTED_ZERO；0 命中的译名 → EXPECTED_ZERO 且 PASS
        hits = c["terminology"]["term_corpus_hits"]
        self.assertGreater(hits["快感"], 0)
        self.assertEqual(hits["原乐"], 0)
        z = {x["term"]: x for x in c["expected_zero_lanes"]}
        self.assertNotIn("快感", z)
        self.assertEqual(z["原乐"]["expectation"], "EXPECTED_ZERO")
        self.assertEqual(z["原乐"]["result"], "PASS")

    def test_08_topology_contract_formalism_lane(self):
        c = compile_for("topology_matheme", "Que exprime la formule $ ◊ a ?",
                        language="fr")
        self.assertEqual(c["contract_type"], "TopologyMathemeResearchContract")
        self.assertIn("formalism", c["required_lanes"])
        self.assertEqual(c["formalism"]["formalism_state"], "RETRIEVED_FORMALISM_MISSING")
        self.assertTrue(c["formalism"]["corpus_scan"]["executed"])

    def test_09_metadata_contract(self):
        c = compile_for("insufficient_unanswerable",
                        "拉康 1953 年 11 月 18 日那场报告的确切时间、地点与在场者是谁？")
        self.assertEqual(c["metadata"]["metadata_state"], "METADATA_UNAVAILABLE")
        self.assertIn("session_date（全库 unknown）", c["metadata"]["metadata_missing_fields"])

    def test_10_abstention_contract_fields(self):
        c = compile_for("insufficient_unanswerable", "拉康如何看待 fMRI 等神经影像研究？")
        self.assertEqual(c["contract_type"], "AbstentionResearchContract")
        for k in ("why_unanswerable", "missing_evidence_type",
                  "structural_or_retrieval", "next_required_source"):
            self.assertIn(k, c["abstention"])

    def test_11_seminar_and_period_constraints(self):
        c = compile_for("topology_matheme", "Seminar XIV 中 $ ◊ a 是什么？",
                        language="fr")
        kinds = {x["kind"] for x in c["required_constraints"]}
        self.assertIn("seminar", kinds)
        c2 = compile_for("concept_definition", "拉康在 1966-1967 年怎么谈 désir？")
        self.assertTrue(any(x["kind"] == "period"
                            for x in c2["required_constraints"]))


# ── Negative：§19 的五类反例 ──────────────────────────────────────────────
class TestNegativeRules(unittest.TestCase):
    def test_20_missing_lane_blocks_supported(self):
        c = compile_for("concept_relation", "desire 与 demand 什么关系？",
                        entities=[("desire", "concept.desir"), ("demand", "concept.demande")],
                        evidence=[ev("passage.S05.unknown.P0001", "le désir ...")],
                        executed=("resolve_entity", "compare_concepts", "get_context"))
        audit = rc.validate_contract(c)
        self.assertIn("MISSING_REQUIRED_LANE",
                      [v["code"] for v in audit["violated_rules"]])
        self.assertNotEqual(audit["state_ceiling"], "SUPPORTED")

    def test_21_missing_operation_blocks_supported(self):
        c = compile_for("translation_terminology", "「快感」这个译名在语料里如何？",
                        executed=("resolve_entity",))
        audit = rc.validate_contract(c)
        self.assertIn("MISSING_REQUIRED_OPERATION",
                      [v["code"] for v in audit["violated_rules"]])

    def test_22_relation_required_but_absent(self):
        c = compile_for("philosophy_to_lacan", "黑格尔如何进入拉康的欲望理论？",
                        entities=[("désir", "concept.desir")],
                        evidence=[ev("passage.S05.unknown.P0001", "le désir est ...")],
                        executed=("resolve_entity", "compare_concepts", "get_context"))
        self.assertTrue(c["relation_evidence_required"])
        self.assertEqual(c["relation_evidence_n"], 0)
        codes = [v["code"] for v in rc.validate_contract(c)["violated_rules"]]
        self.assertIn("RELATION_EVIDENCE_MISSING", codes)

    def test_23_diachronic_endpoint_missing_blocks(self):
        c = compile_for("diachronic_development", "Seminar VII 到 Seminar XX 的 jouissance",
                        entities=[("jouissance", "concept.jouissance")],
                        evidence=[ev("passage.S20.unknown.P0001", "la jouissance ...")],
                        executed=("resolve_entity", "trace_concept", "get_context"))
        audit = rc.validate_contract(c)
        self.assertIn("DIACHRONIC_ENDPOINT_MISSING",
                      [v["code"] for v in audit["violated_rules"]])
        self.assertEqual(audit["state_ceiling"], "INSUFFICIENT_EVIDENCE")

    def test_24_formalism_retrieval_miss_is_not_structural(self):
        # 给一条 substantive 证据，确保「证据不足」不是本次判定的原因，
        # 从而单独检验 formalism 的两层区分。
        c = compile_for("topology_matheme", "Que exprime la formule $ ◊ a ?",
                        language="fr",
                        entities=[("fantasme", "concept.fantasme")],
                        evidence=[ev("passage.S14.unknown.P0066",
                                     "le poinçon est divisé par la barre verticale, "
                                     "c'est le sujet barré à ce rapport de si et "
                                     "seulement si avec le petit(a).")],
                        executed=("resolve_entity", "find_concept_evidence",
                                  "get_context", "search_passages"))
        audit = rc.validate_contract(c)
        codes = [v["code"] for v in audit["violated_rules"]]
        self.assertIn("RETRIEVED_FORMALISM_MISSING", codes)
        self.assertNotIn("CORPUS_FORMALISM_MISSING", codes)
        # 语料里确实有 ◊（whole-corpus 扫描），所以这不是结构性不可答
        self.assertGreater((c["formalism"]["corpus_symbol_counts"] or {}).get("◊", 0), 0)
        self.assertNotEqual(audit["state_ceiling"], "INSUFFICIENT_EVIDENCE")

    def test_25_metadata_unavailable_is_structural(self):
        c = compile_for("insufficient_unanswerable", "1953 年 11 月 18 日的确切日期是哪天？")
        audit = rc.validate_contract(c)
        self.assertIn("METADATA_UNAVAILABLE",
                      [v["code"] for v in audit["violated_rules"]])
        self.assertEqual(audit["state_ceiling"], "INSUFFICIENT_EVIDENCE")

    def test_26_expected_zero_lane_passes(self):
        c = compile_for("translation_terminology", "「原乐」这个译名在语料里如何？")
        z = [x for x in c["expected_zero_lanes"] if x["term"] == "原乐"]
        self.assertTrue(z, c["terminology"])
        self.assertEqual(z[0]["result"], "PASS")
        self.assertEqual(z[0]["observed_hits"], 0)

    def test_27_no_substantive_evidence_blocks(self):
        c = compile_for("concept_definition", "objet petit a 是什么？",
                        entities=[("objet petit a", "concept.objet-petit-a")],
                        evidence=[ev("passage.S01.unknown.L03.P0002", "拉康")])
        audit = rc.validate_contract(c)
        self.assertIn("NO_SUBSTANTIVE_EVIDENCE",
                      [v["code"] for v in audit["violated_rules"]])

    def test_28_expected_zero_violation_is_recorded(self):
        c = compile_for("translation_terminology", "「原乐」这个译名在语料里如何？")
        c["expected_zero_lanes"][0]["result"] = "FAIL"
        audit = rc.validate_contract(c)
        self.assertIn("EXPECTED_ZERO_LANE_VIOLATED",
                      [v["code"] for v in audit["violated_rules"]])


# ── Sufficiency v2.1 ─────────────────────────────────────────────────────
class TestSufficiencyV21(unittest.TestCase):
    def _v2(self, state="SUPPORTED"):
        return {"engine": "evidence_sufficiency/v2", "final_state": state,
                "reasons": ["主题词在知识库里没有 entity（absence profile 的一部分）。",
                            "证据量、多分量一致性、session 多样性、约束满足四项均达标。"],
                "signals": {"component_agreement": None,
                            "constraint_satisfaction": None,
                            "independent_families_executed": [],
                            "passage_count": 10, "distinct_session_count": 3}}

    def test_30_template_reason_is_dropped(self):
        r = v21.sanitize_reasons(self._v2()["reasons"], self._v2()["signals"])
        self.assertTrue(any("四项均达标" in d for d in r["dropped"]))
        self.assertFalse(any("四项均达标" in x for x in r["reasons"]))
        self.assertIn("不适用", r["real_signal_line"])

    def test_31_final_state_is_capped_by_contract(self):
        c = compile_for("concept_relation", "desire 与 demand 什么关系？",
                        entities=[("desire", "concept.desir"),
                                  ("demand", "concept.demande")],
                        evidence=[ev("passage.S05.unknown.P0001", "le désir ...")],
                        executed=("resolve_entity", "compare_concepts", "get_context"))
        out = v21.evaluate_v21(self._v2("SUPPORTED"), c)
        self.assertNotEqual(out["final_state"], "SUPPORTED")
        self.assertEqual(out["v2_final_state"], "SUPPORTED")
        self.assertIsNotNone(out["transition"])
        for k in ("from", "to", "reason_code", "trigger", "evidence", "contract_check"):
            self.assertIn(k, out["transition"])

    def test_32_supported_requires_complete_contract(self):
        c = compile_for("concept_definition", "objet petit a 是什么？",
                        entities=[("objet petit a", "concept.objet-petit-a")],
                        evidence=[ev("passage.S10.unknown.P0001",
                                     "le objet petit a est le reste.")],
                        executed=("resolve_entity", "find_concept_evidence", "get_context"))
        out = v21.evaluate_v21(self._v2("SUPPORTED"), c)
        self.assertEqual(out["completion_state"], "COMPLETE")
        self.assertEqual(out["final_state"], "SUPPORTED")
        self.assertIsNone(out["transition"])

    def test_33_layers_present(self):
        c = compile_for("translation_terminology", "「快感」译名如何？")
        out = v21.evaluate_v21(self._v2("SUPPORTED"), c)
        for k in ("task_completion", "operation_completion", "lane_completion",
                  "constraint_completion", "relation_completion",
                  "source_layer_completion", "formalism_completion",
                  "metadata_completion", "evidence_usability"):
            self.assertIn(k, out["layers"], k)


# ── §20 禁止 task-specific hack ──────────────────────────────────────────
class TestNoTaskSpecificHack(unittest.TestCase):
    def test_40_no_task_id_branches_in_contract_code(self):
        for fn in ("research_contract.py", "evidence_sufficiency_v21.py"):
            src = open(os.path.join(TOOLS, fn), encoding="utf-8").read()
            bad = re.findall(r"rt-[A-Z]\d{2}", src)
            self.assertEqual(bad, [], "%s 出现了 task_id 分支：%s" % (fn, bad))

    def test_41_no_task_id_branches_in_pipeline_contract_wiring(self):
        src = open(os.path.join(TOOLS, "research_answer.py"), encoding="utf-8").read()
        # 允许出现在注释/文档里，但不允许出现在判定条件里
        for m in re.finditer(r"rt-[A-Z]\d{2}", src):
            seg = src[max(0, m.start() - 200):m.start() + 200]
            self.assertIsNone(re.search(r"(if|elif|and|or)\s+[^\n]*rt-[A-Z]\d{2}", seg),
                              "research_answer.py 判定条件里出现 task_id：%s" % seg[:120])

    def test_42_gate17_still_zero(self):
        d = jd(os.path.join(VAULT, "_data", "index", "PHASE4C_HARD_GATES.json"), {})
        if d:
            self.assertEqual(d["new_gates"]["17"]["violations"], 0)


# ── Regression：14 个已评审任务的 contract 编译 ──────────────────────────
class TestRegressionCompilation(unittest.TestCase):
    """§15/§21：只要求 contract 编译与检查正确，不要求答案正确。"""

    @classmethod
    def setUpClass(cls):
        cls.spec = {r["task_id"]: r for r in
                    jl(os.path.join(EVAL, "scholarly_regression_v1.jsonl"))}
        cls.tasks = {r["task_id"]: r for r in
                     jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))}

    def test_50_fourteen_tasks_compile(self):
        from research_answer import make_plan
        self.assertEqual(len(self.spec), 14)
        for tid, t in sorted(self.tasks.items()):
            if tid not in self.spec:
                continue
            with self.subTest(task=tid):
                pub = {k: t[k] for k in ("task_id", "question", "language",
                                         "task_type", "required_capabilities", "split")}
                plan = make_plan(pub)
                c = rc.compile_research_contract(pub, plan, {"evidence": []})
                self.assertEqual(c["task_id"], tid)
                self.assertTrue(c["contract_type"].endswith("Contract"))
                audit = rc.validate_contract(c)
                self.assertIn(audit["state_ceiling"],
                              ("SUPPORTED", "PARTIALLY_SUPPORTED",
                               "INSUFFICIENT_EVIDENCE"))

    def test_51_specific_regression_contracts_hold(self):
        """把 Phase 4C 人工评审直接点名的几条要求，逐条钉成断言。"""
        from research_answer import make_plan
        checks = {
            # B01：三条 lane
            "rt-B01": lambda c: len([l for l in c["required_lanes"]]) >= 3,
            # C03：两个端点
            "rt-C03": lambda c: set(c.get("required_endpoints") or []) >=
                                {"seminar.S07", "seminar.S20"},
            # F01：需要 Freud 来源层
            "rt-F01": lambda c: "freud_source" in c["required_source_layers"],
            # G02：需要 sujet / moi 进入契约（实体层）
            "rt-G02": lambda c: True,      # 实体由 plan 解析决定，见 test_52
            # H02：formalism lane（S14 来自 gold，**不注入** agent 可见的契约；
            #      它作为 evaluation-side 期望留在 regression spec 里，见 test_53）
            "rt-H02": lambda c: "formalism" in c["required_lanes"],
            # I03：三个译名 + 原乐 EXPECTED_ZERO
            "rt-I03": lambda c: ({"快感", "享受", "原乐"} <=
                                 set(c["terminology"]["explicit_terms"])
                                 and any(z["term"] == "原乐"
                                         for z in c["expected_zero_lanes"])),
            # J03：metadata 契约
            "rt-J03": lambda c: c["metadata"]["metadata_state"] == "METADATA_UNAVAILABLE",
            # G01：philosophy 来源层 + relation
            "rt-G01": lambda c: ("philosophy_source" in c["required_source_layers"]
                                 and c["relation_evidence_required"]),
        }
        for tid, pred in sorted(checks.items()):
            t = self.tasks[tid]
            pub = {k: t[k] for k in ("task_id", "question", "language",
                                     "task_type", "required_capabilities", "split")}
            c = rc.compile_research_contract(pub, make_plan(pub), {"evidence": []})
            with self.subTest(task=tid):
                self.assertTrue(pred(c), "%s 契约不满足：%s" % (tid, c["contract_type"]))

    def test_53_gold_side_constraints_stay_evaluation_side(self):
        """gold 的 expected_seminars 不得注入 agent 可见的契约（§6 gold 隔离）。"""
        from research_answer import make_plan
        t = self.tasks["rt-H02"]
        pub = {k: t[k] for k in ("task_id", "question", "language", "task_type",
                                 "required_capabilities", "split")}
        c = rc.compile_research_contract(pub, make_plan(pub), {"evidence": []})
        self.assertEqual([x for x in c["required_constraints"] if x["kind"] == "seminar"],
                         [], "问题文本没点名研讨班时不得凭空加 seminar 约束")
        # 但 regression spec 仍然保留 S14 作为评估侧期望
        spec = self.spec["rt-H02"]
        self.assertIn("seminar.S14", spec["seminar_constraints"])

    def test_52_entity_dependent_contracts_are_honest(self):
        """G02 的 sujet/moi 取决于实体解析；契约必须如实反映解析结果。"""
        from research_answer import make_plan
        t = self.tasks["rt-G02"]
        pub = {k: t[k] for k in ("task_id", "question", "language", "task_type",
                                 "required_capabilities", "split")}
        c = rc.compile_research_contract(pub, make_plan(pub), {"evidence": []})
        resolved = set(c["required_entities"])
        self.assertIsInstance(resolved, set)
        # 无论解析成什么，契约都必须把「已解析实体」逐个列成 lane（不得只跑一条）
        self.assertEqual(set(c["required_lanes"]), resolved | set(
            l for l in c["required_lanes"] if l.startswith("seminar.")))


# ── §18 trace schema v2 ─────────────────────────────────────────────────
class TestTraceSchemaV2(unittest.TestCase):
    V2_FIELDS = ("research_contract", "evaluation_run_manifest", "required_operations",
                 "completed_operations", "missing_operations", "required_lanes",
                 "completed_lanes", "missing_lanes", "required_constraints",
                 "satisfied_constraints", "failed_constraints", "relation_evidence",
                 "source_layer_completion", "formalism_completion",
                 "metadata_completion", "evidence_usability", "sufficiency_v21",
                 "final_state", "final_state_reason_codes", "state_transition_reason")

    def _traces(self):
        d = os.path.join(EVAL, "research_traces_4c1b")
        if not os.path.isdir(d):
            self.skipTest("先跑 run_diagnostic_4c1b.py")
        out = []
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                out.append((fn[:-5], jd(os.path.join(d, fn))))
        return out

    def test_60_v2_traces_have_all_fields(self):
        traces = self._traces()
        self.assertTrue(traces, "诊断目录为空")
        for tid, run in traces:
            tr = run["trace"]
            with self.subTest(task=tid):
                self.assertEqual(tr["schema_version"], "research-trace/v2")
                for f in self.V2_FIELDS:
                    self.assertIn(f, tr, "%s 缺 %s" % (tid, f))
                self.assertEqual(run["schema_version"], "research-run-4c1b/v1")
                self.assertEqual(tr.get("marker"), "DIAGNOSTIC")

    def test_61_gate19_validates_real_v2_traces(self):
        """Gate 19 不得只在『0 条 v2 trace』上空过。"""
        d = jd(os.path.join(EVAL, "trace_integrity_baseline_v1.json"), {})
        self.assertGreaterEqual(d.get("traces_scanned", 0), 1)
        # 至少有一条 v2 trace 真的被扫到（目录里存在）
        traces = self._traces()
        self.assertTrue(traces)
        violations = []
        for tid, run in traces:
            for f in ei.trace_integrity_findings(run):
                if f["severity"] == "VIOLATION":
                    violations.append((tid, f["code"]))
        self.assertEqual(violations, [], "v2 trace 有契约违规：%s" % violations[:5])

    def test_63_contracts_match_schema(self):
        """每份真实契约都必须符合 `research_contract.schema.json`。"""
        import jsonschema
        schema = jd(os.path.join(EVAL, "research_contract.schema.json"))
        self.assertTrue(schema, "缺 research_contract.schema.json")
        jsonschema.Draft7Validator.check_schema(schema)
        v = jsonschema.Draft7Validator(schema)
        traces = self._traces()
        self.assertTrue(traces)
        for tid, run in traces:
            with self.subTest(task=tid):
                v.validate(run["trace"]["research_contract"])

    def test_64_diagnostic_results_are_marked_and_versioned(self):
        d = jd(os.path.join(EVAL, "research_eval_results.4c1b.json"))
        self.assertIsNotNone(d, "缺 diagnostic 结果")
        self.assertEqual(d["marker"], "DIAGNOSTIC")
        self.assertEqual(d["schema_version"], "research-eval-4c1b/v1")
        self.assertEqual(len(d["rows"]), 27)
        for r in d["rows"]:
            self.assertEqual(r["marker"], "DIAGNOSTIC")
            # v2.1 的 final state 不得高于契约上限
            rank = {"INSUFFICIENT_EVIDENCE": 0, "PARTIALLY_SUPPORTED": 1,
                    "SUPPORTED": 2}
            self.assertLessEqual(rank[r["state"]], rank[r["state_ceiling"]])

    def test_62_contract_present_and_consistent(self):
        for tid, run in self._traces():
            tr = run["trace"]
            c = tr["research_contract"]
            with self.subTest(task=tid):
                self.assertEqual(c["schema_version"], "research-contract/v1")
                self.assertEqual(tr["required_lanes"], c["required_lanes"])
                self.assertEqual(tr["missing_lanes"], c["missing_lanes"])
                self.assertEqual(tr["final_state"],
                                 run["evidence_pack"]["evidence_state"]["final_state"])
                if tr["final_state"] != tr["sufficiency_v21"]["v2_final_state"]:
                    self.assertTrue(tr["state_transition_reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
