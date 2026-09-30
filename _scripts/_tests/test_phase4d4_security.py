#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §62/§63：Search safety（注入 / DoS / 越界 / 不可信内容渲染）"""
import json, os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L


class Security(unittest.TestCase):
    def test_00_injection_values_rejected(self):
        for bad in ("seminar=S11' OR 1=1 --", "seminar=S11;DROP TABLE passage_meta",
                    "language=zz", "source_layer=<script>", "provenance=x",
                    "concept=../../etc/passwd", "session=session.S11;--"):
            payload = dict(p.split("=", 1) for p in bad.split("&"))
            with self.assertRaises(ValueError, msg=bad):
                L.B.browse_passages(payload)

    def test_01_limit_is_hard_capped(self):
        out = L.B.browse_passages({"limit": 10 ** 9})
        self.assertEqual(out["page"]["limit"], L.B.passages.MAX_LIMIT)
        out2 = L.B.browse_passages({"limit": -5})
        self.assertGreaterEqual(out2["page"]["limit"], 1)

    def test_02_no_sql_string_interpolation_of_user_values(self):
        """用户值必须走参数绑定。

        允许**唯一**一种拼接：把 `?` 占位符按数量拼进去（`",".join("?" * n)`），
        它不含任何用户数据；一旦发现拼接的是别的表达式就算是注入风险。
        """
        import re as _re
        for rel in ("passages.py", "concepts.py", "seminars.py", "terminology.py",
                    "store.py"):
            src = open(os.path.join(VAULT, "browse_api", rel), encoding="utf-8").read()
            for m in _re.finditer(r'"[^"]*(?:select|where|order by|in \()\s*[^"]*"\s*%\s*([^\n]+)',
                                  src, _re.I):
                expr = m.group(1)
                self.assertIn('"?"', expr,
                              "%s 里 SQL 拼接了非占位符表达式：%s" % (rel, expr[:60]))
            self.assertNotIn("f\"select", src.lower())
        self.assertIn("= ?", open(os.path.join(VAULT, "browse_api", "passages.py"),
                                  encoding="utf-8").read())

    def test_03_regex_dos_is_bounded(self):
        """§62：正则来自白名单，不接受用户自定义 pattern。"""
        with self.assertRaises(ValueError):
            L.B.browse_passages({"formalism": "(a+)+$"})
        names = [p[0] for p in L.B.store.FORMALISM_PATTERNS]
        self.assertIn("S ◊ a", names)
        src = open(os.path.join(VAULT, "browse_api", "passages.py"), encoding="utf-8").read()
        self.assertIn("dict(S.FORMALISM_PATTERNS)[formalism]", src)

    def test_04_untrusted_corpus_text_is_never_html(self):
        """§63：corpus 文本按 untrusted 渲染（只用 textContent）。"""
        src = open(os.path.join(VAULT, "workspace_ui", "static", "src", "explorer.js"),
                   encoding="utf-8").read()
        for bad in (".innerHTML", "insertAdjacentHTML", "document.write", "eval(",
                    "outerHTML"):
            self.assertNotIn(bad, src)
        dom = open(os.path.join(VAULT, "workspace_ui", "static", "src", "dom.js"),
                   encoding="utf-8").read()
        self.assertIn("textContent", dom)
        self.assertIn("else if (k === 'html') continue;", dom)

    def test_05_corpus_text_with_markup_is_escaped_in_dom(self):
        """真实语料里若含 <script>，渲染后必须是文本而不是元素。"""
        import threading
        from workspace_ui.server import httpserver as H
        sys.path.insert(0, HERE)
        import _ui_testlib as U
        if not U.chrome_available():
            self.skipTest("Chrome 不可用")
        srv = H.make_server("127.0.0.1", 0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            dom, _ = U.chrome_render("http://127.0.0.1:%d/?view=passage&id=%s"
                                     % (port, L.P_L1), None, budget_ms=4000)
        finally:
            srv.shutdown()
        self.assertIn("L’ objet(a) dans le champ du visible", dom)
        self.assertNotIn("<script>alert", dom)

    def test_06_unknown_entity_type_refused(self):
        out = L.X.obsidian_create("../../etc", "x")
        self.assertFalse(out["ok"])

    def test_07_no_arbitrary_fields_accepted(self):
        """§62：只接受白名单字段，未知字段被忽略而不是变成 SQL。"""
        out = L.B.browse_passages({"seminar": "S11", "order_by": "id; drop",
                                   "limit": 3})
        self.assertEqual(out["page"]["total"], len(L.raw_ids(
            "where seminar_id=?", ("seminar.S11",))))
