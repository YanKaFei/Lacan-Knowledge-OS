#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1d_entailment.py — Phase 4C.1-D：Claim–Evidence Entailment 测试

六组：
    Atomization     §5/§6：复合 claim 必须拆成原子
    Deterministic   §10–§19：确定性层能独立判定的情形（含离线策略）
    Aggregation     §14/§22：claim 级聚合、disagreement 取保守值
    Repair          §23/§24：NARROW_CLAIM / downgrade / 次数上限
    Rejection       §25/§26：reject 不得进最终答案；答案只能由 validated set 渲染
    Gate21          §36：10 条检查都能抓到对应的错
外加：Calibration（§43）、Adversarial（§33–§35、§42）、RepoSafety。
真实 LLM 集成测试在 test_phase4c1d_llm_integration.py（provider 缺失即 SKIP）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
EVAL = os.path.join(VAULT, "_data", "eval")
CALIB = os.path.join(EVAL, "claim_entailment_calibration_v1.jsonl")
AGG = os.path.join(EVAL, "research_synthesis_results.4c1d.json")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))

import synthesis_claims as scl              # noqa: E402
import synthesis_entailment as se           # noqa: E402
import synthesis_validation as sv           # noqa: E402
import synthesis_adversarial as adv         # noqa: E402
import eval_integrity as ei                 # noqa: E402
import run_synthesis_4c1d as rd             # noqa: E402


def ev(pid="p1", text="le désir est la métonymie du manque",
       cls="SUBSTANTIVE_TEXT", elig="ELIGIBLE", layer="L1_TRANSCRIPTION",
       perms=None, **kw):
    d = {"passage_id": pid, "text": text, "usability_class": cls,
         "citation_eligibility": elig,
         "claim_permissions": perms or (["substantive", "contextual", "limitation"]
                                        if elig != "INELIGIBLE" else ["limitation"]),
         "source_layer": layer, "language": "fr", "authority_level": "L1",
         "selection_reason": ["test"]}
    d.update(kw)
    return d


def contract(evidence=None, relation=None, terminology=None, formalism=None):
    return {"task_id": "t", "task_type": "concept_definition", "status": "READY",
            "answer_permission": "FULL_SYNTHESIS",
            "usable_evidence": evidence or [ev()],
            "relation_evidence": relation or {"required": False, "n": 0, "ids": [],
                                              "strength": "R0_NONE"},
            "terminology_evidence": terminology or {},
            "formalism_evidence": formalism or {},
            "metadata_evidence": {}, "source_layers": {},
            "claim_permissions": {}, "citation_policy": {},
            "abstention_requirements": {}, "warnings": []}


# ══════════════════════════════════════════════════════════════ Atomization
class TestAtomization(unittest.TestCase):
    def test_01_compound_claim_is_split(self):
        c = {"claim_id": "c1", "claim_type": "DEFINITION",
             "claim_text": "目光在视觉场域中是对象 a，并且这一关系结构决定主体的可见性。",
             "evidence_ids": ["p1"]}
        atoms = se.atomize_claim(c, contract())
        self.assertGreaterEqual(len(atoms), 2)
        for a in atoms:
            for f in ("atom_id", "parent_claim_id", "atom_text", "claim_type",
                      "epistemic_status", "evidence_ids", "scope",
                      "source_attribution", "entailment_required"):
                self.assertIn(f, a)
            self.assertTrue(a["atom_text"])

    def test_02_single_clause_stays_single(self):
        c = {"claim_id": "c1", "claim_type": "DEFINITION", "claim_text": "这是一句话",
             "evidence_ids": ["p1"]}
        self.assertEqual(len(se.atomize_claim(c, contract())), 1)

    def test_03_absence_claim_not_required(self):
        c = {"claim_id": "c1", "claim_type": "CORPUS_ABSENCE",
             "claim_text": "本语料没有该词", "evidence_ids": []}
        self.assertFalse(se.atomize_claim(c, contract())[0]["entailment_required"])


