#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §36：SOURCE_TRACE_INCOMPLETE 与 limitations 在导出后仍在。"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import adapter as A

class ProvenancePreservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("provenance")
        cls.l2 = A.save_passage(L.P_L2, vault=cls.v)
        cls.txt = L.note(cls.v, cls.l2["note"])

    def test_00_trace_incomplete_visible(self):
        self.assertIn("Source trace incomplete", self.txt)
        self.assertIn("未闭合到原始物理文件", self.txt)

    def test_01_frontmatter_records_provenance(self):
        from obsidian_adapter.frontmatter import parse_frontmatter
        meta, _ = parse_frontmatter(self.txt)
        self.assertEqual(meta["provenance_status"], "SOURCE_TRACE_INCOMPLETE")
        self.assertEqual(meta["source_layer"], "L2_RECOVERED")
        self.assertTrue(meta["witness"])

    def test_02_l1_note_has_complete_provenance(self):
        out = A.save_passage(L.P_L1, vault=self.v)
        from obsidian_adapter.frontmatter import parse_frontmatter
        meta, _ = parse_frontmatter(L.note(self.v, out["note"]))
        self.assertEqual(meta["provenance_status"], "COMPLETE")

    def test_03_limitations_preserved_in_research_note(self):
        out = L.save(self.v)
        txt = L.note(self.v, out["research_note"])
        v = L.view()
        for lim in v["limitations"]:
            self.assertIn(lim[:30], txt)

    def test_04_source_layer_readable_label(self):
        self.assertIn("recovered/translated", self.txt.lower())
