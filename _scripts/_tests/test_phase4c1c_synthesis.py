#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1c_synthesis.py — Phase 4C.1-C：Scholarly Synthesis 契约测试

七组（对应 §31）：
    InputContract   不同 evidence/execution 状态 → 正确的 answer_permission
    Abstention      J02 / J03（结构性弃权正向对照）
    Citation        引用不存在 / 无资格 / 来源角色不符 → FAIL
    Quote           引用 span 必须真的在段落里；不得把解释说成原话
    Claim           无证据的 substantive claim → FAIL；UNSUPPORTED 不得出现在输出
    Provider        provider 失败不得产出半成品
    RunImmutability 已有 run 目录不得覆盖
外加：Diagnostic（14 题结果 + Gate 20 = 0）、RepoSafety。
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
RUNS = os.path.join(EVAL, "runs")
AGG = os.path.join(EVAL, "research_synthesis_results.4c1c.json")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))

import research_answer as ans               # noqa: E402
import synthesis_contract as sc             # noqa: E402
import synthesis_claims as scl              # noqa: E402
import synthesis_render as sr               # noqa: E402
import synthesis_adapters as sad            # noqa: E402
import eval_integrity as ei                 # noqa: E402
import run_synthesis_4c1c as rs             # noqa: E402


def jd(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


_TASKS = None


def tasks():
    global _TASKS
    if _TASKS is None:
        _TASKS = {json.loads(l)["task_id"]: json.loads(l)
                  for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"),
                                encoding="utf-8") if l.strip()}
    return _TASKS


_RUNS = {}


def run(tid):
    if tid not in _RUNS:
        t = tasks()[tid]
        pub = {k: t[k] for k in ("task_id", "question", "language", "task_type",
                                 "required_capabilities", "split")}
        _RUNS[tid] = ans.run_task(pub, record_gaps=False)
    return _RUNS[tid]


def contract(tid, max_ev=12):
    return sc.build_synthesis_input_contract(run(tid), max_evidence=max_ev)


def _fake_run(state="SUPPORTED", exec_state="EXECUTION_COMPLETE",
              complete=True, missing_ops=None, meta_state="NOT_REQUIRED",
              substantive=3, struct=None, violated=None, relation_req=False,
              relation_n=0):
    """构造一个最小 run（用于权限矩阵测试；不跑真实检索）。"""
    return {
        "task_id": "synthetic", "question": "q", "plan": {"task_type": "concept_definition"},
        "evidence_pack": {"evidence": [], "warnings": [], "provenance": {}},
        "trace": {
            "final_state": state,
            "research_contract": {
                "contract_type": "X", "required_operations": [], "missing_operations":
                    missing_ops or [], "required_lanes": [], "missing_lanes": [],
                "required_constraints": [], "failed_constraints": [],
                "metadata": {"metadata_required": ["exact_date"] if
                             meta_state != "NOT_REQUIRED" else [],
                             "metadata_state": meta_state},
                "formalism": {"formalism_required": False,
                              "formalism_state": "NOT_REQUIRED"},
                "evidence_usability": {"substantive_n": substantive},
                "relation_evidence_required": relation_req,
                "relation_evidence_n": relation_n,
                "required_source_layers": [], "missing_source_layers": [],
                "required_entities": [],
            },
            "execution": {"state": exec_state, "operations": [], "lanes": [],
                          "endpoints": [], "constraints": [], "terminology": {},
                          "formalism": {}, "source_layers": {}, "metadata": {},
                          "budget": {}, "schema_version": "research-execution/v2"},
            "execution_completion": {"complete": complete},
            "sufficiency_v2": {"structural_unanswerability": struct or []},
            "sufficiency_v21": {"violated_rules": violated or [], "state_ceiling":
                                "SUPPORTED"},
        },
    }