# ══════════════════════════════════════════════════════════════ Deterministic
class TestDeterministic(unittest.TestCase):
    def _atom(self, text, ids=("p1",), ctype="DEFINITION", **kw):
        d = {"atom_id": "a1", "atom_text": text, "claim_type": ctype,
             "evidence_ids": list(ids)}
        d.update(kw)
        return d

    def test_10_no_evidence_is_not_entailed(self):
        v = se.validate_atom(self._atom("x", ids=()), contract())
        self.assertEqual(v["status"], "NOT_ENTAILED")

    def test_11_scan_absence_is_entailed(self):
        v = se.validate_atom(self._atom("本语料零见证（全库 0 段）", ids=(),
                                        ctype="CORPUS_ABSENCE",
                                        corpus_scan_ref={"scope": "whole_corpus"}),
                             contract())
        self.assertEqual(v["status"], "ENTAILED")
        self.assertEqual(v["strength"], "E4_DIRECT")

    def test_12_metadata_scan_is_entailed(self):
        v = se.validate_atom(self._atom("全库 session_date 不可用", ids=(),
                                        ctype="METADATA",
                                        corpus_scan_ref={"scope": "whole_corpus"}),
                             contract())
        self.assertEqual(v["status"], "ENTAILED")

    def test_13_ineligible_evidence_is_source_role_mismatch(self):
        c = contract([ev(cls="MEDIA_ONLY", elig="INELIGIBLE")])
        v = se.validate_atom(self._atom("如图所示，结构已经给出", ctype="DEFINITION"), c)
        self.assertEqual(v["status"], "SOURCE_ROLE_MISMATCH")

    def test_14_empty_passage_is_not_entailed(self):
        """空段落无法支撑 substantive 断言：安全兜底把它判为 NOT_ENTAILED。"""
        c = contract([ev(text="")])
        v = se.validate_atom(self._atom("某断言", ctype="DEFINITION"), c)
        self.assertIn(v["status"], ("NOT_ENTAILED", "INSUFFICIENT_CONTEXT"))

    def test_15_unknown_passage_is_not_entailed(self):
        v = se.validate_atom(self._atom("x", ids=("passage.NOPE.P1",)), contract())
        self.assertEqual(v["status"], "NOT_ENTAILED")

    def test_16_quote_not_found_is_not_entailed(self):
        v = se.validate_atom(self._atom(
            "某断言",
            quotation={"kind": "CORPUS_QUOTE", "passage_id": "p1",
                       "exact_span": "这段文字根本不在段落里",
                       "language": "fr", "source_layer": "L1_TRANSCRIPTION"}),
            contract())
        self.assertEqual(v["status"], "NOT_ENTAILED")
        self.assertEqual(v["deterministic_signal"]["signal"], "QUOTE_NOT_FOUND")

    def test_17_source_language_mismatch(self):
        c = contract([ev(elig="QUALIFIED", layer="L2_RECOVERED")])
        v = se.validate_atom(self._atom("拉康法文原文明确写道：X"), c)
        self.assertEqual(v["status"], "SOURCE_ROLE_MISMATCH")

    def test_18_exact_containment_is_entailed(self):
        c = contract([ev(text="le poinçon : (S ◊ a) du désir")])
        v = se.validate_atom(self._atom("在该段（L1 课堂转写）中，拉康：le poinçon : (S ◊ a) du désir"),
                             c)
        self.assertEqual(v["status"], "ENTAILED")
        self.assertEqual(v["strength"], "E4_DIRECT")

    def test_19_relation_r1_cannot_support_relation(self):
        c = contract(relation={"required": True, "n": 0, "ids": [],
                               "strength": "R1_COOCCURRENCE"})
        v = se.validate_atom(self._atom("两者之间存在严格的因果决定关系", ctype="RELATION"), c)
        self.assertEqual(v["status"], "NOT_ENTAILED")

    def test_20_relation_r2_is_qualified(self):
        c = contract(relation={"required": True, "n": 1, "ids": ["p1"],
                               "strength": "R2_CONTEXTUAL_RELATION"})
        v = se.validate_atom(self._atom("两者在同一段中共现，构成语境关系", ctype="RELATION"), c)
        self.assertEqual(v["status"], "PARTIALLY_ENTAILED")
        self.assertEqual(v["strength"], "E2_CONTEXTUAL")

    def test_21_terminology_overclaim_is_contradicted(self):
        c = contract(terminology={"原乐": {
            "mapping_completion": "MAPPING_COMPLETE",
            "attestation_completion": "ZERO_ATTESTATION", "corpus_hits": 0,
            "evidence_ids": []}})
        v = se.validate_atom(self._atom("原乐是本语料中 jouissance 的常用译法",
                                        ctype="TERMINOLOGY"), c)
        self.assertEqual(v["status"], "CONTRADICTED")

    def test_22_terminology_mapping_is_entailed(self):
        c = contract(terminology={"快感": {
            "mapping_completion": "MAPPING_COMPLETE",
            "attestation_completion": "ATTESTED", "corpus_hits": 85,
            "evidence_ids": ["p1"]}})
        v = se.validate_atom(self._atom("快感的译名映射为 enjoyment", ctype="TERMINOLOGY"), c)
        self.assertEqual(v["status"], "ENTAILED")

    def test_23_formalism_hit_is_entailed(self):
        c = contract([ev(text="la formule (S ◊ a) du fantasme")],
                     formalism={"hits": [{"passage_id": "p1",
                                          "raw_matched_form": "(S ◊ a)",
                                          "normalized_matched_form": "S◊a"}],
                                "formalism_required": True})
        v = se.validate_atom(self._atom("语料中的形式表达式为 `(S ◊ a)`（passage p1）",
                                        ctype="FORMALISM"), c)
        self.assertEqual(v["status"], "ENTAILED")

    def test_24_offline_policy_no_overlap(self):
        """离线（无 judge）时：与证据无实质重合的 substantive 断言必须 NOT_ENTAILED。"""
        c = contract([ev(text="un texte complètement différent sur la topologie")])
        v = se.validate_atom(self._atom("镜像阶段与三界拓扑之间存在因果推导关系"), c)
        self.assertEqual(v["status"], "NOT_ENTAILED")
        self.assertEqual(v["deterministic_signal"]["signal"], "NO_SUBSTANTIVE_OVERLAP")


