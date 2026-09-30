#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §40/§41/§70：跨项目隔离与多项目引用"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
import browse_api as B


class CrossProjectIsolation(unittest.TestCase):
    def setUp(self):
        self.ctx = L.isolated_projects("cross")
        self.ctx.__enter__()
        self.view = L.answer(L.Q_GAZE)
        self.a = L.make_project("Project A", "A 的上下文")
        self.b = L.make_project("Project B", "B 的上下文")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_00_same_passage_two_projects_two_references(self):
        """§70：canonical passage 只有一份，workspace 引用两份。"""
        self.a = PA.add_reference(self.a["project_id"], self.a["revision"], "passage", L.P_L1)
        self.b = PA.add_reference(self.b["project_id"], self.b["revision"], "passage", L.P_L1)
        ra = PA.get_project(self.a["project_id"])["saved_passages"]
        rb = PA.get_project(self.b["project_id"])["saved_passages"]
        self.assertEqual([x["id"] for x in ra], [L.P_L1])
        self.assertEqual([x["id"] for x in rb], [L.P_L1])
        self.assertEqual(B.get_passage_view(L.P_L1)["passage_id"], L.P_L1)
        # 不是同一份存储对象
        self.assertIsNot(ra[0], rb[0])

    def test_01_contexts_do_not_leak(self):
        """§41：Project A 的上下文不得进入 Project B。"""
        self.a = PA.add_note(self.a["project_id"], self.a["revision"], "A 私有笔记，含暗号 ZZZ-A")
        self.b = PA.add_note(self.b["project_id"], self.b["revision"], "B 私有笔记，含暗号 ZZZ-B")
        ctx_a = PA.context_for_agent(self.a["project_id"],
                                     selected_note_ids=[n["note_id"]
                                                        for n in PA.get_project(
                                                            self.a["project_id"])["notes"]])
        ctx_b = PA.context_for_agent(self.b["project_id"],
                                     selected_note_ids=[n["note_id"]
                                                        for n in PA.get_project(
                                                            self.b["project_id"])["notes"]])
        self.assertNotIn("ZZZ-B", str(ctx_a))
        self.assertNotIn("ZZZ-A", str(ctx_b))
        self.assertEqual(ctx_a["project_id"], self.a["project_id"])
        self.assertEqual(ctx_b["project_id"], self.b["project_id"])

    def test_02_runs_do_not_migrate(self):
        self.a, rec = PA.add_research_run(self.a["project_id"], self.a["revision"], self.view)
        self.assertEqual(len(PA.list_runs(self.a["project_id"])), 1)
        self.assertEqual(len(PA.list_runs(self.b["project_id"])), 0)
        self.assertIsNone(PA.get_run(self.b["project_id"], rec["run_id"]))

    def test_03_same_research_note_in_two_projects(self):
        """同一 research run 可以进入两个项目，但快照各自独立登记。"""
        self.a, rec_a = PA.add_research_run(self.a["project_id"], self.a["revision"],
                                            self.view)
        self.b, rec_b = PA.add_research_run(self.b["project_id"], self.b["revision"],
                                            self.view)
        self.assertNotEqual(rec_a["run_id"], rec_b["run_id"])
        self.assertEqual(rec_a["source_answer_hash"], rec_b["source_answer_hash"])
        self.assertEqual(len(PA.list_runs(self.a["project_id"])), 1)
        self.assertEqual(len(PA.list_runs(self.b["project_id"])), 1)

    def test_04_broken_reference_is_per_project(self):
        self.a = PA.add_reference(self.a["project_id"], self.a["revision"], "concept",
                                  "concept.nope")
        self.b = PA.add_reference(self.b["project_id"], self.b["revision"], "concept",
                                  L.C_DESIR)
        self.assertEqual(len(PA.get_project(self.a["project_id"])["broken_references"]), 1)
        self.assertEqual(PA.get_project(self.b["project_id"])["broken_references"], [])

    def test_05_search_is_scoped_to_one_project(self):
        self.a = PA.add_note(self.a["project_id"], self.a["revision"], "只在 A 出现的词 QQQ")
        self.b = PA.add_note(self.b["project_id"], self.b["revision"], "B 的内容")
        hits_a = PA.search_project(self.a["project_id"], "QQQ")["items"]
        hits_b = PA.search_project(self.b["project_id"], "QQQ")["items"]
        self.assertTrue(hits_a)
        self.assertEqual(hits_b, [])
