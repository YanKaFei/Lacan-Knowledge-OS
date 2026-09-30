#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4d2_ui_browser_smoke.py — 4D.2 §45/§46：**真实浏览器**烟测（Chrome headless）

不是 DOM 模拟：真的起 HTTP 服务、真的用 Chrome 执行 JS 并 dump 渲染后的 DOM，
同时把 4 个产品态的截图落到 `_workspace/ui_qa/`（视觉 QA 证据，产品工作区，可保留）。

Test A 正常答案 + citation 可点；Test B 弃权；Test C L2 溯源不完整；Test D MCP offline；
另加 XSS 注入在真实 DOM 中不得成为元素。
"""
import json
import os
import sys
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)
sys.path.insert(0, HERE)

import _ui_testlib as L                                        # noqa: E402

QA_DIR = os.path.join(VAULT, "_workspace", "ui_qa")


def url_for(base, **params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return "%s/?%s" % (base, q)


@unittest.skipUnless(L.chrome_available(), "Chrome 不可用，跳过真实浏览器烟测")
class BrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(QA_DIR, exist_ok=True)
        # 预热（服务端进程内缓存）→ 页面渲染在 <1s 内完成
        L.answer(L.QUESTION_RELATION, mode="seminar_specific", language="fr")
        L.answer(L.QUESTION_ABSTAIN)
        L.panel(L.PASSAGE_L2)
        cls.srv = L.LiveServer()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def _render(self, name, url, budget=4000):
        """一次 Chrome 调用同时产出 DOM 与截图（实测每张约 3s）。"""
        shot = os.path.join(QA_DIR, "%s.png" % name)
        dom, shot_ok = L.chrome_render(url, shot, budget_ms=budget, window="1600,1200")
        self.assertTrue(shot_ok, "截图未生成：%s" % shot)
        return dom

    def test_00_js_booted(self):
        dom, _ = L.chrome_render(self.srv.base + "/", budget_ms=3000)
        self.assertIn('data-ready="1"', dom, "前端 JS 未完成装配")

    def test_01_A_normal_answer_with_citation(self):
        dom = self._render("A_answer", url_for(
            self.srv.base, q=L.QUESTION_RELATION, mode="seminar_specific",
            language="fr", provider="mock", autorun="1"))
        self.assertIn("Validated with qualifications", dom)
        self.assertIn("data-passage=", dom, "citation chip 未渲染")
        self.assertIn("Evidence Inspector", dom)
        self.assertIn("Advanced / Audit", dom)
        # citation chip 必须带真实 passage id
        self.assertRegex(dom, r'data-passage="passage\.[^"]+"')

    def test_02_B_abstention_view(self):
        dom = self._render("B_abstain", url_for(
            self.srv.base, q=L.QUESTION_ABSTAIN, provider="mock", autorun="1"))
        self.assertIn("Abstained", dom)
        self.assertIn("Current corpus cannot support a reliable answer", dom)
        self.assertIn("Missing information", dom)
        self.assertIn("Sources needed", dom)
        self.assertNotIn("However", dom)

    def test_03_C_l2_source_trace_incomplete(self):
        dom = self._render("C_l2evidence", url_for(
            self.srv.base, inspect=L.PASSAGE_L2))
        self.assertIn("Source trace incomplete", dom)
        self.assertIn("Recovered / translated material", dom)
        self.assertIn("No aligned translation available", dom)
        # L2 标签与 passage id 必须在 DOM 里
        self.assertIn("passage.S05.unknown.L05.P0056", dom)

    def test_04_D_mcp_offline_fail_closed(self):
        import workspace_ui.server.api as UIA
        from workspace_ui.server.mcp_client import McpUnavailable
        orig = UIA.shared_client

        def boom():
            raise McpUnavailable({"reason": "TEST_FORCED_OFFLINE"})

        try:
            UIA.shared_client = boom
            dom = self._render("D_offline", self.srv.base + "/", budget=3000)
        finally:
            UIA.shared_client = orig
        self.assertIn("MCP Offline", dom)
        self.assertIn("Core freeze: NOT verified", dom)
        # P5D-004：属性顺序无意义（新增 data-i18n 会改变序列化顺序）→ 用结构断言
        import re as _re
        self.assertRegex(dom, r'<button[^>]*id="ask-btn"[^>]*\bdisabled\b',
                         "离线时 ask 按钮必须 disabled")

    def test_05_injected_script_never_becomes_an_element(self):
        payload = "<script>alert(1)</script> objet a 是什么？"
        # autorun=1：让注入文本真的被渲染进答案卡（而不是只填进 textarea）
        dom, _ = L.chrome_render(url_for(self.srv.base, q=payload, provider="mock",
                                         autorun="1"), budget_ms=4000)
        self.assertNotIn("<script>alert(1)</script>", dom,
                         "注入的 script 变成了真实元素（XSS）")
        self.assertIn("&lt;script&gt;", dom, "注入文本应作为转义文本节点出现")
        self.assertNotIn("onerror=", dom.replace("onerror=\"", ""))
        self.assertIn('data-ready="1"', dom)

    def test_06_screenshots_recorded_for_visual_qa(self):
        files = sorted(os.listdir(QA_DIR))
        for name in ("A_answer.png", "B_abstain.png", "C_l2evidence.png",
                     "D_offline.png"):
            self.assertIn(name, files, "视觉 QA 截图缺失：%s" % name)


if __name__ == "__main__":
    unittest.main()
