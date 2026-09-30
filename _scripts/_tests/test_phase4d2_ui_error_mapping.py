#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §29/§30：错误映射 —— 统一 ApiError → 用户文案；不显示 traceback；冻结失败即停用。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402
from workspace_ui.server import config as UIC                  # noqa: E402
from workspace_ui.server import viewmodel as VM                # noqa: E402
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key

class ErrorMapping(unittest.TestCase):
    def _env(self, code, message="x", resolution="", detail=None):
        return {"ok": False, "error": {"code": code, "message": message,
                                       "resolution": resolution,
                                       "detail": detail or {}}, "meta": {}}

    def test_00_all_frozen_codes_have_ux(self):
        for code in UIC.ERROR_UX:
            v = VM.error_view(self._env(code))
            self.assertEqual(v["code"], code)
            self.assertTrue(v["title"] and v["body"], code)
            self.assertFalse(v["title"].startswith("{"), code)

    def test_01_provider_unavailable_mapping(self):
        v = VM.error_view(self._env("PROVIDER_UNAVAILABLE"))
        self.assertIn("provider is unavailable", v["title"])
        self.assertFalse(v["research_disabled"], "LLM 不可用不应整体停用研究")

    def test_02_core_frozen_mismatch_disables_research(self):
        v = VM.error_view(self._env("CORE_FROZEN_MISMATCH"))
        self.assertTrue(v["research_disabled"])
        self.assertIn("integrity verification failed", v["title"])
        src = L.js_sources()["render.js"]
        assert_text_wired(self, "render.js", "Research disabled (fail closed)")  # P5D-004: 文案走 i18n key

    def test_03_not_found_mapping(self):
        v = VM.error_view(self._env("NOT_FOUND"))
        self.assertIn("not found", v["title"].lower())

    def test_04_no_traceback_in_any_error_view(self):
        for code in list(UIC.ERROR_UX) + ["SOMETHING_NEW"]:
            v = VM.error_view(self._env(code, detail={"stack": "Traceback (most recent call last)"}))
            blob = json.dumps(v, ensure_ascii=False)
            self.assertNotIn("Traceback", blob)
            self.assertNotIn('File "', blob)

    def test_05_unknown_code_falls_back_gracefully(self):
        v = VM.error_view(self._env("TOTALLY_NEW_CODE"))
        self.assertEqual(v["code"], "TOTALLY_NEW_CODE")
        self.assertEqual(v["title"], UIC.DEFAULT_ERROR_UX["title"])

    def test_06_api_level_invalid_request(self):
        from workspace_ui.server import api as UIA
        out = UIA.research("x", provider="mock", save_history=False)
        self.assertEqual(out["view"]["kind"], "error")
        self.assertEqual(out["view"]["code"], "INVALID_REQUEST")

    def test_07_research_refused_when_mcp_offline(self):
        """fail closed：MCP 不可达时不返回任何"看似学术"的内容。"""
        import workspace_ui.server.api as UIA
        orig = UIA.status
        try:
            UIA.status = lambda: {"mcp_connected": False, "core_freeze_verified": False,
                                  "research_disabled": True}
            out = UIA.research(L.QUESTION_RELATION, provider="mock", save_history=False)
            self.assertEqual(out["view"]["kind"], "error")
            self.assertTrue(out["view"]["research_disabled"])
            self.assertNotIn("claims", out["view"])
        finally:
            UIA.status = orig

if __name__ == "__main__":
    unittest.main()
