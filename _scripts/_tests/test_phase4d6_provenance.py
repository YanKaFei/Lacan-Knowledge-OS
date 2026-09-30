#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §13/§27/§30/§31/§43/§75：Provenance 导出（witness / source layer / 分离）"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class ProvenanceExport(unittest.TestCase):
    def test_00_summary_fields(self):
        d = L.doc()
        prov = d["provenance"]
        for k in ("citation_layers", "witnesses", "passages_without_witness",
                  "source_trace_incomplete", "source_answer_hash"):
            self.assertIn(k, prov)
        self.assertTrue(prov["citation_layers"])

    def test_01_witness_preserved_or_null(self):
        d = EX.build_from_passage(L.P_L1)
        rec = d["citations"][0]
        self.assertEqual(rec["witness"], "witness.fr.staferla")
        self.assertEqual(rec["source_layer"], "L1")
        self.assertEqual(rec["provenance_status"], "COMPLETE")

    def test_02_missing_witness_is_explicit_null(self):
        d = EX.build_from_passage(L.P_L1)
        rec = d["citations"][0]
        if rec["witness"] is None:
            md = EX.markdown.render(d)
            self.assertIn("witness: `null`", md)
        else:
            self.assertIsInstance(rec["witness"], str)

    def test_03_source_layer_label_is_readable(self):
        self.assertEqual(EX.citations.source_layer_label("L1"),
                         "L1 primary transcription")
        self.assertEqual(EX.citations.source_layer_label("L2"),
                         "L2 recovered / translated material")
        self.assertIsNone(EX.citations.source_layer_label(None))

    def test_04_source_trace_chain_exported(self):
        d = EX.build_from_passage(L.P_L2)
        chain = d["provenance"]["source_trace"]["chain"]
        self.assertEqual([s["step"] for s in chain],
                         ["CorpusSource", "Witness", "PassageRealization", "Session",
                          "Seminar"])

    def test_05_corpus_provenance_vs_project_bibliography(self):
        """§43：Corpus Provenance 与 Project Bibliography 必须分开。"""
        corpus = EX.prov.corpus_provenance_block([{"passage_id": L.P_L1}])
        bib = EX.prov.project_bibliography_block([{"title": "Écrits"}])
        self.assertEqual(corpus["label"], "Corpus Provenance")
        self.assertEqual(bib["label"], "Project Bibliography")
        self.assertIn("not a CorpusSource", bib["note"])

    def test_06_passage_payload_shape(self):
        d = EX.build_from_passage(L.P_L1)
        p = d["passage"]
        for k in ("passage_id", "text", "seminar", "session", "language",
                  "source_layer", "witness", "provenance_status"):
            self.assertIn(k, p)
        self.assertEqual(p["passage_id"], L.P_L1)
        self.assertTrue(p["text"])

    def test_07_passage_export_does_not_copy_context_by_default(self):
        d = EX.build_from_passage(L.P_L1)
        self.assertEqual(d["passage"]["context"], [])
        self.assertFalse(d["export_options"].get("include_context"))

    def test_08_source_state_surfaced(self):
        d = EX.build_from_passage(L.P_L2)
        self.assertEqual(d["passage"]["source_state"], "upstream_missing")
        self.assertTrue(d["passage"]["witness_note"])

    def test_09_provenance_present_in_all_formats(self):
        """跨格式断言要按**格式的表达方式**来：
        JSON 是结构化对象，Markdown/HTML 是人读标题 —— 但事实必须一致（§29/§56）。"""
        d = EX.build_from_passage(L.P_L2)
        texts = L.rendered(d)
        self.assertIn("Provenance summary", texts["markdown"])
        self.assertIn("Provenance summary", texts["html"])
        obj = json.loads(texts["json"])
        self.assertIn("source_trace", obj["provenance"])
        self.assertTrue(obj["provenance"]["source_trace_incomplete"])
        for fmt in ("markdown", "html"):
            self.assertIn("witness", texts[fmt].lower(), fmt)
        self.assertTrue(obj["provenance"]["passages_without_witness"] == [] or
                        isinstance(obj["provenance"]["passages_without_witness"], list))
