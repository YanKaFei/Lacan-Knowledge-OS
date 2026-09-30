#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §17/§18/§40/§46/§54：Passage 引用（只存 id + hash，不复制正文）"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
import browse_api as B


class PassageRefs(unittest.TestCase):
    def test_00_reference_stores_id_not_content(self):
        with L.isolated_projects("pref"):
            p = L.make_project("P")
            p = PA.add_reference(p["project_id"], p["revision"], "passage", L.P_L1,
                                 note="关键段", source_context="gaze 研究")
            ref = p["saved_passages"][0]
            self.assertEqual(ref["id"], L.P_L1)
            self.assertIn("added_at", ref)
            self.assertEqual(ref["user_note"], "关键段")
            self.assertIn("passage_hash_at_save", ref)
            self.assertNotIn("text", ref, "引用不得复制 passage 正文")
            self.assertNotIn("raw_text", str(ref))

    def test_01_referent_is_verified(self):
        with L.isolated_projects("pref2"):
            p = L.make_project("P")
            PA.add_reference(p["project_id"], p["revision"], "passage", L.P_L1)
            ref = PA.get_project(p["project_id"])["saved_passages"][0]
            self.assertFalse(ref["broken"])
            self.assertEqual(ref["referent"]["status"], "OK")
            self.assertEqual(ref["referent"]["source_layer"], "L1")
            self.assertEqual(ref["referent"]["seminar"], "seminar.S11")

    def test_02_passage_content_is_reread_from_store(self):
        """§18：canonical source 仍是 passage store；显示时 `get_passage()`。"""
        p = B.get_passage_view(L.P_L1)
        self.assertTrue(p["text"])
        with L.isolated_projects("pref3"):
            proj = L.make_project("P")
            PA.add_reference(proj["project_id"], proj["revision"], "passage", L.P_L1)
            again = B.get_passage_view(
                PA.get_project(proj["project_id"])["saved_passages"][0]["id"])
            self.assertEqual(again["text"], p["text"])

    def test_03_duplicate_add_is_idempotent(self):
        with L.isolated_projects("pref4"):
            p = L.make_project("P")
            r = p["revision"]
            p = PA.add_reference(p["project_id"], r, "passage", L.P_L1)
            p = PA.add_reference(p["project_id"], p["revision"], "passage", L.P_L1)
            self.assertEqual(len(p["saved_passages"]), 1)
            self.assertEqual(p["revision"], 2, "重复加入不应产生新行")

    def test_04_broken_reference_is_shown_not_deleted(self):
        with L.isolated_projects("pref5"):
            p = L.make_project("P")
            p = PA.add_reference(p["project_id"], p["revision"], "passage",
                                 "passage.S99.unknown.P9999")
            got = PA.get_project(p["project_id"])
            self.assertIn("passage.S99.unknown.P9999", got["broken_references"])
            self.assertEqual(len(got["saved_passages"]), 1, "不得静默删除")
            self.assertTrue(got["saved_passages"][0]["broken"])

    def test_05_remove_only_removes_workspace_reference(self):
        with L.isolated_projects("pref6"):
            p = L.make_project("P")
            p = PA.add_reference(p["project_id"], p["revision"], "passage", L.P_L1)
            before = B.get_passage_view(L.P_L1)
            p = PA.remove_reference(p["project_id"], p["revision"], "passage", L.P_L1)
            self.assertEqual(p["saved_passages"], [])
            self.assertEqual(B.get_passage_view(L.P_L1), before,
                             "移除引用不得影响 canonical passage")

    def test_06_one_passage_many_projects(self):
        """§70：同一 passage 属于多个 project —— canonical 只有一份，引用两份。"""
        with L.isolated_projects("pref7"):
            a = L.make_project("A")
            b = L.make_project("B")
            a = PA.add_reference(a["project_id"], a["revision"], "passage", L.P_L1)
            b = PA.add_reference(b["project_id"], b["revision"], "passage", L.P_L1)
            self.assertEqual([x["id"] for x in a["saved_passages"]], [L.P_L1])
            self.assertEqual([x["id"] for x in b["saved_passages"]], [L.P_L1])
            self.assertEqual(B.get_passage_view(L.P_L1)["passage_id"], L.P_L1)

    def test_07_invalid_ids_rejected(self):
        with L.isolated_projects("pref8"):
            p = L.make_project("P")
            for bad in ("../../etc/passwd", "passage/../x", "", "a" * 300):
                with self.assertRaises(PA.Invalid):
                    PA.add_reference(p["project_id"], p["revision"], "passage", bad)
