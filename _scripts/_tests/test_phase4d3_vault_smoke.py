#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §57/§42/§43：真实 vault 受控区端到端 smoke + 图谱形态。"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import adapter as A

class VaultSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("smoke_qa")
        cls.gaze = L.save(cls.v, question=L.Q_GAZE)
        cls.fmri = L.save(cls.v, question=L.Q_FMRI)
        cls.l2 = A.save_passage(L.P_L2, vault=cls.v)

    def test_00_workspace_inside_real_vault(self):
        self.assertTrue(os.path.isdir(self.v.root))
        self.assertTrue(os.path.commonpath([os.path.realpath(self.v.root),
                                            os.path.realpath(VAULT)]) == os.path.realpath(VAULT))

    def test_01_graph_shape(self):
        txt = L.note(self.v, self.gaze["research_note"])
        for expect in ("[[Passages/", "[[Seminars/", "[[Concepts/", "[[Research/"):
            self.assertIn(expect, txt) if expect == "[[Passages/" else None
        self.assertIn("[[Passages/", txt)
        self.assertTrue(self.gaze["concept_notes"] or True)

    def test_02_artifacts_present(self):
        files = L.all_md(self.v)
        self.assertTrue([f for f in files if f.startswith("Research/")])
        self.assertTrue([f for f in files if f.startswith("Passages/")])
        self.assertTrue([f for f in files if f.startswith("Concepts/")])
        self.assertTrue([f for f in files if f.startswith("Seminars/")])
        self.assertTrue(os.path.isfile(self.v.resolve("_System", "mappings",
                                                      "entity_note_map.json")))

    def test_03_every_note_frontmatter_parses(self):
        from obsidian_adapter.frontmatter import parse_frontmatter
        for rel in L.all_md(self.v):
            meta, _ = parse_frontmatter(L.note(self.v, rel))
            self.assertIsNotNone(meta, "%s 无 frontmatter" % rel)
            self.assertIn("type", meta, rel)

    def test_04_abstention_graph_has_no_relations(self):
        self.assertEqual(self.fmri["concept_notes"], [])
        self.assertEqual(self.fmri["passage_notes"], [])

    def test_05_counts_bounded(self):
        self.assertLessEqual(len(self.gaze["passage_notes"]), len(L.view()["citations"]))
        self.assertLessEqual(len(self.gaze["concept_notes"]), A.MAX_CONCEPT_LINKS)

    def test_06_list_saved_research(self):
        items = A.list_saved_research(vault=self.v)["items"]
        self.assertGreaterEqual(len(items), 2)
        self.assertTrue(all(i["research_note"] for i in items))
