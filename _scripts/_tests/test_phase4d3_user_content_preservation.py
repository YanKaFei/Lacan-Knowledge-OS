#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §13/§14/§47：用户区逐字保留。"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import adapter as A

USER = "这是用户自己写的文字。\n\n- 一条笔记\n- 又一条 🎓\n"

class UserContentPreservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("user_content"); cls.out = L.save(cls.v)

    def _inject(self, rel):
        txt = L.note(self.v, rel); i = txt.find("## My Notes")
        new = txt[:i] + "## My Notes\n\n" + USER
        self.v.write(rel, new); return new

    def test_00_concept_hub_user_text_preserved(self):
        rel = self.out["concept_notes"][0]; self._inject(rel)
        A.ensure_concept_note("concept.objet-petit-a", vault=self.v,
                              related_research=["Research/other.md"])
        after = L.note(self.v, rel)
        self.assertIn(USER, after, "用户文字被改动")

    def test_01_passage_note_user_text_preserved_across_resave(self):
        rel = self.out["passage_notes"][0]; self._inject(rel)
        L.save(self.v, create_snapshot=True)
        self.assertIn(USER, L.note(self.v, rel))

    def test_02_seminar_user_text_preserved(self):
        rel = self.out["seminar_notes"][0]; self._inject(rel)
        A.ensure_seminar_note("seminar.S11", vault=self.v, title="x")
        self.assertIn(USER, L.note(self.v, rel))

    def test_03_user_edits_inside_generated_block_are_detected_not_lost(self):
        rel = self.out["research_note"]
        txt = L.note(self.v, rel).replace("## Research Question", "## 我的问题")
        self.v.write(rel, txt)
        self.assertEqual(A.verify_snapshot(rel, vault=self.v)["status"], "MODIFIED_BY_USER")
        self.assertIn("## 我的问题", L.note(self.v, rel))
