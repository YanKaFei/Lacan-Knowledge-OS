#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4e_product_real_provider_path.py — Phase 4E §32/§36：**产品路径**真实 provider

必须经 **MCP stdio**（`lacan.research`）走一次真实 provider，而不是绕过 MCP
直接 Python 调 core（§36）。断言：

* `ok=True`、`isError=False`、`meta.provider == "llm"`；
* `result` 是合法 FinalScholarlyAnswer，且 `provenance.provider == "llm"`；
* 没有 `INTERNAL_ERROR` / `PROVIDER_CALL_FAILED` / AttributeError；
* 凭据不可用时 SKIP（仓库既有惯例）。
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))
sys.path.insert(0, VAULT)

import synthesis_adapters as sad              # noqa: E402
import run_synthesis_4c1d as rd               # noqa: E402
from workspace_ui.server import mcp_client as MC   # noqa: E402

rd.load_dsh_key()
AVAILABLE = sad.OpenAICompatibleProvider(timeout=10).available
SKIP_REASON = "SKIPPED_PROVIDER_UNAVAILABLE：未配置 provider（DSH_SYNTHESIS_API_KEY）"

QUESTION = "Seminar XI 中 gaze/regard 是如何与 objet a 发生关系的？"


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class TestProductRealProviderPath(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = MC.shared_client()
        cls.env = cls.client.call_tool(
            "lacan.research", {"question": QUESTION, "mode": "seminar_specific",
                               "provider": "llm", "judge": True})
        cls.answer = (cls.env or {}).get("result") or {}
        print("\n[4E product path] ok=%s state=%s claims=%s citations=%s"
              % ((cls.env or {}).get("ok"), cls.answer.get("answer_state"),
                 len(cls.answer.get("validated_claims") or []),
                 len(cls.answer.get("citations") or [])))

    def test_01_mcp_round_trip_succeeds(self):
        self.assertTrue(self.env.get("ok"), "MCP 调用失败：%s"
                        % json.dumps(self.env, ensure_ascii=False)[:400])
        self.assertNotIn("error", self.env)
        blob = json.dumps(self.env, ensure_ascii=False)
        for bad in ("has no attribute 'synthesize'", "INTERNAL_ERROR",
                    "PROVIDER_CALL_FAILED", "PROVIDER_UNAVAILABLE"):
            self.assertNotIn(bad, blob, "产品路径出现 %s" % bad)

    def test_02_answer_identity_and_provider_metadata(self):
        # ★ Phase 5A 已批准把 FinalScholarlyAnswer 升到 v1.1（「加字段=新版本」）。
        #   这里断言它落在**受支持的版本集合**内，并保持 4E 的实质断言
        #   （合法载荷 + provider 元数据）不变。
        from scholarly_api import objects as _O
        self.assertIn(self.answer.get("schema_version"),
                      _O.ANSWER_SCHEMA_VERSIONS_SUPPORTED,
                      "schema_version 不在受支持集合内：%r"
                      % self.answer.get("schema_version"))
        self.assertEqual(self.answer.get("provenance", {}).get("provider"), "llm")
        meta = self.env.get("meta") or {}
        self.assertEqual(meta.get("provider"), "llm")
        self.assertTrue(meta.get("request_id"), "meta 必须有 request_id（可追溯）")
        self.assertTrue(meta.get("core_freeze_version"))

    def test_03_no_secret_in_mcp_response(self):
        blob = json.dumps(self.env, ensure_ascii=False)
        key = os.environ.get("DSH_SYNTHESIS_API_KEY") or ""
        if len(key) >= 8:
            self.assertNotIn(key, blob)
        self.assertNotIn("Bearer ", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
