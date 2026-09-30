#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §18/§52/§42：wikilink 合法性与图谱形态。"""
import os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import links as K

class Links(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("links"); cls.out = L.save(cls.v)
        cls.txt = L.note(cls.v, cls.out["research_note"])

    def test_00_citation_wikilinks_resolve_to_notes(self):
        links = re.findall(r"\[\[([^\]|]+)", self.txt)
        targets = [l for l in links if l.startswith("Passages/")]
        self.assertTrue(targets)
        for t in targets:
            self.assertTrue(self.v.exists(t + ".md"), "链路指向不存在的 note：%s" % t)

    def test_01_research_links_to_concepts_and_seminars(self):
        links = " ".join(re.findall(r"\[\[([^\]|]+)", self.txt))
        self.assertIn("Concepts/", links)
        self.assertIn("Seminars/", links)

    def test_02_special_chars_sanitised(self):
        self.assertEqual(K.wikilink("A/b|c.md", "x]y"), "[[A/bc|xy]]")  # target 里的 | 必须去掉
        self.assertNotIn("]]]", K.wikilink("a]b.md"))

    def test_03_no_self_maintained_backlink_db(self):
        """§18：不自己维护重复的 backlink 数据库（Obsidian 原生 backlink 足够）。"""
        files = L.all_md(self.v)
        self.assertFalse([f for f in files if "backlink" in f.lower()])

    def test_04_graph_edges_are_workspace_only(self):
        """§19/§43：workspace 链接不得被写成 canonical ontology relation。"""
        blob = "".join(L.note(self.v, f) for f in L.all_md(self.v))
        self.assertNotIn("RELATED_TO", blob)
        self.assertNotIn("canonical_relation", blob)

    def test_05_no_dangling_wikilinks_anywhere(self):
        """§18/§42：vault 里**任何** note 的任何 wikilink/embed 都必须指向存在的文件。

        实测踩过：passage note 写好了 `[[Seminars/S05]]`，但 vault 里没有
        `Seminars/S05.md` —— Obsidian 图谱里就是一个悬空节点。
        「链路可浏览」= 没有悬空目标。
        """
        from obsidian_adapter import adapter as A
        v = L.fresh_vault("links_dangling")
        L.save(v, question=L.Q_GAZE)
        A.save_passage(L.P_L2, vault=v)                  # 显式保存单段
        present = set(L.all_md(v))
        missing = []
        for rel in present:
            for t in L.links_in(L.note(v, rel)):
                if t + ".md" not in present:
                    missing.append("%s → %s" % (rel, t))
        self.assertEqual(missing, [], "悬空 wikilink：%s" % missing)

    def test_06_used_in_entries_single_bullet(self):
        """回归：纯文本条目不产生 `- - x`（双项目符号 + 多余空行）。"""
        from obsidian_adapter.adapter import _used_in_entries
        self.assertEqual(_used_in_entries("res-abc123"), ["res-abc123"])
        self.assertEqual(_used_in_entries(["Research/a b.md"]), ["[[Research/a b]]"])
        self.assertEqual(_used_in_entries(None), [])
        for e in _used_in_entries(["res-abc123", "Research/a b.md"]):
            self.assertFalse(e.startswith("- "), e)

    def test_07_corpus_asset_embeds_become_plain_text(self):
        """§12/§49：corpus 资产不拷进 vault → 不得留下 `![[corpus 路径]]` 破图嵌入。"""
        from obsidian_adapter import adapter as A
        v = L.fresh_vault("links_asset")
        out = A.save_passage(L.P_L2, vault=v)
        txt = L.note(v, out["note"])
        self.assertNotIn("![[", txt, "工作区笔记里不得出现 embed 语法")
        self.assertIn("[asset:", txt, "资产路径应以纯文本保留（可回查）")
        self.assertIn("image21.jpeg", txt)