# ══════════════════════════════════════════════════════════════ Aggregation
class TestAggregation(unittest.TestCase):
    def test_30_all_atoms_entailed(self):
        txt = ("le désir est la métonymie du manque；"
               "la demande est autre chose que le besoin")
        c = contract([ev(text=txt)])
        claim = {"claim_id": "c1", "claim_type": "DEFINITION", "claim_text": txt,
                 "evidence_ids": ["p1"]}
        v = se.validate_claim(claim, c)
        self.assertEqual(v["status"], "ENTAILED")

    def test_31_mixed_is_partial(self):
        c = contract([ev(text="le désir est la métonymie du manque")])
        claim = {"claim_id": "c1", "claim_type": "DEFINITION",
                 "claim_text": "在该段中，拉康：le désir est la métonymie du manque；"
                               "而这一结构在全部时期始终有效",
                 "evidence_ids": ["p1"]}
        v = se.validate_claim(claim, c)
        self.assertEqual(v["status"], "PARTIALLY_ENTAILED")
        self.assertFalse(v["reject"], "PARTIALLY 应触发 repair，而不是直接 reject")

    def test_32_contradiction_wins(self):
        c = contract([ev()], terminology={"原乐": {
            "mapping_completion": "MAPPING_COMPLETE",
            "attestation_completion": "ZERO_ATTESTATION", "corpus_hits": 0,
            "evidence_ids": []}})
        claim = {"claim_id": "c1", "claim_type": "TERMINOLOGY",
                 "claim_text": "原乐是常用译法；并且映射不存在",
                 "evidence_ids": ["p1"]}
        v = se.validate_claim(claim, c)
        self.assertIn(v["status"], ("CONTRADICTED", "NOT_ENTAILED"))

    def test_33_judge_cannot_pass_without_overlap(self):
        """judge 说 ENTAILED，但证据与断言零重合 → 冲突 → 取保守值。"""
        jp = adv.ScriptedJudgeProvider({"a1": {"status": "ENTAILED",
                                               "strength": "E4_DIRECT",
                                               "reason": "scripted"}})
        judge = se.EntailmentJudge(provider=jp, enabled=True)
        c = contract([ev(text="texte totalement différent")])
        v = se.validate_atom({"atom_id": "a1", "atom_text": "镜像阶段导致拓扑结构",
                              "claim_type": "DEFINITION", "evidence_ids": ["p1"]},
                             c, judge=judge)
        self.assertEqual(v["status"], "NOT_ENTAILED")
        self.assertTrue(v["disagreement"])

    def test_34_judge_insufficient_without_overlap_is_not_entailed(self):
        jp = adv.ScriptedJudgeProvider({"a1": {"status": "INSUFFICIENT_CONTEXT",
                                               "reason": "scripted"}})
        judge = se.EntailmentJudge(provider=jp, enabled=True)
        c = contract([ev(text="texte totalement différent")])
        v = se.validate_atom({"atom_id": "a1", "atom_text": "某无关断言",
                              "claim_type": "DEFINITION", "evidence_ids": ["p1"]},
                             c, judge=judge)
        self.assertEqual(v["status"], "NOT_ENTAILED")


