#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4d5_ui_browser_smoke.py — 4D.5 §71/§72：真实 Chrome 走完整 Project 动线

流程（§71）：Projects → Create → 加 question → Run research → 保存 run →
从 Explorer 加 passage / concept → 加 Open Question → Obsidian Hub → archive。
"""
import json, os, re, shutil, sys, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _project_testlib as L
import _ui_testlib as U
from workspace_ui.server import httpserver as H
import project_api as PA
from obsidian_adapter import adapter as OA
from obsidian_adapter import vault as OV

# ⚠️ 烟测截图放**独立子目录**：与 build_project_qa.py 的可复核截图同名不同源，
#    实测踩过：两者写同一批文件名，最后交付的截图取决于是谁最后跑的。
QA = os.path.join(VAULT, "_workspace", "project_qa", "browser_qa")
VAULT_ROOT = os.path.join("_workspace", "test_vaults", "project_browser")


@unittest.skipUnless(U.chrome_available(), "Chrome 不可用")
class ProjectBrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = L.isolated_projects("browser")
        cls.ctx.__enter__()
        os.makedirs(QA, exist_ok=True)
        shutil.rmtree(os.path.join(VAULT, VAULT_ROOT), ignore_errors=True)
        os.environ["OBSIDIAN_VAULT_PATH"] = VAULT_ROOT
        cls.srv = H.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.port
        # ⚠️ QA 项目在 setUpClass 建好：单元测试**不得依赖执行顺序**
        #    （实测踩过：单独跑 test_04 时 self.pid 不存在）
        cls.project = L.make_project(
            "拉康欲望理论研究", "长期项目：désir / demande / besoin 与 objet a",
            tags=["désir", "objet-a"],
            questions=["欲望、需求与要求如何关联？",
                       "主人—奴隶辩证法如何进入欲望理论？",
                       "objet a 与欲望是什么关系？"])
        cls.pid = cls.project["project_id"]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        cls.ctx.__exit__(None, None, None)

    def _view(self, qs, name=None, budget=5000):
        shot = os.path.join(QA, "%s.png" % name) if name else None
        dom, ok = U.chrome_render("%s/?%s" % (self.base, qs), shot, budget_ms=budget,
                                  window="1500,1100")
        if name:
            self.assertTrue(ok, "截图失败 %s" % name)
        self.assertNotIn("Project request failed", dom)
        return dom

    def test_00_list_and_empty_filter_state(self):
        dom = self._view("view=projects", "project_list_empty")
        self.assertIn("Research Projects", dom)
        self.assertIn("Create Project", dom)
        # 「空」态用过滤得到（项目本身在 setUpClass 已建，不依赖执行顺序）
        dom0 = self._view("view=projects&query=zzz-no-such-project",
                          "project_list_no_match")
        self.assertIn("No projects yet", dom0)

    def test_01_overview(self):
        p = self.project
        dom = self._view("view=project&id=%s" % p["project_id"], "project_overview")
        self.assertIn("拉康欲望理论研究", dom)
        self.assertIn("Overview", dom)
        self.assertIn("Archive project", dom)
        self.assertIn("workspace counts", dom)

    def test_02_questions_tab(self):
        dom = self._view("view=project&id=%s&tab=questions" % self.pid, "project_questions")
        self.assertIn("Research Questions", dom)
        self.assertIn("欲望、需求与要求如何关联？", dom)
        self.assertIn("project-management states", dom)

    def test_03_add_run_and_research_tab(self):
        view = L.answer(L.Q_GAZE)
        p = PA.get_project(self.pid)
        PA.add_research_run(self.pid, p["revision"], view,
                            project_question_id=p["research_questions"][0]["question_id"])
        dom = self._view("view=project&id=%s&tab=research" % self.pid, "project_runs")
        self.assertIn("Research runs", dom)
        self.assertIn("immutable snapshot", dom)
        self.assertIn("Qualified answer", dom)
        self.assertIn("Snapshot verification: VERIFIED", dom)

    def test_04_abstention_run_visual(self):
        view = L.abstention_answer()
        p = PA.get_project(self.pid)
        PA.add_research_run(self.pid, p["revision"], view)
        dom = self._view("view=project&id=%s&tab=research" % self.pid, "project_abstained_run")
        self.assertIn("ABSTAINED", dom)
        self.assertIn("This run abstained", dom)
        self.assertIn("never as", dom)
        self.assertIn("ABSTAINED", dom)

    def test_05_explorer_adds_passage_and_concept(self):
        p = PA.get_project(self.pid)
        r = p["revision"]
        PA.add_reference(self.pid, r, "passage", L.P_L1, note="gaze 段落")
        p = PA.get_project(self.pid)
        PA.add_reference(self.pid, p["revision"], "concept", L.C_OBJET)
        p = PA.get_project(self.pid)
        PA.add_reference(self.pid, p["revision"], "seminar", "seminar.S11")
        p = PA.get_project(self.pid)
        PA.add_reference(self.pid, p["revision"], "term", "jouissance")
        dom = self._view("view=project&id=%s&tab=evidence" % self.pid, "project_evidence")
        self.assertIn("Evidence references", dom)
        self.assertIn("passage.S11.unknown.P2253", dom)
        self.assertIn("concept.objet-petit-a", dom)
        self.assertIn("seminar.S11", dom)
        self.assertIn("never keeps its own copy", dom)

    def test_06_open_question_from_abstention(self):
        p = PA.get_project(self.pid)
        runs = PA.list_runs(self.pid)
        abst = [r for r in runs if r["is_abstention"]][0]
        PA.open_questions_from_run(self.pid, p["revision"], abst["run_id"])
        dom = self._view("view=project&id=%s&tab=questions_open" % self.pid,
                         "project_open_questions")
        self.assertIn("Open Questions", dom)
        self.assertIn("created_from_run", dom)
        self.assertIn("asserts no", dom)

    def test_07_hypotheses_tab_marks_user_object(self):
        p = PA.get_project(self.pid)
        PA.add_hypothesis(self.pid, p["revision"],
                          "jouissance 在 S20 的重构与 sexual non-relation 密切相关。")
        dom = self._view("view=project&id=%s&tab=hypotheses" % self.pid,
                         "project_hypotheses")
        self.assertIn("not validated by the Scholarly Core", dom)
        self.assertIn("Test with corpus", dom)

    def test_08_notes_and_bibliography(self):
        p = PA.get_project(self.pid)
        PA.add_note(self.pid, p["revision"], "先记：désir 与 demande 的差在大他者。",
                    title="初步想法")
        p = PA.get_project(self.pid)
        PA.add_bibliography_ref(self.pid, p["revision"], "Écrits", author="Lacan",
                                year=1966, source_type="book")
        dom = self._view("view=project&id=%s&tab=notes" % self.pid, "project_notes")
        self.assertIn("Notes", dom)
        self.assertIn("never enter the scholarly evidence pipeline", dom)
        dom2 = self._view("view=project&id=%s&tab=bibliography" % self.pid,
                          "project_bibliography")
        self.assertIn("Écrits", dom2)
        self.assertIn("NOT a CorpusSource", dom2)
        # Phase 5D §20/§21：项目书目必须是**三组**，并提供显式 Link（不自动 link）
        for group in ("pbg-reviewed", "pbg-user-supplied", "pbg-legacy"):
            self.assertIn('id="%s"' % group, dom2)
        self.assertIn("Reviewed references", dom2)
        self.assertIn("User-supplied references", dom2)
        self.assertIn("Unlinked legacy references", dom2)
        self.assertIn("Link to Bibliographic Item", dom2)

    def test_09_obsidian_project_hub_roundtrip(self):
        p = PA.get_project(self.pid)
        out = OA.save_project_note(p)
        self.assertTrue(out["ok"], out)
        v = OV.Vault(VAULT_ROOT)
        self.assertTrue(v.exists(out["note"]))
        txt = v.read(out["note"])
        self.assertIn("lacan-research-project", txt)
        self.assertIn("## My Notes", txt)
        # 用户区保护 + 二次同步幂等
        marker = "\n\n## 我的批注\n\n- 用户自己写的内容。\n"
        v.write(out["note"], txt.rstrip("\n") + marker)
        before = v.read(out["note"]).split("## My Notes")[1]
        OA.save_project_note(PA.get_project(self.pid))
        after = v.read(out["note"]).split("## My Notes")[1]
        self.assertEqual(before, after)
        mapping = OA.project_note_map(vault=v)
        self.assertEqual(mapping[self.pid], out["note"])

    def test_10_revision_conflict_visible(self):
        p = PA.get_project(self.pid)
        PA.update_project(self.pid, p["revision"], title=p["title"])   # 使 revision 前移
        p = PA.get_project(self.pid)
        stale = p["revision"] - 1
        from workspace_ui.server import project_view as PV
        out = PV.project_archive(self.pid, stale)
        self.assertEqual(out["code"], "WORKSPACE_CONFLICT")
        self.assertEqual(out["actual_revision"], p["revision"])

    def test_11_archive_state_rendered(self):
        p = PA.get_project(self.pid)
        PA.archive_project(self.pid, p["revision"])
        dom = self._view("view=project&id=%s" % self.pid, "project_archived")
        self.assertIn("ARCHIVED", dom)
        self.assertIn("Restore to ACTIVE", dom)
        dom2 = self._view("view=projects&status=ARCHIVED", "project_list_archived")
        self.assertIn("拉康欲望理论研究", dom2)

    def test_12_screenshots_recorded(self):
        for n in ("project_list_empty", "project_overview", "project_questions",
                  "project_runs", "project_abstained_run", "project_evidence",
                  "project_open_questions", "project_hypotheses", "project_notes",
                  "project_bibliography", "project_archived", "project_list_archived"):
            self.assertTrue(os.path.isfile(os.path.join(QA, n + ".png")), n)
