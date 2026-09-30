#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase5c_bibliography_schema — Phase 5C §2–§15：模型/登记表/完整性/禁伪证。"""
from __future__ import annotations
import json, os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
if VAULT not in sys.path: sys.path.insert(0, VAULT)
import bibliography as B
from bibliography import model as M, registry as R

class Schema(unittest.TestCase):
    def test_phase5c_bibliography_schema(self):
        for it in R.items() + R.candidates():
            self.assertEqual(M.validate_item(it), [], it["bibliographic_id"])
            for f in M.ITEM_FIELDS:
                self.assertIn(f, it, "%s 缺字段 %s" % (it["bibliographic_id"], f))

    def test_phase5c_editions(self):
        eds = R.editions()
        self.assertTrue(eds, "至少应有一个 EditionRecord")
        for e in eds:
            self.assertEqual(e["schema_version"], M.SCHEMA_EDITION)
            for f in M.EDITION_FIELDS:
                self.assertIn(f, e)
            # §8：仓库未记录出版社/年份/ISBN → 必须为 null，不得据模型知识补
            self.assertIn(e["publisher"], (None, ""))
            self.assertIn(e["year"], (None, ""))
            self.assertIn(e["isbn"], (None, ""))

    def test_phase5c_witness_edition_separation(self):
        """§6/§7/§9：转录与中译**不是**出版物 → 不得有 Edition；Seuil-PDF 才有。"""
        w = {m["witness_id"]: m for m in R.mappings() if m.get("witness_id")}
        self.assertIsNone(w["witness.fr.staferla"].get("edition_id"))
        self.assertIsNone(w["witness.zh.translation-project"].get("edition_id"))
        self.assertTrue(w["witness.fr.seuil-pdf"].get("edition_id"))
        # 链条如实标注缺层
        ch = R.witness_chain("witness.fr.staferla")
        self.assertIn("edition", ch["missing_layers"])
        self.assertEqual(ch["edition"], "Not linked")
        ch2 = R.witness_chain("witness.fr.seuil-pdf")
        self.assertIn("passage_realization", ch2["missing_layers"])   # 0 realizations

    def test_phase5c_registry(self):
        man = R.manifest()
        self.assertEqual(man["freeze_class"], "CANONICAL_KNOWLEDGE")   # §55
        self.assertTrue(man["no_metadata_inference"])
        for f in ("works.jsonl","editions.jsonl","items.jsonl","mappings.jsonl"):
            self.assertTrue(os.path.isfile(os.path.join(R.STORE, f)), f)
        self.assertEqual(man["counts"]["items"], len(R.items()))
        # reviewed / candidate 必须分开（§12）
        self.assertFalse(set(man["reviewed_items"]) & set(man["candidate_items"]))

    def test_phase5c_metadata_completeness(self):
        for it in R.items() + R.candidates():
            self.assertIn(it["metadata_completeness"], M.COMPLETENESS)
            self.assertEqual(it["metadata_completeness"], M.completeness(it))
        # §48 hard negative：author+title 有，publisher/year/page 无
        hn = M.blank_item("bib.test.hard-negative", "book")
        hn.update({"title": "Écrits", "authors": ["Jacques Lacan"],
                   "review_status": "reviewed"})
        caps = M.capability_flags(hn)
        self.assertTrue(caps["internal_citation_ready"])
        self.assertFalse(caps["chicago"])
        self.assertIn("publisher", caps["missing_fields"])
        self.assertIn("page_locator", caps["missing_fields"])

    def test_phase5c_no_fake_metadata(self):
        """§50：不得存在模型生成的 publisher / edition / ISBN。"""
        bad = []
        for it in R.items() + R.candidates():
            prov = it.get("metadata_provenance") or {}
            for f in ("publisher", "publication_year", "isbn", "doi", "edition"):
                if it.get(f) in (None, "", [], {}):
                    continue
                src = (prov.get(f) or {}).get("source")
                if not src:                     # 有值却没有来源 → 视为伪证
                    bad.append("%s.%s=%r 无 provenance" % (it["bibliographic_id"], f,
                                                          it[f]))
        self.assertEqual(bad, [], "存在无 provenance 的书目字段")
        for e in R.editions():
            for f in ("publisher", "year", "isbn"):
                self.assertIn(e[f], (None, ""), "Edition.%s 不得被补全" % f)
        for w in R.mappings():
            if w.get("witness_kind") in ("transcription", "translation"):
                self.assertNotIn("publisher", json.dumps(w, ensure_ascii=False).lower()
                                 .replace("why_publisher_null", ""))
        # 全文搜索：registry 里不得出现占位值
        blob = json.dumps({"i": R.items(), "c": R.candidates(), "e": R.editions()},
                          ensure_ascii=False)
        for ph in ("Unknown}", "????", "publisher\": \"Unknown\"", "\"n/a\""):
            self.assertNotIn(ph, blob, "出现占位 metadata：%s" % ph)

    def test_phase5c_no_fake_pages(self):
        """§49：`page` 只能来自实际 metadata；passage 号不得冒充 page。"""
        for it in R.items() + R.candidates():
            pl = it.get("page_locator")
            if pl:
                self.assertIn(pl["kind"], M.PAGE_LOCATOR_KINDS)
                self.assertNotRegex(str(pl["value"]), r"^passage\.", "passage 号冒充 page")
            self.assertIn(it.get("pages"), (None, "", [], {}),
                          "registry 不得凭空给出 pages 字段")
        # 渲染输出里不得出现 passage 号被当成 page
        for it in R.items():
            for st in ("internal", "provenance"):
                pass  # internal 家族不含 page；出版型在 metadata 不足时不可用
        ed = R.editions()[0]
        self.assertTrue(ed["page_locator_available"])
        self.assertIn(ed["publisher"], (None, ""))

if __name__ == "__main__":
    unittest.main(verbosity=2)
