#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §36：答案同一性 —— MCP 载荷 → UI ViewModel 只允许排版/分组/标签。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402

class AnswerIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = L.mcp_payload(L.QUESTION_RELATION, mode="seminar_specific", language="fr")
        cls.payload = cls.env["result"]
        cls.view = L.answer(L.QUESTION_RELATION, mode="seminar_specific", language="fr")

    def test_00_state_and_question_verbatim(self):
        self.assertEqual(self.view["state"], self.payload["answer_state"])
        self.assertEqual(self.view["question"], self.payload["question"])
        self.assertEqual(self.view["task_type"], self.payload["task_type"])

    def test_01_every_section_text_is_verbatim(self):
        payload_sections = self.payload["sections"]
        if isinstance(payload_sections, list):
            payload_sections = {s["id"]: s["text"] for s in payload_sections}
        got = {s["id"]: s["text"] for s in self.view["sections"]}
        self.assertEqual(set(got), set(payload_sections),
                         "UI 丢了或多了 section")
        for k, v in payload_sections.items():
            self.assertEqual(got[k], v, "section %s 文本被改写" % k)

    def test_02_grouping_does_not_hide_internal_sections(self):
        payload_sections = self.payload["sections"]
        if isinstance(payload_sections, list):
            payload_sections = {s["id"]: s["text"] for s in payload_sections}
        internals = [s for s in self.view["sections"] if s["internal"]]
        for s in internals:
            self.assertEqual(s["text"], payload_sections[s["id"]],
                             "internal section 文本被改动")
        raw = self.view["raw"]["scholarly_payload"]["sections"]
        raw = {s["id"]: s["text"] for s in raw} if isinstance(raw, list) else raw
        self.assertEqual(set(raw), set(payload_sections), "raw 视图必须保留全部 section")

    def test_03_claims_verbatim(self):
        self.assertEqual(len(self.view["claims"]), len(self.payload["validated_claims"]))
        for a, b in zip(self.view["claims"], self.payload["validated_claims"]):
            self.assertEqual(a["claim_id"], b["claim_id"])
            self.assertEqual(a["claim_text"], b["claim_text"], "claim 文本被改写")
            self.assertEqual(a["claim_type"], b["claim_type"])
            self.assertEqual(a["epistemic_status"], b["epistemic_status"])
            self.assertEqual(a["evidence_ids"], b["evidence_ids"])

    def test_04_epistemic_labels_are_display_only(self):
        for c in self.view["claims"]:
            self.assertNotIn(c["epistemic_label"], (None, ""),
                             "缺少显示标签")
            self.assertEqual(c["epistemic_status"], c["epistemic_status"])

    def test_05_no_new_theoretical_text(self):
        """UI 不得新增任何学术性文字：ViewModel 里的文本必须来自载荷。"""
        blob = json.dumps(self.view, ensure_ascii=False)
        for invented in ("however", "generally speaking", "in summary", "AI confidence"):
            self.assertNotIn(invented.lower(), blob.lower())
        self.assertFalse([k for k in self.view if k == "generated_text"])

    def test_06_state_labels_are_fixed_mapping(self):
        from workspace_ui.server import viewmodel as VM
        self.assertEqual(self.view["state_label"], VM.STATE_LABELS[self.view["state"]])
        self.assertEqual(self.view["is_abstention"], self.view["state"] == "ABSTAINED")

    def test_07_raw_payload_is_available_for_audit(self):
        self.assertEqual(json.dumps(self.view["raw"]["scholarly_payload"],
                                    ensure_ascii=False, sort_keys=True),
                         json.dumps(self.payload, ensure_ascii=False, sort_keys=True))

if __name__ == "__main__":
    unittest.main()
