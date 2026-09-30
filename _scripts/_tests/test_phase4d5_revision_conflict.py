#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §56/§57：revision 并发控制（WORKSPACE_CONFLICT）"""
import os, sys, threading, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA


class RevisionConflict(unittest.TestCase):
    def test_00_stale_revision_is_rejected(self):
        with L.isolated_projects("conflict"):
            p = L.make_project("C")
            pid = p["project_id"]
            PA.update_project(pid, p["revision"], title="C2")
            with self.assertRaises(PA.Conflict) as ctx:
                PA.update_project(pid, p["revision"], title="C3")
            self.assertIn("WORKSPACE_CONFLICT", str(ctx.exception))
            self.assertEqual(PA.get_project(pid)["title"], "C2",
                             "冲突时不得写入任何改动")

    def test_01_conflict_reports_expected_and_actual(self):
        with L.isolated_projects("conflict2"):
            p = L.make_project("C")
            pid = p["project_id"]
            PA.add_note(pid, p["revision"], "n")
            try:
                PA.add_note(pid, 1, "n2")
                self.fail("should conflict")
            except PA.Conflict as exc:
                self.assertEqual(exc.expected, 1)
                self.assertEqual(exc.actual, 2)

    def test_02_none_revision_skips_check_for_internal_use(self):
        with L.isolated_projects("conflict3"):
            p = L.make_project("C")
            pid = p["project_id"]
            proj, changed = PA.store.mutate(pid, None, lambda d: d.__setitem__("obsidian_note", "x") or True)
            self.assertTrue(changed)
            self.assertEqual(proj["obsidian_note"], "x")

    def test_03_concurrent_writers_do_not_lose_updates(self):
        """两个线程同时加引用：最终两条都在（进程内锁 + revision 检查）。"""
        with L.isolated_projects("conflict4"):
            p = L.make_project("C")
            pid = p["project_id"]
            results = []

            def worker(kind, item):
                try:
                    PA.add_reference(pid, None, kind, item)
                    results.append(("ok", item))
                except PA.Conflict:
                    results.append(("conflict", item))

            t1 = threading.Thread(target=worker, args=("concept", L.C_DESIR))
            t2 = threading.Thread(target=worker, args=("concept", L.C_OBJET))
            t1.start(); t2.start(); t1.join(); t2.join()
            got = PA.get_project(pid)
            ids = {r["id"] for r in got["saved_concepts"]}
            self.assertEqual(ids, {L.C_DESIR, L.C_OBJET}, results)

    def test_04_error_shape_for_ui(self):
        from workspace_ui.server import project_view as PV
        with L.isolated_projects("conflict5"):
            p = L.make_project("C")
            pid = p["project_id"]
            PA.update_project(pid, p["revision"], title="C2")
            out = PV.project_update(pid, p["revision"], title="C3")
            self.assertEqual(out["code"], "WORKSPACE_CONFLICT")
            self.assertEqual(out["expected_revision"], 1)
            self.assertEqual(out["actual_revision"], 2)
            self.assertIn("nothing was written", out["body"])
