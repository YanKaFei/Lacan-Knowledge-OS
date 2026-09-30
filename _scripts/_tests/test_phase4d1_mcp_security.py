#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-9/§30：安全边界 —— 只接受领域参数；路径/命令/SQL 一律 fail closed。"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _mcp_testlib as L                                        # noqa: E402

class McpSecurity(unittest.TestCase):
    BAD_IDS = ["../../etc/passwd", "/etc/passwd", "passage.../../../x",
               "passage.S11;rm -rf /", "passage.S11`whoami`", "passage.S11$(id)",
               "passage.S11\nP2", "passage.S11\x00"]

    def test_00_passage_id_injection_rejected(self):
        for bad in self.BAD_IDS:
            env = L.call("lacan.get_passage", {"passage_id": bad})
            self.assertFalse(env["ok"], bad)
            self.assertEqual(env["error"]["code"], "SCHEMA_VALIDATION_FAILED", bad)

    def test_01_concept_and_seminar_ids(self):
        for bad in self.BAD_IDS + ["concept.Objet/UPPER", "../concept.x"]:
            self.assertFalse(L.call("lacan.get_concept", {"concept_id": bad})["ok"], bad)
            self.assertFalse(L.call("lacan.get_seminar", {"seminar_id": bad})["ok"], bad)

    def test_02_forbidden_keys_rejected(self):
        for key in ("file", "path", "sql", "command", "shell", "exec", "python",
                    "script", "url"):
            env = L.call("lacan.search_passages", {"query": "x", key: "y"})
            self.assertFalse(env["ok"], key)

    def test_03_dangerous_substrings_rejected(self):
        for payload in ("regard; DROP TABLE passages", "regard $(cat /etc/passwd)",
                        "regard && rm -rf /", "regard `id`", "regard\x00"):
            env = L.call("lacan.search_passages", {"query": payload})
            self.assertFalse(env["ok"], payload)
            self.assertIn(env["error"]["code"],
                          ("POLICY_DENIED", "SCHEMA_VALIDATION_FAILED"), payload)

    def test_04_no_absolute_paths_anywhere(self):
        env = L.call("lacan.search_passages", {"query": "<HOME>"})
        self.assertFalse(env["ok"])
        self.assertEqual(env["error"]["code"], "POLICY_DENIED")

    def test_05_limits_cannot_be_bypassed(self):
        self.assertFalse(L.call("lacan.get_context", {
            "passage_id": "passage.S11.unknown.P2253", "before": 10**6})["ok"])
        self.assertFalse(L.call("lacan.search_passages", {
            "query": "x", "limit": 10**6})["ok"])

    def test_06_unknown_filter_fields_rejected(self):
        self.assertFalse(L.call("lacan.search_passages",
                                {"query": "x", "unknown_filter": 1})["ok"])

    def test_07_question_length_bounded(self):
        self.assertFalse(L.call("lacan.research", {"question": "x" * 5000})["ok"])

    def test_08_error_payload_has_no_filesystem_paths(self):
        env = L.call("lacan.get_passage", {"passage_id": "../../etc/passwd"})
        blob = json.dumps(env, ensure_ascii=False)
        self.assertNotIn("/etc/passwd", blob)
        self.assertNotIn(VAULT, blob)

if __name__ == "__main__":
    unittest.main()
