#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §24/§25：User Hypotheses（USER_HYPOTHESIS，绝不混入 validated claims）"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key


class Hypotheses(unittest.TestCase):
    def test_00_marked_user_object_and_not_validated(self):
        with L.isolated_projects("hyp"):
            p = L.make_project("H")
            p = PA.add_hypothesis(p["project_id"], p["revision"],
                                  "jouissance 在 S20 的重构与 sexual non-relation 相关。")
            h = p["hypotheses"][0]
            self.assertEqual(h["object_class"], "USER_HYPOTHESIS")
            self.assertTrue(h["not_validated"])
            self.assertIn("not validated", h["label"])
            self.assertEqual(h["test_runs"], [])

    def test_01_hypothesis_never_becomes_a_claim(self):
        """§24：项目里永远没有 validated claim 列表；假设不进核心 claim 模型。"""
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("hyp2"):
            p = L.make_project("H")
            p = PA.add_hypothesis(p["project_id"], p["revision"], "假设 A")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            blob = str(PA.get_project(p["project_id"]))
            self.assertIn("USER_HYPOTHESIS", blob)
            self.assertNotIn("validated_claim", blob)
            self.assertNotIn("is_validated\": true", blob)
            # 核心答案里的 claims 只存在于 run 快照中（不在项目假设里）
            self.assertEqual(len(rec["snapshot"]["claims"]),
                             rec["claim_count"])
            self.assertEqual(len(p["hypotheses"]), 1)

    def test_02_test_with_corpus_generates_request_only(self):
        with L.isolated_projects("hyp3"):
            p = L.make_project("H")
            req = PA.hypothesis_research_request("假设 B")
            self.assertEqual(req["tool"], "lacan.research")
            self.assertIn("假设 B", req["request"]["question"])
            self.assertNotIn("verdict", req["request"])
            self.assertIn("never labels a hypothesis as validated", req["note"])

    def test_03_record_core_verdict_keeps_hypothesis_user_object(self):
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("hyp4"):
            p = L.make_project("H")
            p = PA.add_hypothesis(p["project_id"], p["revision"], "假设 C")
            hid = p["hypotheses"][0]["hypothesis_id"]
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            p = PA.record_hypothesis_test(p["project_id"], p["revision"], hid,
                                          rec["run_id"], view["state"])
            h = p["hypotheses"][0]
            self.assertEqual(h["test_runs"][0]["answer_state"],
                             "VALIDATED_WITH_QUALIFICATIONS")
            self.assertTrue(h["not_validated"], "测验记录不改变它是用户对象")

    def test_04_ui_shows_explicit_warning(self):
        js = open(os.path.join(VAULT, "workspace_ui", "static", "src", "project.js"),
                  encoding="utf-8").read()
        assert_text_wired(self, "project.js", "User hypothesis — not validated by the Scholarly Core")
        assert_text_wired(self, "project.js", "Test with corpus")

    def test_05_obsidian_marks_hypotheses_as_user_objects(self):
        """⚠️ 必须指到临时 vault：否则测试会往**真实**工作区 vault 里写 note。"""
        import shutil
        import obsidian_adapter as OA
        root = os.path.join("_workspace", "test_vaults", "hyp_hub")
        shutil.rmtree(os.path.join(VAULT, root), ignore_errors=True)
        old = os.environ.get("OBSIDIAN_VAULT_PATH")
        os.environ["OBSIDIAN_VAULT_PATH"] = root
        try:
            with L.isolated_projects("hyp5"):
                p = L.make_project("H")
                p = PA.add_hypothesis(p["project_id"], p["revision"], "假设 D")
                out = OA.save_project_note(PA.get_project(p["project_id"]))
                self.assertTrue(out["ok"])
                txt = open(os.path.join(VAULT, root, out["note"]),
                           encoding="utf-8").read()
                self.assertIn("not validated by the Scholarly Core", txt)
        finally:
            if old is None:
                os.environ.pop("OBSIDIAN_VAULT_PATH", None)
            else:
                os.environ["OBSIDIAN_VAULT_PATH"] = old
