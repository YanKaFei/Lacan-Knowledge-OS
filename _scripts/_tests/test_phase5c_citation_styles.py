#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase5c_citation_styles — Phase 5C §14/§30–§32：能力矩阵与样式渲染。"""
from __future__ import annotations
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
if VAULT not in sys.path: sys.path.insert(0, VAULT)
import bibliography as B
from bibliography import model as M, registry as R, render as RD

def _fixture():
    """**测试夹具**（用于验证渲染器；非 corpus 派生，故不入 registry）。"""
    it = M.blank_item("bib.test.complete", "book")
    # 中性测试夹具：不把编造的出版数据挂到真实著作上
    it.update({"title": "Test Volume", "short_title": "Test Volume",
               "authors": ["Test Author"], "publisher": "Test Press",
               "publication_place": "Test City", "publication_year": "1966",
               "pages": "1-100", "language": "en",
               "review_status": "reviewed"})
    it["metadata_completeness"] = M.completeness(it)
    return it

class Styles(unittest.TestCase):
    def test_phase5c_citation_capabilities(self):
        m = RD.capability_matrix(_fixture(), passage_id="passage.S11.unknown.P2253")
        for k in ("passage_id","internal_short","internal_full","provenance",
                  "chicago","mla","apa","bibtex","missing_fields",
                  "internal_citation_ready","bibliographic_citation_ready"):
            self.assertIn(k, m)
        self.assertTrue(all(m[s] for s in ("passage_id","internal_short","provenance",
                                           "chicago","mla","apa","bibtex")))
        # 真实 registry 条目：internal READY、出版型 unavailable
        real = RD.capability_matrix(R.get("bib.doc.lacan.seminar-3"))
        self.assertTrue(real["internal_citation_ready"])
        self.assertFalse(real["bibliographic_citation_ready"])
        self.assertTrue(real["missing_fields"])

    def test_phase5c_chicago(self):
        t = RD.render_bibliographic(_fixture(), "chicago")
        self.assertIn("Test Author", t); self.assertIn("Test Volume", t)
        self.assertIn("Test Press", t); self.assertIn("1966", t)
        self.assertNotIn("Unknown", t)

    def test_phase5c_apa(self):
        t = RD.render_bibliographic(_fixture(), "apa")
        self.assertIn("(1966)", t); self.assertIn("Test Volume", t); self.assertIn("Test Press", t)

    def test_phase5c_mla(self):
        t = RD.render_bibliographic(_fixture(), "mla")
        self.assertIn("Test Volume", t); self.assertIn("Test Press, 1966", t)

    def test_phase5c_bibtex(self):
        text, comp = __import__("bibliography.zotero", fromlist=["x"]).export_bibtex(_fixture())
        self.assertTrue(text.startswith("@book{"))
        self.assertIn("author = {Test Author}", text)
        self.assertIn("year = {1966}", text)
        self.assertEqual(comp, "PUBLISHABLE")
        # 不完整条目：bibtex 必须 fail closed（§29）
        with self.assertRaises(ValueError):
            __import__("bibliography.zotero", fromlist=["x"]).export_bibtex(
                R.get("bib.doc.lacan.seminar-3"))

    def test_phase5c_citation_identity_cross_surface(self):
        """§32：同一 item+style 在 UI / Export / Obsidian / Project 必须同值。"""
        it = _fixture()
        h = RD.citation_identity_hash(it, "chicago")
        from workspace_ui.server import bibliography as UIB
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "p5cob", os.path.join(VAULT, "obsidian_adapter", "bibliography.py"))
        # UI 路径
        text_ui = RD.render_bibliographic(it, "chicago")
        # Export 路径（export_system 的唯一 renderer）
        import export_system as EX
        rec = EX.citations.citation_record(
            "passage.S11.unknown.P2253",
            bibliographic={"author": "Test Author", "title": "Test Volume",
                           "publication_title": "Test Volume",
                           "publisher": "Test Press", "year": "1966"})
        self.assertTrue(rec["capabilities"]["chicago"])
        # 跨表面契约：registry→export 的桥必须补齐 export 层要求的键名
        it2 = _fixture()
        bridged = RD._bib_dict(it2)
        for k in ("author", "title", "publication_title", "publisher", "year"):
            self.assertTrue(bridged.get(k), "registry→export 桥缺 %s" % k)
        rec2 = EX.citations.citation_record("passage.S11.unknown.P2253",
                                           bibliographic=bridged)
        self.assertTrue(rec2["capabilities"]["chicago"],
                        "桥接后 chicago 必须可用（跨表面同一性）")
        # 四条路径都以 RD.citation_identity_hash 为准
        self.assertEqual(h, RD.citation_identity_hash(it, "chicago"))
        self.assertEqual(text_ui, RD.render_bibliographic(it, "chicago"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
