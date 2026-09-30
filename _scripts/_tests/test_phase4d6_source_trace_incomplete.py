#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §29/§66/§75：SOURCE_TRACE_INCOMPLETE 在所有格式保留"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class SourceTraceIncomplete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = EX.build_from_passage(L.P_L2, include_context=2)

    def test_00_structured_flag(self):
        self.assertTrue(self.doc["passage"]["trace_incomplete"])
        self.assertEqual(self.doc["passage"]["provenance_status"],
                         "SOURCE_TRACE_INCOMPLETE")
        self.assertEqual(self.doc["passage"]["source_layer"], "L2")
        self.assertTrue(self.doc["provenance"]["source_trace_incomplete"])

    def test_01_all_formats_keep_the_marker(self):
        texts = L.rendered(self.doc)
        texts["bundle"] = "".join(blob.decode("utf-8") for _r, blob in
                                  EX.bundle.build_files(self.doc)[0])
        for fmt, text in texts.items():
            self.assertIn("SOURCE_TRACE_INCOMPLETE", text, fmt)

    def test_02_explanation_present_everywhere(self):
        texts = L.rendered(self.doc)
        for fmt, text in texts.items():
            self.assertTrue("来源链" in text or "upstream" in text.lower()
                            or "witness" in text.lower(), fmt)

    def test_03_not_treated_as_broken_reference(self):
        """§66：来源链未闭合 ≠ broken reference，允许导出。"""
        with L.export_root("sti"):
            out = EX.build_bundle(self.doc)
            self.assertEqual(out["verify"]["status"], "VERIFIED")

    def test_04_bundle_manifest_records_it(self):
        with L.export_root("sti2"):
            out = EX.build_bundle(self.doc)
            prov = json.load(open(os.path.join(out["dir"], "provenance",
                                               "provenance.json"), encoding="utf-8"))
            self.assertTrue(prov["provenance"]["source_trace_incomplete"])
            payload = json.load(open(os.path.join(out["dir"], "passages",
                                                 "passage-S05-unknown-L05-P0056.json"),
                                    encoding="utf-8"))
            self.assertEqual(payload["provenance_status"], "SOURCE_TRACE_INCOMPLETE")

    def test_05_l1_passage_is_not_marked(self):
        d = EX.build_from_passage(L.P_L1)
        self.assertFalse(d["passage"]["trace_incomplete"])
        self.assertFalse(d["provenance"]["source_trace_incomplete"])
        for text in L.rendered(d).values():
            self.assertNotIn("SOURCE_TRACE_INCOMPLETE", text)

    def test_06_limitation_kept_even_without_limitations_list(self):
        self.assertIn("SOURCE_TRACE_INCOMPLETE",
                      EX.json_export.render(self.doc))
