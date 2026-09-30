#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §28：保存的事务性（预检 → temp → 原子 rename → 失败回滚）。"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import adapter as A, vault as V

class AtomicSave(unittest.TestCase):
    def setUp(self):
        self.v = L.fresh_vault("atomic")

    def test_00_preflight_rejects_before_any_write(self):
        tx = self.v.transaction()
        tx.stage("Research/ok.md", "hello")
        with self.assertRaises(V.VaultError):
            tx.stage("../escape.md", "nope")
        self.assertEqual(L.all_md(self.v), [], "预检失败不得留下任何文件")

    def test_01_commit_writes_all_and_no_temp_left(self):
        tx = self.v.transaction()
        tx.stage("Research/a.md", "A"); tx.stage("Passages/b.md", "B")
        tx.commit()
        self.assertEqual(L.all_md(self.v), ["Passages/b.md", "Research/a.md"])
        left = [f for _r, _d, fs in os.walk(self.v.root) for f in fs if ".tmp-" in f]
        self.assertEqual(left, [], "残留临时文件：%s" % left)

    def test_02_failure_rolls_back_partial_writes(self):
        tx = self.v.transaction()
        tx.stage("Research/keep.md", "K")
        orig = self.v.write
        calls = {"n": 0}
        def flaky(rel, text, atomic=True):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("disk full (simulated)")
            return orig(rel, text, atomic=atomic)
        self.v.write = flaky
        try:
            tx.stage("Research/second.md", "S")
            with self.assertRaises(RuntimeError):
                tx.commit()
        finally:
            self.v.write = orig
        self.assertEqual(L.all_md(self.v), [], "回滚后不应留下半套文件")

    def test_03_existing_file_restored_on_rollback(self):
        self.v.write("Research/existing.md", "ORIGINAL")
        tx = self.v.transaction()
        orig = self.v.write
        calls = {"n": 0}
        def flaky(rel, text, atomic=True):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("boom")
            return orig(rel, text, atomic=atomic)
        self.v.write = flaky
        try:
            tx.stage("Research/existing.md", "CHANGED")
            tx.stage("Research/other.md", "X")
            with self.assertRaises(RuntimeError):
                tx.commit()
        finally:
            self.v.write = orig
        self.assertEqual(self.v.read("Research", "existing.md"), "ORIGINAL")

    def test_04_save_research_reports_failure_without_partial_notes(self):
        orig = self.v.write
        def always_fail(rel, text, atomic=True):
            raise RuntimeError("readonly fs (simulated)")
        self.v.write = always_fail
        try:
            out = L.save(self.v)
        finally:
            self.v.write = orig
        self.assertFalse(out.get("ok"), out)
        self.assertEqual(out.get("error"), "SAVE_FAILED")
