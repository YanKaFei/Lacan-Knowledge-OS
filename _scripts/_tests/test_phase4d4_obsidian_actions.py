#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §35/§36/§64：Explorer → Obsidian（复用 4D.3，不另写保存逻辑）"""
import json, os, shutil, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L
from obsidian_adapter import adapter as OA
from obsidian_adapter import vault as OV


class ObsidianActions(unittest.TestCase):
    def setUp(self):
        self.root = os.path.join("_workspace", "test_vaults", "explorer_obsidian")
        shutil.rmtree(os.path.join(VAULT, self.root), ignore_errors=True)
        self.v = OV.Vault(self.root)
        self._old = os.environ.get("OBSIDIAN_VAULT_PATH")
        os.environ["OBSIDIAN_VAULT_PATH"] = self.root

    def tearDown(self):
        if self._old is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = self._old

    def test_00_passage_action_create_then_open(self):
        before = L.X.obsidian_action("passage", L.P_L1)
        if not before.get("exists"):
            self.assertEqual(before["action"], "create")
            self.assertEqual(before["label"], "Create Reference Note")
            out = L.X.obsidian_create("passage", L.P_L1)
            self.assertTrue(out["ok"], out)
            self.assertTrue(self.v.exists(out["note"]))
            self.assertTrue(out.get("obsidian_uri"))
        after = L.X.obsidian_action("passage", L.P_L1)
        self.assertTrue(after["exists"])
        self.assertEqual(after["action"], "open")
        self.assertEqual(after["label"], "Open in Obsidian")
        self.assertTrue(after["obsidian_uri"].startswith("obsidian://open"))

    def test_01_concept_and_seminar_reference_notes(self):
        for et, eid in (("concept", L.C_OBJET_A), ("seminar", "seminar.S11")):
            out = L.X.obsidian_create(et, eid)
            self.assertTrue(out["ok"], out)
            self.assertTrue(self.v.exists(out["note"]), out)
            self.assertTrue(out["note"].startswith(
                "Concepts/" if et == "concept" else "Seminars/"))

    def test_02_only_known_entities(self):
        out = L.X.obsidian_create("person", "x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "UNSUPPORTED_ENTITY")

    def test_03_saved_research_comes_from_manifests(self):
        """§35：Saved Research 必须来自 manifest / mapping，不是扫 Markdown 猜链接。"""
        out = L.X.concept_list(limit=1)
        self.assertTrue(out["items"])
        # 没有保存过 → 空，且说明来源
        v = L.X.concept_detail("concept.besoin")
        self.assertEqual(v["saved_research"]["source"].split("(")[0].strip(),
                         "Workspace / Obsidian manifests")
        for it in v["saved_research"]["items"]:
            self.assertIn("research_id", it)
            self.assertIn("manifest", it)

    def test_04_explorer_never_writes_files_directly(self):
        """§64：写入必须经 4D.3 adapter；explorer.py 不得自己 open(..., 'w')。"""
        src = open(os.path.join(VAULT, "workspace_ui", "server", "explorer.py"),
                   encoding="utf-8").read()
        for bad in ("open(", "os.replace", "shutil", "write_text"):
            self.assertNotIn(bad, src, "explorer.py 不应直接做文件写入：%s" % bad)
        self.assertIn("obsidian_adapter", src)

    def test_05_obsidian_note_content_follows_4d3(self):
        out = L.X.obsidian_create("passage", L.P_L2)
        txt = self.v.read(out["note"])
        self.assertTrue(txt.startswith("---"))
        self.assertIn("read_only_source: true", txt)
        self.assertIn("SOURCE_TRACE_INCOMPLETE", txt)
        self.assertIn("## My Notes", txt)
        self.assertEqual(OA.verify_snapshot(out["note"], vault=self.v)["status"],
                         "VERIFIED")
