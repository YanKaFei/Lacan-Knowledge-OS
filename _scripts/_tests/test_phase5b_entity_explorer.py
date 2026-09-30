#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase5b_entity_explorer.py — Phase 5B §28/§32：browse API / 分页 / 集成 / UI 接线。"""
from __future__ import annotations
import json, os, shutil, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (VAULT, HERE):
    if p not in sys.path: sys.path.insert(0, p)
import entity_browse_api as E
import project_api.entities as PE
from project_api import store as S
import project_api as PA
import obsidian_adapter.entities as OE
from obsidian_adapter import vault as OV

class Explorer(unittest.TestCase):
    def test_00_pagination_is_deterministic_and_complete(self):
        def page_all(fetch):
            seen, cur, g = [], None, 0
            while g < 400:
                g += 1
                r = fetch(cur)
                seen += [i.get("id") or i.get("passage_id") for i in r["items"]]
                cur = r["page"]["next_cursor"]
                if not cur: break
            return seen
        p = page_all(lambda c: E.list_persons(c, 2))
        expect = sorted(r["id"] for r in E.list_persons(None, 50)["items"]) if \
            E.list_persons(None, 50)["page"]["total"] <= 50 else None
        self.assertEqual(len(p), E.list_persons(None, 1)["page"]["total"])
        self.assertEqual(len(p), len(set(p)), "分页不得重复")
        # 同一游标两次 → 同一页（确定性）
        first = E.list_persons(E.encode_cursor(0), 2)
        again = E.list_persons(E.encode_cursor(0), 2)
        self.assertEqual([i["id"] for i in first["items"]], [i["id"] for i in again["items"]])
        with self.assertRaises(ValueError):
            E.decode_cursor("!!!bad!!!")

    def test_01_mentions_pagination_complete(self):
        total = E.mentions("case.schreber", None, 1)["page"]["total"]
        seen, cur, g = [], None, 0
        while g < 50:
            g += 1
            r = E.mentions("case.schreber", cur, 200)
            seen += [i["passage_id"] for i in r["items"]]
            cur = r["page"]["next_cursor"]
            if not cur: break
        self.assertEqual(len(seen), total)
        self.assertEqual(len(seen), len(set(seen)))

    def test_02_project_integration_is_mention_only_and_kind_checked(self):
        tmp = tempfile.mkdtemp(dir=os.path.join(VAULT, "_workspace"))
        prev = S.PROJECTS_DIR
        S.PROJECTS_DIR = tmp
        try:
            proj = PA.create_project("测试项目 P5B", "", ["p5b"])
            pid = proj["project_id"]
            PE.add_entity_reference(pid, proj.get("revision"), "person.schreber", "person")
            PE.add_entity_reference(pid, None, "case.schreber", "case")
            refs = PE.list_entity_references(pid)["entity_references"]
            self.assertEqual(sorted(r["entity_id"] for r in refs),
                             ["case.schreber", "person.schreber"])
            for r in refs:
                self.assertEqual(r["evidence_kind"], "MENTION_ONLY")
                self.assertFalse(r["asserts_influence"])
                self.assertFalse(r["asserts_case_analysis"])
            with self.assertRaises(Exception):
                PE.add_entity_reference(pid, None, "case.schreber", "person")
        finally:
            S.PROJECTS_DIR = prev
            shutil.rmtree(tmp, ignore_errors=True)

    def test_03_obsidian_note_preserves_user_zone(self):
        iso = os.path.join("_workspace", "test_vaults", "p5b_entity_note")
        shutil.rmtree(os.path.join(VAULT, iso), ignore_errors=True)
        v = OV.Vault(iso)
        res = OE.save_entity_note("case.schreber", "case", vault=v)
        self.assertTrue(res["note"].startswith("_System/entities/"), res["note"])
        self.assertNotIn("/07_Cases/", res["note"])
        txt = v.read(res["note"])
        fm = txt.split("---")[1]
        self.assertNotIn("\nid:", fm, "派生参考笔记不得带 id frontmatter（会与 canonical 实体冲突）")
        self.assertIn("entity_ref: case.schreber", fm)
        v.write(res["note"], txt.rstrip("\n") + "\n\n## My Notes\n\n用户自己的字。\n")
        before = v.read(res["note"])
        OE.save_entity_note("case.schreber", "case", vault=v)
        after = v.read(res["note"])
        self.assertEqual(before, after, "用户区必须逐字节保留")
        self.assertIn("MENTION_ONLY", after)
        self.assertNotIn("asserts_influence: true", after)

    def test_04_ui_is_wired(self):
        """5B 原意：Person/Case Explorer 必须在 UI 上**可到达**。

        5D（Final Daily Use §11/§12）把导航收敛为 Home/Research/Explore/Projects/
        Bibliography/Obsidian/History/Saved，Person/Case 改由 **Explore 首页**进入
        （`data-explore="persons"` / `"cases"` → `?view=entities&kind=...`）。
        因此这里断言「Explore 首页有这两个入口 + 深链与路由仍然存在」，
        而不是继续要求一个已被 §11 取代的侧栏项。
        """
        idx = open(os.path.join(VAULT, "workspace_ui", "static", "index.html"),
                   encoding="utf-8").read()
        self.assertIn('id="nav-explore"', idx)
        home = open(os.path.join(VAULT, "workspace_ui", "static", "src", "home.js"),
                    encoding="utf-8").read()
        self.assertIn("'persons'", home)
        self.assertIn("'cases'", home)
        self.assertIn("?view=entities&kind=person", home)
        self.assertIn("?view=entities&kind=case", home)
        app = open(os.path.join(VAULT, "workspace_ui", "static", "src", "app.js"),
                   encoding="utf-8").read()
        self.assertIn("entities", app)
        js = open(os.path.join(VAULT, "workspace_ui", "static", "src", "entities.js"),
                  encoding="utf-8").read()
        self.assertIn("/api/explore/persons", js)
        self.assertIn("Mention evidence only", js)
        r = open(os.path.join(VAULT, "workspace_ui", "static", "src", "router.js"),
                 encoding="utf-8").read()
        self.assertIn("'entities'", r)

    def test_05_server_routes_exist_and_refuse_inference(self):
        src = open(os.path.join(VAULT, "workspace_ui", "server", "httpserver.py"),
                   encoding="utf-8").read()
        for route in ("/api/explore/persons", "/api/explore/cases",
                      "/api/explore/person", "/api/explore/case",
                      "/api/explore/mentions"):
            self.assertIn(route, src, route)
        self.assertIn("INFERENCE_NOT_SUPPORTED", src)

if __name__ == "__main__":
    unittest.main(verbosity=2)
