#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §4/§8/§11/§35/§38：创建 / 读取 / 更新 / 归档 / 过滤"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA


class CreateUpdate(unittest.TestCase):
    def test_00_create_read_update(self):
        with L.isolated_projects("crud"):
            p = L.make_project("T1", "d1", tags=["a", "b"])
            pid = p["project_id"]
            got = PA.get_project(pid)
            self.assertEqual(got["title"], "T1")
            self.assertEqual(got["tags"], ["a", "b"])
            p2 = PA.update_project(pid, p["revision"], description="d2", tags=["b", "c"])
            self.assertEqual(p2["description"], "d2")
            self.assertEqual(p2["tags"], ["b", "c"])
            self.assertEqual(p2["revision"], 2)
            self.assertEqual(p2["project_id"], pid)

    def test_01_revision_increments_once_per_mutation(self):
        with L.isolated_projects("rev"):
            p = L.make_project("R")
            pid = p["project_id"]
            r = p["revision"]
            for i, fn in enumerate([
                    lambda: PA.add_question(pid, r, "q1"),
                    lambda: PA.update_project(pid, r + 1, title="R2"),
                    lambda: PA.add_note(pid, r + 2, "note")]):
                out = fn()
                self.assertEqual(out["revision"], r + i + 1)
            self.assertEqual(PA.get_project(pid)["revision"], r + 3)

    def test_02_list_filters(self):
        with L.isolated_projects("list"):
            a = L.make_project("Alpha", tags=["x"])
            b = L.make_project("Beta", tags=["y"])
            PA.archive_project(b["project_id"], b["revision"])
            self.assertEqual(PA.list_projects(status="ACTIVE")["total"], 1)
            self.assertEqual(PA.list_projects(status="ARCHIVED")["total"], 1)
            self.assertEqual(PA.list_projects(tag="x")["total"], 1)
            self.assertEqual(PA.list_projects(query="alph")["total"], 1)
            self.assertEqual(PA.list_projects()["total"], 2)

    def test_03_summary_counts_are_workspace_counts(self):
        with L.isolated_projects("counts"):
            p = L.make_project("C")
            pid = p["project_id"]
            p = PA.add_reference(pid, p["revision"], "concept", L.C_DESIR)
            p = PA.add_question(pid, p["revision"], "q")
            s = PA.summary(p)
            self.assertEqual(s["counts"]["saved_concepts"], 1)
            self.assertEqual(s["counts"]["research_questions"], 1)
            self.assertEqual(s["counts"]["research_runs"], 0)
            self.assertIn("counts", s)
            blob = str(s).lower()
            for bad in ("quality", "progress", "completeness", "confidence"):
                self.assertNotIn(bad, blob)

    def test_04_archive_does_not_delete(self):
        with L.isolated_projects("archive"):
            p = L.make_project("A")
            pid = p["project_id"]
            p = PA.add_note(pid, p["revision"], "keep me")
            arch = PA.archive_project(pid, p["revision"])
            self.assertEqual(arch["status"], "ARCHIVED")
            self.assertEqual(len(arch["notes"]), 1, "归档不得删除内容（§38）")
            self.assertEqual(PA.get_project(pid)["notes"][0]["text"], "keep me")

    def test_05_duplicate_titles_allowed(self):
        with L.isolated_projects("dup"):
            a = L.make_project("Same")
            b = L.make_project("Same")
            self.assertNotEqual(a["project_id"], b["project_id"])
            self.assertEqual(PA.list_projects()["total"], 2)

    def test_06_unknown_project_is_not_found(self):
        with L.isolated_projects("missing"):
            with self.assertRaises(PA.NotFound):
                PA.get_project("proj_01M3CVMXRP2N7PGSK0DE8Y03W8")
            with self.assertRaises(PA.Invalid):
                PA.get_project("../etc/passwd")

    def test_07_timeline_is_workspace_activity(self):
        with L.isolated_projects("timeline"):
            p = L.make_project("T")
            pid = p["project_id"]
            PA.add_question(pid, p["revision"], "q")
            tl = PA.timeline(pid)
            kinds = {e["kind"] for e in tl["items"]}
            self.assertIn("project_created", kinds)
            self.assertIn("question", kinds)
            self.assertIn("workspace activity", tl["label"])
