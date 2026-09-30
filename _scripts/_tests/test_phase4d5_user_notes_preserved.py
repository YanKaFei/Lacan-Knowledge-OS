#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §26/§61/§63：Notes 与用户内容保护"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA


class UserNotesPreserved(unittest.TestCase):
    def test_00_note_written_as_markdown_not_evidence(self):
        with L.isolated_projects("notes") as root:
            p = L.make_project("N")
            p = PA.add_note(p["project_id"], p["revision"], "内容 A", title="标题 A")
            note = p["notes"][0]
            self.assertFalse(note["is_evidence"])
            path = os.path.join(root, p["project_id"], "notes", "%s.md" % note["note_id"])
            self.assertTrue(os.path.isfile(path))
            txt = open(path, encoding="utf-8").read()
            self.assertIn("is_evidence: false", txt)
            self.assertIn("内容 A", txt)

    def test_01_update_and_remove_note(self):
        with L.isolated_projects("notes2") as root:
            p = L.make_project("N")
            p = PA.add_note(p["project_id"], p["revision"], "v1")
            nid = p["notes"][0]["note_id"]
            p = PA.update_note(p["project_id"], p["revision"], nid, text="v2")
            self.assertEqual(p["notes"][0]["text"], "v2")
            self.assertIn("updated_at", p["notes"][0])
            p = PA.remove_note(p["project_id"], p["revision"], nid)
            self.assertEqual(p["notes"], [])
            self.assertFalse(os.path.isfile(
                os.path.join(root, p["project_id"], "notes", "%s.md" % nid)))

    def test_02_notes_never_enter_research_request(self):
        """§26：笔记不进 scholarly evidence pipeline；也不自动成为研究问题。"""
        with L.isolated_projects("notes3"):
            p = L.make_project("N")
            p = PA.add_note(p["project_id"], p["revision"], "这是一段绝对不该出现在研究请求里的文本 ZZZ")
            from workspace_ui.server import project_view as PV
            out = PV.project_research(p["project_id"], p["revision"], L.Q_GAZE,
                                      provider="mock", store_run=False)
            blob = str(out.get("request"))
            self.assertNotIn("ZZZ", blob)
            self.assertNotIn("ZZZ", str(out["view"].get("question")))

    def test_03_oversized_note_rejected(self):
        with L.isolated_projects("notes4"):
            p = L.make_project("N")
            with self.assertRaises(PA.Invalid):
                PA.add_note(p["project_id"], p["revision"], "x" * 200_001)

    def test_04_note_text_is_untrusted_in_ui(self):
        js = open(os.path.join(VAULT, "workspace_ui", "static", "src", "project.js"),
                  encoding="utf-8").read()
        for bad in (".innerHTML", "insertAdjacentHTML", "document.write", "eval(",
                    "javascript:"):
            self.assertNotIn(bad, js)
        self.assertIn("textContent", open(
            os.path.join(VAULT, "workspace_ui", "static", "src", "dom.js"),
            encoding="utf-8").read())

    def test_05_markdown_note_renders_as_text_not_html(self):
        """含 HTML 的笔记在浏览器里必须是文本（真实 Chrome 验证）。"""
        import threading
        import _ui_testlib as U
        if not U.chrome_available():
            self.skipTest("Chrome 不可用")
        from workspace_ui.server import httpserver as H
        with L.isolated_projects("notes5"):
            p = L.make_project("XSS", "<b>bold</b>")
            payload = "<script>alert(1)</script> **not html**"
            p = PA.add_note(p["project_id"], p["revision"], payload, title="<img src=x>")
            srv = H.make_server("127.0.0.1", 0)
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                dom, _ = U.chrome_render(
                    "http://127.0.0.1:%d/?view=project&id=%s&tab=notes"
                    % (port, p["project_id"]), None, budget_ms=4500)
            finally:
                srv.shutdown()
        self.assertNotIn("<script>alert(1)</script>", dom)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", dom)
        self.assertIn("**not html**", dom)
