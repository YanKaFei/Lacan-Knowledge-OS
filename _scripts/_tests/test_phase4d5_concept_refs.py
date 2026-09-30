#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §19–§21/§46：Concept / Seminar / Term 引用（只做 reference）"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
import browse_api as B


class ConceptRefs(unittest.TestCase):
    def test_00_concept_reference_creates_no_relation(self):
        with L.isolated_projects("cref"):
            before = B.relations_view(L.C_DESIR)
            p = L.make_project("C")
            PA.add_reference(p["project_id"], p["revision"], "concept", L.C_DESIR)
            ref = PA.get_project(p["project_id"])["saved_concepts"][0]
            self.assertEqual(ref["id"], L.C_DESIR)
            self.assertEqual(ref["referent"]["status"], "OK")
            after = B.relations_view(L.C_DESIR)
            self.assertEqual(before, after, "项目引用不得创建 canonical 关系（§19）")

    def test_01_seminar_reference(self):
        with L.isolated_projects("cref2"):
            p = L.make_project("C")
            PA.add_reference(p["project_id"], p["revision"], "seminar", L.S_SEMINAR)
            ref = PA.get_project(p["project_id"])["saved_seminars"][0]
            self.assertEqual(ref["id"], "seminar.S11")
            self.assertEqual(ref["referent"]["status"], "OK")
            self.assertTrue(ref["referent"]["label"])

    def test_02_term_reference_keeps_three_layers(self):
        """§21：term 引用必须仍能回到 mapping / attestation / interpretation 三层。"""
        with L.isolated_projects("cref3"):
            p = L.make_project("C")
            PA.add_reference(p["project_id"], p["revision"], "term", "jouissance")
            ref = PA.get_project(p["project_id"])["saved_terms"][0]
            self.assertFalse(ref["broken"])
            tv = B.get_term_view(ref["id"])
            for zone in ("mapping", "attestation", "interpretation"):
                self.assertIn(zone, tv)
            self.assertFalse(tv["interpretation"]["generated"])

    def test_03_broken_concept_reference(self):
        with L.isolated_projects("cref4"):
            p = L.make_project("C")
            p = PA.add_reference(p["project_id"], p["revision"], "concept",
                                 "concept.does-not-exist")
            got = PA.get_project(p["project_id"])
            self.assertTrue(got["saved_concepts"][0]["broken"])
            self.assertIn("concept.does-not-exist", got["broken_references"])

    def test_04_invalid_kind_rejected(self):
        with L.isolated_projects("cref5"):
            p = L.make_project("C")
            with self.assertRaises(PA.Invalid):
                PA.add_reference(p["project_id"], p["revision"], "person", "x")

    def test_05_all_four_kinds_coexist(self):
        with L.isolated_projects("cref6"):
            p = L.make_project("C")
            for kind, item in (("passage", L.P_L1), ("concept", L.C_OBJET),
                               ("seminar", L.S_SEMINAR), ("term", "jouissance")):
                p = PA.add_reference(p["project_id"], p["revision"], kind, item)
            p = PA.get_project(p["project_id"])
            s = PA.summary(p)["counts"]
            self.assertEqual((s["saved_passages"], s["saved_concepts"],
                              s["saved_seminars"], s["saved_terms"]), (1, 1, 1, 1))
            self.assertEqual(p["broken_references"], [])