# ══════════════════════════════════════════════════════════════ Repair / Reject
class TestRepairAndReject(unittest.TestCase):
    def test_40_partial_is_narrowed(self):
        c = contract([ev(text="le désir est la métonymie du manque")])
        claims = [scl.make_claim(
            "c1", "DEFINITION",
            "le désir est la métonymie du manque；并且这一结论在全部临床结构中始终有效。",
            "DIRECTLY_SUPPORTED", ["p1"])]
        res = sv.validate_and_repair(claims, c)
        self.assertEqual(len(res["repaired"]), 1)
        self.assertTrue(res["validated"])
        repaired = res["validated"][0]
        self.assertIn("repaired_from", repaired)
        self.assertNotIn("始终有效", repaired["claim_text"])
        self.assertEqual(repaired["epistemic_status"], "QUALIFIED_INFERENCE")

    def test_41_repair_is_bounded(self):
        c = contract([ev(text="A")])
        claims = [scl.make_claim("c1", "DEFINITION", "完全无关的断言内容。" * 3,
                                 "DIRECTLY_SUPPORTED", ["p1"])]
        res = sv.validate_and_repair(claims, c, max_attempts=2)
        self.assertTrue(res["rejected"] or res["validated"])
        if res["rejected"]:
            self.assertLessEqual(res["results"][0]["attempts"], 2)

    def test_42_rejection_recorded(self):
        c = contract([ev(text="texte différent")])
        claims = [scl.make_claim("c1", "DEFINITION", "镜像阶段与三界拓扑存在因果推导关系。",
                                 "DIRECTLY_SUPPORTED", ["p1"])]
        res = sv.validate_and_repair(claims, c)
        self.assertEqual(len(res["rejected"]), 1)
        self.assertEqual(res["validated"], [])

    def test_43_final_answer_only_from_validated(self):
        c = contract([ev(text="le désir est la métonymie du manque")])
        draft = {"claims": [
            scl.make_claim("c1", "DEFINITION",
                           "在该段（L1 课堂转写）中，拉康：le désir est la métonymie du manque",
                           "DIRECTLY_SUPPORTED", ["p1"]),
            scl.make_claim("c2", "DEFINITION", "镜像阶段导致三界拓扑。",
                           "DIRECTLY_SUPPORTED", ["p1"])],
            "sections": {"brief_answer": "LLM 的原始散文不应进入最终答案"},
            "abstention": None}
        pipe = sv.run_validation_pipeline(None, c, draft)
        ids = {c_["claim_id"] for c_ in pipe["answer"]["claims"]}
        self.assertIn("c1", ids)
        self.assertNotIn("c2", ids)
        self.assertNotIn("LLM 的原始散文", json.dumps(pipe["answer"], ensure_ascii=False))

    def test_44_validation_failed_when_nothing_valid(self):
        c = contract([ev(text="texte différent")])
        draft = {"claims": [scl.make_claim("c1", "DEFINITION", "完全无关断言。",
                                           "DIRECTLY_SUPPORTED", ["p1"])],
                 "sections": {}, "abstention": None}
        pipe = sv.run_validation_pipeline(None, c, draft)
        self.assertEqual(pipe["answer_state"], "VALIDATION_FAILED")

    def test_45_quote_sanitized_not_silently_kept(self):
        c = contract([ev(text="le désir est la métonymie du manque")])
        bad = scl.make_claim("c1", "DEFINITION", "某断言",
                             "DIRECTLY_SUPPORTED", ["p1"],
                             quotation={"kind": "CORPUS_QUOTE", "passage_id": "p1",
                                        "exact_span": "不存在的引文",
                                        "language": "fr",
                                        "source_layer": "L1_TRANSCRIPTION"})
        kept, dropped, fixes = se.sanitize_claims([bad], c)
        self.assertEqual(len(fixes), 1)
        self.assertIsNone(kept[0]["quotation"])
        self.assertEqual(kept[0]["quotation_dropped"], "QUOTE_NOT_FOUND")


