#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4d1_mcp_agent_smoke.py — 4D.1 §24：Agent → MCP 端到端烟测（6 题）

与其它测试不同：这里**真的起一个 MCP server 进程**，用真实 MCP 协议
（JSON-RPC 2.0 over stdio：initialize → tools/list → tools/call）驱动 6 个问题，
即 DeepSeek Harness / Claude / Cursor 接入时的真实链路。

6 题（§24）：
  1 直接关系（Seminar XI gaze/objet a）  → 必须有真实 citations
  2 术语（Réel / réalité）               → 有答案或合格限定
  3 形式化（$ ◊ a）                      → 有答案
  4 历时限制（jouissance S7→S20）        → core 的限制必须原样保留
  5 主题弃权（fMRI）                     → 必须 ABSTAINED
  6 元数据弃权（1953-11-18 报告）        → 必须 ABSTAINED
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)
sys.path.insert(0, HERE)

import _mcp_testlib as L                                        # noqa: E402

Q = L.FROZEN_QUESTIONS
MOCK = {"provider": "mock"}


class AgentToMcpSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = [("initialize", {"protocolVersion": "2025-11-25"}),
                        ("tools/list", {})]
        order = ["relation", "terminology", "formalism", "diachronic",
                 "abstain_topic", "abstain_metadata"]
        for key in order:
            cls.requests.append(("tools/call",
                                 {"name": "lacan.research",
                                  "arguments": dict(MOCK, question=Q[key],
                                                    mode="scholarly")}))
        cls.responses = L.stdio_session(cls.requests)
        cls.init = cls.responses[0]["result"]
        cls.tools = cls.responses[1]["result"]["tools"]
        cls.envs = {}
        for i, key in enumerate(order, start=2):
            cls.envs[key] = cls.responses[i]["result"]["structuredContent"]

    # ── 协议面
    def test_00_initialize_and_tools_over_real_stdio(self):
        self.assertEqual(self.init["protocolVersion"], "2025-11-25")
        self.assertEqual(self.init["serverInfo"]["name"], "lacan-research")
        self.assertTrue(self.init["meta"]["core_freeze"]["freeze_version"])
        self.assertEqual(len(self.tools), 10)

    # ── 1 直接关系
    def test_01_relation_question_has_real_citations(self):
        env = self.envs["relation"]
        self.assertTrue(env["ok"], env)
        self.assertTrue(env["result"]["citations"], "关系题必须给出真实 citation")
        for c in env["result"]["citations"]:
            rec = L.call("lacan.get_passage", {"passage_id": c["passage_id"]})
            self.assertTrue(rec["ok"], "citation 不可回查：%s" % c["passage_id"])

    # ── 2 术语
    def test_02_terminology_question(self):
        env = self.envs["terminology"]
        self.assertTrue(env["ok"], env)
        r = env["result"]
        self.assertIn(r["answer_state"],
                      ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "ABSTAINED",
                       "STRUCTURALLY_UNAVAILABLE"))
        if r["answer_state"] != "ABSTAINED":
            self.assertTrue(r["validated_claims"] or r["abstention"])

    # ── 3 形式化
    def test_03_formalism_question(self):
        env = self.envs["formalism"]
        self.assertTrue(env["ok"], env)
        self.assertTrue(env["result"]["sections"] or env["result"]["abstention"])

    # ── 4 历时限制
    def test_04_diachronic_limitation_is_preserved(self):
        env = self.envs["diachronic"]
        self.assertTrue(env["ok"], env)
        api_res = L.cached_research(Q["diachronic"], {"mode": "scholarly",
                                                      "provider": "mock"})
        self.assertEqual(L.canon(env["result"]), L.canon(api_res),
                         "历时题的 MCP 载荷与核心不一致（限制可能被改写）")
        # 若核心给出限制/弃权，MCP 必须保留（不允许被"补写成发展史"）
        if api_res["answer_state"] == "ABSTAINED" or api_res["source_limitations"]:
            blob = L.canon(env["result"])
            self.assertTrue(api_res["source_limitations"]
                            or env["result"]["abstention"] is not None)
            self.assertIn("source_limitations", blob)

    # ── 5/6 弃权
    def test_05_topic_abstention(self):
        env = self.envs["abstain_topic"]
        self.assertTrue(env["ok"], env)
        self.assertEqual(env["result"]["answer_state"], "ABSTAINED")
        self.assertEqual(env["result"]["answer_permission"], "ABSTAIN")

    def test_06_metadata_abstention(self):
        env = self.envs["abstain_metadata"]
        self.assertTrue(env["ok"], env)
        self.assertEqual(env["result"]["answer_state"], "ABSTAINED")
        self.assertEqual(env["result"]["answer_permission"], "ABSTAIN")

    # ── 审计
    def test_07_every_call_is_audited(self):
        """6 次 research 调用必须各留一条审计（question_hash，非全文）。"""
        import glob
        files = sorted(glob.glob(os.path.join(VAULT, "_data", "product_audit",
                                              "mcp", "audit-*.jsonl")))
        self.assertTrue(files, "缺 MCP 审计日志")
        rows = [json.loads(l) for l in open(files[-1], encoding="utf-8") if l.strip()]
        hashed = [r for r in rows if r["tool"] == "lacan.research"
                  and r.get("question_hash")]
        self.assertGreaterEqual(len(hashed), 6)
        for r in hashed:
            self.assertNotIn("DEEPSEEK", json.dumps(r))
            self.assertFalse(r.get("question_recorded"), "默认不应记录问题全文")

    def test_08_agent_facing_descriptions_are_restrained(self):
        d = next(t for t in self.tools if t["name"] == "lacan.research")["description"]
        self.assertIn("frozen", d.lower())
        self.assertIn("does NOT answer from model knowledge", d)
        self.assertNotIn("any question about Lacan", d)


if __name__ == "__main__":
    unittest.main()
