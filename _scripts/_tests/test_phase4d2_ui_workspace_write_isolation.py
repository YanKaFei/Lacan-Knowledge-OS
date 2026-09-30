#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §42/§7：写入隔离 —— UI 只能写 USER_WORKSPACE，绝不改核心。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402
from scholarly_api import policy as POL                        # noqa: E402

class WorkspaceWriteIsolation(unittest.TestCase):
    def test_00_history_dir_is_user_workspace(self):
        from workspace_ui.server import config as UIC
        self.assertEqual(POL.classify(UIC.HISTORY_DIR + "/x.json"), "USER_WORKSPACE")

    def test_01_history_save_only_under_workspace(self):
        from workspace_ui.server import history as H
        rec = H.save("isolation probe question", {"advanced": {"request_id": "probe"},
                                                  "state": "VALIDATED", "citations": []},
                     {"mode": "scholarly", "provider": "mock"})
        self.assertTrue(rec["path"].startswith("_workspace/history/"), rec["path"])
        p = os.path.join(VAULT, rec["path"])
        self.assertTrue(os.path.isfile(p))
        os.remove(p)

    def test_02_core_writes_refused(self):
        for target in ("_data/passage_store/passages.jsonl",
                       "_data/core_freeze/scholarly_core_freeze_v1.json",
                       "_data/ontology/v4a1/entities.jsonl",
                       "_data/eval/research_human_review_round2.jsonl"):
            with self.assertRaises(POL.CoreMutationError):
                POL.write_text(target, "x")

    def test_03_history_save_does_not_touch_core(self):
        from workspace_ui.server import history as H
        before = L.core_snapshot()
        rec = H.save("core isolation probe", {"advanced": {"request_id": "probe2"},
                                              "state": "ABSTAINED", "citations": []},
                     {"mode": "scholarly"})
        after = L.core_snapshot()
        self.assertEqual(L.core_diff(before, after), [], "历史写入改动了核心工件")
        os.remove(os.path.join(VAULT, rec["path"]))

    def test_04_ui_layer_does_not_import_core(self):
        core = ("knowledge_api", "research_answer", "research_contract",
                "research_execution", "synthesis_contract", "synthesis_claims",
                "synthesis_render", "synthesis_adapters", "synthesis_entailment",
                "synthesis_validation", "eval_integrity")
        import re
        d = os.path.join(VAULT, "workspace_ui", "server")
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(d, fn), encoding="utf-8").read()
            for mod in core:
                self.assertIsNone(re.search(r"^\s*(import|from)\s+%s\b" % re.escape(mod),
                                            src, re.M),
                                  "%s 直接 import 了核心 %s" % (fn, mod))

    def test_05_ui_goes_through_mcp(self):
        from workspace_ui.server import config as UIC
        src = open(os.path.join(VAULT, "workspace_ui", "server", "mcp_client.py"),
                   encoding="utf-8").read()
        self.assertIn("tools/call", src)
        self.assertTrue(UIC.MCP_SERVER.endswith(os.path.join("mcp_server", "server.py")),
                        UIC.MCP_SERVER)

    def test_06_static_assets_inside_static_dir(self):
        from workspace_ui.server.httpserver import _safe_static_path
        self.assertIsNone(_safe_static_path("../../etc/passwd"))
        self.assertIsNone(_safe_static_path("/etc/passwd"))
        self.assertTrue(_safe_static_path("index.html").endswith("index.html"))

if __name__ == "__main__":
    unittest.main()
