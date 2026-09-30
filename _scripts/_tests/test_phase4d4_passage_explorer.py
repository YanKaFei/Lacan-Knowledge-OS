#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §9–§13/§39/§55/§56/§58-B：Passage Explorer（浏览 ≠ 研究检索）"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L


class PassageExplorer(unittest.TestCase):
    def test_00_case_b_gaze_to_s11_passage(self):
        """§58 Case B：从 gaze 进入 S11 P2253 并看到原文 + provenance。"""
        d = L.X.passage_detail(L.P_L1)
        self.assertEqual(d["passage"]["passage_id"], L.P_L1)
        self.assertTrue(d["passage"]["text"])
        self.assertEqual(d["passage"]["source_layer"], "L1")
        self.assertEqual(d["passage"]["provenance_status"], "COMPLETE")
        self.assertTrue(d["trace"]["chain"])
        # gaze 是 ontology 里的概念，且其 evidence 含 S11 段落（原样给出，不做推断）
        g = L.B.get_concept_view(L.C_GAZE)
        self.assertEqual(g["header"]["preferred_label"], "gaze")

    def test_01_exhaustive_filters_match_full_corpus_truth(self):
        """§39/§40：browse 的筛选是全库 SQL 过滤（exhaustive），不是 top_k 后置过滤。"""
        for f, where, args in (
                ({"seminar": "S11", "language": "fr", "source_layer": "L1"},
                 "where seminar_id=? and language=? and authority_level=?",
                 ("seminar.S11", "fr", "L1")),
                ({"provenance": "SOURCE_TRACE_INCOMPLETE", "language": "zh"},
                 "where trace_status=? and language=?",
                 ("SOURCE_TRACE_INCOMPLETE", "zh")),
                ({"seminar": "S05", "text_role": "translation"},
                 "where seminar_id=? and text_role=?", ("seminar.S05", "translation"))):
            out = L.B.browse_passages(dict(f, limit=5))
            self.assertEqual(out["page"]["total"], len(L.raw_ids(where, args)), f)
            self.assertTrue(out["page"]["exhaustive"])
            self.assertIn("full corpus", out["page"]["filter_mode"])

    def test_02_source_layer_filter_is_all_or_nothing(self):
        """§55：某层无结果就显示 0，不得偷偷 fallback 到别层。"""
        out = L.B.browse_passages({"seminar": "S01", "source_layer": "L3", "limit": 5})
        self.assertEqual(out["items"], [])
        self.assertEqual(out["page"]["total"], 0)
        out2 = L.X.passage_search({"seminar": "S01", "source_layer": "L3"})
        self.assertTrue(out2["zero_note"])

    def test_03_provenance_filter(self):
        """§56：provenance 过滤对学术研究有价值，必须真的可用。"""
        inc = L.B.browse_passages({"provenance": "SOURCE_TRACE_INCOMPLETE", "limit": 5})
        ok = L.B.browse_passages({"provenance": "COMPLETE", "limit": 5})
        self.assertTrue(inc["items"] and ok["items"])
        for it in inc["items"]:
            self.assertEqual(it["provenance_status"], "SOURCE_TRACE_INCOMPLETE")
        for it in ok["items"]:
            self.assertEqual(it["provenance_status"], "COMPLETE")

    def test_04_result_rows_carry_required_fields(self):
        """§11：每条结果至少给 id / snippet / seminar / session / year / language /
        source layer / provenance。"""
        out = L.B.browse_passages({"seminar": "S11", "limit": 3})
        self.assertTrue(out["items"])
        for it in out["items"]:
            for k in ("passage_id", "snippet", "seminar", "session", "language",
                      "source_layer", "provenance_status"):
                self.assertIn(k, it)
        # year 通过 seminar 元数据给出（结果行给 seminar，详情页给年份）
        sem = L.B.list_seminars(limit=50)["items"][0]
        self.assertIn("year_from", sem)

    def test_05_trace_incomplete_is_visible_at_list_level(self):
        """§11：SOURCE_TRACE_INCOMPLETE 在列表级就要有轻量提示。"""
        out = L.X.passage_search({"seminar": "S05", "language": "zh"})
        rows = [i for i in out["items"] if i["provenance_status"] == "SOURCE_TRACE_INCOMPLETE"]
        self.assertTrue(rows)
        html = L.X.passage_detail(L.P_L2)
        self.assertTrue(html["trace_incomplete_note"])
        self.assertIn("SOURCE_TRACE_INCOMPLETE", str(html["trace"]["trace_status"]))

    def test_06_unknown_id_is_not_found_not_invented(self):
        self.assertIsNone(L.B.get_passage_view("passage.S99.unknown.P9999"))
        self.assertIsNone(L.X.passage_detail("passage.S99.unknown.P9999"))

    def test_07_no_full_corpus_payload(self):
        """§38：绝不允许一次返回全量（limit 有硬上限）。"""
        out = L.B.browse_passages({"limit": 100000})
        self.assertLessEqual(len(out["items"]), L.B.passages.MAX_LIMIT)
        self.assertEqual(out["page"]["limit"], L.B.passages.MAX_LIMIT)

    def test_08_dense_banner_present_when_dense_unavailable(self):
        out = L.X.passage_search({"seminar": "S11"})
        a = L.X.availability()
        if not a["dense_available"]:
            self.assertTrue(out["dense_banner"])
            self.assertIn("lexical retrieval active", out["dense_banner"].lower())
        else:
            self.assertIsNone(out["dense_banner"])

    def test_09_browse_label_distinguishes_research(self):
        out = L.X.passage_search({"seminar": "S11"})
        self.assertIn("NOT research retrieval", out["label"])