# ══════════════════════════════════════════════════════════════ Gate 21
class TestGate21(unittest.TestCase):
    def _row(self, **kw):
        base = {"task_id": "t", "answer_permission": "FULL_SYNTHESIS",
                "input_contract": {"usable_evidence": [ev()]},
                "validated_claims": [], "answer": {"claims": [], "answer_state":
                                                   "VALIDATED"},
                "entailment": {"results": [], "rejected": []}}
        base.update(kw)
        return base

    def test_50_substantive_without_evidence(self):
        row = self._row(answer={"claims": [{"claim_id": "c1", "claim_type":
                                            "DEFINITION", "evidence_ids": []}]},
                        validated_claims=[{"claim_id": "c1"}])
        codes = [f["code"] for f in ei.synthesis_entailment_findings({"rows": [row]})]
        self.assertIn("D_SUBSTANTIVE_CLAIM_WITHOUT_EVIDENCE", codes)

    def test_51_invalid_citation(self):
        row = self._row(answer={"claims": [{"claim_id": "c1", "claim_type":
                                            "DEFINITION",
                                            "evidence_ids": ["passage.X.P9"]}]},
                        validated_claims=[{"claim_id": "c1"}])
        codes = [f["code"] for f in ei.synthesis_entailment_findings({"rows": [row]})]
        self.assertIn("D_INVALID_CITATION_IN_FINAL", codes)

    def test_52_rejected_in_final(self):
        row = self._row(answer={"claims": [{"claim_id": "c1", "claim_type":
                                            "DEFINITION", "evidence_ids": ["p1"]}]},
                        validated_claims=[{"claim_id": "c1"}],
                        entailment={"results": [{"claim_id": "c1",
                                                 "final_claim_id": "c1",
                                                 "status": "NOT_ENTAILED"}],
                                    "rejected": []})
        codes = [f["code"] for f in ei.synthesis_entailment_findings({"rows": [row]})]
        self.assertIn("D_REJECTED_CLAIM_IN_FINAL", codes)

    def test_53_invalid_quote_in_final(self):
        row = self._row(answer={"claims": [{"claim_id": "c1", "claim_type":
                                            "DEFINITION", "evidence_ids": ["p1"],
                                            "quotation": {"kind": "CORPUS_QUOTE",
                                                          "passage_id": "p1",
                                                          "exact_span": "不存在的引文"}}]},
                        validated_claims=[{"claim_id": "c1"}])
        codes = [f["code"] for f in ei.synthesis_entailment_findings({"rows": [row]})]
        self.assertIn("D_INVALID_QUOTE_IN_FINAL", codes)

    def test_54_source_role_in_final(self):
        c = {"usable_evidence": [ev(elig="QUALIFIED", layer="L2_RECOVERED")]}
        row = self._row(input_contract=c,
                        answer={"claims": [{"claim_id": "c1", "claim_type":
                                            "DEFINITION", "evidence_ids": ["p1"],
                                            "claim_text": "拉康法文原文明确写道：X"}]},
                        validated_claims=[{"claim_id": "c1"}])
        codes = [f["code"] for f in ei.synthesis_entailment_findings({"rows": [row]})]
        self.assertIn("D_SOURCE_ROLE_VIOLATION_IN_FINAL", codes)

    def test_55_abstention_with_substantive(self):
        row = self._row(answer_permission="ABSTAIN",
                        answer={"claims": [{"claim_id": "c1", "claim_type":
                                            "DEFINITION", "evidence_ids": ["p1"]}],
                                "answer_state": "ABSTAINED"})
        codes = [f["code"] for f in ei.synthesis_entailment_findings({"rows": [row]})]
        self.assertIn("D_ABSTENTION_CONTAINS_SUBSTANTIVE_CLAIM", codes)

    def test_56_absence_without_scan(self):
        row = self._row(answer={"claims": [{"claim_id": "c1",
                                            "claim_type": "CORPUS_ABSENCE",
                                            "evidence_ids": []}]},
                        validated_claims=[{"claim_id": "c1"}])
        codes = [f["code"] for f in ei.synthesis_entailment_findings({"rows": [row]})]
        self.assertIn("D_ABSENCE_CLAIM_WITHOUT_SCAN_PROVENANCE", codes)

    def test_57_final_claim_not_in_validated_set(self):
        row = self._row(answer={"claims": [{"claim_id": "cX", "claim_type":
                                            "DEFINITION", "evidence_ids": ["p1"]}]},
                        validated_claims=[{"claim_id": "c1"}])
        codes = [f["code"] for f in ei.synthesis_entailment_findings({"rows": [row]})]
        self.assertIn("D_FINAL_CLAIM_NOT_IN_VALIDATED_SET", codes)

    def test_58_clean_row_has_no_finding(self):
        row = self._row(answer={"claims": [{"claim_id": "c1", "claim_type":
                                            "DEFINITION", "evidence_ids": ["p1"]}]},
                        validated_claims=[{"claim_id": "c1"}],
                        entailment={"results": [{"claim_id": "c1",
                                                 "final_claim_id": "c1",
                                                 "status": "ENTAILED"}],
                                    "rejected": []})
        self.assertEqual(ei.synthesis_entailment_findings({"rows": [row]}), [])


