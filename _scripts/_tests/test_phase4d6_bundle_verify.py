#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §16：verify_export_bundle 的 VERIFIED / MODIFIED / BROKEN"""
import json, os, shutil, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class BundleVerify(unittest.TestCase):
    def setUp(self):
        self.ctx = L.export_root("verify")
        self.root = self.ctx.__enter__()
        self.out = EX.build_bundle(L.doc())
        self.dir = self.out["dir"]

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_00_verified(self):
        v = EX.verify_bundle(self.dir)
        self.assertEqual(v["status"], "VERIFIED")
        self.assertEqual(v["problems"], [])

    def test_01_modified_file_detected(self):
        p = os.path.join(self.dir, "citations", "citations.json")
        doc = json.load(open(p, encoding="utf-8"))
        doc["citations"][0]["internal_full"] = "被改写"
        json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        v = EX.verify_bundle(self.dir)
        self.assertIn(v["status"], ("MODIFIED", "BROKEN"))
        self.assertTrue(any("hash mismatch" in x for x in v["problems"]))

    def test_02_missing_file_is_broken(self):
        os.remove(os.path.join(self.dir, "provenance", "provenance.json"))
        v = EX.verify_bundle(self.dir)
        self.assertEqual(v["status"], "BROKEN")
        self.assertTrue(any("missing file" in x for x in v["problems"]))

    def test_03_missing_manifest_is_broken(self):
        os.remove(os.path.join(self.dir, "manifest.json"))
        v = EX.verify_bundle(self.dir)
        self.assertEqual(v["status"], "BROKEN")
        self.assertIn("manifest.json missing", v["problems"])

    def test_04_unlisted_file_detected(self):
        with open(os.path.join(self.dir, "sneaky.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        v = EX.verify_bundle(self.dir)
        self.assertNotEqual(v["status"], "VERIFIED")
        self.assertTrue(any("unlisted" in x for x in v["problems"]))

    def test_05_source_identity_checked(self):
        v = EX.verify_bundle(self.dir, expect_source_id="someone-else")
        self.assertNotEqual(v["status"], "VERIFIED")
        self.assertTrue(any("identity" in x for x in v["problems"]))

    def test_06_tampered_bundle_hash_detected(self):
        p = os.path.join(self.dir, "manifest.json")
        man = json.load(open(p, encoding="utf-8"))
        man["bundle_hash"] = "0" * 64
        json.dump(man, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        v = EX.verify_bundle(self.dir)
        self.assertNotEqual(v["status"], "VERIFIED")
        self.assertTrue(any("bundle_hash" in x for x in v["problems"]))

    def test_07_broken_citation_blocks_verification(self):
        """§65：citation 指向不存在的 passage → verification 不通过。"""
        p = os.path.join(self.dir, "citations", "citations.json")
        doc = json.load(open(p, encoding="utf-8"))
        doc["citations"][0]["passage_id"] = "passage.S99.unknown.P9999"
        json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        v = EX.verify_bundle(self.dir)
        self.assertNotEqual(v["status"], "VERIFIED")
        self.assertTrue(any("not resolvable" in x for x in v["problems"]))
