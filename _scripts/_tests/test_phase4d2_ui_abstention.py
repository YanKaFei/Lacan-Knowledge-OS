#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §33/§19：Abstention UX —— 硬门禁；UI 不得补答、不得出现"不过一般来说…"。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402

SUBSTANTIVE = ("DEFINITION", "RELATION", "DISTINCTION", "DIACHRONIC_CHANGE",
               "REINTERPRETATION", "SOURCE_INFLUENCE", "FORMALISM", "TERMINOLOGY")

class AbstentionUX(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.views = {k: L.answer(q) for k, q in
                     (("topic", L.QUESTION_ABSTAIN), ("metadata", L.QUESTION_METADATA))}
        cls.payloads = {k: L.mcp_payload(q)["result"] for k, q in
                        (("topic", L.QUESTION_ABSTAIN), ("metadata", L.QUESTION_METADATA))}

    def test_00_state_propagated(self):
        for k, v in self.views.items():
            self.assertEqual(v["state"], "ABSTAINED", k)
            self.assertTrue(v["is_abstention"], k)
            self.assertEqual(v["state_label"], "Abstained")

    def test_01_abstention_block_rendered(self):
        for k, v in self.views.items():
            ab = v["abstention"]
            self.assertIsNotNone(ab, k)
            self.assertEqual(ab["title"], "Current corpus cannot support a reliable answer")
            self.assertTrue(ab["categories"], k)
            self.assertIsNotNone(ab["missing_information"])

    def test_02_all_four_blocks_present(self):
        for k, v in self.views.items():
            ab = v["abstention"]
            for field in ("categories", "missing_information",
                          "available_partial_information", "required_sources"):
                self.assertIn(field, ab, "%s: 缺 %s" % (k, field))

    def test_03_no_substantive_claim_rendered(self):
        for k, v in self.views.items():
            for c in v["claims"]:
                self.assertNotIn(c["claim_type"], SUBSTANTIVE,
                                 "%s: 弃权视图出现实质性断言" % k)

    def test_04_no_filler_or_model_knowledge(self):
        for k, v in self.views.items():
            blob = json.dumps(v, ensure_ascii=False).lower()
            for filler in ("however", "generally speaking", "it is known that",
                           "in general", "although not in the corpus"):
                self.assertNotIn(filler, blob, "%s: 出现补答样式文本" % k)

    def test_05_abstention_matches_mcp_payload(self):
        for k, v in self.views.items():
            self.assertEqual(L.canon(v["raw"]["scholarly_payload"]) if hasattr(L, "canon")
                             else json.dumps(v["raw"]["scholarly_payload"],
                                             ensure_ascii=False, sort_keys=True),
                             json.dumps(self.payloads[k], ensure_ascii=False,
                                        sort_keys=True), k)

    def test_06_render_source_has_abstention_path(self):
        src = L.js_sources()["render.js"]
        self.assertIn("renderAbstention", src)
        self.assertIn("Current corpus cannot support a reliable answer", src)
        self.assertNotIn("however", src.lower())

if __name__ == "__main__":
    unittest.main()
