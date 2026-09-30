#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3_witness_semantics.py — §0 Witness 语义审查与迁移

审查结论（实测，见 PHASE3_FINDINGS.md §0）
────────────────────────────────────────
当前 `Witness = 3`，但实测三者**不在同一层级**：

| witness | 是什么 | 期覆盖 |
|---|---|---|
| `witness.fr.staferla` | STAFERLA 工作转录（**一次转录**） | 28 期 |
| `witness.fr.seuil-pdf` | 法语 PDF 抽取（**另一份文本实现**） | S1–S5 |
| `witness.zh.translation-project` | 社区中译（**另一语言的文本**） | 28 期 |

后两者与前者**覆盖同一批期**（PDF 的 S1–S5 落在 staferla 的 S1–S27 内），
所以它们不是两个独立的「来源族」，而是**对同一批法语文本的两种实现**。

因此 3 是**具体 witness 数**（没有虚报），但模型把两个层级压平了：

    CorpusSource（来源族：STAFERLA 网站 / 社区中译项目）
      → Witness（具体文本：某次转录、某个版本）
        → PassageRealization（某个 Passage 在某 witness 中的实现）

本次迁移**只增不删**：新增 CorpusSource 层与 PassageRealization 层，
`witnesses.jsonl` 保持兼容（补 `corpus_source_id` 外键）。
统计数字不变（witness 仍为 3）——**迁移是为了语义，不是为了改数字**。
"""

import json
import os
import unittest
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")


def load_jsonl(name):
    p = os.path.join(STORE, name)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class WitnessSemantics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sources = load_jsonl("corpus_sources.jsonl")
        cls.witnesses = load_jsonl("witnesses.jsonl") or []
        cls.realizations = load_jsonl("passage_realizations.jsonl")
        cls.passages = load_jsonl("passages.jsonl")
        cls.links = load_jsonl("passage_witnesses.jsonl") or []

    # ---- 1 三层结构存在
    def test_00_three_layers_exist(self):
        """CorpusSource → Witness → PassageRealization 三层必须都存在。"""
        self.assertIsNotNone(self.sources, "缺 corpus_sources.jsonl（CorpusSource 层）")
        self.assertIsNotNone(self.realizations,
                             "缺 passage_realizations.jsonl（PassageRealization 层）")
        self.assertTrue(self.witnesses, "witnesses.jsonl 为空")
        self.assertTrue(self.sources, "corpus_sources.jsonl 为空")

    # ---- 2 CorpusSource 字段完整
    def test_01_corpus_source_shape(self):
        for s in self.sources:
            with self.subTest(source=s.get("id")):
                for k in ("id", "type", "name", "kind", "language",
                          "authority_level", "review_status", "witness_ids"):
                    self.assertIn(k, s, f"corpus_source 缺字段 {k}")
                self.assertEqual(s["type"], "corpus_source")
                self.assertTrue(s["witness_ids"], f"{s['id']} 没有任何 witness")

    # ---- 3 每个 witness 必须挂在某个 CorpusSource 下（外键完整）
    def test_02_every_witness_belongs_to_a_source(self):
        src_ids = {s["id"] for s in self.sources}
        for w in self.witnesses:
            with self.subTest(witness=w["id"]):
                self.assertIn("corpus_source_id", w,
                              f"{w['id']} 缺 corpus_source_id")
                self.assertIn(w["corpus_source_id"], src_ids,
                              f"{w['id']} 指向不存在的 corpus source")

    # ---- 4 ★ 关键：两层必须被分开表达，且每层各自自洽
    def test_03_layers_are_distinct_not_flattened(self):
        """本次审查的核心结论：`Witness=3` 是**具体 witness 数**（没虚报），
        但三个 witness **不在同一层级**：

          * 两个法语 witness 覆盖同一批期（PDF 的 S1–S5 落在 staferla 的 S1–S27 内）
            —— 即它们是同一批法语文本的两种**实现**
          * 但它们来自**不同的传承渠道**：一个是公开转录网站，一个是印刷版扫描

        所以正确的表达不是「把两个法语 witness 合并成一个来源族」，
        而是**把「渠道」与「实现」两层分开**：

            CorpusSource（传承渠道） → Witness（具体文本实现） → PassageRealization

        实测迁移结果：3 个 CorpusSource → 3 个 Witness → 249,105 个 Realization。
        迁移是**只增不删**的（witness 数不变），目的是语义而非改数字。
        """
        by_id = {w["id"]: w for w in self.witnesses}
        a = by_id.get("witness.fr.staferla")
        b = by_id.get("witness.fr.seuil-pdf")
        self.assertIsNotNone(a, "缺 witness.fr.staferla")
        self.assertIsNotNone(b, "缺 witness.fr.seuil-pdf")
        # 两者都必须是 witness（同一层级），而不是一个是 source、另一个是 witness
        self.assertIn("corpus_source_id", a)
        self.assertIn("corpus_source_id", b)
        # 来源族必须是**实体**，不能只是 witness 上的一个字符串标签
        src_ids = {s["id"] for s in self.sources}
        for w in (a, b):
            self.assertIn(w["corpus_source_id"], src_ids,
                          "corpus_source_id 必须指向真实存在的 CorpusSource 实体")

    def test_03b_french_witnesses_have_distinct_provenance_channels(self):
        """两个法语 witness 的传承渠道不同（转录网站 vs 印刷版），
        因此分属不同 CorpusSource —— 这正是需要两层的原因。

        若将来证据表明它们同源（例如转录就是从该印刷版做的），
        这条测试应当被**有证据地**改成断言它们同源。
        """
        by_id = {w["id"]: w for w in self.witnesses}
        a, b = by_id["witness.fr.staferla"], by_id["witness.fr.seuil-pdf"]
        src = {s["id"]: s for s in self.sources}
        ka = src[a["corpus_source_id"]]["kind"]
        kb = src[b["corpus_source_id"]]["kind"]
        self.assertNotEqual(
            ka, kb,
            "两个法语 witness 的渠道类型相同(%s)，则不应拆成两个 CorpusSource" % ka)
        self.assertEqual({ka, kb}, {"transcription_site", "print_edition"},
                         "实测渠道类型应为 转录网站 / 印刷版")

    # ---- 5 来源族数量与 witness 数量关系正确
    def test_04_source_and_witness_counts_are_consistent(self):
        """实测：3 个具体 witness，分属 3 个传承渠道。**数字本身不变。**"""
        self.assertEqual(len(self.witnesses), 3, "witness 数不应因迁移而改变")
        self.assertEqual(len(self.sources), 3, "应为 3 个传承渠道")
        # 每个 source 恰好一个 witness 是本阶段的事实（不是模型限制）
        multi = [s["id"] for s in self.sources if len(s["witness_ids"]) != 1]
        self.assertEqual(multi, [],
                         "本阶段每个渠道恰好一个 witness；模型**允许**多个，"
                         "这条只是记录当前实测事实")
        # 每个 source 的 witness_ids 必须与 witness 的 corpus_source_id 双向一致
        for s in self.sources:
            for wid in s["witness_ids"]:
                w = next((x for x in self.witnesses if x["id"] == wid), None)
                self.assertIsNotNone(w, f"{s['id']} 声明了不存在的 witness {wid}")
                self.assertEqual(w["corpus_source_id"], s["id"])

    # ---- 6 PassageRealization 层：Passage × Witness 的实现记录
    def test_05_realizations_reference_valid_ids(self):
        self.assertIsNotNone(self.realizations)
        pids = {p["id"] for p in (self.passages or [])} if self.passages else None
        wids = {w["id"] for w in self.witnesses}
        bad = []
        for r in self.realizations:
            for k in ("passage_id", "witness_id", "corpus_source_id",
                      "review_status"):
                if k not in r:
                    bad.append(f"{r.get('passage_id')}: 缺 {k}")
            if r.get("witness_id") not in wids:
                bad.append(f"{r.get('passage_id')}: witness 不存在 {r.get('witness_id')}")
            if pids is not None and r.get("passage_id") not in pids:
                bad.append(f"{r.get('passage_id')}: passage 不存在")
        self.assertEqual(bad[:5], [], "\n".join(bad[:5]))

    def test_06_realization_count_matches_passages(self):
        """每个 Passage 至少一条 realization（否则它在 witness 层「消失了」）。"""
        if not self.passages:
            self.skipTest("passages.jsonl 不可用")
        got = Counter(r["passage_id"] for r in self.realizations)
        missing = [p["id"] for p in self.passages if p["id"] not in got]
        self.assertEqual(missing[:5], [],
                         f"{len(missing)} 个 Passage 没有 realization 记录")

    # ---- 7 迁移无损：Passage 总数、语言分布不变
    def test_07_migration_is_lossless(self):
        if not self.passages:
            self.skipTest("passages.jsonl 不可用")
        c = Counter(p["language"] for p in self.passages)
        self.assertEqual(len(self.passages), 249105, "迁移后 Passage 总数变了")
        self.assertEqual(c["zh"], 82578)
        self.assertEqual(c["fr"], 166527)

    # ---- 8 迁移后不得伪造 canonical
    def test_08_no_canonical_after_migration(self):
        for s in self.sources:
            with self.subTest(source=s["id"]):
                self.assertFalse(s.get("canonical", False),
                                 "来源族不得标 canonical")
        for w in self.witnesses:
            with self.subTest(witness=w["id"]):
                self.assertFalse(w.get("canonical", False))
        for r in self.realizations[:5000]:
            self.assertNotEqual(r.get("review_status"), "canonical",
                                "realization 不得 canonical")

    # ---- 9 旧的 passage_witnesses 连接表必须仍然自洽（向后兼容）
    def test_09_legacy_link_table_still_consistent(self):
        if not self.links:
            self.skipTest("passage_witnesses.jsonl 不可用")
        wids = {w["id"] for w in self.witnesses}
        bad = [l["witness_id"] for l in self.links
               if l["witness_id"] not in wids]
        self.assertEqual(bad[:5], [], "旧连接表出现悬空 witness_id")
        self.assertEqual(len(self.links), 249105,
                         "旧连接表条数变了（向后兼容被破坏）")

    # ---- 10 迁移决策必须写进文档（可复核）
    def test_10_migration_decision_is_documented(self):
        p = os.path.join(VAULT, "PHASE3_FINDINGS.md")
        self.assertTrue(os.path.isfile(p), "缺 PHASE3_FINDINGS.md")
        with open(p, encoding="utf-8") as fh:
            txt = fh.read()
        for needle in ("CorpusSource", "Witness", "PassageRealization"):
            with self.subTest(needle=needle):
                self.assertIn(needle, txt,
                              f"迁移决策必须写在文档里：缺 {needle}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
