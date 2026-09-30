#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase5c_zotero_layer — Phase 5C §22–§29/§43：Zotero 导入/去重/冲突/安全。"""
from __future__ import annotations
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
if VAULT not in sys.path: sys.path.insert(0, VAULT)
from bibliography import zotero as Z, model as M, registry as R

# ⚠️ 测试样例使用**中性标题 + 标准示例 ISBN**：不得给真实著作编造标识（§50 精神）
CSL = json.dumps([
    {"id": "ABCD1234", "type": "book", "title": "Test Volume",
     "author": [{"literal": "Test Author"}], "publisher": "Test Press",
     "issued": {"date-parts": [[1966]]}, "ISBN": "9780306406157"},
    {"id": "ABCD1234", "type": "book", "title": "Test Volume",
     "author": [{"literal": "Test Author"}], "publisher": "Test Press",
     "issued": {"date-parts": [[1967]]}, "ISBN": "9780306406157"},
    {"id": "EFGH9999", "type": "article-journal", "title": "Test Article",
     "author": [{"literal": "Test Author"}], "issued": {"date-parts": [[1949]]}},
])

class Zotero(unittest.TestCase):
    def test_phase5c_zotero_import(self):
        r = Z.import_file(CSL, "csl-json")
        self.assertEqual(len(r["candidates"]), 3)
        for c in r["candidates"]:
            self.assertEqual(c["review_status"], "candidate")     # §25 不自动 canonicalize
            self.assertFalse(c["canonicalized"])
            self.assertEqual(c["item_type"] in M.ITEM_TYPES, True)
        # 导入的候选**不得**出现在 reviewed registry
        reviewed = {i["bibliographic_id"] for i in R.items()}
        self.assertFalse({c["candidate_id"] for c in r["candidates"]} & reviewed)

    def test_phase5c_zotero_dedup(self):
        r = Z.import_file(CSL, "csl-json")
        dups = r["duplicates"]
        self.assertTrue(dups)
        for d in dups:
            self.assertFalse(d["auto_merged"], "去重**不得**自动合并（§26）")
        kinds = {d["dedup_key_kind"] for d in dups}
        self.assertTrue(kinds & {"isbn", "doi", "zotero", "title_author_year"})
        # 弱键（title+author+year）只能标 candidate_duplicate
        weak = Z.dedup_key({"title": "X", "authors": ["A"], "publication_year": "2000"})
        self.assertEqual(weak[0], "title_author_year")

    def test_phase5c_metadata_conflict(self):
        r = Z.import_file(CSL, "csl-json")
        self.assertTrue(r["conflicts"], "1966 vs 1967 必须产生 METADATA_CONFLICT")
        for c in r["conflicts"]:
            self.assertEqual(c["code"], "METADATA_CONFLICT")
            self.assertFalse(c["auto_overwrite"], "禁止 last-write-wins（§27）")
            self.assertGreaterEqual(len(c["values"]), 2)
            self.assertEqual(c["resolution"], "UNRESOLVED")

    def test_phase5c_security(self):
        # 路径穿越 / 危险 key：逐条**拒绝并记录**（不让整批导入失败）
        for bad_key in ("../../etc/passwd", "<script>alert(1)</script>",
                        "a/b", "..\\win", "x" * 300):
            rr = Z.import_file(json.dumps([{"id": bad_key, "title": "x"}]), "csl")
            self.assertEqual(len(rr["candidates"]), 0,
                             "危险 key 不得进入 candidates：%r" % bad_key)
            self.assertEqual(len(rr["rejected"]), 1, bad_key)
            self.assertIn("KEY", rr["rejected"][0]["reason"])
        # javascript: URL → 该条目 fail closed（进 rejected，不静默丢弃）
        r = Z.import_file(json.dumps([{"id": "OK1", "title": "t",
                                       "URL": "javascript:alert(1)"}]), "csl")
        self.assertEqual(len(r["candidates"]), 0)
        self.assertIn("UNSAFE_URL_SCHEME", r["rejected"][0]["reason"])
        # http(s) 正常通过
        r_ok = Z.import_file(json.dumps([{"id": "OK3", "title": "t",
                                          "URL": "https://example.org/x"}]), "csl")
        self.assertEqual(r_ok["candidates"][0]["url"], "https://example.org/x")
        # 超大导入
        with self.assertRaises(Z.ImportError_):
            Z.import_file("[" + ",".join(["{}"] * (Z.MAX_ITEMS + 5)) + "]", "csl")
        # XML（Billion Laughs 类）不支持 → 显式拒绝
        with self.assertRaises(Z.ImportError_) as cm:
            Z.import_file("<!DOCTYPE x [<!ENTITY a 'b'>]><x/>", "rdf")
        self.assertIn("UNSUPPORTED_FORMAT", str(cm.exception))
        # 畸形 UTF-8 → 容错而非崩溃
        raw = b'[{"id":"U1","title":"caf\xe9"}]'
        out = Z.import_file(raw, "csl")
        self.assertEqual(len(out["candidates"]), 1)
        # DOI/ISBN 结构验证（不联网、不补全）
        self.assertIsNone(M.valid_doi(None))
        with self.assertRaises(ValueError):
            M.valid_doi("not-a-doi")
        # 用**标准示例** ISBN（ISO 手册的例子），而不是给真实著作编造标识
        self.assertEqual(M.valid_isbn("978-0-306-40615-7"), "9780306406157")
        self.assertEqual(M.valid_isbn("0-306-40615-2"), "0306406152")
        with self.assertRaises(ValueError):
            M.valid_isbn("9780306406158")
        # HTML 注入净化
        r2 = Z.import_file(json.dumps([{"id": "OK2",
                                        "title": "<img src=x onerror=alert(1)>"}]),
                           "csl")
        self.assertNotIn("<img", r2["candidates"][0]["title"] or "")

    def test_phase5c_zotero_export(self):
        c = Z.import_file(CSL, "csl-json")["candidates"][0]
        csl = Z.export_csl_json(c)
        self.assertEqual(csl["title"], "Test Volume")
        self.assertEqual(csl["publisher"], "Test Press")
        self.assertIn("issued", csl)
        # 部分条目：bibtex 必须拒绝而不是填空
        partial = dict(c); partial["publisher"] = None
        with self.assertRaises(ValueError):
            Z.export_bibtex(R.get("bib.witness.staferla"))
        # 导出的 CSL 不得含占位值
        self.assertNotIn("Unknown", json.dumps(csl, ensure_ascii=False))

if __name__ == "__main__":
    unittest.main(verbosity=2)
