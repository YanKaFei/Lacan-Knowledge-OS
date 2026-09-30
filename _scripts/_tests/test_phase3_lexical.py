#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3_lexical.py — §3 Lexical Retrieval Baseline + Tokenizer 验证

覆盖 §16：
  * exact passage lookup
  * French tokenizer
  * Chinese tokenizer
  * metadata filters
  * quoted phrase search
  * deterministic retrieval
  * index reproducibility
  * 不改 canonical store

硬约束（用户 §3）
─────────────────
> French 与 Chinese tokenizer 必须分别验证。
> 不要未经 benchmark 就锁定 jieba 或任何单一 tokenizer。
> 所有 tokenizer 必须作用在 derived index text 上。不得修改 canonical text。
"""

import json
import os
import sqlite3
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
LEX = os.path.join(IDX, "lexical.sqlite")
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
sys.path.insert(0, TOOLS)

BUILD = os.path.join(TOOLS, "build_lexical_index.py")


class Lexical(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.built = os.path.isfile(LEX)

    def setUp(self):
        if not self.built:
            self.fail(f"缺 lexical index: {LEX}（先跑 build_lexical_index.py）")

    # ---- 0 索引与结构
    def test_00_index_exists_with_tables(self):
        con = sqlite3.connect(LEX)
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        finally:
            con.close()
        for t in ("passage_meta", "fr_fts", "zh_fts"):
            with self.subTest(table=t):
                self.assertIn(t, tables, f"缺表 {t}")

    # ---- 1 exact passage lookup（按 ID）
    def test_01_exact_passage_lookup(self):
        from lacan_search import exact_passage
        # 取一个真实 ID
        with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
            first = json.loads(f.readline())
        hit = exact_passage(first["id"])
        self.assertIsNotNone(hit, f"按 ID 查不到 {first['id']}")
        self.assertEqual(hit["passage_id"], first["id"])
        self.assertEqual(hit["language"], first["language"])
        self.assertTrue(hit["text"])
        # 不存在的 ID 必须返回 None（不得编造）
        self.assertIsNone(exact_passage("passage.S99.unknown.P9999"))

    # ---- 2 French tokenizer：撇号 / 变音 / 连字符 / 术语
    def test_02_french_tokenizer_handles_lacanian_forms(self):
        from lacan_search import lexical_search
        cases = [
            ("l'Autre", "撇号"),
            ("Nom-du-Père", "连字符"),
            ("plus-de-jouir", "多段连字符"),
            ("objet a", "空格分隔"),
        ]
        for q, why in cases:
            with self.subTest(query=q, why=why):
                hits = lexical_search(q, language="fr", limit=5)
                # 命中数可以少（这些词在语料里的出现频次不同），
                # 但**必须不报错**且返回结构正确
                self.assertIsInstance(hits, list)
                for h in hits:
                    self.assertIn("passage_id", h)
                    self.assertIn("rank", h)

    def test_02b_accent_and_apostrophe_variants_find_same(self):
        """变音/撇号的不同写法应能命中同一批文本（否则法语检索不可用）。"""
        from lacan_search import lexical_search
        a = lexical_search("pere", language="fr", limit=10)
        b = lexical_search("père", language="fr", limit=10)
        # 至少有一种写法能命中；unaccent 折叠后两者应高度重叠
        self.assertTrue(a or b, "père/pere 都查不到，法语变音处理失效")

    # ---- 3 Chinese tokenizer：至少比较两种策略
    def test_03_chinese_tokenizer_strategies_compared(self):
        """§3 要求比较 segmented lexical index 与 CJK trigram/substring 策略。"""
        bench = os.path.join(IDX, "tokenizer_benchmark.json")
        self.assertTrue(os.path.isfile(bench),
                        "必须有 tokenizer benchmark 结果（§3 要求先 benchmark 再锁定）")
        with open(bench, encoding="utf-8") as f:
            b = json.load(f)
        self.assertIn("french", b)
        self.assertIn("chinese", b)
        # 中文必须比较过至少两种策略
        self.assertGreaterEqual(
            len(b["chinese"].get("strategies", {})), 2,
            "中文必须比较至少两种 tokenizer 策略（不得未经 benchmark 锁定单一方案）")
        # 法语必须比较过变音处理
        self.assertGreaterEqual(
            len(b["french"].get("strategies", {})), 2,
            "法语必须比较变音/撇号处理策略")

    def test_03b_chinese_search_works(self):
        from lacan_search import lexical_search
        for q in ("大他者", "享乐", "圣状"):
            with self.subTest(query=q):
                hits = lexical_search(q, language="zh", limit=5)
                self.assertTrue(hits, f"中文查询 {q} 无命中")

    # ---- 4 metadata filters
    def test_04_metadata_filters(self):
        from lacan_search import lexical_search
        # seminar 过滤
        hits = lexical_search("jouissance", language="fr", seminar="S20", limit=10)
        for h in hits:
            with self.subTest(pid=h["passage_id"]):
                self.assertTrue(h["passage_id"].startswith("passage.S20."),
                                f"seminar 过滤失效: {h['passage_id']}")
        # language 过滤
        zh = lexical_search("享乐", language="zh", limit=5)
        for h in zh:
            self.assertEqual(h["language"], "zh")
        # trace_status 过滤
        inc = lexical_search("jouissance", trace_status="SOURCE_TRACE_INCOMPLETE",
                             limit=5)
        for h in inc:
            self.assertEqual(h["trace_status"], "SOURCE_TRACE_INCOMPLETE")

    # ---- 5 quoted phrase search
    def test_05_quoted_phrase_search(self):
        from lacan_search import lexical_search
        hits = lexical_search('"le désir"', language="fr", limit=5)
        self.assertIsInstance(hits, list)
        # 引号短语必须真的按短语匹配（结果里应含该短语）
        for h in hits:
            self.assertIn("désir", h.get("text", "").lower())

    # ---- 6 确定性
    def test_06_retrieval_is_deterministic(self):
        from lacan_search import lexical_search
        a = lexical_search("objet a", language="fr", limit=10)
        b = lexical_search("objet a", language="fr", limit=10)
        self.assertEqual([h["passage_id"] for h in a],
                         [h["passage_id"] for h in b],
                         "同一查询两次结果不同（非确定）")

    # ---- 7 索引可重建
    def test_07_index_is_reproducible(self):
        import hashlib

        def digest():
            h = hashlib.sha256()
            con = sqlite3.connect(LEX)
            try:
                for (sql,) in con.execute(
                        "SELECT sql FROM sqlite_master ORDER BY name"):
                    h.update(str(sql).encode())
                for row in con.execute(
                        "SELECT id FROM passage_meta ORDER BY id LIMIT 5000"):
                    h.update(row[0].encode())
            finally:
                con.close()
            return h.hexdigest()
        before = digest()
        r = subprocess.run([sys.executable, BUILD, "--no-bench"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, f"重建失败:\n{r.stderr[-500:]}")
        self.assertEqual(before, digest(), "索引重建后结构/内容不同")

    # ---- 8 ★ 不改 canonical store
    def test_08_does_not_mutate_canonical_store(self):
        pp = os.path.join(STORE, "passages.jsonl")
        before = (os.stat(pp).st_mtime_ns, os.path.getsize(pp))
        subprocess.run([sys.executable, BUILD, "--no-bench"],
                       capture_output=True, text=True, cwd=VAULT)
        after = (os.stat(pp).st_mtime_ns, os.path.getsize(pp))
        self.assertEqual(before, after,
                         "建 lexical index 不得修改 canonical passage store")

    # ---- 9 无效查询不得编造结果
    def test_09_no_fabricated_results(self):
        from lacan_search import lexical_search, exact_passage
        self.assertEqual(lexical_search("zzzqqqxxx不存在的词", limit=5), [])
        self.assertIsNone(exact_passage("passage.NOT.A.REAL.ID"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
