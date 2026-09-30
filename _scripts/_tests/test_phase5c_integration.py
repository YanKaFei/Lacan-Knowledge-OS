#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase5c_integration — Phase 5C §33–§36/§43/§46：项目/Obsidian/兼容/写隔离。"""
from __future__ import annotations
import json, os, shutil, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (VAULT, HERE):
    if p not in sys.path: sys.path.insert(0, p)
import bibliography as B
from bibliography import registry as R
import project_api as PA
import project_api.bibliography as PB
from project_api import store as S
import obsidian_adapter.bibliography as OB
from obsidian_adapter import vault as OV

REVIEWED = "bib.doc.lacan.seminar-3"

class Integration(unittest.TestCase):
    def test_phase5c_project_integration(self):
        tmp = tempfile.mkdtemp(dir=os.path.join(VAULT, "_workspace"))
        prev = S.PROJECTS_DIR
        S.PROJECTS_DIR = tmp
        try:
            proj = PA.create_project("P5C 项目", "", ["p5c"])
            pid = proj["project_id"]
            PB.add_bibliographic_item(pid, proj.get("revision"), REVIEWED,
                                      user_note="核心语料")
            out = PB.list_bibliography(pid)
            self.assertEqual(len(out["project_bibliography_refs"]), 1)
            ref = out["project_bibliography_refs"][0]
            self.assertEqual(ref["bibliographic_id"], REVIEWED)
            self.assertFalse(ref["user_supplied"])
            self.assertIn("capabilities", ref)
            # candidate 不得挂接（§12）
            cand = R.candidates()[0]["bibliographic_id"]
            with self.assertRaises(Exception):
                PB.add_bibliographic_item(pid, None, cand)
        finally:
            S.PROJECTS_DIR = prev
            shutil.rmtree(tmp, ignore_errors=True)

    def test_phase5c_backward_compat(self):
        """§46：4D.5 的自由文本 bibliography_refs 必须仍可读（只读适配）。"""
        tmp = tempfile.mkdtemp(dir=os.path.join(VAULT, "_workspace"))
        prev = S.PROJECTS_DIR
        S.PROJECTS_DIR = tmp
        try:
            proj = PA.create_project("P5C legacy", "", ["legacy"])
            pid = proj["project_id"]
            PA.add_bibliography_ref(pid, proj.get("revision"), "Écrits",
                                    author="Jacques Lacan", year=1966)
            out = PB.list_bibliography(pid)
            self.assertEqual(len(out["legacy_user_supplied_refs"]), 1)
            lg = out["legacy_user_supplied_refs"][0]
            self.assertTrue(lg["user_supplied"])
            self.assertIsNone(lg["bibliographic_id"])      # 未强行 canonicalize
            self.assertTrue(lg["legacy"])
            # 显式关联（不删除 legacy）
            PB.link_legacy_ref(pid, None, lg["ref_id"], REVIEWED)
            out2 = PB.list_bibliography(pid)
            p = PA.get_project(pid)
            linked = [r for r in p["bibliography_refs"]
                      if r.get("linked_bibliographic_id") == REVIEWED]
            self.assertTrue(linked, "legacy ref 应被显式关联而非改写")
        finally:
            S.PROJECTS_DIR = prev
            shutil.rmtree(tmp, ignore_errors=True)

    def test_phase5c_obsidian(self):
        iso = os.path.join("_workspace", "test_vaults", "p5c_bib_note")
        shutil.rmtree(os.path.join(VAULT, iso), ignore_errors=True)
        v = OV.Vault(iso)
        try:
            res = OB.save_bibliography_note(REVIEWED, vault=v)
            self.assertTrue(res["note"].startswith("_System/bibliography/"), res["note"])
            txt = v.read(res["note"])
            fm = txt.split("---")[1]
            self.assertNotIn("\nid:", fm, "派生笔记不得带 id frontmatter")
            self.assertIn("bibliographic_ref:", fm)
            self.assertIn(REVIEWED, fm)
            v.write(res["note"], txt.rstrip("\n") + "\n\n## My Notes\n\n用户自己的字。\n")
            before = v.read(res["note"])
            OB.save_bibliography_note(REVIEWED, vault=v)
            after = v.read(res["note"])
            self.assertEqual(before, after, "用户区必须逐字节保留")
            self.assertIn("Citation capabilities", after)
            # 不得出现理论相关性判断（§21）
            for bad in ("影响巨大", "influence", "theoretical relevance"):
                self.assertNotIn(bad, after)
        finally:
            shutil.rmtree(os.path.join(VAULT, iso), ignore_errors=True)

    def test_phase5c_write_isolation(self):
        """写操作必须在隔离根内；不得写 canonical 分区或 registry 之外。"""
        iso = os.path.join("_workspace", "test_vaults", "p5c_iso")
        shutil.rmtree(os.path.join(VAULT, iso), ignore_errors=True)
        v = OV.Vault(iso)
        try:
            res = OB.save_bibliography_note(REVIEWED, vault=v)
            self.assertTrue(os.path.isfile(os.path.join(VAULT, iso, res["note"])))
            for d in ("07_Cases", "11_Thinkers", "01_Sources/Editions"):
                self.assertFalse(os.path.isfile(
                    os.path.join(VAULT, iso, d, "%s.md" % REVIEWED)))
            self.assertFalse(os.path.isfile(
                os.path.join(VAULT, "07_Cases", "%s.md" % REVIEWED)))
        finally:
            shutil.rmtree(os.path.join(VAULT, iso), ignore_errors=True)
        # registry 是只读派生：重新构建必须幂等
        a = B.registry.manifest()["content_hash"]
        res2 = B.registry.build()
        b = B.registry.write_all(res2)["content_hash"]
        self.assertEqual(a, b, "registry 构建必须确定性/幂等")

if __name__ == "__main__":
    unittest.main(verbosity=2)
