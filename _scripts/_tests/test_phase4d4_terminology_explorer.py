#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §27–§31/§58-C：Terminology Explorer（Mapping / Attestation / Interpretation）"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key


class TerminologyExplorer(unittest.TestCase):
    def test_00_three_zones_always_separate(self):
        """§28：页面必须明确拆成 Mapping / Attestation / Interpretation。"""
        d = L.X.terminology_detail("jouissance")
        self.assertEqual([z["id"] for z in d["zones"]],
                         ["mapping", "attestation", "interpretation"])
        for k in ("mapping", "attestation", "interpretation"):
            self.assertIn(k, d)
        self.assertIn("ontology", d["mapping"]["source"])
        self.assertIn("corpus", d["attestation"]["source"])

    def test_01_mapping_never_implies_corpus_attestation(self):
        """§29/§33：有 mapping ≠ 语料出现过。"""
        d = L.X.terminology_detail("jouissance")
        self.assertIn("does NOT mean the corpus attests", d["mapping"]["warning"])
        self.assertIn("NOT ontology evidence", d["attestation"]["label"])

    def test_02_case_c_jouissance_zones(self):
        """§58 Case C：jouissance 必须区分 mapping / attestation / interpretation。"""
        d = L.X.terminology_detail("jouissance")
        forms = {r["form"] for r in d["attestation"]["rows"]}
        self.assertTrue({"jouissance", "快感"} <= forms, forms)
        got = {r["form"]: r["hits"] for r in d["attestation"]["rows"]}
        self.assertGreater(got["jouissance"], 1000)
        self.assertGreater(got["快感"], 0)
        self.assertFalse(d["interpretation"]["generated"])
        self.assertIsNone(d["interpretation"]["answer"])
        self.assertEqual(d["interpretation"]["action"]["tool"],
                         "lacan.research_translation")

    def test_03_zero_attestation_is_shown_not_hidden(self):
        """§30：0 就是 0，必须显示 Zero corpus attestation。"""
        d = L.X.terminology_detail("jouissance")
        zeros = [r for r in d["attestation"]["rows"] if r["hits"] == 0]
        self.assertTrue(zeros, "该案例应含 0 命中的写法（如 原乐）")
        self.assertTrue(all(r["zero"] for r in zeros))
        self.assertEqual(sorted(d["attestation"]["zero_forms"]),
                         sorted(r["form"] for r in zeros))
        d2 = L.X.terminology_detail("原乐")
        self.assertTrue(d2["attestation"]["rows"])
        self.assertEqual(d2["attestation"]["rows"][0]["hits"], 0)

    def test_04_attestation_matches_an_independent_count(self):
        """计数必须与独立实现一致（不靠缓存自证）。"""
        import sqlite3
        con = sqlite3.connect("file:%s?mode=ro" % L.LEX, uri=True)
        try:
            for form in ("jouissance", "快感", "原乐"):
                real = con.execute("select count(*) from passage_meta where raw_text like ?",
                                   ("%" + form + "%",)).fetchone()[0]
                got = L.B.attestation(form)["hits"]
                self.assertEqual(got, real, form)
        finally:
            con.close()

    def test_05_list_and_lookup(self):
        out = L.X.terminology_list(query="jouissance", limit=10)
        self.assertTrue(out["items"])
        self.assertTrue(all("jouissance" in r["term"].lower() or
                            "jouissance" in (r["label"] or "").lower()
                            for r in out["items"]))
        self.assertIn("Mapping", out["zones"])

    def test_06_unknown_term_returns_none(self):
        self.assertIsNone(L.B.get_term_view("zzz-not-a-term-zzz"))

    def test_07_interpretation_requires_explicit_research(self):
        src = open(os.path.join(VAULT, "workspace_ui", "static", "src", "explorer.js"),
                   encoding="utf-8").read()
        assert_text_wired(self, "explorer.js", "not generated")
        self.assertIn("translation-research", src)
