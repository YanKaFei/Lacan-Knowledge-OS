#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.2 §30：core freeze mismatch —— UI 必须停用研究提交（fail closed），历史仍可看。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L                                        # noqa: E402
from workspace_ui.server import api as UIA                     # noqa: E402
from workspace_ui.server import viewmodel as VM                # noqa: E402

class FreezeMismatchUX(unittest.TestCase):
    def test_00_status_view_reports_freeze(self):
        st = UIA.status()
        self.assertTrue(st["mcp_connected"])
        self.assertTrue(st["core_freeze_verified"])
        self.assertFalse(st["research_disabled"])

    def test_01_mismatch_disables_research(self):
        v = VM.status_view({"connected": True, "core_freeze_verified": False,
                            "core_freeze": {"freeze_version": "x",
                                            "scholarly_status": "DRIFTED"}})
        self.assertTrue(v["research_disabled"])

    def test_02_offline_disables_research(self):
        v = VM.status_view({"connected": False, "core_freeze_verified": False})
        self.assertTrue(v["research_disabled"])

    def test_03_ui_disables_submit_button(self):
        src = L.js_sources()["app.js"]
        self.assertIn("research_disabled", src)
        self.assertIn("ask-btn", src)
        self.assertIn("disabled", src)

    def test_04_history_remains_browsable_when_disabled(self):
        src = L.js_sources()["app.js"]
        self.assertIn("loadHistory", src)                 # 历史不因停用而消失
        self.assertIn("nav-history", src)

    def test_05_no_ignore_option_in_ui(self):
        blob = "".join(L.js_sources().values()).lower()
        for bad in ("ignore warning", "ignore error", "dismiss anyway",
                    "continue anyway", "override freeze"):
            self.assertNotIn(bad, blob)

    def test_06_freeze_lineage_present_and_zero_semantic_changes(self):
        import subprocess
        r = subprocess.run([sys.executable,
                            os.path.join(VAULT, "_scripts", "_tools", "freeze_lineage.py"),
                            "--verify", "--quiet"], capture_output=True, text=True,
                           cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = json.load(open(os.path.join(VAULT, "_data", "core_freeze",
                                          "freeze_lineage.json"), encoding="utf-8"))
        self.assertTrue(doc["live_matches_last_segment"])
        self.assertTrue(doc["all_segments_semantic_changes_zero"])
        phases = [s["phase"] for s in doc["segments"]]
        self.assertIn("4D.0", phases)
        self.assertIn("4D.1", phases)
        self.assertIn("4D.2", phases)

if __name__ == "__main__":
    unittest.main()
