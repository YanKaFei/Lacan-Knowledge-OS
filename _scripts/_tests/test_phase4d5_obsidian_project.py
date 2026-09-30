#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §27–§31/§62/§63：Obsidian Project Hub（映射表权威、链接不嵌入、归档不删）"""
import json, os, shutil, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
from obsidian_adapter import adapter as OA
from obsidian_adapter import vault as OV
from obsidian_adapter.frontmatter import parse_frontmatter


class ObsidianProject(unittest.TestCase):
    def setUp(self):
        self.ctx = L.isolated_projects("obs")
        self.ctx.__enter__()
        self.root = os.path.join("_workspace", "test_vaults", "project_hub")
        shutil.rmtree(os.path.join(VAULT, self.root), ignore_errors=True)
        self.v = OV.Vault(self.root)
        self._old = os.environ.get("OBSIDIAN_VAULT_PATH")
        os.environ["OBSIDIAN_VAULT_PATH"] = self.root

    def tearDown(self):
        if self._old is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = self._old
        self.ctx.__exit__(None, None, None)

    def test_00_frontmatter_and_sections(self):
        p = L.make_project("拉康欲望理论研究", "长期项目", tags=["désir"])
        out = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        self.assertTrue(out["ok"], out)
        txt = self.v.read(out["note"])
        meta, _ = parse_frontmatter(txt)
        self.assertEqual(meta["type"], "lacan-research-project")
        self.assertEqual(meta["project_id"], p["project_id"])
        self.assertEqual(meta["status"], "ACTIVE")
        self.assertIn("created", meta)
        for sec in ("## Research Questions", "## Research Runs", "## Concepts",
                    "## Seminars", "## Saved Passages", "## Open Questions",
                    "## My Notes"):
            self.assertIn(sec, txt)

    def test_01_runs_are_linked_not_embedded(self):
        """§29：不要把 run 全文塞进 Project Note。"""
        view = L.answer(L.Q_GAZE)
        p = L.make_project("Hub")
        p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
        out = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        txt = self.v.read(out["note"])
        body_section = txt.split("## Research Runs")[1].split("##")[0]
        self.assertIn("not saved to Obsidian yet", body_section)
        for s in view["sections"]:
            if s.get("text"):
                self.assertNotIn(s["text"][:60], txt,
                                 "run 正文不得复制进 Project Hub")
        self.assertLess(len(txt), 20000)

    def test_02_mapping_is_authoritative(self):
        """§62：映射表才是权威；改名不改路径。"""
        p = L.make_project("Old Name")
        out1 = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        p2 = PA.update_project(p["project_id"], p["revision"], title="New Name")
        out2 = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        self.assertEqual(out2["note"], out1["note"], "改名不得另建文件")
        mapping = OA.project_note_map(vault=self.v)
        self.assertEqual(mapping[p["project_id"]], out1["note"])
        self.assertTrue(self.v.exists(out1["note"]))

    def test_03_user_zone_preserved(self):
        p = L.make_project("UZ")
        out = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        rel = out["note"]
        marker = "\n\n## 我自己的批注\n\n- 不要动我。\n"
        self.v.write(rel, (self.v.read(rel) or "").rstrip("\n") + marker)
        before = self.v.read(rel).split("## My Notes")[1]
        PA.add_note(p["project_id"], p["revision"], "新笔记")
        OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        after = self.v.read(rel).split("## My Notes")[1]
        self.assertEqual(before, after, "用户区必须逐字节保留（§61）")

    def test_04_archive_updates_managed_metadata_only(self):
        """§63：归档只更新 managed 元数据，绝不删除用户笔记。"""
        p = L.make_project("A")
        out = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        rel = out["note"]
        self.v.write(rel, (self.v.read(rel) or "") + "\n用户自己加的一段。\n")
        PA.archive_project(p["project_id"], p["revision"])
        out2 = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        txt = self.v.read(out2["note"])
        self.assertTrue(self.v.exists(rel), "归档不得删除 note")
        self.assertIn("用户自己加的一段。", txt)
        meta, _ = parse_frontmatter(txt)
        self.assertEqual(meta["status"], "ARCHIVED")

    def test_05_research_link_matched_by_hash_not_title(self):
        """§30：run ↔ Research Note 靠 source_answer_hash 对上（不靠标题/时间猜）。"""
        view = L.answer(L.Q_GAZE)
        p = L.make_project("Link")
        p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
        # 在 vault 里放一份 manifest（模拟 4D.3 保存过研究）
        man_dir = self.v.resolve("_System", "manifests")
        os.makedirs(man_dir, exist_ok=True)
        man = {"schema_version": "obsidian-save-manifest/v1",
               "research_id": "res-test", "source_answer_hash": rec["source_answer_hash"],
               "research_note_path": "Research/2026-01-01 - test.md",
               "answer_state": view["state"]}
        with open(os.path.join(man_dir, "res-test.json"), "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False)
        links = OA.research_links_for_project(PA.get_project(p["project_id"]), vault=self.v)
        self.assertEqual(len(links), 1)
        self.assertTrue(links[0]["linked"])
        self.assertEqual(links[0]["research_note"], "Research/2026-01-01 - test.md")

    def test_06_unmanaged_existing_file_is_preserved(self):
        """用户在同名路径上有自己的文件 → 绝不改写，改用 `<title> (2).md`。"""
        p = L.make_project("Collide")
        rel = "Projects/%s.md" % OA.slug("Collide")
        self.v.write(rel, "# 用户自己的文件\n")
        out = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        self.assertEqual(self.v.read(rel), "# 用户自己的文件\n", "用户文件必须逐字节不变")
        self.assertNotEqual(out["note"], rel, "不得接管用户既有文件")
        self.assertTrue(self.v.exists(out["note"]))
        mapping = OA.project_note_map(vault=self.v)
        self.assertEqual(mapping[p["project_id"]], out["note"])

    def test_06b_mapped_but_foreign_file_is_not_rewritten(self):
        """路径已映射给本项目、但文件不是我们的 → existing_unmanaged_preserved。"""
        p = L.make_project("Mapped")
        first = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        self.v.write(first["note"], "# 用户把系统文件换成了自己的内容\n")
        out = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        self.assertEqual(out["status"], "existing_unmanaged_preserved")
        self.assertEqual(self.v.read(first["note"]),
                         "# 用户把系统文件换成了自己的内容\n")

    def test_07_frontmatter_has_no_invented_fields(self):
        p = L.make_project("FM")
        out = OA.save_project_note(PA.get_project(p["project_id"]), vault=self.v)
        meta, _ = parse_frontmatter(self.v.read(out["note"]))
        for bad in ("confidence", "quality", "progress", "score"):
            self.assertNotIn(bad, meta)
