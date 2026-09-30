#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §32/§58-D：Réel / réalité 控制案例（禁止 alias collapse）"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key


class ReelRealite(unittest.TestCase):
    def test_00_two_distinct_entities(self):
        """§58 Case D：不得 alias collapse。"""
        d = L.B.reel_realite_control()
        self.assertTrue(d["distinct_entities"])
        self.assertFalse(d["collapsed"])
        # 交集必须为空：一旦有交集就是 alias collapse
        self.assertEqual(set(d["reel_entities"]) & set(d["realite_entities"]), set())
        self.assertTrue(set(d["reel_entities"]))
        self.assertTrue(set(d["realite_entities"]))

    def test_01_lookup_does_not_merge(self):
        reel = L.B.get_term_view("Réel", attestation_forms=["实在界"])
        realite = L.B.get_term_view("réalité")
        self.assertNotIn(L.C_REALITE,
                         [e["concept_id"] for e in reel["entities"]])
        self.assertNotIn(L.C_REEL,
                         [e["concept_id"] for e in realite["entities"]])
        self.assertEqual([e["concept_id"] for e in realite["entities"]], [L.C_REALITE])

    def test_02_no_shared_alias_forms(self):
        """两边的字面形式不得交叉（交叉即 collapse 风险）。"""
        i = L.B.concept_index()
        reel_forms = {f["form"] for f in i[L.C_REEL]["forms"]}
        realite_forms = {f["form"] for f in i[L.C_REALITE]["forms"]}
        self.assertEqual(reel_forms & realite_forms, set())
        self.assertIn("实在界", reel_forms)
        self.assertIn("现实", realite_forms)

    def test_03_distinction_is_recorded_in_ontology(self):
        """本体里必须**已经记录**了二者的区分（不是前端现编）。"""
        rels = L.B.relations_view(L.C_REEL)
        preds = {(r["predicate"], r["other_id"]) for r in
                 rels["reviewed"] + rels["candidate"]}
        self.assertIn(("distinct_from", L.C_REALITE), preds)
        self.assertTrue(all(r["review_status"] for r in rels["candidate"]))

    def test_04_attestation_differs_by_form(self):
        d = L.B.reel_realite_control()
        reel = {r["form"]: r["hits"] for r in d["reel"]["attestation"]}
        realite = {r["form"]: r["hits"] for r in d["realite"]["attestation"]}
        self.assertGreater(reel.get("实在界", 0), 0)
        self.assertGreater(realite.get("réalité", 0), 0)
        self.assertNotIn("réalité", reel)
        self.assertNotIn("实在界", realite)

    def test_05_ui_renders_side_by_side(self):
        src = open(os.path.join(VAULT, "workspace_ui", "static", "src", "explorer.js"),
                   encoding="utf-8").read()
        self.assertIn("control-reel", src)
        self.assertIn("control-realite", src)
        assert_text_wired(self, "explorer.js", "collapsed — investigate")
