#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §7/§8/§9：Research Note 生成与不变量。"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L

class ResearchNote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = L.fresh_vault("research_note"); cls.out = L.save(cls.v)
        cls.txt = L.note(cls.v, cls.out["research_note"])

    def test_00_saved_under_workspace_layout(self):
        self.assertTrue(self.out["ok"], self.out)
        self.assertTrue(self.out["research_note"].startswith("Research/"))
        self.assertTrue(self.v.exists(self.out["research_note"]))

    def test_01_frontmatter_fields(self):
        from obsidian_adapter.frontmatter import parse_frontmatter
        meta, _ = parse_frontmatter(self.txt)
        for k in ("type","status","created","research_id","request_id","task_type",
                  "answer_state","answer_permission","provider","core_freeze_version",
                  "source_answer_hash","citation_count","seminars"):
            self.assertIn(k, meta, "缺 frontmatter 字段 %s" % k)
        self.assertEqual(meta["type"], "lacan-research")
        self.assertNotIn("confidence", meta)

    def test_02_question_and_answer_verbatim(self):
        v = L.view()
        for s in v["sections"]:
            if s["internal"]: continue
            self.assertIn(str(s["text"]).strip().split("\n")[0][:40], self.txt)

    def test_03_claims_and_limitations_preserved(self):
        v = L.view()
        for c in v["claims"]:
            self.assertIn(str(c["claim_text"])[:30], self.txt)
        for lim in v["limitations"]:
            self.assertIn(lim[:30], self.txt)

    def test_04_user_zone_present(self):
        self.assertIn("## My Notes", self.txt)

    def test_05_idempotent_by_research_id(self):
        again = L.save(self.v)
        self.assertEqual(again["status"], "already_saved")
        self.assertEqual(len([f for f in L.all_md(self.v) if f.startswith("Research/")]), 1)

    def test_06_duplicate_safe_naming_for_new_snapshot(self):
        out2 = L.save(self.v, create_snapshot=True)
        self.assertEqual(out2["status"], "saved")
        self.assertNotEqual(out2["research_note"], self.out["research_note"])
        self.assertIn("(2)", out2["research_note"])

    def test_07_manifest_written(self):
        import json as _j
        man = _j.load(open(self.v.resolve(self.out["manifest"]), encoding="utf-8"))
        for k in ("research_id","saved_at","source_answer_hash","research_note_path",
                  "passage_note_paths","concept_note_paths","seminar_note_paths",
                  "core_freeze_version"):
            self.assertIn(k, man)
