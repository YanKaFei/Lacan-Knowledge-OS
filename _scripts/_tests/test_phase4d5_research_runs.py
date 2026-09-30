#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §12–§14/§48/§49/§75/§76：Run 快照（含弃权与 qualified）"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
from workspace_ui.server import project_view as PV
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key


class ResearchRuns(unittest.TestCase):
    def test_00_snapshot_equals_core_answer_verbatim(self):
        """§75：存储快照 == MCP 返回的 FinalScholarlyAnswer（Project 层不摘要）。"""
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("runs"):
            p = L.make_project("R")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view,
                                         request_meta={"mode": "scholarly",
                                                       "provider": "mock"})
            self.assertEqual(rec["snapshot"], view, "快照必须逐字段等于核心答案")
            self.assertEqual(rec["source_answer_hash"], PA.answer_hash(view))
            self.assertEqual(rec["citation_ids"],
                             [c["passage_id"] for c in view["citations"]])
            self.assertEqual(rec["claim_count"], len(view["claims"]))
            self.assertEqual(rec["limitations"], list(view["limitations"]))
            self.assertEqual(rec["answer_state"], view["state"])

    def test_01_qualified_state_preserved(self):
        """§49：VALIDATED_WITH_QUALIFICATIONS 必须原样保留。"""
        view = L.answer(L.Q_GAZE)
        self.assertEqual(view["state"], "VALIDATED_WITH_QUALIFICATIONS")
        with L.isolated_projects("runs_q"):
            p = L.make_project("Q")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            self.assertTrue(rec["is_qualified"])
            self.assertFalse(rec["is_abstention"])
            self.assertEqual(rec["answer_state"], "VALIDATED_WITH_QUALIFICATIONS")
            ui = PV.project_detail(p["project_id"], tab="research")
            self.assertTrue(ui["runs"][0]["is_qualified"])
            # UI 文案必须说 Qualified answer 而不是笼统的 Answered（§49）
            js = open(os.path.join(VAULT, "workspace_ui", "static", "src", "project.js"),
                      encoding="utf-8").read()
            assert_text_wired(self, "project.js", "Qualified answer")
            self.assertNotIn("Answered", js)

    def test_02_abstention_preserved_not_marked_answered(self):
        """§76：Core ABSTAIN → Project snapshot ABSTAIN。"""
        view = L.abstention_answer()
        self.assertTrue(view.get("is_abstention"))
        with L.isolated_projects("runs_a"):
            p = L.make_project("A")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            self.assertEqual(rec["answer_state"], "ABSTAINED")
            self.assertTrue(rec["is_abstention"])
            self.assertNotIn(rec["answer_state"], ("VALIDATED", "ANSWERED"))
            self.assertTrue(rec["snapshot"]["abstention"])

    def test_03_run_metadata_recorded(self):
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("runs_meta"):
            p = L.make_project("M")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view,
                                         request_meta={"mode": "concept_definition",
                                                       "provider": "mock"})
            for k in ("run_id", "question", "created_at", "mode", "provider",
                      "answer_state", "task_type", "source_answer_hash",
                      "citation_ids", "limitations", "snapshot"):
                self.assertIn(k, rec, k)
            self.assertEqual(rec["mode"], "concept_definition")
            self.assertEqual(rec["provider"], "mock")
            self.assertEqual(rec["core_freeze_version"], "scholarly_core_freeze_v1")

    def test_04_listing_and_detail(self):
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("runs_list"):
            p = L.make_project("L", questions=["gaze 与 objet a 的关系？"])
            qid = p["research_questions"][0]["question_id"]
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view,
                                         project_question_id=qid)
            runs = PA.list_runs(p["project_id"])
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["run_id"], rec["run_id"])
            # 研究过的 question 状态自动变为 RESEARCHED（项目管理状态）
            got = PA.get_project(p["project_id"])
            self.assertEqual(got["research_questions"][0]["status"], "RESEARCHED")
            self.assertEqual(got["research_questions"][0]["last_run_id"], rec["run_id"])

    def test_05_run_rejects_non_answer(self):
        with L.isolated_projects("runs_bad"):
            p = L.make_project("B")
            with self.assertRaises(PA.Invalid):
                PA.add_research_run(p["project_id"], p["revision"],
                                    {"kind": "note", "text": "hi"})

    def test_06_compare_runs_is_structural_only(self):
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("runs_cmp"):
            p = L.make_project("C")
            p, r1 = PA.add_research_run(p["project_id"], p["revision"], view)
            p, r2 = PA.add_research_run(p["project_id"], p["revision"], view)
            cmp = PA.compare_runs(p["project_id"], r1["run_id"], r2["run_id"])
            for k in ("answer_state", "citation_set", "claim_count", "limitations"):
                self.assertIn(k, cmp)
            self.assertFalse(cmp["answer_state"]["changed"])
            self.assertEqual(cmp["citation_set"]["only_a"], [])
            blob = str(cmp).lower()
            for bad in ("improved", "better", "重大", "理论发生"):
                self.assertNotIn(bad, blob)
            self.assertIn("structural diff only", cmp["note"].lower())
