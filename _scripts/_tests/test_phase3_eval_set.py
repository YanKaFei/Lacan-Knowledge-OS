#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3_eval_set.py — §2 Gold Evaluation Set validator

评测集是 Phase 3 的**measurement instrument**：如果它自己坏了，
所有「检索变好了」的结论都不成立。所以先给它上一组硬校验：

  * 结构完整（§2 要求的每个字段）
  * query_id 唯一
  * **所有 gold/acceptable passage ID 必须真实存在于 canonical store**
    （这是 §15 硬门禁 fabricated passage IDs = 0 在评测集侧的对应物）
  * intent 必须落在声明的 13 类里
  * 没有 gold 的必须**如实给出原因**，且不得计入 recall 分母
  * 覆盖率：13 类 intent 全部出现
  * 规模 100–200 条（用户要求至少 100、理想 150–200）
"""

import json
import os
import sys
import unittest
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
EVAL = os.path.join(VAULT, "retrieval_eval.jsonl")
SPEC = os.path.join(VAULT, "_data", "retrieval_eval_spec.jsonl")
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))

# 用户 §2 点名的 13 类意图
REQUIRED_INTENTS = {
    "concept_lookup", "exact_quotation", "seminar_specific",
    "diachronic_concept", "concept_relationship", "case_analysis",
    "topology_matheme", "discourse", "philosophy_relation",
    "translation_terminology", "cross_language", "freud_lacan_comparison",
    "secondary_interpretation",
}


def load_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class EvalSet(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = load_jsonl(EVAL) if os.path.isfile(EVAL) else None
        cls.spec = load_jsonl(SPEC) if os.path.isfile(SPEC) else []
        # 真实存在的 passage ID（从机器层取，不重复解析 373MB 全文）
        cls.ids = set()
        import sqlite3
        lex = os.path.join(VAULT, "_data", "index", "lexical.sqlite")
        if os.path.isfile(lex):
            con = sqlite3.connect(lex)
            try:
                for (i,) in con.execute("SELECT id FROM passage_meta"):
                    cls.ids.add(i)
            finally:
                con.close()

    def setUp(self):
        self.assertIsNotNone(self.rows, f"缺 {EVAL}")

    # ---- 0 规模与结构
    def test_00_size_and_schema(self):
        n = len(self.rows)
        self.assertGreaterEqual(n, 100, f"评测集至少 100 条（用户要求），实际 {n}")
        self.assertLessEqual(n, 200, f"评测集 100–200 条为宜，实际 {n}")
        required = ("query_id", "query", "intent", "expected_entities",
                    "expected_seminars", "gold_passages", "acceptable_passages",
                    "language", "notes")
        for r in self.rows:
            for k in required:
                with self.subTest(q=r.get("query_id"), field=k):
                    self.assertIn(k, r, f"{r.get('query_id')} 缺字段 {k}")

    def test_01_query_ids_unique(self):
        ids = [r["query_id"] for r in self.rows]
        dup = [k for k, v in Counter(ids).items() if v > 1]
        self.assertEqual(dup, [], f"query_id 重复: {dup}")

    # ---- 2 ★ 硬门禁：gold/acceptable 里不得有编造的 passage ID
    def test_02_no_fabricated_passage_ids(self):
        if not self.ids:
            self.skipTest("lexical index 不可用，无法校验 ID 存在性")
        bad = []
        for r in self.rows:
            for pid in (r["gold_passages"] + r["acceptable_passages"]):
                if pid not in self.ids:
                    bad.append(f"{r['query_id']} -> {pid}")
        self.assertEqual(bad[:10], [],
                         f"评测集含不存在的 passage ID（{len(bad)} 个）:\n"
                         + "\n".join(bad[:10]))

    # ---- 3 intent 覆盖
    def test_03_all_required_intents_covered(self):
        got = {r["intent"] for r in self.rows}
        missing = REQUIRED_INTENTS - got
        self.assertEqual(missing, set(), f"缺 intent 类别: {sorted(missing)}")
        extra = got - REQUIRED_INTENTS
        self.assertEqual(extra, set(), f"出现未声明的 intent: {sorted(extra)}")

    def test_04_intent_distribution_is_reasonable(self):
        c = Counter(r["intent"] for r in self.rows)
        thin = [k for k, v in c.items() if v < 3]
        self.assertEqual(thin, [], f"这些 intent 样本过少(<3): {thin}")

    # ---- 5 多 gold 是允许且应当存在的
    def test_05_multiple_gold_allowed_and_present(self):
        with_multi = [r for r in self.rows if len(r["gold_passages"]) > 1]
        self.assertTrue(with_multi,
                        "应有多 gold 的 query —— 用户明确要求不得强迫每题只有一个答案")
        self.assertGreater(len(with_multi), len(self.rows) * 0.5,
                           "多数 query 应有多条 gold（否则评测太窄）")

    # ---- 6 没有 gold 的必须如实说明且不计入分母
    def test_06_no_gold_is_honest(self):
        for r in self.rows:
            with self.subTest(q=r["query_id"]):
                if r["gold_passages"]:
                    self.assertTrue(r.get("counted_in_recall"),
                                    "有 gold 就必须计入 recall 分母")
                    self.assertIsNone(r.get("no_gold_reason"))
                else:
                    self.assertFalse(r.get("counted_in_recall"),
                                     "无 gold 不得计入 recall 分母")
                    self.assertTrue(r.get("no_gold_reason"),
                                    "无 gold 必须写明原因，不得静默留空")
                    self.assertIn(r["no_gold_reason"],
                                  ("no_expected_entities",
                                   "expected_entities_absent_from_corpus"))

    # ---- 7 seminar 约束自洽
    def test_07_seminar_constraint_consistent(self):
        for r in self.rows:
            if not r["expected_seminars"]:
                continue
            for pid in r["gold_passages"]:
                with self.subTest(q=r["query_id"], pid=pid):
                    # passage ID 第 2 段含期号
                    parts = pid.split(".")
                    self.assertGreaterEqual(len(parts), 3)
                    sem = "seminar." + parts[1]
                    self.assertIn(sem, r["expected_seminars"],
                                  f"{pid} 不属于期望期 {r['expected_seminars']}")

    # ---- 7b ★ gold 不得有「扫描顺序 → 低期号」的系统性偏差（本轮实测真缺陷）
    def test_07b_gold_has_no_corpus_order_bias(self):
        """gold 必须按 seminar 分层，不得偏向低期号。

        缺陷来源：第一版 gold = 「语料扫描顺序里前 40 条含该词的段」。
        实测 S01 独占 57%、≤S05 占 78% —— gold 变成「早期研讨班抽样」，
        而 BM25 返回的是跨全语料的最佳匹配，两者交集常为空，
        于是 Recall 测的是**截断偏差**而不是检索质量。

        修正：按 seminar 分层抽样（每期 ≤3 条）。
        本条测试锁住修正后的分布特征。
        """
        import re
        from collections import Counter
        c = Counter()
        for r in self.rows:
            for pid in r["gold_passages"]:
                m = re.match(r"passage\.S(\d+)", pid)
                if m:
                    c[int(m.group(1))] += 1
        total = sum(c.values())
        self.assertGreater(total, 0, "没有任何 gold")
        # 覆盖期数应接近全部 27 期
        self.assertGreaterEqual(len(c), 20,
                                f"gold 只覆盖 {len(c)} 期 —— 疑似仍偏向少数期号")
        # 单一期不得垄断
        top_share = max(c.values()) / total
        self.assertLess(top_share, 0.20,
                        f"最高期号占 {top_share:.1%} —— 疑似存在扫描顺序偏差")
        # 低期号不得占绝对多数
        low = sum(v for k, v in c.items() if k <= 5) / total
        self.assertLess(low, 0.55,
                        f"≤S05 占 {low:.1%} —— 疑似仍偏向早期语料")

    def test_07c_gold_by_seminar_is_populated(self):
        """`gold_by_seminar` 声明了就必须有内容（原先 120/120 全为空）。"""
        bad = [r["query_id"] for r in self.rows
               if r["gold_passages"] and not r.get("gold_by_seminar")]
        self.assertEqual(bad[:5], [], f"{len(bad)} 条有 gold 却 gold_by_seminar 为空")
        # 其内容必须与 gold_passages 一致
        for r in self.rows:
            if not r.get("gold_by_seminar"):
                continue
            flat = {p for v in r["gold_by_seminar"].values() for p in v}
            self.assertEqual(flat, set(r["gold_passages"]),
                             f"{r['query_id']} 的 gold_by_seminar 与 gold_passages 不一致")

    def test_07d_acceptable_is_subset_of_gold(self):
        """`acceptable` 命名暗示包含于 gold；原先 0/96 成立，现已修为真子集。"""
        bad = [r["query_id"] for r in self.rows
               if not set(r["acceptable_passages"]) <= set(r["gold_passages"])]
        self.assertEqual(bad[:5], [],
                         f"{len(bad)} 条 acceptable 不是 gold 的子集（命名误导）")

    # ---- 8 gold 来源可解释
    def test_08_gold_source_is_explainable(self):
        for r in self.rows:
            with self.subTest(q=r["query_id"]):
                self.assertIn(r.get("gold_source"),
                              ("entity_needle_match", "seminar_level_fallback"))
                if r["gold_source"] == "seminar_level_fallback":
                    self.assertTrue(r["gold_passages"],
                                    "期级回退必须真的产出 gold")
                self.assertIn("gold_derivation", r)
                self.assertTrue(r["gold_derivation"].get("method"))

    # ---- 9 ★ 评测集可复现：从 spec 重生成必须逐字节一致
    def test_09_eval_set_is_reproducible(self):
        import hashlib
        import subprocess
        before = hashlib.sha256(open(EVAL, "rb").read()).hexdigest()
        r = subprocess.run([sys.executable,
                            os.path.join(VAULT, "_scripts", "_tools",
                                         "build_retrieval_eval.py")],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, f"重生成失败:\n{r.stderr[-500:]}")
        after = hashlib.sha256(open(EVAL, "rb").read()).hexdigest()
        self.assertEqual(before, after, "评测集重生成结果不同（不可复现）")

    # ---- 10 spec 与产物一一对应
    def test_10_spec_and_output_align(self):
        self.assertEqual(len(self.spec), len(self.rows),
                         "spec 条数与产物条数不一致")
        self.assertEqual([s["query_id"] for s in self.spec],
                         [r["query_id"] for r in self.rows],
                         "spec 与产物的 query 顺序/集合不一致")

    # ---- 11 不得改动 canonical store
    def test_11_does_not_mutate_canonical_store(self):
        import subprocess
        pp = os.path.join(STORE, "passages.jsonl")
        before = os.stat(pp).st_mtime_ns
        subprocess.run([sys.executable,
                        os.path.join(VAULT, "_scripts", "_tools",
                                     "build_retrieval_eval.py")],
                       capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(os.stat(pp).st_mtime_ns, before,
                         "生成评测集不得修改 canonical passage store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
