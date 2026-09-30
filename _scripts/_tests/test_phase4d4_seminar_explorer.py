#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §19–§26：Seminar Explorer（标题不伪造 / 形式识别 / 人物缺就说缺）"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L


class SeminarExplorer(unittest.TestCase):
    def test_00_list_has_required_columns(self):
        out = L.X.seminar_list()
        self.assertEqual(out["total"], 28)
        for it in out["items"]:
            for k in ("seminar_id", "title", "year_from", "sessions_n", "passages_n",
                      "languages"):
                self.assertIn(k, it)
            if it["title"] is None:
                self.assertTrue(it["title_missing"])
                self.assertEqual(it["note"], "No canonical title recorded.")
        self.assertIn("titles come from the canonical store", out["title_policy"])

    def test_01_detail_sections(self):
        d = L.X.seminar_detail(L.S_SEMINAR)
        m = d["metadata"]
        self.assertEqual(m["seminar_id"], "seminar.S11")
        self.assertEqual(m["title"], "精神分析的四个基本概念")
        self.assertEqual(m["roman"], "XI")
        self.assertTrue(d["sessions"])
        self.assertIn("concepts", d)
        self.assertIn("passages", d)
        self.assertIn("formalisms", d)
        self.assertIn("cases_persons", d)
        self.assertIn("saved_research", d)

    def test_02_session_counts_reconcile_with_corpus(self):
        d = L.X.seminar_detail(L.S_SEMINAR)
        total = sum(int(s.get("passage_count") or 0) for s in d["sessions"])
        real = len(L.raw_ids("where seminar_id=?", ("seminar.S11",)))
        self.assertEqual(total, real)

    def test_03_concept_counts_are_labelled_as_corpus_occurrence(self):
        """§24：概念计数必须标注 corpus occurrence，不是理论重要性。"""
        c = L.X.seminar_detail(L.S_SEMINAR)["concepts"]
        self.assertEqual(c["attestation"]["mode"], "corpus.form-attestation")
        self.assertIn("corpus occurrence", c["attestation"]["label"])
        self.assertIn("not theoretical importance", c["label"])

    def test_04_formalism_index_is_deterministic_and_evidence_based(self):
        """§25：只能来自真实语料文本的确定性模式识别，不得由模型生成。"""
        f = L.X.seminar_detail(L.S_SEMINAR)["formalisms"]
        self.assertEqual(f["method"], "deterministic regex count")
        self.assertFalse(f["is_canonical_metadata"])
        self.assertTrue(f["items"])
        for it in f["items"]:
            self.assertTrue(it["pattern"])
            self.assertGreater(it["passages"], 0)
            self.assertTrue(it["sample_passages"])
            self.assertEqual(it["detected_by"], "regex over corpus text")
        # 计数可复算
        top = f["items"][0]
        got = L.B.browse_passages({"seminar": "seminar.S11", "formalism": top["formalism"],
                                   "limit": 1})
        self.assertEqual(got["page"]["total"], top["passages"])

    def test_05_j_formalism_excludes_french_elision(self):
        """实测教训：宽松 `\\bJ\\b` 命中的全是 `J’ai`；收紧后才 95 条。"""
        import re
        con = L.LEX
        import sqlite3
        c = sqlite3.connect("file:%s?mode=ro" % con, uri=True)
        loose = c.execute("select count(*) from passage_meta where raw_text like '%J’ai%'").fetchone()[0]
        strict = L.B.formalism_counts(None)
        j = [x for x in strict["items"] if x["formalism"] == "J"]
        if j:
            self.assertLess(j[0]["passages"], loose,
                            "收窄后的 J 不应比法语省音出现次数还多")
        c.close()

    def test_06_cases_persons_absent_is_stated(self):
        """§26：没有 person/case 实体层就如实说明，不从文本里猜人名。"""
        cp = L.X.seminar_detail(L.S_SEMINAR)["cases_persons"]
        if not cp["available"]:
            self.assertIn("No person/case entity layer", cp["note"])

    def test_07_ask_about_seminar_is_prefill_only(self):
        r = L.X.research_requests()
        ids = {x["id"] for x in r["requests"]}
        self.assertIn("seminar", ids)
        sem = [x for x in r["requests"] if x["id"] == "seminar"][0]
        self.assertIn("seminar_specific", sem["mode"])
        self.assertIn("never executes research", r["note"])
