#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-5/§9/§26：citation 必须可回溯（research → citation → get_passage → span）。"""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _mcp_testlib as L                                        # noqa: E402

Q = L.FROZEN_QUESTIONS["relation"]
OPTS = {"mode": "seminar_specific", "language": "fr", "provider": "mock"}

class CitationRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = L.call("lacan.research", dict(OPTS, question=Q))
        cls.citations = cls.env["result"]["citations"]

    def test_00_has_citations(self):
        self.assertTrue(self.citations, "本题应有可回溯 citation")

    def test_01_every_citation_resolves_to_stored_passage(self):
        for c in self.citations:
            env = L.call("lacan.get_passage", {"passage_id": c["passage_id"]})
            self.assertTrue(env["ok"], "citation 指向不存在的 passage：%s" % c["passage_id"])
            self.assertEqual(env["result"]["passage_id"], c["passage_id"])
            self.assertTrue(env["result"]["text"], "passage 无正文")

    def test_02_quoted_span_is_resolvable_in_passage_text(self):
        checked = 0
        for c in self.citations:
            if not c.get("quoted_span"):
                continue            # contextual/synthetic binding：按 CitationBinding policy 允许无 span
            env = L.call("lacan.get_passage", {"passage_id": c["passage_id"]})
            text = env["result"]["text"] or ""
            self.assertIn(c["quoted_span"].strip(), text,
                          "quoted_span 无法在 passage 原文中解析：%s" % c["passage_id"])
            checked += 1
        self.assertGreater(checked, 0, "至少应有一条 citation 带可解析的 quoted span")

    def test_03_citation_binding_fields(self):
        for c in self.citations:
            self.assertTrue(c["passage_id"])
            self.assertIn(c["source_layer"],
                          ("L1_TRANSCRIPTION", "L2_RECOVERED", "L1_EDITION", None))
            self.assertIn(c["provenance_status"],
                          ("COMPLETE", "SOURCE_TRACE_INCOMPLETE", None))

    def test_04_citations_match_api_layer(self):
        api_res = L.cached_research(Q, OPTS)
        self.assertEqual(L.canon(self.citations), L.canon(api_res["citations"]))

if __name__ == "__main__":
    unittest.main()
