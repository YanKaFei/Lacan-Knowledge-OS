#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §34/§17/§18：provenance 与 L1/L2 —— SOURCE_TRACE_INCOMPLETE 必须可见且带解释。"""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key

class ProvenanceUX(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.l1 = L.panel(L.PASSAGE_L1)
        cls.l2 = L.panel(L.PASSAGE_L2)

    def test_00_l1_panel_complete(self):
        p = self.l1["passage"]
        self.assertEqual(p["passage_id"], L.PASSAGE_L1)
        self.assertEqual(self.l1["source_layer"]["code"], "L1_TRANSCRIPTION")
        self.assertEqual(self.l1["source_layer"]["tag"], "L1")
        self.assertFalse(self.l1["trace_incomplete"])
        self.assertTrue(p["witness"])

    def test_01_l2_shows_incomplete_and_explanation(self):
        self.assertEqual(self.l2["source_layer"]["code"], "L2_RECOVERED")
        self.assertEqual(self.l2["source_layer"]["tag"], "L2")
        self.assertTrue(self.l2["trace_incomplete"])
        self.assertIn("无法完整追溯", self.l2["trace_incomplete_note"])
        self.assertIn("source limitation", self.l2["trace_incomplete_note"])

    def test_02_incomplete_not_downgraded_to_plain_warning(self):
        """不是普通 warning：必须作为独立的 provenance 事实出现。"""
        self.assertEqual(self.l2["provenance"]["trace_status"], "SOURCE_TRACE_INCOMPLETE")
        self.assertEqual(self.l2["passage"]["trace_status"], "SOURCE_TRACE_INCOMPLETE")
        self.assertNotIn("warnings", self.l2)

    def test_03_context_window_preserves_order_and_ids(self):
        ids = [c["passage_id"] for c in self.l1["context"]]
        self.assertTrue(ids)
        self.assertIn(L.PASSAGE_L1, ids)
        env = L.mcp_envelope("lacan.get_context",
                             {"passage_id": L.PASSAGE_L1, "before": 3, "after": 3})
        self.assertEqual(ids, [i["passage_id"] for i in env["result"]["items"]])

    def test_04_chain_fields_surface(self):
        prov = self.l1["provenance"]
        for k in ("corpus_source", "witness", "seminar", "session", "source_layer",
                  "trace_status", "chain"):
            self.assertIn(k, prov)

    def test_05_aligned_translation_not_faked(self):
        self.assertIsNone(self.l2["aligned_translation"])
        self.assertEqual(self.l2["aligned_translation_note"],
                         "No aligned translation available")

    def test_06_ui_renders_trace_notice(self):
        src = L.js_sources()["inspector.js"]
        assert_text_wired(self, "inspector.js", "Source trace incomplete")  # P5D-004: 文案走 i18n key
        self.assertIn("trace_incomplete_note", src)

    def test_07_context_limit_clamped_by_server(self):
        from workspace_ui.server import api as UIA
        v = UIA.context_window(L.PASSAGE_L1, 999, 999)
        self.assertLessEqual(v["before"], 20)
        self.assertLessEqual(v["after"], 20)

if __name__ == "__main__":
    unittest.main()