# ══════════════════════════════════════════════════════════════ Calibration
class TestCalibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [json.loads(l) for l in open(CALIB, encoding="utf-8")
                     if l.strip()]

    def test_60_calibration_set_shape(self):
        self.assertGreaterEqual(len(self.cases), 30)
        cats = {c["category"] for c in self.cases}
        for want in ("positive_direct", "positive_paraphrase", "partial",
                     "lexical_only", "wrong_source_role", "wrong_citation",
                     "contradiction", "composite_overreach", "corpus_absence",
                     "metadata_absence"):
            self.assertIn(want, cats)
        for c in self.cases:
            for f in ("case_id", "category", "contract", "atom", "expected_status"):
                self.assertIn(f, c)

    def test_61_calibration_is_reproducible(self):
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "build_entailment_calibration.py"),
                            "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_62_offline_calibration_accuracy(self):
        out = rd.run_calibration(judge=None, quiet=True)
        self.assertIsNotNone(out["accuracy"])
        self.assertGreaterEqual(out["accuracy"], 0.9,
                                "离线（确定性层）准确率过低：%s" % out["by_category"])

    def test_63_expected_statuses_are_legal(self):
        for c in self.cases:
            self.assertIn(c["expected_status"], se.ENTAILMENT_STATUS)


# ══════════════════════════════════════════════════════════════ Adversarial
class TestAdversarial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = [adv.run_case(c) for c in adv.CASES]

    def test_70_all_adversarial_detected(self):
        bad = [r["case_id"] for r in self.results if not r["detected"]]
        self.assertEqual(bad, [], "未被拦下的对抗用例：%s" % bad)

    def test_71_no_adversarial_claim_in_final(self):
        leaked = [r["case_id"] for r in self.results
                  if r["adversarial_claim_in_final"]]
        self.assertEqual(leaked, [])

    def test_72_expected_defense_layer(self):
        bad = [(r["case_id"], r["expect"], r["detected_by"]) for r in self.results
               if not r["expected_match"]]
        self.assertEqual(bad, [], "防线与预期不符：%s" % bad)

    def test_73_covers_three_required_kinds(self):
        kinds = {r["kind"] for r in self.results}
        for k in ("outside_knowledge_leakage", "source_layer_leakage",
                  "citation_laundering"):
            self.assertIn(k, kinds)


