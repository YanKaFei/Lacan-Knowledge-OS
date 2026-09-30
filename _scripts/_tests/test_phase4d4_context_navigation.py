#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §14/§15/§51：Context 导航 / 语言对译 / Copy Citation"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L


class ContextNavigation(unittest.TestCase):
    def test_00_window_sizes_clamped_and_centered(self):
        for n in (2, 5, 10):
            d = L.X.context_window(L.P_L1, n, n)
            self.assertEqual(d["before"], n)
            self.assertEqual(d["after"], n)
            self.assertLessEqual(len(d["items"]), 2 * n + 1)
            self.assertIsNotNone(d["target_index"])
            self.assertTrue(d["items"][d["target_index"]]["is_target"])

    def test_01_clamp_beyond_limits(self):
        d = L.X.context_window(L.P_L1, 999, 999)
        self.assertLessEqual(d["before"], 20)
        self.assertLessEqual(d["after"], 20)

    def test_02_previous_next_are_contiguous(self):
        """§14：Previous/Next 必须落在相邻段，且不一次载入整个 corpus。"""
        d = L.X.context_window(L.P_L1, 2, 2)
        ids = [x["passage_id"] for x in d["items"]]
        i = d["target_index"]
        self.assertLess(len(ids), 50)
        if i > 0:
            prev = L.X.passage_detail(ids[i - 1])
            self.assertIsNotNone(prev)
        if i < len(ids) - 1:
            nxt = L.X.passage_detail(ids[i + 1])
            self.assertIsNotNone(nxt)

    def test_03_open_session_targets_real_session(self):
        d = L.X.passage_detail(L.P_L1)
        sid = d["context"]["session"]
        self.assertTrue(sid)
        out = L.X.session_reading(sid, limit=3)
        self.assertTrue(out["items"])
        self.assertIn(L.P_L1.split(".")[1], sid)

    def test_04_no_alignment_is_stated_not_guessed(self):
        """§15：没有可靠对齐 → No aligned realization available；禁止按相似文本猜。"""
        l = L.B.realization_languages(L.P_L1)
        self.assertFalse(l["aligned_available"])
        self.assertIn("No aligned realization available.", l["note"])
        self.assertIn("never inferred from similar text", l["policy"])
        self.assertEqual(l["aligned"], [])
        # 同一 session 内确实只有一种语言（因此 side-by-side 无从谈起）
        self.assertEqual(l["available_languages"], ["fr"])

    def test_05_citation_never_invents_bibliography(self):
        """§51：只给存在的字段，绝不生成不存在的出版学 citation。"""
        c = L.X.citation_block(L.B.get_passage_view(L.P_L1))
        self.assertEqual(c["passage_id"], L.P_L1)
        self.assertIn("S11", c["short"])
        self.assertIn("P2253", c["short"])
        blob = (c["full"] + " " + c["note"]).lower()
        self.assertIn("no bibliographic citation is invented", blob)
        for invented in ("seuil, paris", "p. 1", "isbn", "(19"):
            self.assertNotIn(invented, (c["full"] + c["short"]).lower())
        self.assertIsNone(c.get("page"))
