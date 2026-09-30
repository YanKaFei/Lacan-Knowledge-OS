#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §35/§57：JSON 导出与 round-trip"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class JsonExport(unittest.TestCase):
    def test_00_has_schema_version_and_stable_names(self):
        d = L.doc()
        raw = EX.json_export.render(d)
        obj = json.loads(raw)
        self.assertEqual(obj["schema_version"], EX.EXPORT_MODEL_VERSION)
        for key in ("source_type", "source_id", "answer_state", "sections", "claims",
                    "citations", "limitations", "provenance", "evidence_role"):
            self.assertIn(key, obj)

    def test_01_roundtrip_preserves_identity(self):
        d = L.doc()
        back = EX.json_export.load(EX.json_export.render(d))
        self.assertEqual(EX.scholarly_identity(d), EX.scholarly_identity(back))
        self.assertEqual(EX.export_payload_hash(d), EX.export_payload_hash(back))
        EX.assert_identity(d, back)

    def test_02_missing_keys_rejected(self):
        raw = json.dumps({"schema_version": EX.EXPORT_MODEL_VERSION})
        with self.assertRaises(EX.ExportError) as ctx:
            EX.json_export.load(raw)
        self.assertEqual(ctx.exception.code, "SCHEMA_VALIDATION_FAILED")

    def test_03_invalid_json_rejected(self):
        with self.assertRaises(EX.ExportError) as ctx:
            EX.json_export.load("{not json")
        self.assertEqual(ctx.exception.code, "SCHEMA_VALIDATION_FAILED")

    def test_04_unexpected_key_rejected(self):
        d = L.doc()
        d["surprise"] = 1
        with self.assertRaises(EX.ExportError):
            EX.json_export.render(d)

    def test_05_json_is_not_html_or_yaml(self):
        obj = json.loads(EX.json_export.render(L.doc()))
        for rec in obj["citations"]:
            self.assertIn("internal_short", rec)
            self.assertIn("capabilities", rec)
        self.assertIsInstance(obj["sections"], list)

    def test_06_unicode_preserved(self):
        d = L.doc()
        d["question"] = "中译术语：原乐、快感、实在界"
        obj = json.loads(EX.json_export.render(d))
        self.assertIn("原乐", obj["question"])