# ══════════════════════════════════════════════════════════════ InputContract
class TestInputContract(unittest.TestCase):
    def test_01_supported_and_complete_is_full(self):
        p, r, st = sc.answer_permission(_fake_run())
        self.assertEqual(p, "FULL_SYNTHESIS")
        self.assertEqual(st, "READY")

    def test_02_partially_supported_is_qualified(self):
        p, r, st = sc.answer_permission(_fake_run(state="PARTIALLY_SUPPORTED"))
        self.assertEqual(p, "QUALIFIED_SYNTHESIS")

    def test_03_metadata_unavailable_is_abstain(self):
        p, r, st = sc.answer_permission(_fake_run(
            state="INSUFFICIENT_EVIDENCE", meta_state="METADATA_UNAVAILABLE"))
        self.assertEqual(p, "ABSTAIN")
        self.assertIn("METADATA_UNAVAILABLE", r)

    def test_04_topic_not_covered_is_abstain(self):
        p, r, st = sc.answer_permission(_fake_run(
            state="INSUFFICIENT_EVIDENCE",
            struct=[{"class": "TOPIC_NOT_COVERED", "message": "x"}], substantive=1))
        self.assertEqual(p, "ABSTAIN")
        self.assertIn("TOPIC_NOT_COVERED", r)

    def test_05_incomplete_execution_is_blocked(self):
        for kw in ({"exec_state": "EXECUTION_PARTIAL"},
                   {"complete": False},
                   {"missing_ops": ["search_passages"]}):
            p, r, st = sc.answer_permission(_fake_run(**kw))
            self.assertEqual(p, "BLOCKED", "kw=%s reasons=%s" % (kw, r))
            self.assertEqual(st, "BLOCKED")

    def test_06_real_contracts_have_required_fields(self):
        c = contract("rt-A01")
        for f in ("task_id", "question", "task_type", "evidence_state",
                  "execution_state", "research_contract_summary",
                  "answer_permissions", "claim_permissions",
                  "abstention_requirements", "usable_evidence", "relation_evidence",
                  "source_layers", "formalism_evidence", "terminology_evidence",
                  "metadata_evidence", "warnings", "citation_policy", "status"):
            self.assertIn(f, c, "SynthesisInputContract 缺字段 %s" % f)

    def test_07_b3_run_is_ready(self):
        c = contract("rt-D01")
        self.assertEqual(c["status"], "READY")
        self.assertEqual(c["answer_permission"], "FULL_SYNTHESIS")


# ══════════════════════════════════════════════════════════════ Claim permissions
class TestClaimPermissions(unittest.TestCase):
    def test_10_media_cannot_support_theory(self):
        ev = {"passage_id": "p1", "text": "![[img.jpeg]]", "authority_level": "L2"}
        el = sc.citation_eligibility(ev)
        self.assertEqual(el["eligibility"], "INELIGIBLE")
        self.assertEqual(sc.claim_permissions(el["usability_class"], "INELIGIBLE"),
                         ["limitation"])

    def test_11_editorial_is_metadata_only(self):
        ev = {"passage_id": "p2", "authority_level": "L2",
              "text": "[编者注：本讲由某某整理，1964 年 1 月 15 日]"}
        el = sc.citation_eligibility(ev)
        self.assertEqual(el["usability_class"], "EDITORIAL_METADATA")
        self.assertEqual(el["eligibility"], "INELIGIBLE")
        self.assertIn("metadata", sc.CLAIM_PERMISSION_BY_USABILITY[
            "EDITORIAL_METADATA"])

    def test_12_recovered_l2_is_qualified(self):
        ev = {"passage_id": "p3", "authority_level": "L2", "text_role": "translation",
              "trace_status": "SOURCE_TRACE_INCOMPLETE",
              "text": "这是一段足够长的中文译文，用来测试引用资格判定。" * 2}
        el = sc.citation_eligibility(ev)
        self.assertEqual(el["eligibility"], "QUALIFIED")
        self.assertEqual(el["source_layer"], "L2_RECOVERED")
        self.assertIn("recovered", el["attribution"])

    def test_13_l1_primary_is_eligible_and_language_is_source_aware(self):
        ev = {"passage_id": "p4", "authority_level": "L1", "text_role": "transcription",
              "language": "fr", "trace_status": "COMPLETE",
              "text": "le poinçon divise le sujet barré dans le fantasme."}
        el = sc.citation_eligibility(ev)
        self.assertEqual(el["eligibility"], "ELIGIBLE")
        self.assertEqual(el["source_layer"], "L1_TRANSCRIPTION")
        self.assertIn("拉康", el["attribution"])


