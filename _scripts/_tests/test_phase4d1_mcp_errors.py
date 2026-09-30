#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-7/§17：错误契约 —— 统一 ApiError 形状，绝不外泄 traceback。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _mcp_testlib as L                                        # noqa: E402
from mcp_server import errors as E                              # noqa: E402

class McpErrorContract(unittest.TestCase):
    def _assert_error_shape(self, env, code):
        self.assertFalse(env["ok"])
        err = env["error"]
        self.assertEqual(err["code"], code)
        for k in ("message", "detail", "resolution"):
            self.assertIn(k, err)
        blob = json.dumps(env, ensure_ascii=False)
        for bad in ("Traceback", "File \"", "  at ", "0x"):
            self.assertNotIn(bad, blob, "错误响应泄露了内部细节：%s" % bad)

    def test_00_not_found_passage(self):
        env = L.call("lacan.get_passage", {"passage_id": "passage.S99.unknown.P999999"})
        self._assert_error_shape(env, "NOT_FOUND")

    def test_01_not_found_seminar(self):
        env = L.call("lacan.get_seminar", {"seminar_id": "seminar.S99"})
        self._assert_error_shape(env, "NOT_FOUND")

    def test_02_invalid_request_empty_question(self):
        env = L.call("lacan.research", {"question": "   "})
        self._assert_error_shape(env, "SCHEMA_VALIDATION_FAILED")

    def test_03_invalid_provider(self):
        env = L.call("lacan.research", {"question": "objet a 是什么？", "provider": "bogus"})
        self._assert_error_shape(env, "SCHEMA_VALIDATION_FAILED")

    def test_04_provider_unavailable_no_fallback(self):
        home, key = os.environ.get("HOME"), os.environ.get("DSH_SYNTHESIS_API_KEY")
        tmp = os.path.join(VAULT, "_index", "_tmp_home_mcp_test")
        try:
            os.makedirs(tmp, exist_ok=True)
            os.environ["HOME"] = tmp
            os.environ.pop("DSH_SYNTHESIS_API_KEY", None)
            env = L.call("lacan.research", {"question": "objet a 是什么？",
                                           "provider": "llm"})
            self._assert_error_shape(env, "PROVIDER_UNAVAILABLE")
            self.assertIn("不要", env["error"]["resolution"])
        finally:
            if home is not None:
                os.environ["HOME"] = home
            if key is not None:
                os.environ["DSH_SYNTHESIS_API_KEY"] = key
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_05_policy_denied_forbidden_key(self):
        env = L.call("lacan.search_passages", {"query": "x", "file": "/etc/passwd"})
        self._assert_error_shape(env, "SCHEMA_VALIDATION_FAILED")   # schema 先挡
        env2 = L.call("lacan.get_passage", {"passage_id": "/etc/passwd"})
        self._assert_error_shape(env2, "SCHEMA_VALIDATION_FAILED")

    def test_06_error_codes_are_the_frozen_set(self):
        for code in ("INVALID_REQUEST", "NOT_FOUND", "SCHEMA_VALIDATION_FAILED",
                     "PROVIDER_UNAVAILABLE", "CORE_FROZEN_MISMATCH",
                     "INDEX_UNAVAILABLE", "POLICY_DENIED", "INTERNAL_ERROR",
                     "TIMEOUT"):
            self.assertIn(code, E.CODES)

    def test_07_api_error_mapping(self):
        err = E.from_api_error({"error_code": "PASSAGE_NOT_FOUND", "message": "x"})
        self.assertEqual(err.code, "NOT_FOUND")
        self.assertEqual(E.from_api_error({"error_code": "WHAT"}).code, "INTERNAL_ERROR")

    def test_08_mcp_tool_response_marks_iserror(self):
        env = L.call("lacan.get_passage", {"passage_id": "passage.S99.unknown.P1"})
        from mcp_server.serializers import tool_response
        resp = tool_response(env)
        self.assertTrue(resp["isError"])
        self.assertEqual(resp["structuredContent"]["error"]["code"], "NOT_FOUND")

if __name__ == "__main__":
    unittest.main()
