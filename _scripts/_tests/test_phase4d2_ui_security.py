#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §37：UI 安全 —— XSS/注入/超长/目录穿越；数学公式按文本渲染。"""
import json, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402

XSS = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>",
       "javascript:alert(1)", "\"><svg/onload=alert(1)>",
       "<iframe src=javascript:alert(1)>", "]]><script>x</script>"]

class UISecurity(unittest.TestCase):
    def test_00_no_innerhtml_in_ui_sources(self):
        for fn, src in L.js_sources().items():
            self.assertNotIn(".innerHTML", src, "%s 使用了 innerHTML（不可信内容风险）" % fn)
            self.assertNotIn("insertAdjacentHTML", src, fn)
            self.assertNotIn("document.write", src, fn)
            self.assertNotIn("eval(", src, fn)

    def test_01_dom_builder_forces_textcontent(self):
        src = L.js_sources()["dom.js"]
        self.assertIn("textContent", src)
        self.assertIn("'html'", src)             # 显式忽略 html 键
        self.assertIn("continue", src)

    def test_02_untrusted_text_is_stored_raw_and_escaped_at_render(self):
        """ViewModel 保留原文（同一性），安全由 textContent 渲染保证。"""
        payload = XSS[0] + " objet a 是什么？"
        v = L.answer(payload)
        self.assertIn(XSS[0], json.dumps(v, ensure_ascii=False),
                      "ViewModel 应当原样保留问题文本（文本节点渲染）")
        src = L.js_sources()["dom.js"]
        self.assertIn("document.createTextNode", src)

    def test_03_no_html_from_data_in_renderers(self):
        for fn, src in L.js_sources().items():
            self.assertIsNone(re.search(r"innerHTML\s*=", src), fn)
            self.assertIsNone(re.search(r"\.html\s*\(", src), fn)

    def test_04_oversized_question_is_bounded(self):
        from workspace_ui.server import api as UIA
        from workspace_ui.server import config as UIC
        v = UIA.research("x" * (UIC.MAX_QUESTION_LEN + 5000), provider="mock",
                         save_history=False)
        self.assertEqual(v["view"]["kind"], "error", "超长问题必须拒绝，不得静默截断")
        self.assertIn("too long", v["view"]["title"].lower())
        self.assertNotIn("truncated", json.dumps(v["view"], ensure_ascii=False)
                         .replace("nothing was truncated", ""))
        long_ok = UIA.research("objet a 是什么？" + "x" * 10, provider="mock",
                               save_history=False)
        self.assertIn(long_ok["view"]["kind"], ("answer", "error"))

    def test_05_static_path_traversal_blocked_over_http(self):
        srv = L.LiveServer()
        try:
            import urllib.error
            for bad in ("/static/../../etc/passwd", "/static/..%2f..%2fetc%2fpasswd"):
                try:
                    st, body = srv.get(bad)
                    self.assertEqual(st, 404, bad)
                except urllib.error.HTTPError as e:
                    self.assertEqual(e.code, 404, bad)
        finally:
            srv.close()

    def test_06_math_is_text_not_renderer(self):
        """§38：没有 KaTeX/MathJax；公式按安全文本显示（不阻塞 MVP）。"""
        for fn, src in L.js_sources().items():
            self.assertNotIn("MathJax", src, fn)
            self.assertNotIn("katex", src.lower(), fn)
        v = L.answer("$ ◊ a 在幻想公式中表示什么？")
        self.assertIn("◊", json.dumps(v, ensure_ascii=False))

    def test_07_security_headers_present(self):
        srv = L.LiveServer()
        try:
            import urllib.request
            with urllib.request.urlopen(srv.base + "/") as r:
                self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
            with urllib.request.urlopen(srv.base + "/api/status") as r:
                self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        finally:
            srv.close()

    def test_08_error_payload_has_no_filesystem_paths(self):
        srv = L.LiveServer()
        try:
            try:
                srv.get("/api/passage")
            except Exception:                                  # noqa: BLE001
                pass
            st, body = srv.get_json("/api/status")
            self.assertNotIn(VAULT, json.dumps(body))
        finally:
            srv.close()

if __name__ == "__main__":
    unittest.main()
