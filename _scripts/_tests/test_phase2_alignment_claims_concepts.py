#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase2_alignment_claims_concepts.py — §五 Alignment / §九 Gold Concept / §十 Claim / §十二 OCR

覆盖用户要求的测试项：
  8. alignment target existence
  12. Gold Concept linkage
  13. L4 / AI candidate cannot become canonical
  14. recovered translation cannot silently become canonical
  + §十二 OCR pipeline interface 与 page → passage 可追踪模型
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
TOOLS = os.path.join(VAULT, "_scripts", "_tools")

GOLD_EXPECTED = 53


def load_jsonl(name):
    p = os.path.join(STORE, name)
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class AlignmentClaimsConcepts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.passage_ids = set()
        pp = os.path.join(STORE, "passages.jsonl")
        if os.path.isfile(pp):
            with open(pp, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        cls.passage_ids.add(json.loads(line)["id"])
        cls.alignments = load_jsonl("alignments.jsonl")
        cls.claims = load_jsonl("claims.jsonl")
        cls.concepts = load_jsonl("concepts.jsonl")
        cls.states = load_jsonl("concept_states.jsonl")
        cls.translations = load_jsonl("translations.jsonl")

    # ============================================== §五 Alignment
    def test_00_alignment_entities_exist_with_required_fields(self):
        self.assertTrue(self.alignments, "没有 alignment 实体")
        required = ("alignment_id", "source_passages", "target_passages",
                    "relation_type", "confidence", "review_status", "method")
        for a in self.alignments:
            for k in required:
                with self.subTest(a=a.get("alignment_id"), field=k):
                    self.assertIn(k, a, f"alignment 缺字段 {k}")

    def test_01_no_1to1_assumption(self):
        """§五：166,527 vs 82,578 —— 禁止假设 1:1。

        模型必须能表达 1:1 / N:1 / 1:N / 1:0 / 0:1，且**实际出现**了非 1:1 的情形。
        """
        kinds = {a["relation_type"] for a in self.alignments}
        for k in ("1:1", "N:1", "1:0", "0:1"):
            with self.subTest(kind=k):
                self.assertIn(k, kinds, f"模型必须能表达 {k}")
        # 1:0（缺译）必须存在 —— 实测 fr 是 zh 的 2.0166 倍，缺译是常态而非异常
        self.assertTrue(any(a["relation_type"] == "1:0" for a in self.alignments),
                        "必须能表达『法文有、中译无』")

    def test_02_alignment_targets_exist(self):
        """§五 测试项 8：alignment 引用的 passage 必须真实存在。"""
        missing = []
        for a in self.alignments:
            for pid in (a.get("source_passages") or []) + (a.get("target_passages") or []):
                if pid not in self.passage_ids:
                    missing.append(f"{a['alignment_id']} -> {pid}")
        self.assertEqual(missing, [], "alignment 指向不存在的 passage:\n" + "\n".join(missing))

    def test_03_heuristic_alignment_is_candidate_only(self):
        """§五：任何 heuristic alignment 默认只能是 candidate，不得自动 canonical。"""
        for a in self.alignments:
            with self.subTest(a=a["alignment_id"]):
                if "heuristic" in str(a.get("method", "")).lower() or \
                   "illustrative" in str(a.get("method", "")).lower() or \
                   "seed" in str(a.get("method", "")).lower():
                    self.assertEqual(a["review_status"], "candidate",
                                     "启发式对齐不得是 candidate 之外的状态")
                self.assertNotEqual(a["review_status"], "canonical",
                                    "本阶段不允许任何 canonical alignment")
                self.assertIn(a["review_status"],
                              ("candidate", "needs_review", "reviewed", "rejected"))

    def test_04_alignment_has_confidence(self):
        for a in self.alignments:
            with self.subTest(a=a["alignment_id"]):
                self.assertIsInstance(a["confidence"], (int, float))
                self.assertGreaterEqual(a["confidence"], 0.0)
                self.assertLessEqual(a["confidence"], 1.0)

    # ============================================== §十 Claim
    def test_10_claim_fields(self):
        self.assertTrue(self.claims, "没有 claim")
        required = ("id", "statement", "supporting_passages", "source_type",
                    "authority_level", "status", "review_status", "confidence",
                    "created_by")
        for c in self.claims:
            for k in required:
                with self.subTest(claim=c.get("id"), field=k):
                    self.assertIn(k, c, f"claim 缺字段 {k}")

    def test_11_ai_claims_default_candidate(self):
        """§十：AI 自动生成的 Claim 默认 candidate。"""
        for c in self.claims:
            with self.subTest(claim=c["id"]):
                by = str(c.get("created_by") or "")
                if by.startswith("ai:") or by.startswith("script:"):
                    self.assertEqual(c["review_status"], "candidate",
                                     f"{by} 生成的 claim 必须是 candidate")

    def test_12_claim_without_evidence_cannot_be_canonical(self):
        """§十 核心：没有 supporting_passages 的 Claim 不得进入 canonical。

        这是「禁止无证据 Claim 进入 canonical」的机械化表达。
        """
        for c in self.claims:
            with self.subTest(claim=c["id"]):
                if not (c.get("supporting_passages") or []):
                    self.assertNotEqual(
                        c["review_status"], "canonical",
                        f"{c['id']} 无 supporting_passages 却标为 canonical")
                    self.assertEqual(
                        c.get("trace_status"), "SOURCE_TRACE_INCOMPLETE",
                        f"{c['id']} 无证据时必须标 SOURCE_TRACE_INCOMPLETE")

    def test_13_claim_passages_resolve(self):
        missing = []
        for c in self.claims:
            for pid in c.get("supporting_passages") or []:
                if pid not in self.passage_ids:
                    missing.append(f"{c['id']} -> {pid}")
        self.assertEqual(missing, [], "claim 指向不存在的 passage:\n" + "\n".join(missing))

    def test_14_no_canonical_claim_in_this_phase(self):
        """本阶段不应有任何 canonical claim（无人工审核记录）。"""
        canon = [c["id"] for c in self.claims if c["review_status"] == "canonical"]
        self.assertEqual(canon, [], f"本阶段不应出现 canonical claim: {canon}")

    # ============================================== §九 Gold Concept Set
    def test_20_gold_set_size(self):
        """§九：以现有 53 条卡为准，不凭空创建。"""
        self.assertEqual(len(self.concepts), GOLD_EXPECTED,
                         f"Gold Concept Set 应为 {GOLD_EXPECTED} 条，实际 {len(self.concepts)}")

    def test_21_concepts_have_required_shape(self):
        for c in self.concepts:
            with self.subTest(concept=c.get("id")):
                for k in ("id", "canonical_name", "aliases", "catalog_source",
                          "authority_level", "review_status", "passages",
                          "trace_status"):
                    self.assertIn(k, c, f"concept 缺字段 {k}")
                self.assertIsInstance(c["aliases"], list)
                self.assertTrue(c["catalog_source"].startswith(("terms_catalog",
                                                                 "clinical_catalog",
                                                                 "cases_catalog")),
                                "必须能追到具体 catalog 来源")

    def test_22_concept_linkage_chain(self):
        """§九 验证链：Concept → aliases → seminar → session → passages。

        至少要有一条**完整可查询**的链：concept 有 passage，passage 能落到
        session/seminar。这是「概念第一次真正连到证据」的证明。
        """
        # 取一个有 passage 的概念
        with_p = [c for c in self.concepts if c.get("passages")]
        self.assertTrue(with_p, "没有任何 concept 连到 passage —— linkage 未建立")
        # 建 passage → (session, seminar) 索引
        idx = {}
        pp = os.path.join(STORE, "passages.jsonl")
        need = {pid for c in with_p for pid in c["passages"]}
        with open(pp, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                if d["id"] in need:
                    idx[d["id"]] = (d["session_id"], d["seminar_id"])
        missing = [pid for c in with_p for pid in c["passages"] if pid not in idx]
        self.assertEqual(missing[:5], [], f"概念引用的 passage 不存在: {missing[:3]}")
        # 抽查一条完整链
        c0 = with_p[0]
        pid = c0["passages"][0]
        sess, sem = idx[pid]
        self.assertRegex(sess, r"^session\.S\d{2}")
        self.assertRegex(sem, r"^seminar\.S\d{2}")
        self.assertTrue(c0["aliases"], f"{c0['id']} 没有 aliases，链不完整")

    def test_23_no_invented_concepts(self):
        """§九：不得凭空创建概念 —— 每个 concept 必须来自 6 个既有 catalog。"""
        allowed = {"terms_catalog.TERMS", "terms_catalog_b.TERMS_B",
                   "terms_catalog_c.TERMS_C", "terms_catalog_fr.TERMS_FR",
                   "clinical_catalog.CLINICAL", "cases_catalog.CASES"}
        for c in self.concepts:
            with self.subTest(concept=c["id"]):
                self.assertIn(c["catalog_source"], allowed,
                              f"{c['id']} 的来源不在既有 catalog 内")

    def test_24_concept_states_bound_to_concepts(self):
        cids = {c["id"] for c in self.concepts}
        for st in self.states:
            with self.subTest(state=st.get("id")):
                self.assertIn(st["concept_id"], cids,
                              f"{st['id']} 的 concept_id 不存在")
                self.assertIn("period", st)

    def test_25_no_concept_canonical(self):
        """恢复期不得把概念标为 canonical。"""
        canon = [c["id"] for c in self.concepts
                 if c.get("review_status") == "canonical" or c.get("canonical")]
        self.assertEqual(canon, [], f"本阶段不应有 canonical concept: {canon}")

    # ============================================== §四 recovered translation
    def test_30_recovered_translation_not_canonical(self):
        """§四/测试项 14：恢复了的中译不得被静默提升为 canonical。"""
        self.assertTrue(self.translations, "没有 translation 记录")
        zh = [t for t in self.translations if t.get("language") == "zh"]
        self.assertTrue(zh, "缺中文 translation 记录")
        for t in zh:
            with self.subTest(t=t["id"]):
                self.assertEqual(t["status"], "recovered",
                                 "中译初始状态必须是 recovered")
                self.assertFalse(t["canonical"],
                                 "中译不得自动 canonical")
                self.assertEqual(t.get("source_state"), "upstream_missing",
                                 "必须记录上游源目录已消失")

    def test_31_recovered_status_requires_review_to_upgrade(self):
        """升级路径必须存在且需要人工审核（不是自动）。"""
        for t in self.translations:
            with self.subTest(t=t["id"]):
                if not t["canonical"]:
                    self.assertIn(t["review_status"],
                                  ("candidate", "needs_review", "reviewed", "rejected"),
                                  "未 canonical 的 translation 必须有审核状态")

    # ============================================== §十二 OCR pipeline
    def test_40_ocr_pipeline_interface_exists(self):
        """§十二：建立 OCR pipeline interface 与 provenance schema。

        本阶段**不执行** OCR（工具链未装，且 Passage Schema 需先稳定）；
        但接口与 schema 必须存在，且不得偷偷用不可复现的方法。
        """
        p = os.path.join(TOOLS, "ocr_pipeline.py")
        self.assertTrue(os.path.isfile(p), f"缺 OCR pipeline 接口: {p}")

    def test_41_ocr_schema_and_page_tracking(self):
        p = os.path.join(TOOLS, "ocr_pipeline.py")
        if not os.path.isfile(p):
            self.skipTest("OCR pipeline 尚未创建")
        r = subprocess.run([sys.executable, p, "--print-schema"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, f"--print-schema 失败:\n{r.stderr[-400:]}")
        schema = json.loads(r.stdout)
        for k in ("page_to_passage", "provenance_fields", "engine_requirements",
                  "not_executed_reason"):
            with self.subTest(field=k):
                self.assertIn(k, schema, f"OCR schema 缺 {k}")
        # page → passage 可追踪
        self.assertIn("page", schema["page_to_passage"])
        self.assertIn("passage_id", schema["page_to_passage"])
        # 必须记录「为什么本阶段没跑 OCR」
        self.assertTrue(schema["not_executed_reason"])

    def test_42_no_ocr_was_actually_run(self):
        """不得偷偷跑不可复现的 OCR：本阶段不应出现 OCR 产物。"""
        for d in ("_data/ocr", "_data/ocr_output"):
            p = os.path.join(VAULT, d)
            if os.path.isdir(p):
                files = [f for f in os.listdir(p) if not f.startswith(".")]
                self.assertEqual(files, [], f"{d} 里出现了 OCR 产物，本阶段不应执行 OCR")


if __name__ == "__main__":
    unittest.main(verbosity=2)
