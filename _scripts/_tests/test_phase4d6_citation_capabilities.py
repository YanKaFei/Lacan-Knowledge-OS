#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §21/§22/§67/§78：citation_capabilities 与不可用样式的 UI 行为"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX
from workspace_ui.server import export_view as EV


class CitationCapabilities(unittest.TestCase):
    def test_00_capability_shape(self):
        caps = EX.citation_capabilities({})
        for k in ("internal_short", "internal_full", "provenance", "chicago", "mla",
                  "apa", "bibtex"):
            self.assertIn(k, caps["capabilities"])
        for k in ("internal_short", "internal_full", "provenance"):
            self.assertTrue(caps["capabilities"][k])

    def test_01_missing_fields_listed(self):
        caps = EX.citation_capabilities({}, bibliographic={"author": "Lacan"})
        self.assertIn("chicago", caps["missing_fields"])
        self.assertIn("title", caps["missing_fields"]["chicago"])
        self.assertFalse(caps["bibliographic_metadata_complete"])

    def test_02_complete_metadata_enables_styles(self):
        bib = {"author": "A", "title": "T", "publication_title": "P", "publisher": "P",
               "year": 1966}
        caps = EX.citation_capabilities({}, bibliographic=bib)
        self.assertTrue(caps["capabilities"]["chicago"])
        self.assertTrue(caps["capabilities"]["mla"])
        self.assertTrue(caps["bibliographic_metadata_complete"])

    def test_03_ui_menu_advertises_all_but_gates(self):
        menu = EV.menus()
        styles = {s["id"]: s for s in menu["citation_styles"]}
        for s in EX.INTERNAL_STYLES:
            self.assertTrue(styles[s]["available"])
        for s in EX.BIBLIOGRAPHIC_STYLES:
            self.assertFalse(styles[s]["available"])

    def test_04_real_passage_has_no_bibliographic_capability(self):
        """§78：找一条真实 passage，确认 Chicago=false 而内部三样式=true。"""
        data = EV.citation("passage.S11.unknown.P2253")
        styles = {s["id"]: s for s in data["styles"]}
        self.assertTrue(styles["internal-short"]["available"])
        self.assertTrue(styles["internal-full"]["available"])
        self.assertTrue(styles["provenance"]["available"])
        self.assertFalse(styles["chicago"]["available"])
        self.assertEqual(styles["chicago"]["reason"], "BIBLIOGRAPHIC_METADATA_INCOMPLETE")

    def test_05_unavailable_style_has_no_text(self):
        data = EV.citation("passage.S11.unknown.P2253")
        for s in data["styles"]:
            if not s["available"]:
                self.assertIsNone(s["text"], s["id"])

    def test_06_ui_does_not_render_button_for_unavailable(self):
        js = open(os.path.join(VAULT, "workspace_ui", "static", "src", "export.js"),
                  encoding="utf-8").read()
        self.assertIn("unavailable —", js)
        self.assertIn("if (s.available)", js)

    def test_07_ui_menu_only_lists_implemented_formats(self):
        menu = EV.menus()
        self.assertEqual([f["id"] for f in menu["formats"]],
                         ["markdown", "json", "html", "bundle"])
        self.assertNotIn("docx", str(menu).lower())
        self.assertNotIn("pdf", str(menu).lower())
