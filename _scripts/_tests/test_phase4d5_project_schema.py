#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §4/§5/§6/§58：ResearchProject 数据模型与 schema 版本"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
from project_api import store as PS


class ProjectSchema(unittest.TestCase):
    def test_00_required_fields(self):
        with L.isolated_projects("schema") as root:
            p = L.make_project("拉康欲望理论研究", "desc", tags=["désir"],
                               questions=["欲望与要求的关系？"])
            for k in ("project_id", "title", "description", "created_at", "updated_at",
                      "status", "tags", "revision", "schema_version",
                      "research_questions", "research_runs", "saved_passages",
                      "saved_concepts", "saved_seminars", "saved_terms", "notes",
                      "open_questions", "hypotheses", "bibliography_refs",
                      "obsidian_note"):
                self.assertIn(k, p, k)
            self.assertEqual(p["schema_version"], 1)
            self.assertEqual(p["status"], "ACTIVE")
            self.assertEqual(p["revision"], 1)
            self.assertTrue(p["research_questions"][0]["question_id"].startswith("q_"))

    def test_01_project_id_is_stable_and_not_title_based(self):
        with L.isolated_projects("schema_id"):
            p = L.make_project("Same Title")
            old = p["project_id"]
            self.assertTrue(PS.PROJECT_ID_RE.match(old), old)
            p2 = PA.update_project(old, p["revision"], title="Different Title")
            self.assertEqual(p2["project_id"], old, "改标题不得改 id（§7）")
            # 同名两个项目靠 id 区分（§36）
            other = L.make_project("Same Title")
            self.assertNotEqual(other["project_id"], old)

    def test_02_status_only_active_archived(self):
        with L.isolated_projects("schema_status"):
            p = L.make_project("S")
            with self.assertRaises(PA.Invalid):
                PA.update_project(p["project_id"], p["revision"], status="PENDING")
            p = PA.archive_project(p["project_id"], p["revision"])
            self.assertEqual(p["status"], "ARCHIVED")
            p = PA.restore_project(p["project_id"], p["revision"])
            self.assertEqual(p["status"], "ACTIVE")

    def test_03_on_disk_layout(self):
        with L.isolated_projects("schema_disk") as root:
            p = L.make_project("布局")
            pid = p["project_id"]
            self.assertTrue(os.path.isfile(os.path.join(root, pid, "project.json")))
            self.assertTrue(os.path.isdir(os.path.join(root, pid, "notes")) or True)
            PA.add_note(pid, p["revision"], "note text", title="t")
            self.assertTrue(os.path.isdir(os.path.join(root, pid, "notes")))
            PA.add_research_run(pid, 2, L.answer(L.Q_GAZE))
            self.assertTrue(os.path.isdir(os.path.join(root, pid, "snapshots")))

    def test_04_schema_version_rejected_when_wrong(self):
        with L.isolated_projects("schema_ver") as root:
            p = L.make_project("v")
            path = os.path.join(root, p["project_id"], "project.json")
            doc = json.load(open(path, encoding="utf-8"))
            doc["schema_version"] = 99
            json.dump(doc, open(path, "w", encoding="utf-8"))
            with self.assertRaises(PA.Invalid):
                PA.read_project(p["project_id"])

    def test_05_malformed_json_is_reported_not_crashed(self):
        with L.isolated_projects("schema_bad") as root:
            p = L.make_project("bad")
            path = os.path.join(root, p["project_id"], "project.json")
            open(path, "w", encoding="utf-8").write("{not json")
            with self.assertRaises(PA.Invalid):
                PA.read_project(p["project_id"])
            lst = PA.list_projects()
            self.assertTrue(any(i["status"] == "MALFORMED" for i in lst["items"]))

    def test_06_audit_log_written(self):
        with L.isolated_projects("schema_audit"):
            p = L.make_project("audit")
            PA.add_reference(p["project_id"], p["revision"], "concept", L.C_DESIR)
            actions = [a["action"] for a in PA.read_audit(p["project_id"])]
            self.assertIn("create", actions)
            self.assertIn("add_concept", actions)
