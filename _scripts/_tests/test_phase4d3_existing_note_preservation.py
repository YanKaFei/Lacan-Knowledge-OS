#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §31/§48：已存在的非受管文件绝不被重写。"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import adapter as A

USER_FILE = "# 欲望\n\n我自己的笔记，没有 Lacan OS frontmatter。\n"

class ExistingNotePreservation(unittest.TestCase):
    def setUp(self):
        self.v = L.fresh_vault("existing_note")
        os.makedirs(self.v.resolve("Concepts"), exist_ok=True)
        # 未受管文件故意用**用户自己的名字**（中文），与 adapter 计算出的 slug 不同
        open(self.v.resolve("Concepts", "欲望.md"), "w", encoding="utf-8").write(USER_FILE)

    def test_00_same_slug_unmanaged_file_not_rewritten(self):
        """同 slug 的未受管文件 → 只登记映射，不重写。"""
        open(self.v.resolve("Concepts", "desir.md"), "w", encoding="utf-8").write(USER_FILE)
        out = A.ensure_concept_note("concept.desir", vault=self.v)
        self.assertEqual(out["status"], "existing_unmanaged_preserved")
        self.assertEqual(open(self.v.resolve("Concepts", "desir.md"),
                             encoding="utf-8").read(), USER_FILE)

    def test_01_mapped_as_unmanaged(self):
        open(self.v.resolve("Concepts", "desir.md"), "w", encoding="utf-8").write(USER_FILE)
        A.ensure_concept_note("concept.desir", vault=self.v)
        import json
        mapping = json.load(open(self.v.resolve("_System", "mappings",
                                               "entity_note_map.json"), encoding="utf-8"))
        self.assertIn("concept.desir", mapping)
        self.assertFalse(mapping["concept.desir"]["managed"])
        self.assertEqual(mapping["concept.desir"]["reason"], "existing_unmanaged")

    def test_02b_explicit_mapping_of_user_file(self):
        """§31：用户明确指定自己的 note → 只登记映射，绝不重写。"""
        out = A.ensure_concept_note("concept.desir", vault=self.v,
                                    existing_note="Concepts/欲望.md")
        self.assertEqual(out["status"], "existing_unmanaged_preserved")
        self.assertEqual(open(self.v.resolve("Concepts", "欲望.md"),
                             encoding="utf-8").read(), USER_FILE)
        import json
        mapping = json.load(open(self.v.resolve("_System", "mappings",
                                               "entity_note_map.json"), encoding="utf-8"))
        self.assertEqual(mapping["concept.desir"]["note"], "Concepts/欲望.md")
        self.assertFalse(mapping["concept.desir"]["managed"])

    def test_02_save_research_does_not_touch_unmanaged(self):
        L.save(self.v)
        self.assertEqual(open(self.v.resolve("Concepts", "欲望.md"),
                             encoding="utf-8").read(), USER_FILE)

    def test_03_managed_note_detected_by_frontmatter(self):
        L.save(self.v)
        from obsidian_adapter.frontmatter import parse_frontmatter
        txt = L.note(self.v, "Concepts/objet-petit-a.md")
        meta, _ = parse_frontmatter(txt)
        self.assertEqual(meta["type"], "lacan-concept")

    def test_04_save_research_maps_unmanaged_hub_as_unmanaged(self):
        """同路径的用户文件在 `save_research` 路径下也不得被记成 managed。

        实测踩过：`_stage_concept` / `_stage_seminar` 遇到非受管文件直接 return，
        调用方却无条件写 `managed: true` —— provenance 记录在撒谎
        （文件其实一个字节都没被系统碰过）。
        """
        import json
        user = "# 我自己的 S10 笔记\n"
        os.makedirs(self.v.resolve("Concepts"), exist_ok=True)
        os.makedirs(self.v.resolve("Seminars"), exist_ok=True)
        open(self.v.resolve("Concepts", "desir.md"), "w", encoding="utf-8").write(USER_FILE)
        open(self.v.resolve("Seminars", "S10.md"), "w", encoding="utf-8").write(user)
        L.save(self.v)
        self.assertEqual(open(self.v.resolve("Concepts", "desir.md"),
                              encoding="utf-8").read(), USER_FILE)
        self.assertEqual(open(self.v.resolve("Seminars", "S10.md"),
                              encoding="utf-8").read(), user)
        mapping = json.load(open(self.v.resolve("_System", "mappings",
                                                "entity_note_map.json"), encoding="utf-8"))
        for key in ("concept.desir", "seminar.S10"):
            self.assertFalse(mapping[key]["managed"], key)
            self.assertEqual(mapping[key]["reason"], "existing_unmanaged", key)
        # 系统自己建的 hub 仍然是 managed
        for key in ("concept.objet-petit-a", "seminar.S11"):
            self.assertTrue(mapping[key]["managed"], key)

    def test_05_dangling_links_absent_with_user_files_present(self):
        """用户文件占据了 hub 路径时，链接依然不悬空（文件存在即解析）。"""
        import re
        open(self.v.resolve("Concepts", "desir.md"), "w", encoding="utf-8").write(USER_FILE)
        out = L.save(self.v)
        present = set(L.all_md(self.v))
        dangling = [(r, t) for r in present for t in L.links_in(L.note(self.v, r))
                    if t + ".md" not in present]
        self.assertEqual(dangling, [])
        self.assertTrue(out["concept_notes"])
