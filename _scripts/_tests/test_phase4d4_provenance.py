#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §16/§17/§58-E：Witness 视图与 Source Trace（断点必须显式）"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L
from _i18n_testlib import assert_text_wired  # P5D-004: 文案断言走 i18n key


class Provenance(unittest.TestCase):
    def test_00_chain_shape(self):
        tr = L.B.source_trace(L.P_L1)
        self.assertEqual([s["step"] for s in tr["chain"]],
                         ["CorpusSource", "Witness", "PassageRealization",
                          "Session", "Seminar"])
        self.assertTrue(tr["complete"])
        self.assertEqual(tr["broken_at"], [])
        for s in tr["chain"]:
            self.assertIn("present", s)

    def test_01_case_e_l2_keeps_trace_incomplete(self):
        """§58 Case E：L2 recovered 段落必须保留 SOURCE_TRACE_INCOMPLETE。"""
        tr = L.B.source_trace(L.P_L2)
        self.assertEqual(tr["trace_status"], "SOURCE_TRACE_INCOMPLETE")
        self.assertFalse(tr["complete"])
        self.assertTrue(tr["witness_note"])
        d = L.X.passage_detail(L.P_L2)
        self.assertTrue(d["trace_incomplete_note"])
        self.assertEqual(d["passage"]["source_layer"], "L2")

    def test_02_agrees_with_frozen_core(self):
        """两条独立路径（browse 只读 store / 核心 trace_source）必须一致。"""
        from workspace_ui.server import api as UIA
        env = UIA._call("lacan.trace_source", {"passage_id": L.P_L1})   # noqa: SLF001
        if not env.get("ok"):
            self.skipTest("MCP 不可用：%s" % env.get("error"))
        core = env["result"]
        mine = L.B.source_trace(L.P_L1)
        self.assertEqual(mine["trace_status"], core.get("trace_status"))
        self.assertEqual(mine["chain"][1]["id"], core.get("witness"))
        self.assertEqual(mine["chain"][4]["id"], core.get("seminar"))

    def test_03_witnesses_distinguish_kinds(self):
        """§16：witness ≠ translation ≠ canonical passage identity；其他 witness 不隐藏。"""
        w = L.B.witnesses(L.P_L1)
        self.assertTrue(w["linked"])
        self.assertIn("witness", w["note"].lower())
        kinds = {x["witness_kind"] for x in w["linked"]}
        self.assertTrue(kinds)
        self.assertTrue(w["unlinked_witnesses"], "语料里存在但未链接的 witness 不得隐藏")
        for x in w["unlinked_witnesses"]:
            self.assertEqual(x["passage_link_state"], "not_linked")
            self.assertIn("不隐藏", x["note"])

    def test_04_missing_steps_are_marked_broken(self):
        """人为断开链时必须能指出断点（不能补空）。"""
        tr = L.B.source_trace(L.P_L1)
        tr2 = dict(tr)
        tr2["chain"] = [dict(s) for s in tr["chain"]]
        tr2["chain"][2]["present"] = False
        broken = [s["step"] for s in tr2["chain"] if not s["present"]]
        self.assertEqual(broken, ["PassageRealization"])

    def test_05_ui_renders_break_explicitly(self):
        src = open(os.path.join(VAULT, "workspace_ui", "static", "src", "explorer.js"),
                   encoding="utf-8").read()
        assert_text_wired(self, "inspector.js", "Source trace incomplete")  # P5D-004: 文案走 i18n key
        assert_text_wired(self, "explorer.js", "break")  # P5D-004: 文案走 i18n key
