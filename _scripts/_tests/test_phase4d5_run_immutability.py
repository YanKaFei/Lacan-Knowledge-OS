#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §15/§53/§77：Run 不可变 + 快照校验"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA


class RunImmutability(unittest.TestCase):
    def setUp(self):
        self.ctx = L.isolated_projects("immutable")
        self.root = self.ctx.__enter__()
        p = L.make_project("I")
        self.pid = p["project_id"]
        self.view = L.answer(L.Q_GAZE)
        p, self.rec = PA.add_research_run(self.pid, p["revision"], self.view)
        self.project = p

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_00_second_run_creates_new_id_never_overwrites(self):
        p, rec2 = PA.add_research_run(self.pid, self.project["revision"], self.view)
        self.assertNotEqual(rec2["run_id"], self.rec["run_id"])
        self.assertEqual(len(p["research_runs"]), 2)
        a = PA.get_run(self.pid, self.rec["run_id"])
        b = PA.get_run(self.pid, rec2["run_id"])
        self.assertEqual(a["snapshot"], b["snapshot"])
        self.assertNotEqual(a["run_id"], b["run_id"])

    def test_01_snapshot_file_marks_immutable(self):
        rec = PA.get_run(self.pid, self.rec["run_id"])
        self.assertTrue(rec["immutable"])
        self.assertIn("hijacked_fields", rec)

    def test_02_verify_returns_verified(self):
        out = PA.verify_project_runs(self.pid)
        self.assertEqual(out["overall"], "VERIFIED")
        self.assertEqual(out["runs"][0]["status"], "VERIFIED")
        self.assertEqual(out["runs"][0]["stored_hash"],
                         out["runs"][0]["recomputed_hash"])

    def test_03_tampered_snapshot_is_modified(self):
        path = os.path.join(self.root, self.pid, "snapshots",
                            "%s.json" % self.rec["run_id"])
        doc = json.load(open(path, encoding="utf-8"))
        doc["snapshot"]["sections"][0]["text"] = "被改写的文本"
        json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        out = PA.verify_project_runs(self.pid)
        self.assertEqual(out["overall"], "MODIFIED")
        self.assertEqual(out["runs"][0]["status"], "MODIFIED")

    def test_04_missing_citation_becomes_broken_reference(self):
        path = os.path.join(self.root, self.pid, "snapshots",
                            "%s.json" % self.rec["run_id"])
        doc = json.load(open(path, encoding="utf-8"))
        doc["citation_ids"] = ["passage.S99.unknown.P9999"]
        json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        out = PA.verify_project_runs(self.pid)
        self.assertEqual(out["runs"][0]["status"], "BROKEN_REFERENCE")
        self.assertEqual(out["runs"][0]["broken_citations"],
                         ["passage.S99.unknown.P9999"])

    def test_05_missing_snapshot_file_is_reported(self):
        os.remove(os.path.join(self.root, self.pid, "snapshots",
                               "%s.json" % self.rec["run_id"]))
        out = PA.verify_project_runs(self.pid)
        self.assertEqual(out["runs"][0]["status"], "MISSING_SNAPSHOT")
        self.assertNotEqual(out["overall"], "VERIFIED")
