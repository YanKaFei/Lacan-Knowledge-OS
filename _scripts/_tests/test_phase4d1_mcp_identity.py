#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-3/§25：跨层同一性 —— core == api == MCP（只允许 transport 差异）。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _mcp_testlib as L                                        # noqa: E402
import scholarly_api as api                                     # noqa: E402

Q = L.FROZEN_QUESTIONS["relation"]
OPTS = {"mode": "seminar_specific", "language": "fr", "provider": "mock"}

class CrossLayerIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_res = L.cached_research(Q, OPTS)
        cls.env = L.call("lacan.research", dict(OPTS, question=Q))

    def test_00_api_ok(self):
        self.assertNotEqual(self.api_res.get("ok"), False, self.api_res)

    def test_01_mcp_returns_ok_envelope(self):
        self.assertTrue(self.env["ok"], self.env)
        self.assertEqual(self.env["meta"]["tool"], "lacan.research")
        self.assertEqual(self.env["meta"]["api_version"], "scholarly-api/v1")
        self.assertEqual(self.env["meta"]["provider"], "mock")

    def test_02_scholarly_payload_is_identical(self):
        """核心载荷必须逐字相同（不允许 claim/citation/answer/limitation 变化）。"""
        self.assertEqual(L.canon(self.env["result"]), L.canon(self.api_res),
                         "MCP 结果与 scholarly_api 结果不一致")

    def test_03_only_meta_differs(self):
        a = dict(self.api_res); b = dict(self.env["result"])
        self.assertEqual(L.canon(a), L.canon(b))
        for k in ("summary", "sections", "validated_claims", "citations",
                  "source_limitations", "abstention", "answer_state",
                  "answer_permission", "warnings"):
            self.assertEqual(L.canon(a.get(k)), L.canon(b.get(k)), "字段 %s 被改动" % k)

    def test_04_three_layer_identity(self):
        """core == api == mcp：直接跑一次核心编排再比对。"""
        again = api.research(Q, dict(OPTS, task_id=dict(OPTS).get("task_id")))
        self.assertEqual(L.canon(again), L.canon(self.api_res),
                         "同一冻结输入两次 API 结果不一致（非确定性）")

    def test_05_meta_does_not_leak_into_result(self):
        for key in ("request_id", "duration_ms", "mcp_version", "server"):
            self.assertNotIn(key, self.env["result"])

if __name__ == "__main__":
    unittest.main()