# ══════════════════════════════════════════════════════════════ RepoSafety
class TestRepoSafety(unittest.TestCase):
    def test_80_run_immutability_guard(self):
        rid, d = rd.new_run_dir("testonly", run_id="4c1d_test_%d" % os.getpid())
        try:
            with self.assertRaises(SystemExit):
                rd.new_run_dir("testonly", run_id=os.path.basename(d))
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_81_no_force_overwrite(self):
        src = open(os.path.join(TOOLS, "run_synthesis_4c1d.py"),
                   encoding="utf-8").read()
        self.assertNotIn('add_argument("--force', src)
        self.assertIn("不提供 force-overwrite", src)

    def test_82_no_task_id_branch(self):
        """引擎模块不得有 task_id 分支；对抗夹具模块允许引用真实 task_id 作为**输入**，
        但不得出现「按 task_id 决定行为」的写法。"""
        import re
        for fn in ("synthesis_entailment.py", "synthesis_validation.py",
                   "run_synthesis_4c1d.py", "synthesis_adapters.py"):
            src = open(os.path.join(TOOLS, fn), encoding="utf-8").read()
            self.assertEqual(re.findall(r"rt-[A-Z]\d{2}", src), [], fn)
        adv = open(os.path.join(TOOLS, "synthesis_adversarial.py"),
                   encoding="utf-8").read()
        for m in re.finditer(r"(if|elif)[^\n]*task_id[^\n]*rt-[A-Z]\d{2}", adv):
            self.fail("对抗夹具出现 task_id 分支：%s" % m.group(0))

    def test_83_human_baseline_untouched(self):
        import hashlib
        h = hashlib.sha256(open(os.path.join(EVAL, "research_human_review.jsonl"),
                                "rb").read()).hexdigest()
        self.assertEqual(
            h, "a14ea5316ccaaf90f95e197f9674bca9620848fcc726a1bd5d4c9694fe4bfb3d")

    def test_84_aggregate_present_and_pinned(self):
        agg = json.load(open(AGG, encoding="utf-8"))
        self.assertEqual(agg.get("phase"), "4C.1-D")
        self.assertFalse(agg.get("human_validated"))
        man = json.load(open(os.path.join(VAULT, agg["run_dir"],
                                          "run_manifest.json"), encoding="utf-8"))
        self.assertEqual(man["run_id"], agg["run_id"])
        self.assertEqual(man["validator_version"], rd.VALIDATOR_VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
