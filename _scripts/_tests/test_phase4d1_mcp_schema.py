#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-1：MCP tool schema 契约（清单 / 输入校验 / fail closed / 默认 provider）。"""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _mcp_testlib as L                                        # noqa: E402
from mcp_server import schemas as S                             # noqa: E402
from scholarly_api import objects as O                          # noqa: E402

EXPECTED = ["lacan.research", "lacan.search_passages", "lacan.get_passage",
            "lacan.get_context", "lacan.get_concept", "lacan.get_seminar",
            "lacan.trace_source", "lacan.compare_terms",
            "lacan.research_diachronic", "lacan.research_translation"]

class McpToolSchema(unittest.TestCase):
    def test_00_exact_tool_inventory(self):
        self.assertEqual(S.TOOL_NAMES, EXPECTED, "工具集必须正好是 v1 的 10 个")

    def test_01_input_schemas_are_strict(self):
        for t in S.TOOLS:
            sch = t["inputSchema"]
            self.assertFalse(sch.get("additionalProperties", True),
                             "%s 必须 additionalProperties=false" % t["name"])
            self.assertIn("required", sch, "%s 缺 required" % t["name"])
            self.assertEqual(sch.get("type"), "object")

    def test_02_outputs_use_frozen_objects_only(self):
        for t in S.TOOLS:
            self.assertIn(t["output_object"], O.SCHEMAS,
                          "%s 的输出对象不在 4D.0 稳定对象里" % t["name"])

    def test_03_provider_defaults_to_mock(self):
        ok, errs, filled = S.validate_input("lacan.research", {"question": "objet a 是什么？"})
        self.assertTrue(ok, errs)
        self.assertEqual(filled["provider"], "mock", "provider 必须默认 mock（§6）")
        self.assertEqual(filled["mode"], "scholarly")

    def test_04_context_defaults_and_limits(self):
        ok, _, filled = S.validate_input("lacan.get_context",
                                        {"passage_id": "passage.S11.unknown.P2253"})
        self.assertTrue(ok); self.assertEqual((filled["before"], filled["after"]), (3, 3))
        ok, errs, _ = S.validate_input("lacan.get_context",
            {"passage_id": "passage.S11.unknown.P2253", "before": 21})
        self.assertFalse(ok, "before > 20 必须被拒（§12）")

    def test_05_search_limit_bounds(self):
        ok, _, filled = S.validate_input("lacan.search_passages", {"query": "regard"})
        self.assertTrue(ok); self.assertEqual(filled["limit"], 10)
        self.assertFalse(S.validate_input("lacan.search_passages",
                                         {"query": "x", "limit": 101})[0])

    def test_06_unknown_field_rejected(self):
        self.assertFalse(S.validate_input("lacan.research",
                                         {"question": "q", "max_tokens": 10})[0])

    def test_07_tools_list_shape(self):
        r = L.mcp_roundtrip("tools/list")
        tools = r["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], EXPECTED)
        for t in tools:
            self.assertTrue(t["description"].strip())
            self.assertIn("inputSchema", t)
            self.assertNotIn("outputSchema", t)

    def test_08_initialize_declares_tools_only(self):
        r = L.mcp_roundtrip("initialize", {"protocolVersion": "2025-11-25"})
        res = r["result"]
        self.assertEqual(res["protocolVersion"], "2025-11-25")
        self.assertEqual(list(res["capabilities"].keys()), ["tools"])
        self.assertEqual(res["serverInfo"]["name"], "lacan-research")

    def test_09_bad_input_fails_closed(self):
        env = L.call("lacan.get_context",
                     {"passage_id": "passage.S11.unknown.P2253", "before": 999})
        self.assertFalse(env["ok"])
        self.assertEqual(env["error"]["code"], "SCHEMA_VALIDATION_FAILED")
        self.assertIn("schema_errors", env["error"]["detail"])

    def test_10_unknown_tool_is_protocol_error(self):
        r = L.mcp_roundtrip("tools/call", {"name": "lacan.nope", "arguments": {}})
        self.assertEqual(r["error"]["code"], -32602)
        self.assertEqual(r["error"]["data"]["code"], "UNKNOWN_TOOL")

if __name__ == "__main__":
    unittest.main()
