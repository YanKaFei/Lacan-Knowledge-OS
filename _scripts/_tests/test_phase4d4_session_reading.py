#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §22/§23：Session Browser 与 Reading Mode"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key


class SessionReading(unittest.TestCase):
    def test_00_sessions_listed_in_lesson_order(self):
        out = L.X.sessions("S11")
        self.assertTrue(out["items"])
        lessons = [s["lesson"] for s in out["items"]]
        known = [x for x in lessons if x is not None]
        self.assertEqual(known, sorted(known))
        self.assertEqual(lessons, sorted(lessons, key=lambda x: (x is None, x or 0)))

    def test_01_session_without_lesson_is_last_and_marked(self):
        out = L.X.sessions("S11")
        last = out["items"][-1]
        if last["lesson"] is None:
            self.assertTrue(last["lesson_missing"])
            self.assertIn("no lesson number", last["note"])

    def test_02_reading_stream_is_corpus_order(self):
        """§22/§23：按原顺序连续阅读，顺序 = 语料顺序。"""
        out = L.X.session_reading(L.S_SESSION, limit=10)
        ids = [x["passage_id"] for x in out["items"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(out["page"]["total"], len(
            L.raw_ids("where session_id=?", (L.S_SESSION,))))
        self.assertTrue(out["reading_mode"])

    def test_03_reading_pages_are_contiguous(self):
        a = L.X.session_reading(L.S_SESSION, limit=10)
        b = L.X.session_reading(L.S_SESSION, limit=10, cursor=a["page"]["next_cursor"])
        ia = [x["passage_id"] for x in a["items"]]
        ib = [x["passage_id"] for x in b["items"]]
        self.assertEqual(set(ia) & set(ib), set())
        self.assertEqual(ib, sorted(ib))
        self.assertLess(ia[-1], ib[0])

    def test_04_reading_actions_stay_available(self):
        """§23：阅读模式保留 Save Passage / Copy Citation / Open Context。"""
        src = open(os.path.join(VAULT, "workspace_ui", "static", "src", "explorer.js"),
                   encoding="utf-8").read()
        self.assertIn("is-reading-mode", src)
        for label in ("Save Passage", "Copy Citation", "Open Context"):
            # P5D-004：文案已接入 i18n → 断言 key 接线 + 双语词典（比字面量 grep 更强）
            assert_text_wired(self, "explorer.js", label)

    def test_05_no_whole_corpus_load(self):
        out = L.X.session_reading(L.S_SESSION, limit=1000)
        self.assertLessEqual(len(out["items"]), 50)
