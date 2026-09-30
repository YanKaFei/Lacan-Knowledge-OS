#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §2/§6/§56：跨格式 scholarly payload 一致性（本阶段核心门禁）"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


def _from_bundle(path):
    """从 bundle 里读回 JSON 导出的 ExportDocument（真正的跨格式比较）。"""
    sid = None
    for f in os.listdir(os.path.join(path, "research")):
        if f.endswith(".json"):
            sid = f
    with open(os.path.join(path, "research", sid), encoding="utf-8") as fh:
        return json.load(fh)


class CrossFormatIdentity(unittest.TestCase):
    def test_00_four_formats_same_payload(self):
        """§56：Markdown / JSON / HTML / Bundle 的 scholarly payload 必须一致。"""
        d = L.doc()
        with L.export_root("ident"):
            out = EX.build_bundle(d)
            from_bundle = _from_bundle(out["dir"])
        texts = L.rendered(d)
        json_doc = EX.json_export.load(texts["json"])
        for other in (json_doc, from_bundle):
            EX.assert_identity(d, other)

    def test_01_claim_texts_identical_everywhere(self):
        d = L.doc()
        texts = L.rendered(d)
        claims = [c["claim_text"] for c in d["claims"]]
        for fmt in ("markdown", "html"):
            for c in claims:
                self.assertIn(str(c)[:40], texts[fmt], fmt)
        for c in json.loads(texts["json"])["claims"]:
            self.assertIn(c["claim_text"], claims)

    def test_02_citation_ids_identical(self):
        d = L.doc()
        ids = [c["passage_id"] for c in d["citations"]]
        self.assertEqual([c["passage_id"] for c in
                          json.loads(L.rendered(d)["json"])["citations"]], ids)
        md = L.rendered(d)["markdown"]
        for pid in ids:
            self.assertIn(pid, md)
        html = L.rendered(d)["html"]
        for pid in ids:
            self.assertIn(pid, html)

    def test_03_same_payload_hash_across_formats(self):
        d = L.doc()
        with L.export_root("ident2"):
            out = EX.build_bundle(d)
            from_bundle = _from_bundle(out["dir"])
            self.assertEqual(EX.export_payload_hash(d),
                             EX.export_payload_hash(from_bundle))
            self.assertEqual(out["export_payload_hash"], d["export_payload_hash"])

    def test_04_qualified_and_abstention_cross_format(self):
        for view, state in ((L.view(), "VALIDATED_WITH_QUALIFICATIONS"),
                            (L.abstention_view(), "ABSTAINED")):
            d = EX.build_from_answer(view)
            self.assertEqual(d["answer_state"], state)
            for fmt, text in L.rendered(d).items():
                self.assertIn(state, text, fmt)

    def test_05_markdown_html_are_not_required_to_roundtrip(self):
        """§57：只有 JSON 要求无损反序列化；md/html 只要求内容一致。"""
        d = L.doc()
        md = EX.markdown.render(d)
        self.assertNotIn("{", md[:3])
        with self.assertRaises(EX.ExportError):
            EX.json_export.load(md)

    def test_06_limitations_present_in_all_four(self):
        d = L.doc()
        d["limitations"] = ["限制一"]
        with L.export_root("ident3"):
            out = EX.build_bundle(d)
            from_bundle = _from_bundle(out["dir"])
        self.assertEqual(from_bundle["limitations"], ["限制一"])
        self.assertIn("限制一", L.rendered(d)["markdown"])
        self.assertIn("限制一", L.rendered(d)["html"])
