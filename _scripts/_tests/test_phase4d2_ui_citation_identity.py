#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §35：citation 同一性 —— chip 只加显示标签，不改 passage_id/span/layer/provenance。"""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402

class CitationIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = L.mcp_payload(L.QUESTION_RELATION, mode="seminar_specific", language="fr")
        cls.payload = cls.env["result"]
        cls.view = L.answer(L.QUESTION_RELATION, mode="seminar_specific", language="fr")

    def test_00_same_count_and_order(self):
        self.assertEqual(len(self.view["citations"]), len(self.payload["citations"]))

    def test_01_citation_fields_verbatim(self):
        for a, b in zip(self.view["citations"], self.payload["citations"]):
            self.assertEqual(a["passage_id"], b["passage_id"])
            self.assertEqual(a["claim_id"], b["claim_id"])
            self.assertEqual(a["quoted_span"], b["quoted_span"])
            self.assertEqual(a["source_layer"], b["source_layer"])
            self.assertEqual(a["provenance_status"], b["provenance_status"])

    def test_02_label_is_derivation_only(self):
        for c in self.view["citations"]:
            self.assertTrue(c["label"].startswith("[") and c["label"].endswith("]"))
            core = c["passage_id"].split(".")
            self.assertIn(core[1], c["label"])
            self.assertIn(core[-1], c["label"])

    def test_03_chip_resolves_to_stored_passage(self):
        for c in self.view["citations"]:
            env = L.mcp_envelope("lacan.get_passage", {"passage_id": c["passage_id"]})
            self.assertTrue(env["ok"], c["passage_id"])
            self.assertEqual(env["result"]["passage_id"], c["passage_id"])

    def test_04_span_resolvable_when_present(self):
        checked = 0
        for c in self.view["citations"]:
            if not c["quoted_span"]:
                continue
            env = L.mcp_envelope("lacan.get_passage", {"passage_id": c["passage_id"]})
            self.assertIn(c["quoted_span"].strip(), env["result"]["text"] or "")
            checked += 1
        self.assertGreater(checked, 0)

    def test_05_no_substituted_citation(self):
        payload_ids = [c["passage_id"] for c in self.payload["citations"]]
        view_ids = [c["passage_id"] for c in self.view["citations"]]
        self.assertEqual(payload_ids, view_ids)

if __name__ == "__main__":
    unittest.main()
