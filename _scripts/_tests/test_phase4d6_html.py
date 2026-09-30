#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §32/§33：Standalone HTML 导出与注入安全"""
import os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class HtmlExport(unittest.TestCase):
    def test_00_standalone_no_remote_assets(self):
        html = EX.html_export.render(L.doc())
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("<style>", html)
        for bad in ("http://", "https://", "<script", "<iframe", "<link rel=\"stylesheet\"",
                    "cdn."):
            self.assertNotIn(bad, html.lower().replace("//cdn.", "cdn-blocked"), bad)
        self.assertNotIn("<script", html.lower())

    def test_01_corpus_text_is_escaped(self):
        d = L.doc()
        d["sections"] = [{"label": "<img src=x onerror=alert(1)>",
                          "text": "<script>alert('x')</script> & \"quotes\""}]
        html = EX.html_export.render(d)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)

    def test_02_user_note_is_escaped(self):
        d = L.doc()
        d["user_blocks"] = {"user_notes": [{"id": "n", "title": "<b>t</b>",
                                            "text": "<script>alert(2)</script>"}]}
        html = EX.html_export.render(d)
        self.assertNotIn("<script>alert(2)</script>", html)
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", html)

    def test_03_no_javascript_urls(self):
        """HTML 导出**不产生任何链接属性**：`javascript:` 只能作为被转义的文本出现。"""
        d = L.doc()
        d["user_blocks"] = {"bibliography": [{"title": "javascript:alert(1)"}]}
        html = EX.html_export.render(d)
        for attr in ("href=", "src=", "action=", "formaction="):
            self.assertNotIn(attr, html, attr)
        self.assertNotIn('href="javascript:', html)
        self.assertIn("javascript:alert(1)", html)   # 作为文本保留，不丢信息

    def test_04_answer_state_and_abstention_visible(self):
        d = EX.build_from_answer(L.abstention_view())
        html = EX.html_export.render(d)
        self.assertIn("ABSTAINED", html)
        self.assertIn("Current corpus cannot support a reliable answer", html)

    def test_05_trace_incomplete_visible(self):
        d = EX.build_from_passage(L.P_L2)
        html = EX.html_export.render(d)
        self.assertIn("SOURCE_TRACE_INCOMPLETE", html)
        self.assertIn("L2", html)

    def test_06_printable_styles_present(self):
        html = EX.html_export.render(L.doc())
        self.assertIn("@media print", html)

    def test_07_hypothesis_label_present(self):
        d = L.doc()
        d["user_blocks"] = {"user_hypotheses": [{"text": "H", "not_validated": True}]}
        html = EX.html_export.render(d)
        self.assertIn("NOT VALIDATED BY THE SCHOLARLY CORE", html)
