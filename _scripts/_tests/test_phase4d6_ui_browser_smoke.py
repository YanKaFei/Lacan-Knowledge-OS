#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4d6_ui_browser_smoke.py — 4D.6 §79/§80：真实 Chrome 的导出动线

流程：Research answer → Export Markdown/JSON/HTML → Bundle →
Copy citation（capability 门禁）→ Abstention display 保持 → Project export。
"""
import json, os, re, shutil, sys, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _export_testlib as L
import _project_testlib as PL
import _ui_testlib as U
import export_system as EX
import project_api as PA
from workspace_ui.server import httpserver as H

QA = os.path.join(VAULT, "_workspace", "export_qa")


@unittest.skipUnless(U.chrome_available(), "Chrome 不可用")
class ExportBrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = L.export_root("browser")
        cls.ctx.__enter__()
        cls.pctx = PL.isolated_projects("export_browser")
        cls.pctx.__enter__()
        os.makedirs(QA, exist_ok=True)
        p = PL.make_project("导出 QA 项目", "browser smoke",
                            questions=["gaze 与 objet a 的关系？"])
        cls.pid = p["project_id"]
        cls.srv = H.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.port
        # 研究视图走 UI 的自动深链（?autorun=1），导出按钮在同一页面上
        import urllib.parse
        cls.q = L.Q_GAZE
        cls.answer_url = "%s/?q=%s&mode=scholarly&provider=mock&autorun=1" % (
            cls.base, urllib.parse.quote(cls.q))
        cls.answer_dom, _ = U.chrome_render(cls.answer_url,
                                            os.path.join(QA, "export_menu.png"),
                                            budget_ms=6000, window="1500,1100")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.pctx.__exit__(None, None, None)
        cls.ctx.__exit__(None, None, None)

    def _view(self, qs, name=None, budget=5000, window="1500,1100"):
        """窗口高度可调：段落/项目页面很长，1100px 只能拍到页首，
        视觉 QA 要能真的看到 citation 菜单与导出菜单（否则截图名不副实）。"""
        shot = os.path.join(QA, "%s.png" % name) if name else None
        dom, ok = U.chrome_render("%s/?%s" % (self.base, qs), shot, budget_ms=budget,
                                  window=window)
        if name:
            self.assertTrue(ok, name)
        return dom

    def test_00_export_menu_on_answer(self):
        dom = self.answer_dom
        self.assertIn("export-actions", dom)
        for fmt in ("markdown", "json", "html", "bundle"):
            self.assertIn('id="export-%s"' % fmt, dom, fmt)
        self.assertIn("export-preview-btn", dom)

    def test_01_export_markdown_json_html_via_api_then_render(self):
        """UI 调用的就是这三个端点；导出的文件必须存在且内容一致。"""
        import urllib.request
        view = L.view()
        for fmt in ("markdown", "json", "html"):
            body = json.dumps({"source_type": "research_run", "view": view,
                               "format": fmt}).encode()
            req = urllib.request.Request(self.base + "/api/export/run", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read().decode())
            self.assertTrue(out["ok"], fmt)
            path = os.path.join(EX.policy.VAULT, out["file"])
            self.assertTrue(os.path.isfile(path), fmt)
            text = open(path, encoding="utf-8").read()
            self.assertIn(view["citations"][0]["passage_id"], text, fmt)

    def test_02_bundle_via_api_and_open(self):
        import urllib.request
        view = L.view()
        body = json.dumps({"source_type": "research_run", "view": view,
                           "format": "bundle", "include_context": 2}).encode()
        req = urllib.request.Request(self.base + "/api/export/run", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
        self.assertEqual(out["verify"]["status"], "VERIFIED")
        self.assertTrue(os.path.isfile(os.path.join(EX.policy.VAULT,
                                                    "manifest.json" if False else
                                                    out["rel_dir"], "manifest.json")))
        # 校验页（Bundle verification status）
        dom = self._view("view=exports", "bundle_verify", budget=6000)
        self.assertIn("Exports", dom)

    def test_03_citation_menu_capability_gating(self):
        dom = self._view("view=passage&id=passage.S11.unknown.P2253", "citation_menu",
                         budget=6000, window="1500,2600")
        self.assertIn("citation-menu", dom)
        self.assertIn("internal-short", dom)
        self.assertIn("internal-full", dom)
        self.assertIn("provenance", dom)
        self.assertIn("BIBLIOGRAPHIC_METADATA_INCOMPLETE", dom)
        # 不可用样式不得有 Copy 按钮
        block = dom.split("chicago")[-1][:400] if "chicago" in dom else ""
        self.assertNotIn(">Copy<", block)

    def test_04_copy_citation_text_comes_from_formatter(self):
        dom = self._view("view=passage&id=passage.S11.unknown.P2253")
        self.assertIn("S11 · P2253", dom)
        self.assertIn("Seminar XI", dom)

    def test_05_l2_export_keeps_trace_incomplete(self):
        dom = self._view("view=passage&id=passage.S05.unknown.L05.P0056",
                         "l2_export", budget=6000, window="1500,2600")
        self.assertIn("SOURCE_TRACE_INCOMPLETE", dom)
        self.assertIn("export-actions", dom)

    def test_06_abstention_export_keeps_state(self):
        import urllib.parse, urllib.request
        url = "%s/?q=%s&provider=mock&autorun=1" % (
            self.base, urllib.parse.quote(L.Q_FMRI))
        dom, _ = U.chrome_render(url, os.path.join(QA, "abstention_export.png"),
                                 budget_ms=6000, window="1500,1100")
        self.assertIn("ABSTAINED", dom)
        self.assertIn("Current corpus cannot support a reliable answer", dom)
        self.assertIn("export-actions", dom)

    def test_07_project_export_menu(self):
        dom = self._view("view=project&id=%s" % self.pid, "project_export", budget=6000,
                         window="1500,2000")
        self.assertIn("project-export-host", dom)
        self.assertIn("export-actions", dom)

    def test_08_export_failure_is_visible(self):
        """§80：导出失败必须显式可见（用不存在的 source 触发）。"""
        import urllib.request, urllib.error
        body = json.dumps({"source_type": "research_run", "view": None,
                           "format": "markdown"}).encode()
        req = urllib.request.Request(self.base + "/api/export/run", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.loads(r.read().decode())
            code = out.get("code")
        except urllib.error.HTTPError as e:
            code = json.loads(e.read().decode()).get("code")
        self.assertEqual(code, "EXPORT_SOURCE_NOT_FOUND")

    def test_09_screenshots_recorded(self):
        for n in ("export_menu", "citation_menu", "l2_export", "abstention_export",
                  "project_export", "bundle_verify"):
            self.assertTrue(os.path.isfile(os.path.join(QA, n + ".png")), n)