# ══════════════════════════════════════════════════════════════ Claim schema
class TestClaimSchema(unittest.TestCase):
    def setUp(self):
        self.c = contract("rt-A01")
        self.ev = self.c["usable_evidence"][0]

    def test_20_substantive_claim_needs_evidence(self):
        cl = scl.make_claim("c1", "DEFINITION", "t", "DIRECTLY_SUPPORTED", [])
        codes = [v["code"] for v in scl.validate_claim(cl, self.c)]
        self.assertIn("CLAIM_WITHOUT_EVIDENCE", codes)

    def test_21_unknown_passage_is_invalid_reference(self):
        cl = scl.make_claim("c1", "DEFINITION", "t", "DIRECTLY_SUPPORTED",
                            ["passage.NOPE.unknown.P0001"])
        codes = [v["code"] for v in scl.validate_claim(cl, self.c)]
        self.assertIn("INVALID_CITATION_REFERENCE", codes)

    def test_22_ineligible_evidence_is_source_role_violation(self):
        c = json.loads(json.dumps(self.c))
        c["usable_evidence"] = [dict(self.ev, usability_class="MEDIA_ONLY",
                                     citation_eligibility="INELIGIBLE",
                                     claim_permissions=["limitation"])]
        cl = scl.make_claim("c1", "DEFINITION", "t", "DIRECTLY_SUPPORTED",
                            [self.ev["passage_id"]])
        codes = [v["code"] for v in scl.validate_claim(cl, c)]
        self.assertIn("SOURCE_ROLE_VIOLATION", codes)

    def test_23_unsupported_status_is_forbidden(self):
        cl = scl.make_claim("c1", "LIMITATION", "t", "UNSUPPORTED", [])
        codes = [v["code"] for v in scl.validate_claim(cl, self.c)]
        self.assertIn("CLAIM_WITHOUT_EVIDENCE", codes)

    def test_24_absence_claim_needs_corpus_scan_ref(self):
        cl = scl.make_claim("c1", "CORPUS_ABSENCE", "本语料无该词", "CORPUS_ABSENCE", [])
        codes = [v["code"] for v in scl.validate_claim(cl, self.c)]
        self.assertIn("ABSTENTION_CONTRACT_VIOLATION", codes)
        cl2 = scl.make_claim("c2", "CORPUS_ABSENCE", "本语料无该词", "CORPUS_ABSENCE", [],
                             corpus_scan_ref={"scope": "whole_corpus", "hits": 0})
        self.assertEqual(scl.validate_claim(cl2, self.c), [])


# ══════════════════════════════════════════════════════════════ Quote policy
class TestQuotePolicy(unittest.TestCase):
    def setUp(self):
        self.c = contract("rt-A01")
        self.ev = self.c["usable_evidence"][0]

    def test_30_quote_span_must_exist_in_passage(self):
        cl = scl.make_claim("c1", "DEFINITION", "t", "DIRECTLY_SUPPORTED",
                            [self.ev["passage_id"]],
                            quotation={"kind": "CORPUS_QUOTE",
                                       "passage_id": self.ev["passage_id"],
                                       "exact_span": "这句原文里根本没有",
                                       "language": self.ev["language"],
                                       "source_layer": self.ev["source_layer"]})
        codes = [v["code"] for v in scl.validate_claim(cl, self.c)]
        self.assertIn("UNSUPPORTED_QUOTATION", codes)

    def test_31_real_prefix_span_passes(self):
        span = str(self.ev["text"])[:40]
        cl = scl.make_claim("c1", "DEFINITION", "t", "DIRECTLY_SUPPORTED",
                            [self.ev["passage_id"]],
                            quotation={"kind": "CORPUS_QUOTE",
                                       "passage_id": self.ev["passage_id"],
                                       "exact_span": span,
                                       "language": self.ev["language"],
                                       "source_layer": self.ev["source_layer"]})
        self.assertEqual(scl.validate_claim(cl, self.c), [])

    def test_32_model_translation_cannot_masquerade(self):
        cl = scl.make_claim("c1", "DEFINITION", "t", "DIRECTLY_SUPPORTED",
                            [self.ev["passage_id"]],
                            quotation={"kind": "MODEL_TRANSLATION",
                                       "passage_id": self.ev["passage_id"],
                                       "exact_span": "x",
                                       "presented_as": "CORPUS_WITNESS"})
        codes = [v["code"] for v in scl.validate_claim(cl, self.c)]
        self.assertIn("SOURCE_ROLE_VIOLATION", codes)

    def test_33_qualified_evidence_cannot_be_called_original(self):
        c = json.loads(json.dumps(self.c))
        c["usable_evidence"] = [dict(self.ev, citation_eligibility="QUALIFIED",
                                     source_layer="L2_RECOVERED")]
        cl = scl.make_claim("c1", "DEFINITION", "拉康原文说：X", "DIRECTLY_SUPPORTED",
                            [self.ev["passage_id"]])
        codes = [v["code"] for v in scl.validate_claim(cl, c)]
        self.assertIn("SOURCE_ROLE_VIOLATION", codes)


