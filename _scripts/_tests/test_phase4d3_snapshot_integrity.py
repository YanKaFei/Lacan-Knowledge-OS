#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §20：Research snapshot 完整性（VERIFIED / MODIFIED_BY_USER / UNKNOWN）。"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import adapter as A

class SnapshotIntegrity(unittest.TestCase):
    def setUp(self):
        """每个测试用**独立 vault**：避免上个测试的改动污染下个测试。"""
        self.v = L.fresh_vault("snapshot_%s" % self._testMethodName[:24])
        self.out = L.save(self.v)
        self.rel = self.out["research_note"]

    def test_00_verified_after_save(self):
        self.assertEqual(A.verify_snapshot(self.rel, vault=self.v)["status"], "VERIFIED")

    def test_01_modified_inside_generated_detected(self):
        txt = L.note(self.v, self.rel).replace("## Research Question", "## 改动过的问题")
        self.v.write(self.rel, txt)
        self.assertEqual(A.verify_snapshot(self.rel, vault=self.v)["status"],
                         "MODIFIED_BY_USER")

    def test_02_user_zone_edit_does_not_invalidate(self):
        """用户区在 managed 区块外，编辑它不应被判为 MODIFIED。"""
        txt = L.note(self.v, self.rel)
        self.v.write(self.rel, txt + "\n补充一行用户笔记\n")
        self.assertEqual(A.verify_snapshot(self.rel, vault=self.v)["status"], "VERIFIED")

    def test_03_unknown_for_missing_note(self):
        self.assertEqual(A.verify_snapshot("Research/nope.md", vault=self.v)["status"],
                         "UNKNOWN")

    def test_04_source_answer_hash_recorded(self):
        from obsidian_adapter.frontmatter import parse_frontmatter
        meta, _ = parse_frontmatter(L.note(self.v, self.rel))
        self.assertEqual(meta["source_answer_hash"], A.answer_hash(
            L.view()["raw"]["scholarly_payload"]))

    def test_05_verify_is_read_only(self):
        before = L.core_snapshot()
        A.verify_snapshot(self.rel, vault=self.v)
        self.assertEqual(L.POL.diff_snapshot(before, L.core_snapshot()), [])
