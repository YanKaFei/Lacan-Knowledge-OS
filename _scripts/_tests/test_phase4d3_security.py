#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §49/§50/§51：注入、路径、超长、YAML/Markdown 安全。"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import adapter as A, links as K, vault as V
from obsidian_adapter.frontmatter import dump_frontmatter, parse_frontmatter

class Security(unittest.TestCase):
    def setUp(self):
        self.v = L.fresh_vault("security")

    def test_00_path_traversal_blocked(self):
        for bad in ("../outside.md", "a/../../b.md", "/abs/x.md", "~/x.md"):
            with self.assertRaises(V.VaultError, msg=bad):
                self.v.resolve(bad)

    def test_01_malicious_title_cannot_escape(self):
        rel = os.path.join(V.LAYOUT["research"], "%s.md" % K.slug("../../etc/passwd"))
        self.assertNotIn("..", rel)
        self.assertTrue(rel.startswith("Research/"))
        self.v.write(rel, "x")                       # 允许，但仍在 vault 内
        self.assertTrue(os.path.isfile(self.v.resolve(rel)))

    def test_02_yaml_injection_stays_quoted(self):
        fm = dump_frontmatter({"type": "x", "question": "a\nb: evil\n---\nstatus: hacked",
                               "list": ["- item", "a: b"]})
        meta, body = parse_frontmatter(fm + "\nbody\n")
        self.assertEqual(meta["type"], "x")
        self.assertEqual(meta.get("status"), None, "注入的 status 不应出现")
        self.assertEqual(meta["question"].count("---"), 1)

    def test_03_markdown_injection_in_question(self):
        q = "# heading\n[[link]]\n<html>\n---\n"
        out = L.save(self.v, question=q + " objet a 是什么？")
        txt = L.note(self.v, out["research_note"])
        meta, body = parse_frontmatter(txt)
        self.assertEqual(meta["type"], "lacan-research")
        self.assertIn("[[link]]", body)              # 正文里是文本，不破坏 frontmatter

    def test_04_oversized_title_bounded(self):
        long_title = "问" * 500
        self.assertLessEqual(len(K.slug(long_title)), 80)
        out = L.save(self.v, question=long_title)
        self.assertTrue(self.v.exists(out["research_note"]))
        self.assertLess(len(os.path.basename(out["research_note"])), 120)

    def test_05_invalid_utf8_surrogate_safe(self):
        """孤立代理项不可编码为 UTF-8：adapter 必须安全化而不是崩（§49）。"""
        from obsidian_adapter import adapter as A
        view = {"kind": "answer", "question": "objet a \udcff 是什么？",
                "state": "ABSTAINED", "state_label": "Abstained",
                "task_type": "concept_definition", "answer_permission": "ABSTAIN",
                "sections": [], "claims": [], "citations": [], "limitations": [],
                "abstention": {"title": "x", "categories": [],
                               "missing_information": [],
                               "available_partial_information": [],
                               "required_sources": []},
                "warnings": [], "advanced": {"request_id": "probe"},
                "raw": {"scholarly_payload": {"question": "q"}}}
        out = A.save_research(view, vault=self.v)
        self.assertTrue(out["ok"], out)
        self.assertTrue(self.v.exists(out["research_note"]))
        text = open(self.v.resolve(out["research_note"]), encoding="utf-8").read()
        self.assertNotIn("\udcff", text)

    def test_06_wikilink_specials_sanitised(self):
        self.assertEqual(K.wikilink("A|B#C^D.md"), "[[ABCD]]")
        self.assertEqual(K.slug("a/b:c*d?e\"f<g>h|i"), "a-b-c-d-e-f-g-h-i")

    def test_07_symlink_escape_blocked(self):
        outside = os.path.join(L.VAULT, "_workspace", "test_vaults", "outside_target")
        os.makedirs(outside, exist_ok=True)
        link = os.path.join(self.v.root, "Research", "link")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link) if os.path.islink(link) else None
        try:
            os.symlink(outside, link)
        except OSError:
            self.skipTest("symlink 不可用")
        with self.assertRaises(V.VaultError):
            self.v.write(os.path.join("Research", "link", "x.md"), "x")
