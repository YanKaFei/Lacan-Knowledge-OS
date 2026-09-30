#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §10/§11/§12/§35/§60：Saved Passage Note。"""
import os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L

class PassageNote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("passage_note"); cls.out = L.save(cls.v)
        cls.rels = cls.out["passage_notes"]

    def test_00_only_cited_passages_materialized(self):
        v = L.view()
        self.assertEqual(len(self.rels), len(v["citations"]))
        self.assertLess(len(self.rels), 50, "§60：不得因一次研究生成海量 note")

    def test_01_frontmatter_marks_snapshot(self):
        from obsidian_adapter.frontmatter import parse_frontmatter
        txt = L.note(self.v, self.rels[0]); meta, _ = parse_frontmatter(txt)
        self.assertEqual(meta["type"], "lacan-passage")
        self.assertTrue(meta["read_only_source"])
        self.assertTrue(meta["source_snapshot"])
        self.assertEqual(meta["context_snapshot"], 2)
        self.assertIn("passage_id", meta)

    def test_02_body_has_passage_and_source(self):
        txt = L.note(self.v, self.rels[0])
        self.assertIn("## Passage", txt)
        self.assertIn("## Source", txt)
        self.assertIn("Canonical source", txt)
        self.assertIn("## My Notes", txt)

    def test_03_not_canonical_writeback(self):
        txt = L.note(self.v, self.rels[0])
        self.assertIn("只读快照", txt)
        self.assertNotIn("canonical write", txt.lower())

    def test_04_save_passage_explicit_and_idempotent(self):
        from obsidian_adapter import adapter as A
        o1 = A.save_passage(L.P_L2, vault=self.v)
        self.assertEqual(o1["status"], "saved")
        o2 = A.save_passage(L.P_L2, vault=self.v)
        self.assertEqual(o2["status"], "already_saved")

    def test_05_passage_note_verifiable(self):
        from obsidian_adapter import adapter as A
        self.assertEqual(A.verify_snapshot(self.rels[0], vault=self.v)["status"], "VERIFIED")

    def test_06_used_in_research_recorded_and_still_verifiable(self):
        """被引用的 passage 必须列出研究 note；且 used_in 计入生成区哈希（仍 VERIFIED）。

        实测踩过：先算 generated_body_hash、之后再补 `## Used in Research`，
        新保存的 note 立刻被判成 MODIFIED_BY_USER。
        """
        from obsidian_adapter import adapter as A
        for rel in self.rels:
            txt = L.note(self.v, rel)
            self.assertIn("## Used in Research", txt)
            sec = txt.split("## Used in Research")[1].split("## My Notes")[0]
            self.assertIn("[[Research/", sec, rel)
            self.assertEqual(A.verify_snapshot(rel, vault=self.v)["status"],
                             "VERIFIED", rel)

    def test_07_standalone_save_creates_seminar_hub_no_dangling_link(self):
        """显式保存单段（Inspector 的 Save Passage）时 seminar hub 必须存在。

        实测踩过：vault 里没有 `Seminars/S05.md`，passage note 里的
        `[[Seminars/S05]]` 是悬空链接 —— 图谱里是个幽灵节点。
        """
        from obsidian_adapter import adapter as A
        v = L.fresh_vault("passage_note_l2")
        out = A.save_passage(L.P_L2, vault=v)
        self.assertEqual(out["status"], "saved")
        self.assertTrue(out.get("seminar_note"), "save_passage 未建 seminar hub")
        self.assertTrue(v.exists(out["seminar_note"]))
        targets = re.findall(r"\[\[([^\]|]+)", L.note(v, out["note"]))
        self.assertTrue([t for t in targets if t.startswith("Seminars/")])
        for t in targets:
            self.assertTrue(v.exists(t + ".md"), "悬空链接：%s" % t)
