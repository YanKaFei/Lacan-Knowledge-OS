#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §17：Seminar Note（不伪造 bibliography）。"""
import os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L

class SeminarNote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("seminar_note"); cls.out = L.save(cls.v)

    def test_00_created_for_cited_seminars(self):
        self.assertTrue(self.out["seminar_notes"])
        for rel in self.out["seminar_notes"]:
            self.assertTrue(self.v.exists(rel), rel)

    def test_01_frontmatter(self):
        from obsidian_adapter.frontmatter import parse_frontmatter
        txt = L.note(self.v, self.out["seminar_notes"][0]); meta, _ = parse_frontmatter(txt)
        self.assertEqual(meta["type"], "lacan-seminar")
        self.assertIn("seminar_id", meta)

    def test_02_sections_and_no_fabricated_bibliography(self):
        txt = L.note(self.v, self.out["seminar_notes"][0])
        for sec in ("## Metadata", "## Saved Research", "## Saved Passages",
                    "## Concepts", "## My Notes"):
            self.assertIn(sec, txt)
        self.assertIn("不伪造", txt)

    def test_03_ensure_seminar_note_merges_managed_only(self):
        from obsidian_adapter import adapter as A
        rel = self.out["seminar_notes"][0]
        before = L.note(self.v, rel)
        A.ensure_seminar_note(before.split("\n")[1].split(":")[1].strip(), vault=self.v,
                              title="t", years=1964, languages=["fr"])
        after = L.note(self.v, rel)
        self.assertIn("## My Notes", after)
        self.assertEqual(before.split("## My Notes")[1], after.split("## My Notes")[1])

    def test_04_only_own_passages_listed(self):
        """§18：研讨班页只能列**本研讨班**的 passage。

        实测踩过：过滤条件写成 `_seminar_from_passage(basename.split(".")[0])`
        （传入 `S10`，正则永不匹配）→ 恒真 → S10 页里出现 S11 的段落。
        """
        for rel in self.out["seminar_notes"]:
            sid = L.seminar_short(self.v, rel)
            sec = L.note(self.v, rel).split("## Saved Passages")[1].split("## Concepts")[0]
            for t in re.findall(r"\[\[(Passages/([^.|\]]+)\.)", sec):
                self.assertEqual(t[1], sid, "%s 里列出了 %s 的段落" % (rel, t[1]))

    def test_05_accumulates_research_links(self):
        """参考页是累积的：第二次保存不得抹掉第一次的研究链接。"""
        v = L.fresh_vault("seminar_note_accum")
        o1 = L.save(v, question=L.Q_GAZE)
        o2 = L.save(v, question=L.Q_GAZE, create_snapshot=True)
        self.assertNotEqual(o1["research_note"], o2["research_note"])
        for rel in o2["seminar_notes"]:
            sec = L.note(v, rel).split("## Saved Research")[1].split("## Saved Passages")[0]
            self.assertIn(o1["research_note"][:-3], sec, rel)
            self.assertIn(o2["research_note"][:-3], sec, rel)
        # ensure_seminar_note（默认空列表）同样不得清空已有链接
        rel = o2["seminar_notes"][0]
        sid = L.seminar_short(v, rel)
        from obsidian_adapter import adapter as A
        A.ensure_seminar_note(sid, vault=v)
        sec = L.note(v, rel).split("## Saved Research")[1].split("## Saved Passages")[0]
        self.assertIn(o1["research_note"][:-3], sec)
