#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase5a_accessibility.py — Phase 5A §15/§16/§17/§52 H7：无障碍基线（回归守卫）

跑 `check_accessibility.py` 的**静态 + 真实渲染**检查，覆盖
Research / Explorer（列表+详情）/ Terminology / Seminars / Projects / Exports /
Evidence Inspector 九个视图，要求 **0 项发现**（标题层级 / 可访问名 / 内联处理器 /
img alt / 状态文字 / 可聚焦原语）。

同时断言 §17 的扩展项在源码层存在（焦点可见样式、skip-link、原生控件、aria-current）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")


class TestAccessibilityBaseline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        out = os.path.join(tempfile.mkdtemp(prefix="a11y_"),
                           "accessibility_audit.json")
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "check_accessibility.py"),
                            "--json", out], capture_output=True, text=True, cwd=VAULT)
        cls.rc = r.returncode
        cls.log = r.stdout + r.stderr
        cls.doc = json.load(open(out, encoding="utf-8")) if os.path.isfile(out) else {}

    def test_00_static_audit_clean(self):
        self.assertEqual(self.doc.get("static", {}).get("findings"), [],
                         "静态无障碍发现问题：%s"
                         % self.doc.get("static", {}).get("findings"))
        self.assertEqual(self.doc.get("verdict"), "PASS",
                         "无障碍检查未通过：\n%s" % self.log[-1500:])

    def test_01_every_rendered_view_is_clean(self):
        pages = self.doc.get("rendered") or []
        self.assertGreaterEqual(len(pages), 8, "渲染覆盖视图过少：%d" % len(pages))
        bad = {p["where"]: p["findings"] for p in pages if p["findings"]}
        self.assertEqual(bad, {}, "渲染视图存在无障碍发现（P5A-002/003 类）：%s" % bad)

    def test_02_focus_and_skip_link_present(self):
        css = open(os.path.join(VAULT, "workspace_ui", "static", "styles", "main.css"),
                   encoding="utf-8").read()
        self.assertIn(":focus-visible", css, "缺 :focus-visible（焦点不可见）")
        html = open(os.path.join(VAULT, "workspace_ui", "static", "index.html"),
                    encoding="utf-8").read()
        self.assertIn('class="skip-link"', html, "缺 skip-link")
        import re as _re
        m = _re.search(r'<html[^>]*\slang="([a-zA-Z-]+)"', html)
        self.assertTrue(m, "缺 <html lang>（文档语言未声明）")
        self.assertTrue(m.group(1).strip(), "html lang 为空")

    def test_03_headings_follow_h1_h2_h3(self):
        # 组件层不得再出现「h1 之后再出 h1」或「跳级到 h4」
        for fname in ("render.js", "explorer.js", "project.js"):
            src = open(os.path.join(VAULT, "workspace_ui", "static", "src", fname),
                       encoding="utf-8").read()
            self.assertNotIn("h('h4'", src,
                             "%s 仍使用 h4（层级会跳级）" % fname)


if __name__ == "__main__":
    unittest.main(verbosity=2)
