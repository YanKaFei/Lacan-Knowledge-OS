#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §5/§6/§36/§59/§60：统一 Export Model 与身份哈希"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class ExportModel(unittest.TestCase):
    def test_00_required_fields(self):
        d = L.doc()
        for k in ("export_id", "export_type", "source_type", "source_id", "created_at",
                  "title", "question", "answer_state", "task_type", "sections",
                  "claims", "citations", "limitations", "abstention", "provenance",
                  "bibliographic_metadata", "source_answer_hash",
                  "core_freeze_version", "schema_version"):
            self.assertIn(k, d, k)
        self.assertEqual(d["schema_version"], EX.EXPORT_MODEL_VERSION)

    def test_01_schema_definition_matches_disk(self):
        """§36：schema 定义与磁盘文件一致（沿用 4D.0 纪律）。"""
        for name in (EX.SCHEMA_EXPORT_DOCUMENT, EX.SCHEMA_BUNDLE_MANIFEST,
                     EX.SCHEMA_CITATION_RECORD):
            self.assertTrue(os.path.isfile(EX.model.schema_path(name)), name)
            sch = EX.model.load_schema(name)
            self.assertIn("required", sch)
            self.assertFalse(sch.get("additionalProperties", True), name)
        self.assertEqual(EX.model.load_schema(EX.SCHEMA_EXPORT_DOCUMENT)["$id"],
                         EX.SCHEMA_EXPORT_DOCUMENT)

    def test_02_document_validates(self):
        d = L.doc()
        self.assertTrue(EX.validate(d, EX.SCHEMA_EXPORT_DOCUMENT))

    def test_03_invalid_source_type_rejected(self):
        with self.assertRaises(EX.ExportError) as ctx:
            EX.make_document(export_type="x", source_type="made_up", source_id="1",
                             title="t", created_at="now")
        self.assertEqual(ctx.exception.code, "SCHEMA_VALIDATION_FAILED")

    def test_04_invalid_answer_state_rejected(self):
        with self.assertRaises(EX.ExportError) as ctx:
            EX.make_document(export_type="x", source_type="research_run", source_id="1",
                             title="t", created_at="now", answer_state="MAYBE")
        self.assertEqual(ctx.exception.code, "SCHEMA_VALIDATION_FAILED")

    def test_05_identity_hash_ignores_volatile_fields(self):
        """§59/§60：export_payload_hash 不随 export_id / created_at / format 变化。"""
        d = L.doc()
        d2 = dict(d, export_id="other", created_at="2099-01-01T00:00:00+00:00",
                  format="html")
        self.assertEqual(EX.export_payload_hash(d), EX.export_payload_hash(d2))
        self.assertEqual(d["export_payload_hash"], EX.export_payload_hash(d))

    def test_06_identity_hash_changes_with_payload(self):
        d = L.doc()
        d2 = json.loads(json.dumps(d))
        d2["claims"] = d2["claims"] + [{"claim_id": "extra", "claim_text": "x"}]
        self.assertNotEqual(EX.export_payload_hash(d), EX.export_payload_hash(d2))

    def test_07_content_hash_deterministic(self):
        a, b = L.doc(), L.doc()
        self.assertEqual(EX.content_hash(a), EX.content_hash(b))

    def test_08_assert_identity_detects_drift(self):
        d = L.doc()
        other = json.loads(json.dumps(d))
        other["claims"][0]["claim_text"] = "被改写"
        with self.assertRaises(EX.ExportError) as ctx:
            EX.assert_identity(d, other)
        self.assertEqual(ctx.exception.code, "EXPORT_SOURCE_MODIFIED")

    def test_09_error_codes_are_defined(self):
        for code in ("EXPORT_SOURCE_NOT_FOUND", "EXPORT_SOURCE_MODIFIED",
                     "BROKEN_REFERENCE", "SCHEMA_VALIDATION_FAILED",
                     "BIBLIOGRAPHIC_METADATA_INCOMPLETE", "EXPORT_POLICY_DENIED",
                     "EXPORT_WRITE_FAILED", "BUNDLE_VERIFICATION_FAILED",
                     "UNSUPPORTED_FORMAT"):
            self.assertIn(code, EX.ERROR_CODES)

    def test_10_export_id_is_deterministic_shape(self):
        d = L.doc()
        self.assertTrue(d["export_id"].startswith("exp_"))
        self.assertLess(len(d["export_id"]), 80)
        self.assertNotIn(" ", d["export_id"])
