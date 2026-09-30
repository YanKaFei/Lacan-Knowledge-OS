#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4d0_core_boundary.py — Phase 4D.0 核心边界契约测试

守的是 4D.0 的九条完成门（§9）：
  1. core freeze manifest 合法          2. core hashes 被钉住
  3. stable domain objects 已定义        4. 读写边界已定义
  5. API boundary 已实现                 6. 产品层无法改动学术工件
  7. boundary tests 绿                   8. 既有 scholarly suite 绿（由套件级保证）
  9. 测试期间 HEAD 稳定（由套件级保证）

纪律：本测试**只读**核心；只在 USER_WORKSPACE 内写临时文件并清理；
绝不调用真实 LLM（provider 一律 mock，或故意把凭据置为不可用）。
"""
import glob
import json
import os
import re
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))

import scholarly_api as S              # noqa: E402
import scholarly_api.objects as O      # noqa: E402
import scholarly_api.policy as P       # noqa: E402
import core_freeze as CF               # noqa: E402

FREEZE = os.path.join(VAULT, "_data", "core_freeze",
                      "scholarly_core_freeze_v1.json")


class CoreFreeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.load(open(FREEZE, encoding="utf-8")) if os.path.isfile(FREEZE) else {}

    def test_00_freeze_manifest_verifies(self):
        """§9-1/2：清单存在、逐项复算一致（哈希被钉住）。"""
        self.assertTrue(self.doc, "缺 core freeze manifest")
        self.assertEqual(CF.verify(quiet=True), 0, "core freeze 校验未通过")

    def test_01_all_required_components_present(self):
        """§3 要求的字段必须逐个存在且非空。"""
        need = ["research_contract_hash", "execution_engine_hash",
                "evidence_sufficiency_hash", "synthesis_boundary_hash",
                "synthesis_prompt_hash", "judge_prompt_hash", "claim_atom_hash",
                "entailment_validator_hash", "repair_rules_hash",
                "citation_policy_hash", "source_role_policy_hash",
                "abstention_policy_hash", "gate13_hash", "gate19_hash",
                "gate20_hash", "gate21_hash", "ontology_version",
                "passage_store_version", "retrieval_index_lexical",
                "human_review_round1_hash", "human_review_round2_hash",
                "scholarly_readiness_gate_hash"]
        comp = self.doc.get("components") or {}
        missing = [k for k in need if not comp.get(k)]
        self.assertEqual(missing, [], "freeze manifest 缺组件：%s" % missing)
        for k in ("d2_sealed_run_id", "d2_seal_hash"):
            self.assertTrue(self.doc.get(k), "freeze manifest 缺 %s" % k)

    def test_02_status_and_identity(self):
        self.assertEqual(self.doc.get("scholarly_status"), "SCHOLARLY_CORE_READY")
        self.assertEqual(self.doc.get("freeze_version"), "scholarly_core_freeze_v1")
        self.assertEqual(self.doc.get("unresolved_components"), [])
        # D2 seal 必须与封存 run 的 seal.json 一致
        run_dir = os.path.join(VAULT, "_data", "eval", "runs",
                               self.doc["d2_sealed_run_id"])
        seal = os.path.join(run_dir, "seal.json")
        if os.path.isfile(seal):
            self.assertEqual(CF.sha_file(os.path.relpath(seal, VAULT)),
                             self.doc["d2_seal_hash"])

    def test_03_prompt_and_gate_hashes_match_frozen_values(self):
        comp = self.doc["components"]
        self.assertTrue(comp["synthesis_prompt_hash"].startswith("cc7170f8bbd21f5d"))
        self.assertTrue(comp["judge_prompt_hash"].startswith("3708ccb8e02459dc"))
        self.assertTrue(comp["scholarly_readiness_gate_hash"].startswith("ca915b0ba362d7a7"))

    def test_04_api_itself_is_pinned(self):
        comp = self.doc["components"]
        for k in ("scholarly_api_core_hash", "scholarly_api_objects_hash",
                  "scholarly_api_policy_hash"):
            self.assertTrue(comp.get(k), "API 自身未被钉住：%s" % k)


class StableObjects(unittest.TestCase):
    def test_10_schemas_shipped_on_disk(self):
        files = sorted(glob.glob(os.path.join(S.objects.SCHEMA_DIR, "*.json")))
        self.assertEqual(len(files), len(O.SCHEMAS),
                         "schema 文件数与 objects.SCHEMAS 不一致（跑 python3 -m "
                         "scholarly_api.objects 重新导出）")

    def test_11_schema_files_match_definitions(self):
        """磁盘上的 schema 必须与 objects.py 的定义逐字一致（禁止手改 schema）。"""
        for name in O.SCHEMAS:
            p = os.path.join(S.objects.SCHEMA_DIR,
                             "%s.json" % O._kebab(name))
            self.assertTrue(os.path.isfile(p), "缺 schema 文件：%s" % p)
            self.assertEqual(json.load(open(p, encoding="utf-8")), O.schema_doc(name),
                             "%s 的 schema 文件与定义不一致" % name)

    def test_12_readonly_api_outputs_are_schema_valid(self):
        cases = [("PassageRecord", S.get_passage("passage.S11.unknown.P2253")),
                 ("PassageContext", S.get_context("passage.S11.unknown.P2253", 2, 2)),
                 ("PassageSearchResult", S.search_passages("regard", {"top_k": 3})),
                 ("ConceptRecord", S.get_concept("concept.objet-petit-a")),
                 ("SeminarRecord", S.get_seminar("seminar.S11")),
                 ("ProvenanceRecord", S.trace_source("passage.S11.unknown.P2253"))]
        for name, obj in cases:
            self.assertNotEqual(obj.get("ok"), False, "%s 返回错误：%s" % (name, obj))
            ok, errs = O.validate(name, obj)
            self.assertTrue(ok, "%s schema 违规：%s" % (name, errs[:3]))
            self.assertNotIn("_schema_errors", obj)

    def test_13_source_layer_derivation_is_documented_and_mechanical(self):
        """source_layer 只能由既有字段机械派生（README 表），不得凭空发明。"""
        rec = S.get_passage("passage.S11.unknown.P2253")
        self.assertIn(rec.get("source_layer"),
                      ("L1_TRANSCRIPTION", "L2_RECOVERED", "L1_EDITION", None))
        self.assertEqual(rec.get("source_layer"), "L1_TRANSCRIPTION")


class ResearchIntegrity(unittest.TestCase):
    """§18 Research integrity：UI answer == core final answer（不得二次改写）。"""

    QUESTION = "Seminar XI 中 gaze/regard 是如何与 objet a 发生关系的？"

    @classmethod
    def setUpClass(cls):
        cls.res = S.research(cls.QUESTION, {"mode": "seminar_specific",
                                           "language": "fr", "provider": "mock",
                                           "task_id": "boundary-test-1"})

    def test_20_answer_is_schema_valid(self):
        self.assertNotEqual(self.res.get("ok"), False, self.res)
        ok, errs = O.validate("FinalScholarlyAnswer", self.res)
        self.assertTrue(ok, errs[:3])
        self.assertNotIn("_schema_errors", self.res)

    def test_21_no_text_rewriting(self):
        """validated_claims 的文本必须逐字出现在 sections 里（核心文本未经改写）。"""
        blob = json.dumps(self.res["sections"], ensure_ascii=False)
        for c in self.res["validated_claims"]:
            self.assertIn(str(c["claim_text"])[:24], blob,
                          "claim 文本未逐字出现在 sections 中：%s" % c["claim_id"])

    def test_22_summary_counts_consistent(self):
        s = self.res["summary"]
        self.assertEqual(s["validated_claims_n"], len(self.res["validated_claims"]))
        self.assertEqual(s["citations_n"], len(self.res["citations"]))
        self.assertIn(self.res["answer_state"],
                      ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "ABSTAINED",
                       "STRUCTURALLY_UNAVAILABLE"))
        self.assertEqual(self.res["provenance"]["provider"], "mock")

    def test_23_citations_are_bound_and_traceable(self):
        self.assertTrue(self.res["citations"], "本题应有可回溯 citation")
        for c in self.res["citations"]:
            self.assertTrue(c["passage_id"], "citation 缺 passage_id")
            rec = S.get_passage(c["passage_id"])
            self.assertNotEqual(rec.get("ok"), False,
                                "citation 指向不存在的 passage：%s" % c["passage_id"])
            self.assertEqual(rec["passage_id"], c["passage_id"])

    def test_24_abstention_is_propagated_not_filled(self):
        """核心 ABSTAIN → API 必须继承弃权，且不得产出实质性 claim。"""
        res = S.research("拉康 1953 年 11 月 18 日那场报告的确切时间、地点与在场者是谁？",
                         {"mode": "scholarly", "provider": "mock",
                          "task_id": "boundary-test-abstain"})
        self.assertNotEqual(res.get("ok"), False, res)
        self.assertEqual(res["answer_state"], "ABSTAINED")
        self.assertEqual(res["answer_permission"], "ABSTAIN")
        self.assertIsNotNone(res["abstention"])
        for c in res["validated_claims"]:
            self.assertNotIn(c["claim_type"], ("DEFINITION", "RELATION", "DISTINCTION"),
                             "弃权答案里出现实质性断言：%s" % c["claim_id"])

    def test_25_llm_provider_requires_credentials_no_silent_fallback(self):
        """凭据不可用 → ApiError，绝不回退到模型自身知识。"""
        home_backup = os.environ.get("HOME")
        key_backup = os.environ.get("DSH_SYNTHESIS_API_KEY")
        tmp_home = os.path.join(VAULT, "_index", "_tmp_home_for_test")
        try:
            os.makedirs(tmp_home, exist_ok=True)
            os.environ["HOME"] = tmp_home
            os.environ.pop("DSH_SYNTHESIS_API_KEY", None)
            res = S.research("objet a 是什么？", {"provider": "llm",
                                                "task_id": "boundary-test-nokey"})
            self.assertEqual(res.get("ok"), False)
            self.assertEqual(res["error_code"], "PROVIDER_UNAVAILABLE")
            self.assertIn("不要", res["resolution"] + "".join(
                str(v) for v in res.get("detail", {}).values()))
        finally:
            if home_backup is not None:
                os.environ["HOME"] = home_backup
            if key_backup is not None:
                os.environ["DSH_SYNTHESIS_API_KEY"] = key_backup
            shutil.rmtree(tmp_home, ignore_errors=True)

    def test_26_invalid_request_is_rejected(self):
        res = S.research("   ", {})
        self.assertEqual(res.get("ok"), False)
        self.assertEqual(res["error_code"], "INVALID_RESEARCH_REQUEST")

    def test_27_invalid_provider_is_rejected(self):
        res = S.research("objet a 是什么？", {"provider": "bogus"})
        self.assertEqual(res.get("ok"), False)
        self.assertEqual(res["error_code"], "INVALID_PROVIDER")


class WriteBoundary(unittest.TestCase):
    def test_30_classification(self):
        cases = {
            "_data/eval/runs/4c1d2_llm_x/results.json": "IMMUTABLE_CORE",
            "_data/core_freeze/scholarly_core_freeze_v1.json": "IMMUTABLE_CORE",
            "_data/eval/research_human_review_round2.jsonl": "IMMUTABLE_CORE",
            "_data/ontology/v4a1/entities.jsonl": "IMMUTABLE_CORE",
            "_scripts/_tools/synthesis_entailment.py": "IMMUTABLE_CORE",
            "_index/passage_store.sqlite": "REBUILDABLE_MACHINE",
            "_index/Reports/validation-report.json": "REBUILDABLE_MACHINE",
            "_index/Views/by-type.md": "REBUILDABLE_MACHINE",
            "_data/ontology/candidate/entities.jsonl": "CANONICAL_KNOWLEDGE",
            "Research/2026-01-01 - x.md": "USER_WORKSPACE",
            "Projects/desire/notes.md": "USER_WORKSPACE",
            "_core_change_requests/requests/CCR-0001.json": "USER_WORKSPACE",
            "some/random/place.txt": "UNKNOWN",
        }
        for path, want in cases.items():
            self.assertEqual(P.classify(path), want, "分类错误：%s" % path)

    def test_31_immutable_writes_are_refused(self):
        for path in ("_data/eval/runs/4c1d2_llm_x/results.json",
                     "_data/core_freeze/scholarly_core_freeze_v1.json",
                     "_data/eval/research_human_review_round2.jsonl",
                     "_scripts/_tools/synthesis_entailment.py"):
            with self.assertRaises(P.CoreMutationError):
                P.write_text(path, "x")
        with self.assertRaises(P.CoreMutationError):        # 未知路径保守拒绝
            P.write_text("some/random/place.txt", "x")

    def test_32_canonical_requires_review_token(self):
        p = "_data/ontology/candidate/entities.jsonl"
        with self.assertRaises(P.CoreMutationError):
            P.assert_writable(p)
        self.assertEqual(P.assert_writable(p, review_token="review-1"),
                         "CANONICAL_KNOWLEDGE")

    def test_33_product_writes_do_not_mutate_core(self):
        """§7：保存研究笔记 / Obsidian 导出 / UI 缓存都不许碰核心工件。"""
        before = P.snapshot_immutable()
        made = []
        try:
            made.append(P.write_text("Research/2026-01-01 - boundary-test.md",
                                     "# research note\n")["path"])
            made.append(P.write_json("Projects/boundary-test/note.json",
                                     {"ok": True})["path"])
            made.append(P.write_text(
                "Research/boundary-test-export.md", "# export\n")["path"])
            made.append(P.write_text(
                "_core_change_requests/requests/CCR-9999.json",
                json.dumps({"probe": True}))["path"])
        finally:
            after = P.snapshot_immutable()
            for rel in made:
                p = os.path.join(VAULT, rel)
                if os.path.isfile(p):
                    os.remove(p)
            for d in ("Research", "Projects/boundary-test", "Projects"):
                dp = os.path.join(VAULT, d)
                if os.path.isdir(dp) and not os.listdir(dp):
                    os.rmdir(dp)
        self.assertEqual(P.diff_snapshot(before, after), [],
                         "产品写入改动了核心工件")

    def test_34_obsidian_export_target_is_user_workspace(self):
        self.assertEqual(P.classify("Exports/research-bundle/answer.md"),
                         "USER_WORKSPACE")
        self.assertEqual(P.classify("Seminars/S11.md"), "USER_WORKSPACE")
        self.assertEqual(P.classify("Concepts/objet-petit-a.md"), "USER_WORKSPACE")


class CoreChangeRequestProtocol(unittest.TestCase):
    def test_40_protocol_files_exist(self):
        for rel in ("_core_change_requests/SCHEMA.json",
                    "_core_change_requests/TEMPLATE.json",
                    "_core_change_requests/README.md"):
            self.assertTrue(os.path.isfile(os.path.join(VAULT, rel)), rel)

    def test_41_template_validates_and_statuses_complete(self):
        sc = json.load(open(os.path.join(VAULT, "_core_change_requests",
                                        "SCHEMA.json"), encoding="utf-8"))
        tmpl = json.load(open(os.path.join(VAULT, "_core_change_requests",
                                          "TEMPLATE.json"), encoding="utf-8"))
        # ★ Phase 4E/5A：CCR 协议新增**终态** `RESOLVED`（只有在 Gate 全部判据、
        #   含 E14 真人复核，PASS 之后才允许进入）。断言随之扩展，并保持状态机可核。
        self.assertEqual(sorted(sc["properties"]["status"]["enum"]),
                         sorted(["OPEN", "TRIAGED", "ACCEPTED_FOR_REMEDIATION",
                                 "REJECTED", "DEFERRED", "RESOLVED"]))
        try:
            import jsonschema  # noqa: PLC0415
            jsonschema.Draft202012Validator(sc).validate(tmpl)
        except ImportError:
            self.skipTest("无 jsonschema")

    def test_42_protocol_checker_passes(self):
        import subprocess  # noqa: PLC0415
        p = os.path.join(VAULT, "_scripts", "_tools",
                         "check_core_change_requests.py")
        r = subprocess.run([sys.executable, p, "--verify", "--quiet"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class ProductCannotImportCore(unittest.TestCase):
    """§5：只有 scholarly_api/core.py 可以 import 核心内部实现。"""

    CORE_MODULES = ("knowledge_api", "research_answer", "research_contract",
                    "research_execution", "synthesis_contract", "synthesis_claims",
                    "synthesis_render", "synthesis_adapters", "synthesis_entailment",
                    "synthesis_validation", "eval_integrity")

    def test_50_only_core_module_imports_core(self):
        api_dir = os.path.join(VAULT, "scholarly_api")
        for fn in sorted(os.listdir(api_dir)):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(api_dir, fn), encoding="utf-8").read()
            hits = []
            for mod in self.CORE_MODULES:
                if re.search(r"^\s*(import|from)\s+%s\b" % re.escape(mod), src, re.M):
                    hits.append(mod)
            if fn == "core.py":
                self.assertTrue(hits, "core.py 应当承担全部核心 import")
            else:
                self.assertEqual(hits, [], "%s 不得直接 import 核心：%s" % (fn, hits))


if __name__ == "__main__":
    unittest.main()
