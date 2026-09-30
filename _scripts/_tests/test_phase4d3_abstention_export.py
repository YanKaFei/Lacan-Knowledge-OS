#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §37/§43：弃权研究也能进知识库，且不制造任何 canonical 关系。"""
import json, os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L

class AbstentionExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("abstention"); cls.out = L.save(cls.v, question=L.Q_FMRI)
        cls.txt = L.note(cls.v, cls.out["research_note"])

    def test_00_saved_with_abstained_state(self):
        self.assertTrue(self.out["ok"])
        self.assertEqual(self.out["answer_state"], "ABSTAINED")

    def test_01_four_blocks_present(self):
        for sec in ("Why this cannot be answered", "Missing information",
                    "Available partial information", "Sources needed"):
            self.assertIn(sec, self.txt)

    def test_02_no_concept_or_passage_relations_created(self):
        self.assertEqual(self.out["concept_notes"], [])
        self.assertEqual(self.out["passage_notes"], [])

    def test_03_no_canonical_relation_written(self):
        blob = "".join(L.note(self.v, f) for f in L.all_md(self.v))
        for bad in ("DEFINED_IN", "RELATED_TO", "canonical_relation"):
            self.assertNotIn(bad, blob)

    def test_04_no_model_filler(self):
        for bad in ("however", "generally speaking", "it is known that"):
            self.assertNotIn(bad.lower(), self.txt.lower())

    def test_05_metadata_abstention_also_exported(self):
        out = L.save(self.v, question=L.Q_META)
        txt = L.note(self.v, out["research_note"])
        self.assertIn("Current corpus cannot support a reliable answer", txt)
        self.assertIn("Missing information", txt)
