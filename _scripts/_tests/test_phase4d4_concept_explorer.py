#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §5–§8/§45/§46/§58-A：Concept Explorer"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L


class ConceptExplorer(unittest.TestCase):
    def test_00_case_a_objet_a(self):
        """§58 Case A：concept.objet-petit-a 应能看到 aliases / relations / seminars / passages。"""
        d = L.X.concept_detail(L.C_OBJET_A)
        hd = d["header"]
        self.assertEqual(hd["concept_id"], L.C_OBJET_A)
        self.assertTrue(hd["preferred_label"])
        self.assertTrue(len(hd["aliases"]) >= 5, hd["aliases"])
        self.assertIn("ontology_status", hd)
        self.assertIn("relations", d)
        self.assertIn("seminar_distribution", d)
        self.assertIn("evidence", d)

    def test_01_list_supports_search_and_paging(self):
        allc = L.X.concept_list(limit=10)
        self.assertGreater(allc["total"], 40)
        self.assertLessEqual(len(allc["items"]), 10)
        hit = L.X.concept_list(query="objet")
        self.assertTrue(any(i["concept_id"] == L.C_OBJET_A for i in hit["items"]),
                        [i["concept_id"] for i in hit["items"]])
        # 别名也参与检索
        alias_hit = L.X.concept_list(query="客体小a")
        self.assertTrue(any(i["concept_id"] == L.C_OBJET_A for i in alias_hit["items"]))
        # 分页不重不漏
        p1 = L.X.concept_list(limit=10)
        p2 = L.X.concept_list(limit=10, cursor=p1["page"]["next_cursor"])
        a = {i["concept_id"] for i in p1["items"]}
        b = {i["concept_id"] for i in p2["items"]}
        self.assertEqual(a & b, set())

    def test_02_no_generated_definition_masquerading_as_canonical(self):
        """§7A：ontology 没写定义就必须显示 No canonical definition recorded."""
        v = L.B.get_concept_view(L.C_GAZE)          # ontology-only concept
        cr = v["canonical_reference"]
        if not cr["canonical_definition"]:
            self.assertEqual(cr["empty_note"], "No canonical definition recorded.")
            self.assertIsNone(cr["source_layer"])
        # 有定义时也必须能指出来自哪一层
        v2 = L.B.get_concept_view(L.C_OBJET_A)
        if v2["canonical_reference"]["canonical_definition"]:
            self.assertTrue(v2["canonical_reference"]["source_layer"])

    def test_03_relations_separate_reviewed_from_candidate(self):
        v = L.B.get_concept_view("concept.besoin")
        rel = v["relations"]
        self.assertEqual(rel["reviewed_n"] + rel["candidate_n"], len(rel["reviewed"]) + len(rel["candidate"]))
        for r in rel["candidate"]:
            self.assertNotEqual(r["status_bucket"], "reviewed")
        self.assertIn("canonical", v["relations"]["note"])

    def test_04_graph_draws_only_reviewed_edges(self):
        """§45/§46：图只用 reviewed 边；candidate 只能列出来、不能画进去。"""
        g = L.B.concept_graph("concept.besoin")
        self.assertEqual(len(g["edges"]), 0)
        self.assertTrue(g["empty_note"])
        self.assertTrue(g["candidate_edges_n"] >= 1)
        for e in g["candidate_edges"]:
            self.assertFalse(e["drawn"])
            self.assertIn("evidence", e)
        # 边必须可解释
        if g["edges"]:
            for e in g["edges"]:
                for k in ("predicate", "review_status", "ontology_source", "relation_id"):
                    self.assertIn(k, e)

    def test_05_distribution_is_corpus_count_not_importance(self):
        """§7D/§24：只能是 corpus occurrence，且不得出现 importance 评分字段。"""
        v = L.B.get_concept_view(L.C_OBJET_A)
        dist = v["seminar_distribution"]
        self.assertIn("corpus occurrence", dist["label"])
        self.assertIn("not theoretical importance", dist["label"])
        # 只有「段数」一种数值，没有评分/排名/百分比字段
        keys = set()
        for row in dist["seminars"]:
            keys |= set(row.keys())
        self.assertEqual(keys, {"seminar", "passages"})
        for bad in ("score", "rank", "percent", "weight"):
            self.assertNotIn(bad, keys)
        self.assertTrue(dist["seminars"])

    def test_06_diachronic_does_not_infer_evolution(self):
        """§7E：时间轴只显示语料出现，不自动推导演化结论。"""
        d = L.B.get_concept_view(L.C_OBJET_A)["diachronic"]
        self.assertIsNone(d["derived_conclusion"])
        self.assertIn("does not infer", d["note"])
        self.assertTrue(all("year" in p and "passages" in p for p in d["points"]))

    def test_07_research_actions_are_prefill_only(self):
        """§8：按钮只预填 ResearchRequest，不得自己写研究逻辑。"""
        d = L.X.concept_detail(L.C_OBJET_A)
        ids = {a["id"] for a in d["research_actions"]}
        self.assertTrue({"research", "compare", "diachronic", "translation"} <= ids)
        for a in d["research_actions"]:
            self.assertTrue(a["request"])
            self.assertNotIn("answer", a)

    def test_08_zero_result_wording(self):
        """§66：0 结果只表示当前 browse 条件下没有匹配段落。"""
        d = L.X.concept_detail(L.C_OBJET_A)
        self.assertIn("not 'Lacan does not have this concept'", d["note"])
