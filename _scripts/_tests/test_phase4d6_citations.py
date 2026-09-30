#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §17–§20/§23/§78：Citation 系统（三种内部样式 + 禁止伪造出版型）"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class Citations(unittest.TestCase):
    def test_00_internal_short_style(self):
        self.assertEqual(EX.short_citation("passage.S11.unknown.P2253"), "S11 · P2253")
        self.assertEqual(EX.short_citation("passage.S05.unknown.L05.P0056"), "S05 · P0056")

    def test_01_internal_full_style_uses_real_metadata(self):
        s = EX.full_citation("passage.S11.unknown.P2253",
                             {"seminar_key": "S11", "year": 1964, "language": "fr",
                              "source_layer": "L1"})
        self.assertIn("Seminar XI", s)
        self.assertIn("1964", s)
        self.assertIn("P2253", s)
        self.assertIn("L1 primary transcription", s)

    def test_02_provenance_style_keeps_all_fields(self):
        s = EX.provenance_citation("passage.S05.unknown.L05.P0056",
                                   {"seminar_key": "S05", "source_layer": "L2",
                                    "witness": "witness.zh.translation-project",
                                    "provenance_status": "SOURCE_TRACE_INCOMPLETE"})
        for part in ("passage.S05.unknown.L05.P0056", "L2 recovered",
                     "witness.zh.translation-project", "SOURCE_TRACE_INCOMPLETE"):
            self.assertIn(part, s)

    def test_03_missing_fields_are_dashes_not_inventions(self):
        s = EX.provenance_citation("passage.S11.unknown.P2253", {})
        self.assertIn("witness —", s)
        self.assertIn("provenance —", s)

    def test_04_record_has_three_internal_styles(self):
        with L.export_root("cit"):
            d = EX.build_from_passage(L.P_L1)
            rec = d["citations"][0]
            for k in ("internal_short", "internal_full", "provenance"):
                self.assertTrue(rec[k], k)
            self.assertEqual(rec["kind"], "internal_scholarly")

    def test_05_bibliographic_refused_without_metadata(self):
        """§19/§78：没有出版元数据就不能生成出版型 citation。"""
        rec = EX.citation_record("passage.S11.unknown.P2253", meta={"seminar_key": "S11"})
        for style in ("chicago", "mla", "apa", "bibtex"):
            self.assertFalse(rec["capabilities"][style], style)
            with self.assertRaises(EX.ExportError) as ctx:
                EX.render_citation(rec, style)
            self.assertEqual(ctx.exception.code, "BIBLIOGRAPHIC_METADATA_INCOMPLETE")

    def test_06_bibliographic_allowed_with_metadata(self):
        bib = {"author": "Jacques Lacan", "title": "Écrits", "publication_title": "Seuil",
               "publisher": "Seuil", "year": 1966}
        rec = EX.citation_record("passage.S11.unknown.P2253", meta={"seminar_key": "S11"},
                                 bibliographic=bib)
        self.assertTrue(rec["capabilities"]["chicago"])
        text = EX.render_citation(rec, "chicago")
        self.assertIn("Seuil", text)
        self.assertIn("1966", text)

    def test_07_no_invented_publisher_or_page(self):
        rec = EX.citation_record("passage.S11.unknown.P2253", meta={"seminar_key": "S11"})
        blob = str(rec)
        for bad in ("Seuil", "p. 103", "ISBN", "Gallimard"):
            self.assertNotIn(bad, blob)

    def test_08_unsupported_style_rejected(self):
        rec = EX.citation_record("passage.S11.unknown.P2253", meta={"seminar_key": "S11"})
        with self.assertRaises(EX.ExportError) as ctx:
            EX.render_citation(rec, "vancouver")
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_FORMAT")

    def test_09_record_validates_against_schema(self):
        rec = EX.citation_record("passage.S11.unknown.P2253", meta={"seminar_key": "S11"})
        self.assertTrue(EX.validate(rec, EX.SCHEMA_CITATION_RECORD))

    def test_10_ui_never_builds_citations_itself(self):
        """§54：前端不得自己拼 citation 字符串。"""
        src = open(os.path.join(VAULT, "workspace_ui", "static", "src", "export.js"),
                   encoding="utf-8").read()
        self.assertIn("api.exportCitation", src)
        self.assertNotIn("S11 · ", src)
        self.assertNotIn("' · '", src)
