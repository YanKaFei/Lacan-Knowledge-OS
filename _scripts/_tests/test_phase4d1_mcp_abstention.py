#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-4/§8：弃权必须原样传播（core == api == MCP），任何人不得补答。"""
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _mcp_testlib as L                                        # noqa: E402

SUBSTANTIVE = ("DEFINITION", "RELATION", "DISTINCTION", "DIACHRONIC_CHANGE",
               "REINTERPRETATION", "SOURCE_INFLUENCE", "FORMALISM")

class AbstentionPropagation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {}
        for key in ("abstain_topic", "abstain_metadata"):
            q = L.FROZEN_QUESTIONS[key]
            opts = {"mode": "scholarly", "provider": "mock"}
            api_res = L.cached_research(q, opts)
            env = L.call("lacan.research", dict(opts, question=q))
            cls.cases[key] = (q, api_res, env)

    def test_00_core_and_api_abstain(self):
        for key, (q, api_res, env) in self.cases.items():
            self.assertEqual(api_res.get("answer_state"), "ABSTAINED",
                             "%s：核心未弃权（%s）" % (key, api_res.get("answer_state")))
            self.assertEqual(api_res.get("answer_permission"), "ABSTAIN")

    def test_01_mcp_preserves_abstention_verbatim(self):
        for key, (q, api_res, env) in self.cases.items():
            self.assertTrue(env["ok"], env)
            self.assertEqual(env["result"]["answer_state"], "ABSTAINED")
            self.assertEqual(env["result"]["answer_permission"], "ABSTAIN")
            self.assertEqual(env["meta"]["answer_state"], "ABSTAINED")
            self.assertEqual(L.canon(env["result"]), L.canon(api_res),
                             "%s：MCP 载荷与 API 载荷不一致（可能被包装器改写）" % key)

    def test_02_no_substantive_claims_in_abstention(self):
        for key, (q, api_res, env) in self.cases.items():
            for c in env["result"]["validated_claims"]:
                self.assertNotIn(c.get("claim_type"), SUBSTANTIVE,
                                 "%s：弃权答案里出现实质性断言 %s" % (key, c.get("claim_id")))

    def test_03_abstention_block_present(self):
        for key, (q, api_res, env) in self.cases.items():
            ab = env["result"]["abstention"]
            self.assertIsNotNone(ab, "%s：MCP 丢了 abstention 块" % key)
            self.assertTrue(ab.get("categories") or ab.get("category"))
            self.assertTrue(ab.get("missing_information") is not None)

    def test_04_tool_description_forbids_filling_in(self):
        """工具描述必须写明 abstention 会被传播、不得用模型知识补答。"""
        r = L.mcp_roundtrip("tools/list")
        desc = next(t for t in r["result"]["tools"]
                    if t["name"] == "lacan.research")["description"]
        self.assertIn("abstain", desc.lower())
        self.assertIn("does NOT answer from model knowledge", desc)

if __name__ == "__main__":
    unittest.main()
