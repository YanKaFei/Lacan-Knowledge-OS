#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-8/§27：core freeze guard —— 漂移时 fail closed，不在漂移状态下服务。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _mcp_testlib as L                                        # noqa: E402
from mcp_server import guard as G                               # noqa: E402
from mcp_server import tools as T                               # noqa: E402

class FreezeGuard(unittest.TestCase):
    def test_00_freeze_currently_ok(self):
        ok, detail = G.verify_core_freeze()
        self.assertTrue(ok, detail)
        self.assertEqual(detail.get("scholarly_status"), "SCHOLARLY_CORE_READY")
        self.assertEqual(detail.get("freeze_version"), "scholarly_core_freeze_v1")

    def test_01_guard_passes_when_frozen(self):
        state = {"ok": True, "detail": {"freeze_version": "x"}}
        self.assertEqual(G.assert_core_frozen(state), {"freeze_version": "x"})

    def test_02_drift_fails_closed_for_research(self):
        orig = G.verify_core_freeze
        try:
            G.verify_core_freeze = lambda timeout_s=180: (
                False, {"reason": "FREEZE_DRIFT", "stdout": "drift!"})
            env = T.call_tool("lacan.research", {"question": "objet a 是什么？"},
                              freeze_state=None, audit=False)
            self.assertFalse(env["ok"])
            self.assertEqual(env["error"]["code"], "CORE_FROZEN_MISMATCH")
        finally:
            G.verify_core_freeze = orig

    def test_03_drift_fails_closed_for_readonly_too(self):
        orig = G.verify_core_freeze
        try:
            G.verify_core_freeze = lambda timeout_s=180: (False, {"reason": "X"})
            for tool, args in (("lacan.get_passage",
                                {"passage_id": "passage.S11.unknown.P2253"}),
                               ("lacan.search_passages", {"query": "regard"}),
                               ("lacan.trace_source",
                                {"passage_id": "passage.S11.unknown.P2253"})):
                env = T.call_tool(tool, args, freeze_state=None, audit=False)
                self.assertFalse(env["ok"], tool)
                self.assertEqual(env["error"]["code"], "CORE_FROZEN_MISMATCH", tool)
        finally:
            G.verify_core_freeze = orig

    def test_04_manifest_pins_the_api(self):
        man = json.load(open(os.path.join(VAULT, "_data", "core_freeze",
                                         "scholarly_core_freeze_v1.json"),
                             encoding="utf-8"))
        for k in ("scholarly_api_core_hash", "scholarly_api_objects_hash",
                  "scholarly_api_policy_hash"):
            self.assertTrue(man["components"].get(k), k)

    def test_05_server_selftest_reports_freeze(self):
        reqs = [("initialize", {"protocolVersion": "2025-11-25"})]
        res = L.stdio_session(reqs)
        self.assertIn("core_freeze", res[0]["result"]["meta"])

if __name__ == "__main__":
    unittest.main()