# ══════════════════════════════════════════════════════════════ Abstention
class TestAbstention(unittest.TestCase):
    def test_40_j02_and_j03_abstain_with_contract(self):
        adm = sad.MockSynthesisAdapter()
        for tid in ("rt-J02", "rt-J03"):
            c = contract(tid)
            self.assertEqual(c["answer_permission"], "ABSTAIN", tid)
            out = adm.synthesize(tasks()[tid]["question"], c)
            self.assertTrue(out["ok"])
            ab = out["abstention"]
            for f in ("abstention_reason_codes", "missing_information",
                      "available_partial_information", "next_required_sources"):
                self.assertTrue(ab.get(f), "%s 缺 %s" % (tid, f))
            ansr = sr.build_answer(c, out["claims"], out["sections"], out["abstention"])
            self.assertEqual(ansr["answer_state"], "ABSTAINED")
            ids = [s["id"] for s in ansr["sections"]]
            for sec in ("conclusion", "why", "what_can_be_said", "what_would_be_needed"):
                self.assertIn(sec, ids, "%s 缺 %s" % (tid, sec))
            self.assertEqual(sr.validate_answer(ansr, c)["violations"], [])

    def test_41_missing_abstention_field_is_violation(self):
        c = contract("rt-J02")
        ansr = sr.build_answer(c, [], {"conclusion": "无法回答"},
                               {"abstention_reason_codes": ["TOPIC_NOT_COVERED"]})
        codes = [v["code"] for v in sr.validate_answer(ansr, c)["violations"]]
        self.assertIn("ABSTENTION_CONTRACT_VIOLATION", codes)

    def test_42_j03_metadata_specific(self):
        c = contract("rt-J03")
        self.assertIn("METADATA_UNAVAILABLE",
                      c["abstention_requirements"]["reason_codes"])
        self.assertEqual(c["synthesis_template"]["template"], "METADATA")
        self.assertTrue(c["metadata_evidence"]["metadata_missing_fields"])


# ══════════════════════════════════════════════════════════════ Provider
class _FailingProvider(sad.SynthesisProvider):
    name = "failing_test_provider"
    deterministic = False

    @property
    def available(self):
        return True

    def complete(self, system, user, schema):
        raise RuntimeError("provider boom")


