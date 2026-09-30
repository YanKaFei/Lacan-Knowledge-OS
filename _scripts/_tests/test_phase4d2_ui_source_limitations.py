#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §21/§26：Limitations 原样来自载荷；核心验证日志不进正文（但完整保留）。"""
import json, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key

ENGINEERING = re.compile(r"(已剔除|未通过验证|NOT_ENTAILED|被剔除|strength=R\d)")

class SourceLimitationsUX(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = L.mcp_payload(L.QUESTION_RELATION, mode="seminar_specific",
                                    language="fr")["result"]
        cls.view = L.answer(L.QUESTION_RELATION, mode="seminar_specific", language="fr")

    def test_00_limitations_come_from_payload(self):
        self.assertEqual(len(self.view["limitations"]),
                         len(self.payload["source_limitations"]))
        for a, b in zip(self.view["limitations"], self.payload["source_limitations"]):
            self.assertEqual(a, b, "UI 自己生成了 limitation 或改写了他")

    def test_01_engineering_log_not_in_body_sections(self):
        body = [s for s in self.view["sections"] if not s["internal"]]
        for s in body:
            self.assertIsNone(ENGINEERING.search(s["text"]),
                              "正文里出现了核心验证日志：%s" % s["id"])

    def test_02_engineering_log_still_available(self):
        internals = [s for s in self.view["sections"] if s["internal"]]
        if not internals:
            self.skipTest("本用例的载荷里没有工程性 section")
        raw = self.view["raw"]["scholarly_payload"]["sections"]
        raw = {s["id"]: s["text"] for s in raw} if isinstance(raw, list) else raw
        for s in internals:
            self.assertIn(s["id"], raw)
            self.assertEqual(raw[s["id"]], s["text"])

    def test_03_ui_never_invents_limitations(self):
        """UI 的 limitations 必须是载荷 source_limitations 的**逐条子集且等长**。"""
        self.assertEqual(self.view["limitations"], self.payload["source_limitations"])
        self.assertNotIn("generated_limitations", self.view)

    def test_04_advanced_exposes_verbatim_sections(self):
        src = L.js_sources()["render.js"]
        self.assertIn("Section verbatim", src)
        assert_text_wired(self, "render.js", "View raw response")

    def test_05_qualified_answer_marks_qualified(self):
        self.assertTrue(self.view["is_qualified"])
        self.assertEqual(self.view["state_label"], "Validated with qualifications")
        src = L.js_sources()["render.js"]
        assert_text_wired(self, "render.js", "Qualified scholarly answer")  # P5D-004: 文案走 i18n key

if __name__ == "__main__":
    unittest.main()
