#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §13/§14/§47/§48：Research Bundle 结构与写入纪律"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class Bundle(unittest.TestCase):
    def test_00_standard_structure(self):
        with L.export_root("bundle"):
            out = EX.build_bundle(L.doc())
            self.assertTrue(out["ok"])
            files = L.bundle_files(out["dir"])
            for need in ("README.md", "manifest.json"):
                self.assertIn(need, files)
            self.assertTrue(any(f.startswith("research/") and f.endswith(".md")
                                for f in files))
            self.assertTrue(any(f.startswith("research/") and f.endswith(".json")
                                for f in files))
            self.assertIn("claims/claims.json", files)
            self.assertIn("citations/citations.json", files)
            self.assertIn("provenance/provenance.json", files)
            self.assertTrue(any(f.startswith("passages/") for f in files))

    def test_01_only_referenced_passages(self):
        """§14：不得 materialize 全库，只导出被引用/保存的 passage。"""
        with L.export_root("bundle2"):
            d = L.doc()
            out = EX.build_bundle(d)
            ids = EX.collect_passage_ids(d)
            files = [f for f in L.bundle_files(out["dir"]) if f.startswith("passages/")]
            self.assertEqual(len(files), len(ids))
            self.assertLess(len(files), 50)
            self.assertEqual(out["manifest"]["passage_count"], len(ids))
            for f in files:
                payload = json.load(open(os.path.join(out["dir"], f), encoding="utf-8"))
                self.assertIn(payload["passage_id"], ids)

    def test_02_verify_status_and_manifest_fields(self):
        with L.export_root("bundle3"):
            out = EX.build_bundle(L.doc())
            man = out["manifest"]
            for k in ("export_id", "created_at", "exporter_version", "source_type",
                      "source_id", "source_snapshot_hash", "core_freeze_version",
                      "file_count", "files", "hash_algorithm", "file_hashes" if False
                      else "citation_count", "passage_count", "bundle_hash"):
                self.assertIn(k, man, k)
            self.assertEqual(man["hash_algorithm"], "sha256")
            self.assertEqual(out["verify"]["status"], "VERIFIED")

    def test_03_include_context_recorded(self):
        """§28：context 选项必须记录在 manifest 里。"""
        with L.export_root("bundle4"):
            out = EX.build_bundle(L.doc(), include_context=2)
            self.assertEqual(out["manifest"]["export_options"].get("include_context"), 2)
            pdir = os.path.join(out["dir"], "passages")
            f = sorted(os.listdir(pdir))[0]
            payload = json.load(open(os.path.join(pdir, f), encoding="utf-8"))
            self.assertIn("context", payload)
            self.assertEqual(payload["context_window"], 2)

    def test_04_zip_created_after_verify_and_safe(self):
        with L.export_root("bundle5"):
            out = EX.build_bundle(L.doc(), make_zip=True)
            self.assertTrue(out["zip"].endswith(".zip"))
            zpath = os.path.join(EX.policy.VAULT, out["zip"])
            self.assertTrue(os.path.isfile(zpath))
            import zipfile
            with zipfile.ZipFile(zpath) as z:
                names = z.namelist()
            self.assertIn("manifest.json", names)
            for n in names:
                self.assertFalse(n.startswith("/"), n)
                self.assertNotIn("..", n.split("/"))

    def test_05_zip_slip_extraction_refused(self):
        with L.export_root("bundle6"):
            zpath = os.path.join(EX.policy.VAULT, EX.export_root(),
                                 "evil.zip") if False else None
            import zipfile
            target = os.path.join(EX.policy.VAULT, "_workspace", "test_exports",
                                  "bundle6", "evil.zip")
            with zipfile.ZipFile(target, "w") as z:
                z.writestr("../escape.txt", "x")
                z.writestr("/abs.txt", "y")
            with self.assertRaises(EX.ExportError) as ctx:
                EX.extract_zip(target, os.path.join(os.path.dirname(target), "out"))
            self.assertEqual(ctx.exception.code, "EXPORT_POLICY_DENIED")

    def test_06_bundle_refuses_modified_without_optin(self):
        with L.export_root("bundle7"):
            d = L.doc()
            d["snapshot_integrity"] = "MODIFIED"
            with self.assertRaises(EX.ExportError) as ctx:
                EX.build_bundle(d)
            self.assertEqual(ctx.exception.code, "BUNDLE_VERIFICATION_FAILED")

    def test_07_failed_bundle_leaves_no_half_product(self):
        """§47：失败不留「看起来成功」的半 bundle。"""
        with L.export_root("bundle8") as root:
            d = L.doc()
            d["citations"][0]["passage_id"] = "passage.S99.unknown.P9999"
            with self.assertRaises(EX.ExportError):
                EX.build_bundle(d)
            leftovers = [n for n in os.listdir(root) if not n.startswith(".")]
            self.assertEqual(leftovers, [], leftovers)
            self.assertFalse([n for n in os.listdir(root) if n.startswith(".tmp-")])

    def test_08_bundle_excludes_uncited_corpus(self):
        with L.export_root("bundle9"):
            out = EX.build_bundle(L.doc())
            total = 0
            for root, _d, files in os.walk(out["dir"]):
                for fn in files:
                    total += os.path.getsize(os.path.join(root, fn))
            self.assertLess(total, 2_000_000, "bundle 不应像全库导出那样巨大")
