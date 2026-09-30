#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-6/§15：provenance 往返 + SOURCE_TRACE_INCOMPLETE 原样保留。"""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _mcp_testlib as L                                        # noqa: E402

L1 = "passage.S11.unknown.P2253"        # fr L1 transcription
L2 = "passage.S05.unknown.L05.P0056"    # zh L2 recovered

class ProvenanceRoundTrip(unittest.TestCase):
    def test_00_trace_l1_complete(self):
        env = L.call("lacan.trace_source", {"passage_id": L1})
        self.assertTrue(env["ok"], env)
        r = env["result"]
        self.assertEqual(r["passage_id"], L1)
        self.assertEqual(r["trace_status"], "COMPLETE")
        self.assertEqual(r["source_layer"], "L1_TRANSCRIPTION")
        self.assertTrue(r["witness"])

    def test_01_trace_incomplete_is_preserved_verbatim(self):
        env = L.call("lacan.trace_source", {"passage_id": L2})
        self.assertTrue(env["ok"], env)
        r = env["result"]
        self.assertEqual(r["trace_status"], "SOURCE_TRACE_INCOMPLETE",
                         "L2 recovered 段落的溯源不完整状态被改写/隐藏了")
        self.assertEqual(r["source_layer"], "L2_RECOVERED")

    def test_02_provenance_not_downgraded_to_warning(self):
        env = L.call("lacan.trace_source", {"passage_id": L2})
        blob = L.canon(env["result"])
        self.assertIn("SOURCE_TRACE_INCOMPLETE", blob)
        self.assertNotIn("warnings", env["result"])

    def test_03_get_passage_agrees_with_trace_source(self):
        for pid in (L1, L2):
            a = L.call("lacan.get_passage", {"passage_id": pid})["result"]
            b = L.call("lacan.trace_source", {"passage_id": pid})["result"]
            self.assertEqual(a["trace_status"], b["trace_status"], pid)
            self.assertEqual(a["source_layer"], b["source_layer"], pid)
            self.assertEqual(a["seminar"], b["seminar"], pid)

    def test_04_chain_fields_present(self):
        r = L.call("lacan.trace_source", {"passage_id": L1})["result"]
        for k in ("corpus_source", "witness", "passage_realization", "seminar",
                  "session", "document", "edition", "source_layer", "trace_status",
                  "chain"):
            self.assertIn(k, r)

if __name__ == "__main__":
    unittest.main()
