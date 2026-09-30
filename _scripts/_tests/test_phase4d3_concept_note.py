#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §15/§16/§31/§33：Concept Reference Hub（不是 canonical 定义）。"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L

class ConceptNote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("concept_note"); cls.out = L.save(cls.v)

    def test_00_hub_created_for_referenced_concepts(self):
        self.assertTrue(self.out["concept_notes"])
        for rel in self.out["concept_notes"]:
            self.assertTrue(self.v.exists(rel), rel)

    def test_01_frontmatter_is_reference_only(self):
        from obsidian_adapter.frontmatter import parse_frontmatter
        txt = L.note(self.v, self.out["concept_notes"][0]); meta, _ = parse_frontmatter(txt)
        self.assertEqual(meta["type"], "lacan-concept")
        self.assertEqual(meta["canonical_source"], "scholarly-core")
        self.assertIn("concept_id", meta)

    def test_02_no_answer_as_definition(self):
        txt = L.note(self.v, self.out["concept_notes"][0])
        self.assertIn("workspace reference hub", txt)
        self.assertNotIn("## Definition", txt)
        v = L.view()
        for c in v["claims"]:
            self.assertNotIn(str(c["claim_text"])[:30], txt,
                             "研究 claim 不得写进概念页")

    def test_03_related_research_section(self):
        txt = L.note(self.v, self.out["concept_notes"][0])
        self.assertIn("## Related Research", txt)
        self.assertIn("[[Research/", txt)

    def test_04_aliases_only_from_canonical(self):
        from obsidian_adapter.frontmatter import parse_frontmatter
        txt = L.note(self.v, self.out["concept_notes"][1]); meta, _ = parse_frontmatter(txt)
        if "aliases" in meta:
            self.assertIsInstance(meta["aliases"], list)

    def test_05_user_zone_exists(self):
        self.assertIn("## My Notes", L.note(self.v, self.out["concept_notes"][0]))

    def test_06_related_research_accumulates(self):
        """§18：概念页 Related Research 是累积的 —— 第二次研究不得抹掉第一次的链接。"""
        from obsidian_adapter import adapter as A
        v = L.fresh_vault("concept_note_accum")
        o1 = L.save(v, question=L.Q_GAZE)
        o2 = L.save(v, question=L.Q_GAZE, create_snapshot=True)
        for rel in o2["concept_notes"]:
            sec = L.note(v, rel).split("## Related Research")[1].split("## Saved Passages")[0]
            self.assertIn(o1["research_note"][:-3], sec, rel)
            self.assertIn(o2["research_note"][:-3], sec, rel)
        rel = o2["concept_notes"][0]
        from obsidian_adapter.frontmatter import parse_frontmatter
        cid = parse_frontmatter(L.note(v, rel))[0]["concept_id"]
        A.ensure_concept_note(cid, vault=v)          # 默认空列表：不得清空
        sec = L.note(v, rel).split("## Related Research")[1].split("## Saved Passages")[0]
        self.assertIn(o1["research_note"][:-3], sec)
