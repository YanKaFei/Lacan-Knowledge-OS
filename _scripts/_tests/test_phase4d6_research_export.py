#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §6/§7/§72/§73：Research Run 导出（内容逐字、qualified 保留）"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class ResearchExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.view = L.view()
        cls.doc = EX.build_from_answer(cls.view)

    def test_00_sections_verbatim(self):
        """§6 + **Phase 5A §47 呈现策略**：sections 逐字不变 —— 但只对**用户可见面**。

        Phase 5A 起，分类为 `AUDIT_DIAGNOSTIC` 的段落（校验器 reject 日志 / 验证计量摘要）
        不进入标准导出；它们必须在 **Audit Bundle**（`include_audit=True`）里 100% 取回。
        逐字性本身没有被削弱：该给的照旧一字不改，只是不再混进用户可见正文。
        """
        src = [s.get("text") for s in self.view["sections"] if not s.get("internal")]
        got = [s.get("text") for s in self.doc["sections"]]
        self.assertEqual(got, src)
        if any(s.get("internal") for s in self.view["sections"]):
            doc_a = EX.build_from_answer(self.view, export_options={"include_audit": True})
            self.assertEqual([s.get("text") for s in doc_a["sections"]],
                             [s.get("text") for s in self.view["sections"]],
                             "audit 面必须在 include_audit 下原样可取回（不得丢弃）")

    def test_01_claims_verbatim(self):
        src = [c.get("claim_text") for c in self.view["claims"]]
        got = [c.get("claim_text") for c in self.doc["claims"]]
        self.assertEqual(got, src)
        self.assertEqual([c.get("claim_id") for c in self.doc["claims"]],
                         [c.get("claim_id") for c in self.view["claims"]])

    def test_02_citation_ids_and_spans_verbatim(self):
        src = [(c.get("passage_id"), c.get("quoted_span"))
               for c in self.view["citations"]]
        got = [(c["passage_id"], c.get("quoted_span")) for c in self.doc["citations"]]
        self.assertEqual(got, src)

    def test_03_answer_state_and_task_type(self):
        self.assertEqual(self.doc["answer_state"], self.view["state"])
        self.assertEqual(self.doc["task_type"], self.view["task_type"])

    def test_04_source_answer_hash_present(self):
        self.assertTrue(self.doc["source_answer_hash"])
        self.assertEqual(len(self.doc["source_answer_hash"]), 64)

    def test_05_qualified_keeps_state_and_never_upgraded(self):
        """§8/§73：VALIDATED_WITH_QUALIFICATIONS 不得因为导出而变成 VALIDATED。"""
        self.assertEqual(self.doc["answer_state"], "VALIDATED_WITH_QUALIFICATIONS")
        for fmt, text in L.rendered(self.doc).items():
            self.assertIn("VALIDATED_WITH_QUALIFICATIONS", text, fmt)
            self.assertNotIn('"VALIDATED"', text.replace(
                '"VALIDATED_WITH_QUALIFICATIONS"', ''), fmt)
        self.assertIn("Qualified answer", "".join(L.rendered(self.doc).values()))

    def test_06_limitations_present_in_all_formats(self):
        d = L.doc()
        d["limitations"] = ["限制 A", "限制 B"]
        for fmt, text in L.rendered(d).items():
            self.assertIn("限制 A", text, fmt)
            self.assertIn("限制 B", text, fmt)

    def test_07_no_project_notes_by_default(self):
        """§7：默认不把 Project Notes 塞进 run 导出。"""
        d = L.doc()
        self.assertEqual(d.get("user_blocks"), {})
        self.assertNotIn("## USER NOTES", EX.markdown.render(d))

    def test_08_passage_missing_is_broken_reference(self):
        """§65：citation 指向不存在的 passage → BROKEN_REFERENCE（不静默删）。"""
        import copy
        v = copy.deepcopy(self.view)
        v["citations"][0]["passage_id"] = "passage.S99.unknown.P9999"
        with self.assertRaises(EX.ExportError) as ctx:
            EX.build_from_answer(v)
        self.assertEqual(ctx.exception.code, "BROKEN_REFERENCE")
        self.assertEqual(ctx.exception.detail["broken"][0]["passage_id"],
                         "passage.S99.unknown.P9999")

    def test_09_history_export_does_not_research(self):
        """§37：历史导出不得重新执行 research。"""
        import inspect
        src = inspect.getsource(EX.build_from_history)
        self.assertNotIn("research(", src)
        self.assertIn("EXPORT_SOURCE_NOT_FOUND", src)
