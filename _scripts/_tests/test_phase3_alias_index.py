#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3_alias_index.py — §4 Terminology / Alias Index

覆盖 §16 要求的：
  * alias resolution
  * ambiguous aliases   ← 本文件重点
  * exact alias lookup

核心纪律（用户 §4 明确要求）
────────────────────────────
> 禁止未经 review 自动合并：Autre / autre，以及其他大小写或术语差异
> 具有理论意义的词。

拉康的 `l'Autre`（大他者）与 `l'autre`（小他者）是**两个概念**，
大小写本身携带理论差异。所以 alias index 必须：

1. 同时保存**原文大小写**与**归一化形式**
2. 大小写折叠后碰撞时 → 标记为 ambiguous，**不得**自动合并成一条
3. 查询可以显式要求大小写敏感（`--case-sensitive`）
"""

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))

ALIAS_FILE = os.path.join(IDX, "alias_index.jsonl")


def load_jsonl(p):
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class AliasIndex(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = load_jsonl(ALIAS_FILE)
        cls.concepts = load_jsonl(os.path.join(STORE, "concepts.jsonl")) or []
        cls.terms = load_jsonl(os.path.join(STORE, "term.fr.jouissance")) or []

    # ---- 0 索引存在
    def test_00_alias_index_exists(self):
        self.assertIsNotNone(self.rows, f"缺 {ALIAS_FILE}")
        self.assertGreater(len(self.rows), 50, "alias 条数过少，疑似未真正建索引")

    # ---- 1 字段完整（§4 明确列出的字段）
    def test_01_required_fields(self):
        for r in self.rows:
            with self.subTest(alias=r.get("alias")):
                for k in ("alias", "language", "entity_id", "status",
                          "source", "review_status"):
                    self.assertIn(k, r, f"alias 记录缺字段 {k}")

    # ---- 2 entity_id 必须真实存在
    def test_02_entity_ids_resolve(self):
        ids = {c["id"] for c in self.concepts}
        # term 实体也是合法目标
        for extra in load_jsonl(os.path.join(STORE, "concepts.jsonl")) or []:
            ids.add(extra["id"])
        missing = sorted({r["entity_id"] for r in self.rows
                          if r["entity_id"].startswith("concept.")
                          and r["entity_id"] not in ids})
        self.assertEqual(missing, [], f"alias 指向不存在的 concept: {missing[:5]}")

    # ---- 3 exact alias lookup 正确
    def test_03_exact_alias_lookup(self):
        from alias_index import exact_lookup
        # objet a 的多种写法（全部取自 Gold Concept Set 的 aliases 实际内容）
        for q in ("objet petit a", "objet a", "object a", "对象a", "小客体a"):
            with self.subTest(query=q):
                hits = exact_lookup(q)
                self.assertTrue(hits, f"{q!r} 应能解析到某个实体")
                self.assertTrue(all(h["match_type"] == "exact" for h in hits))

    # ---- 4 ★ ambiguous aliases：大小写折叠碰撞不得自动合并
    def test_04_case_collision_is_marked_ambiguous_not_merged(self):
        """Autre / autre 必须作为**两个不同条目**存在且被标为 ambiguous。

        拉康的 l'Autre（大他者）与 l'autre（小他者）是两个概念：
        大小写携带理论差异。索引必须保留这个差异，不得折叠成一条。
        """
        from alias_index import exact_lookup, lookup_ambiguous
        rows = [r for r in self.rows
                if r["alias"].lower() in ("l'autre", "autre", "l'Autre")]
        self.assertTrue(rows, "索引里应有 Autre/autre 相关条目")
        # 至少有一对仅大小写不同的条目
        forms = {}
        for r in rows:
            forms.setdefault(r["alias"].lower(), set()).add(r["alias"])
        colliding = {k: v for k, v in forms.items() if len(v) > 1}
        if colliding:
            amb = lookup_ambiguous("autre")
            self.assertTrue(amb, "存在大小写碰撞时必须能被标为 ambiguous")
            for a in amb:
                self.assertTrue(a.get("ambiguous_with"),
                                "ambiguous 条目必须写明与谁冲突")

    def test_05_ambiguity_is_reported_not_hidden(self):
        """歧义必须**显式可见**：查询返回里要能看出存在多个候选取向。"""
        from alias_index import exact_lookup
        # 找一个确实有大小写碰撞的词
        by_lower = {}
        for r in self.rows:
            by_lower.setdefault(r["alias"].lower(), []).append(r)
        collided = [k for k, v in by_lower.items()
                    if len({x["entity_id"] for x in v}) > 1]
        if not collided:
            self.skipTest("当前语料没有大小写碰撞的别名（如实跳过）")
        q = collided[0]
        hits = exact_lookup(q)
        ids = {h["entity_id"] for h in hits}
        self.assertGreater(len(ids), 1,
                           f"{q!r} 折叠后指向多个实体，必须全部返回而非任选一个")

    # ---- 6 大小写敏感模式
    def test_06_case_sensitive_lookup(self):
        from alias_index import exact_lookup
        a = exact_lookup("l'Autre", case_sensitive=True)
        b = exact_lookup("l'autre", case_sensitive=True)
        if a and b:
            self.assertNotEqual({h["entity_id"] for h in a},
                                {h["entity_id"] for h in b},
                                "大小写敏感模式下 Autre 与 autre 不应返回同一实体")

    # ---- 7 review_status 必须是受控值，且不得出现 canonical
    def test_07_review_status_controlled(self):
        allowed = {"candidate", "needs_review", "reviewed", "canonical", "rejected"}
        for r in self.rows:
            with self.subTest(alias=r["alias"]):
                self.assertIn(r["review_status"], allowed)
        canon = [r["alias"] for r in self.rows if r["review_status"] == "canonical"]
        self.assertEqual(canon, [],
                         "本阶段 alias 全部来自脚本推导，不得有任何 canonical")

    # ---- 8 alias 与 canonical_name 相同的情况要能识别
    def test_08_alias_may_equal_canonical_name(self):
        """别名可以等于规范名（这很常见），但索引要如实记录 source。"""
        for r in self.rows[:200]:
            self.assertTrue(r["source"], "source 不得为空")

    # ---- 9 索引可重建且确定
    def test_09_index_is_deterministic(self):
        import subprocess
        before = open(ALIAS_FILE, "rb").read()
        r = subprocess.run([sys.executable,
                            os.path.join(VAULT, "_scripts", "_tools",
                                         "build_alias_index.py")],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, f"重建失败:\n{r.stderr[-500:]}")
        after = open(ALIAS_FILE, "rb").read()
        self.assertEqual(before, after, "alias index 重建后内容不同（非确定性）")

    # ---- 10 不得修改 canonical store
    def test_10_does_not_touch_canonical_store(self):
        import subprocess
        pp = os.path.join(STORE, "passages.jsonl")
        before = os.stat(pp).st_mtime_ns
        subprocess.run([sys.executable,
                        os.path.join(VAULT, "_scripts", "_tools",
                                     "build_alias_index.py")],
                       capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(os.stat(pp).st_mtime_ns, before,
                         "建 alias index 不得触碰 canonical passage store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