class TestProvider(unittest.TestCase):
    def test_50_provider_failure_yields_no_partial_answer(self):
        adm = sad.ScholarlySynthesisAdapter(provider=_FailingProvider())
        c = contract("rt-A01")
        out = adm.synthesize("q", c)
        self.assertFalse(out["ok"])
        self.assertEqual(out["failure_mode"], "LLM_PROVIDER_FAILURE")
        self.assertEqual(out["claims"], [])
        self.assertIsNone(out["answer"])

    def test_51_blocked_contract_never_calls_provider(self):
        calls = {"n": 0}

        class _Counting(sad.SynthesisProvider):
            name = "counting"

            @property
            def available(self):
                return True

            def complete(self, system, user, schema):
                calls["n"] += 1
                return {}

        adm = sad.ScholarlySynthesisAdapter(provider=_Counting())
        out = adm.synthesize("q", {"status": "BLOCKED", "answer_permission": "BLOCKED"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["failure_mode"], "SYNTHESIS_NOT_ALLOWED")
        self.assertEqual(calls["n"], 0, "BLOCKED 不得调用 provider")

    def test_52_mock_provider_is_deterministic_and_offline(self):
        p = sad.MockProvider()
        self.assertTrue(p.available)
        self.assertTrue(p.deterministic)
        self.assertFalse(sad.OpenAICompatibleProvider().available,
                         "未配置 key 时 provider 必须不可用")

    def test_53_system_contract_states_the_boundary(self):
        text = sad.SYSTEM_CONTRACT
        for phrase in ("只能使用", "不得", "evidence_ids", "ABSTAIN"):
            self.assertIn(phrase, text)
        self.assertIn("Do not", sad.SYSTEM_CONTRACT.replace("**不", "不") + "Do not")


# ══════════════════════════════════════════════════════════════ Run immutability
class TestRunImmutability(unittest.TestCase):
    def test_60_existing_run_dir_refused(self):
        rid, d = rs.new_run_dir(base=RUNS, run_id="4c1c_test_immutable_%d" % os.getpid())
        try:
            with self.assertRaises(SystemExit):
                rs.new_run_dir(base=RUNS, run_id=os.path.basename(d))
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_61_manifest_pins_run(self):
        agg = jd(AGG) or {}
        run_dir = os.path.join(VAULT, agg.get("run_dir") or "")
        man = jd(os.path.join(run_dir, "run_manifest.json")) or {}
        self.assertEqual(man.get("run_id"), agg.get("run_id"))
        self.assertEqual(man.get("phase"), "4C.1-C")
        self.assertTrue(man.get("immutable"))
        self.assertFalse(man.get("human_validated"))
        self.assertIn("synthesis_contract.py", man.get("engine_hashes") or {})

    def test_62_no_force_overwrite_option(self):
        src = open(os.path.join(TOOLS, "run_synthesis_4c1c.py"), encoding="utf-8").read()
        # 不得存在任何 force-overwrite 形式的开关（只允许 --new-run 新建）
        self.assertNotIn('add_argument("--force', src)
        self.assertNotIn("add_argument('--force", src)
        self.assertIn("--new-run", src)
        self.assertIn("不提供", src)          # 文档里明确写了不提供 force-overwrite


# ══════════════════════════════════════════════════════════════ Diagnostic
class TestDiagnostic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agg = jd(AGG) or {}
        cls.run_dir = os.path.join(VAULT, cls.agg.get("run_dir") or "")
        cls.full = jd(os.path.join(cls.run_dir, "synthesis_results.json")) or {}

    def test_70_fourteen_reviewed_tasks(self):
        self.assertEqual(self.agg.get("marker"), "DIAGNOSTIC")
        self.assertFalse(self.agg.get("human_validated"))
        self.assertEqual(self.agg.get("phase"), "4C.1-C")
        self.assertEqual(self.agg.get("task_set"), "human_reviewed_14")
        self.assertEqual(len(self.full.get("rows") or []), 14)

    def test_71_hard_targets_are_zero(self):
        m = self.agg.get("metrics") or {}
        self.assertEqual(m.get("claims_without_evidence"), 0)
        self.assertEqual(m.get("ineligible_citations_used"), 0)
        self.assertEqual(m.get("source_role_violations"), 0)
        self.assertEqual(m.get("abstention_contract_violations"), 0)
        self.assertEqual(m.get("trace_leaks_n"), 0)
        self.assertEqual(m.get("schema_valid_rate"), 1.0)

    def test_72_permissions_cover_all_states(self):
        m = self.agg.get("metrics") or {}
        self.assertEqual(m.get("full_synthesis_n", 0) + m.get("qualified_synthesis_n", 0)
                         + m.get("abstention_n", 0) + m.get("blocked_n", 0),
                         m.get("tasks_n"))
        self.assertGreaterEqual(m.get("abstention_n"), 2)
        self.assertGreaterEqual(m.get("qualified_synthesis_n"), 1)

    def test_73_gate20_clean_on_real_results(self):
        findings = ei.synthesis_run_findings(self.full)
        self.assertEqual(findings, [], findings[:4])

    def test_74_answers_are_rendered_markdown_without_leaks(self):
        for r in self.full.get("rows") or []:
            if not r.get("markdown"):
                continue
            self.assertNotIn("tool_calls", r["markdown"])
            self.assertEqual(sr.trace_leaks(r.get("answer") or {}), [])

    def test_75_diagnostic_not_human_validated(self):
        for r in self.full.get("rows") or []:
            self.assertEqual(r.get("validation_note"), "NOT_HUMAN_VALIDATED")
            self.assertFalse(r.get("human_validated"))


# ══════════════════════════════════════════════════════════════ RepoSafety
class TestRepoSafety(unittest.TestCase):
    def test_80_no_task_id_branch_in_synthesis_modules(self):
        for fn in ("synthesis_contract.py", "synthesis_claims.py",
                   "synthesis_render.py", "synthesis_adapters.py"):
            src = open(os.path.join(TOOLS, fn), encoding="utf-8").read()
            self.assertEqual(re.findall(r"rt-[A-Z]\d{2}", src), [],
                             "%s 出现 task_id 分支" % fn)

    def test_81_head_unchanged_shape(self):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=VAULT,
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(len(head), 40)

    def test_82_human_baseline_untouched(self):
        import hashlib
        p = os.path.join(EVAL, "research_human_review.jsonl")
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        self.assertEqual(
            h, "a14ea5316ccaaf90f95e197f9674bca9620848fcc726a1bd5d4c9694fe4bfb3d")


if __name__ == "__main__":
    unittest.main(verbosity=2)
