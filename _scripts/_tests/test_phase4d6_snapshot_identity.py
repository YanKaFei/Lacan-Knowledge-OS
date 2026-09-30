#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §58/§59/§60/§64/§72/§73/§75：来源身份、快照完整性与跨格式一致"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class SnapshotIdentity(unittest.TestCase):
    def test_00_source_answer_hash_on_every_export(self):
        d = L.doc()
        self.assertEqual(len(d["source_answer_hash"]), 64)
        self.assertEqual(d["source_answer_hash"], EX.prov.answer_hash(L.view()))

    def test_01_determinism_except_volatile(self):
        """§60：同 source + 同 options → 规范化 payload 一致；export_id 必须互不相同
        （否则同一秒导两次会互相覆盖 —— 实测踩过）。"""
        a, b = L.doc(), L.doc()
        self.assertNotEqual(a["export_id"], b["export_id"])
        self.assertEqual(EX.export_payload_hash(a), EX.export_payload_hash(b))
        self.assertEqual(EX.canonical_payload(a), EX.canonical_payload(b))
        with L.export_root("nodup"):
            r1 = EX.build_bundle(a)
            r2 = EX.build_bundle(b)
            self.assertNotEqual(r1["rel_dir"], r2["rel_dir"])
            self.assertTrue(os.path.isdir(r1["dir"]))
            self.assertTrue(os.path.isdir(r2["dir"]))

    def test_02_project_run_keeps_its_own_hash(self):
        import _project_testlib as PL
        import project_api as PA
        with PL.isolated_projects("hashrun"):
            p = PL.make_project("H")
            view = L.view()
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            d = EX.build_from_project_run(p["project_id"], rec["run_id"])
            self.assertEqual(d["source_answer_hash"], rec["source_answer_hash"])
            self.assertEqual(d["source_snapshot_hash"], rec["snapshot_hash"])

    def test_03_bundle_manifest_carries_hashes(self):
        with L.export_root("ident"):
            out = EX.build_bundle(L.doc())
            man = out["manifest"]
            self.assertEqual(man["source_answer_hash"], out["manifest"]["source_answer_hash"])
            self.assertTrue(man["export_payload_hash"])
            self.assertTrue(man["content_hash"])
            self.assertEqual(man["core_freeze_version"], "scholarly_core_freeze_v1")

    def test_04_user_edited_document_is_marked(self):
        """§64：用户编辑过的 note 不能宣称 scholarly verified。"""
        d = L.doc()
        d["evidence_role"] = "USER_EDITED_DOCUMENT"
        md = EX.markdown.render(d)
        self.assertIn("USER_EDITED_DOCUMENT", md)
        self.assertNotIn("SCHOLARLY_CORE_OUTPUT", md)

    def test_05_default_evidence_role_is_core_output(self):
        self.assertEqual(L.doc()["evidence_role"], "SCHOLARLY_CORE_OUTPUT")
        proj = EX.build_project_summary.__doc__
        self.assertIsNotNone(proj)

    def test_06_export_options_recorded_in_manifest(self):
        with L.export_root("opts"):
            d = L.doc()
            d["export_options"] = {"include_context": 0, "purpose": "qa"}
            out = EX.build_bundle(d)
            self.assertEqual(out["manifest"]["export_options"]["purpose"], "qa")
