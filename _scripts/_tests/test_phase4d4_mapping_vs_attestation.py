#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §33：Ontology 说有关系/映射 ≠ 语料有 attestation"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L


class MappingVsAttestation(unittest.TestCase):
    def test_00_a_mapping_can_have_zero_corpus_attestation(self):
        """存在映射记录 ≠ 语料出现：必须能找到映射存在但 attestation 为 0 的形式。"""
        found = []
        for term in ("原乐", "enjoyment", "the gaze", "objet petit a"):
            d = L.B.get_term_view(term)
            if not d:
                continue
            for r in d["attestation"]["rows"]:
                if r["hits"] == 0 and r["mapping"]:
                    found.append((term, r["form"]))
        self.assertTrue(found, "未能构造『有映射但 0 语料出现』的实证样本")

    def test_01_view_labels_the_two_sources_differently(self):
        v = L.B.get_concept_view(L.C_OBJET_A)
        self.assertIn("corpus", v["attestation"]["source"])
        self.assertIn("NOT ontology evidence", v["attestation"]["label"])
        self.assertEqual(v["attestation"]["mode"],
                         "substring count over the full corpus (deterministic)")
        # 关系块来自 ontology，且标注了 review_status
        self.assertIn("canonical", v["relations"]["note"])

    def test_02_ontology_evidence_vs_corpus_count_can_differ(self):
        """§7C/§7D：ontology 记录的 evidence 数 与 语料计数 是两套数字。"""
        v = L.B.get_concept_view("concept.besoin")      # ontology 里有 evidence
        ev_n = v["evidence"]["ontology_evidence_n"]
        att = {r["form"]: r["hits"] for r in v["attestation"]["items"]}
        self.assertGreater(ev_n, 0)
        self.assertLessEqual(len(v["evidence"]["sample"]), 20)
        self.assertNotEqual(ev_n, att.get("besoin"),
                            "两种计数不应被混为一谈（否则说明有一边被复用）")

    def test_03_ui_uses_distinct_visual_labels(self):
        css = open(os.path.join(VAULT, "workspace_ui", "static", "styles", "main.css"),
                   encoding="utf-8").read()
        for cls in (".tag.is-ontology", ".tag.is-corpus", ".tag.is-catalog",
                    ".tag.is-reviewed", ".tag.is-candidate"):
            self.assertIn(cls, css, "缺少区分 ontology / corpus / candidate 的视觉标签")

    def test_04_candidate_is_never_presented_as_canonical(self):
        v = L.B.get_concept_view("concept.besoin")
        for c in v["relations"]["candidate"]:
            self.assertNotEqual(c["status_bucket"], "reviewed")
            self.assertEqual(c["review_status"], "candidate")
        self.assertTrue(v["relations"]["reviewed_n"] == 0)

    def test_05_terminology_control_endpoint(self):
        d = L.X.terminology_control()
        self.assertTrue(d["distinct_entities"])
        self.assertFalse(d["collapsed"])
