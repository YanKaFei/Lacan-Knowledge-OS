#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §34：Markdown 导出（可移植、frontmatter 受控、用户区块分区）"""
import os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class MarkdownExport(unittest.TestCase):
    def test_00_frontmatter_controlled(self):
        md = EX.markdown.render(L.doc())
        self.assertTrue(md.startswith("---\n"))
        head = md.split("---")[1]
        for key in ("type: \"lacan-export\"", "export_schema:", "export_id:",
                    "source_type:", "answer_state:", "export_payload_hash:"):
            self.assertIn(key, head, key)
        # 禁止把不可信文本塞进 frontmatter
        self.assertNotIn("Seminar XI 中 gaze", head)

    def test_01_frontmatter_injection_blocked(self):
        """§69：标题/问题里的 YAML 结构不得逃出 frontmatter。"""
        d = L.doc()
        d["question"] = "a\nb: evil\n---\nstatus: hacked"
        md = EX.markdown.render(d)
        head = md.split("---")[1]
        self.assertNotIn("status: hacked", head)
        from obsidian_adapter.frontmatter import parse_frontmatter
        meta, _ = parse_frontmatter(md)
        self.assertNotIn("b", meta)
        self.assertEqual(meta["type"], "lacan-export")

    def test_02_sections_and_claims_present(self):
        d = L.doc()
        md = EX.markdown.render(d)
        for s in d["sections"]:
            self.assertIn(str(s.get("text"))[:40], md)
        for c in d["claims"]:
            self.assertIn(str(c.get("claim_text"))[:40], md)
            self.assertIn(c["claim_id"], md)

    def test_03_user_blocks_are_separated(self):
        d = L.doc()
        d["user_blocks"] = {
            "user_hypotheses": [{"text": "假设 H", "not_validated": True}],
            "open_questions": [{"text": "开放问题 Q", "origin": "user_created"}],
            "user_notes": [{"id": "n1", "title": "笔记", "text": "用户笔记正文"}],
            "bibliography": [{"title": "Écrits", "author": "Lacan", "year": 1966,
                              "missing_fields": ["publisher"]}],
        }
        md = EX.markdown.render(d)
        self.assertIn("USER HYPOTHESIS — NOT VALIDATED BY THE SCHOLARLY CORE", md)
        self.assertIn("OPEN RESEARCH QUESTIONS (not claims)", md)
        self.assertIn("USER NOTES (not scholarly output)", md)
        self.assertIn("PROJECT BIBLIOGRAPHY", md)
        self.assertIn("BibliographyRef", md)
        self.assertIn("CorpusSource", md)

    def test_04_not_an_obsidian_managed_note(self):
        """§34：portable export ≠ Obsidian managed note（不得写 managed block）。"""
        md = EX.markdown.render(L.doc())
        self.assertNotIn("LACAN-OS:GENERATED:START", md)
        self.assertNotIn("## My Notes", md)

    def test_05_abstention_markdown(self):
        d = EX.build_from_answer(L.abstention_view())
        md = EX.markdown.render(d)
        self.assertIn("Current corpus cannot support a reliable answer", md)
        for label in ("Why this cannot be answered", "Missing information",
                      "Available partial information", "Sources needed"):
            if d["abstention"].get({"Why this cannot be answered": "categories",
                                    "Missing information": "missing_information",
                                    "Available partial information":
                                        "available_partial_information",
                                    "Sources needed": "required_sources"}[label]):
                self.assertIn(label, md)

    def test_06_trace_incomplete_in_markdown(self):
        d = EX.build_from_passage(L.P_L2, include_context=2)
        md = EX.markdown.render(d)
        self.assertIn("SOURCE_TRACE_INCOMPLETE", md)
        self.assertIn("L2", md)
        self.assertIn("witness", md)

    def test_07_no_broken_pipe_of_binary(self):
        md = EX.markdown.render(L.doc())
        self.assertNotIn("\x00", md)
