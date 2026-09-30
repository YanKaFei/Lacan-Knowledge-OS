#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §22/§23/§48：Open Questions（来源必须记录，不自动变知识）"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key


class OpenQuestions(unittest.TestCase):
    def test_00_user_created_origin(self):
        with L.isolated_projects("oq"):
            p = L.make_project("O")
            p = PA.add_open_question(p["project_id"], p["revision"], "需要 S13 的 L1 证据。")
            q = p["open_questions"][0]
            self.assertEqual(q["origin"], "user_created")
            self.assertFalse(q["is_evidence"])
            self.assertEqual(q["status"], "OPEN")

    def test_01_from_limitation_records_run(self):
        view = L.abstention_answer()
        with L.isolated_projects("oq2"):
            p = L.make_project("O")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            p = PA.add_open_question(p["project_id"], p["revision"],
                                     "语料缺少该主题的论述。",
                                     origin="created_from_limitation",
                                     run_id=rec["run_id"],
                                     limitation="目标主题在当前语料中只有极少数旁及命中")
            q = p["open_questions"][0]
            self.assertEqual(q["origin"], "created_from_limitation")
            self.assertEqual(q["run_id"], rec["run_id"])
            self.assertTrue(q["limitation"])

    def test_02_origin_requires_run_id(self):
        with L.isolated_projects("oq3"):
            p = L.make_project("O")
            with self.assertRaises(PA.Invalid):
                PA.add_open_question(p["project_id"], p["revision"], "x",
                                     origin="created_from_run")
            with self.assertRaises(PA.Invalid):
                PA.add_open_question(p["project_id"], p["revision"], "x",
                                     origin="invented_origin")

    def test_03_convert_from_abstention_missing_information(self):
        """§48：弃权 run 的 missing information → open question（用户点击才发生）。"""
        view = L.abstention_answer()
        with L.isolated_projects("oq4"):
            p = L.make_project("O")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            p = PA.open_questions_from_run(p["project_id"], p["revision"], rec["run_id"])
            self.assertTrue(p["open_questions"])
            origins = {q["origin"] for q in p["open_questions"]}
            self.assertTrue(origins <= {"created_from_run", "created_from_limitation"})
            for q in p["open_questions"]:
                self.assertEqual(q["run_id"], rec["run_id"])
                self.assertFalse(q["is_evidence"])

    def test_04_open_question_does_not_create_relation(self):
        """§23：写进项目不会变成知识关系。"""
        import browse_api as B
        before = {c: B.relations_view(c) for c in (L.C_DESIR, L.C_OBJET)}
        with L.isolated_projects("oq5"):
            p = L.make_project("O")
            PA.add_open_question(p["project_id"], p["revision"],
                                 "diamond 是否表达主体与对象 a 的拓扑非对称？")
        after = {c: B.relations_view(c) for c in (L.C_DESIR, L.C_OBJET)}
        self.assertEqual(before, after)

    def test_05_ui_labels_origin(self):
        js = open(os.path.join(VAULT, "workspace_ui", "static", "src", "project.js"),
                  encoding="utf-8").read()
        self.assertIn("Open Questions", js)
        assert_text_wired(self, "project.js",
                          "An open question is a research question with a recorded origin.")
