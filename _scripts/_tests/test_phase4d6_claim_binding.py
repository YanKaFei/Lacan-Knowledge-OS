#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §24/§25/§26：Claim ↔ Citation 绑定与 quoted span"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class ClaimBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.view = L.view()
        cls.doc = EX.build_from_answer(cls.view)

    def test_00_bindings_present(self):
        b = self.doc["claim_bindings"]
        self.assertEqual(len(b["bindings"]), len(self.doc["claims"]))
        for row in b["bindings"]:
            self.assertIn("claim_id", row)
            self.assertIn("citation_ids", row)

    def test_01_binding_matches_view(self):
        for claim in self.view["claims"]:
            cid = claim["claim_id"]
            expected = sorted(c["passage_id"] for c in self.view["citations"]
                              if c.get("claim_id") == cid)
            got = sorted(next((r["citation_ids"] for r in
                               self.doc["claim_bindings"]["bindings"]
                               if r["claim_id"] == cid), []))
            self.assertEqual(got, expected, cid)

    def test_02_no_flat_bibliography_only(self):
        """§25：不能只导出一份扁平 bibliography 而丢掉 claim–evidence 关系。"""
        md = EX.markdown.render(self.doc)
        self.assertIn("### Claim `", md)
        self.assertIn("Evidence:", md)
        seen_claims = sum(1 for c in self.doc["claims"]
                          if c["claim_id"] in md)
        self.assertEqual(seen_claims, len(self.doc["claims"]))

    def test_03_quoted_span_kept_but_truncated(self):
        """§26：quoted span 保留，但不为了漂亮扩成整段。"""
        d = EX.build_from_passage(L.P_L1)
        rec = d["citations"][0]
        self.assertIn("quoted_span", rec)

    def test_04_unbound_citations_reported(self):
        d = L.doc()
        d["citations"] = d["citations"] + [dict(d["citations"][0], claim_id="ghost")]
        b = EX.citation_bindings(d["claims"], d["citations"])
        self.assertEqual(len(b["unbound_citations"]), 1)

    def test_05_claim_text_not_rewritten(self):
        for a, b in zip(self.view["claims"], self.doc["claims"]):
            self.assertEqual(a["claim_text"], b["claim_text"])

    def test_06_epistemic_status_exported(self):
        for c in self.doc["claims"]:
            self.assertIn("epistemic_label", c)
            self.assertIn("claim_type", c)
