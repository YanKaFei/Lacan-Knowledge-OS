#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase5b_entity_registry.py — Phase 5B §28–§31：登记表与 no-inference 铁律。"""
from __future__ import annotations
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
if VAULT not in sys.path: sys.path.insert(0, VAULT)
import entity_browse_api as E

ENT = os.path.join(VAULT, "_data", "entities")
def jd(n):
    with open(os.path.join(ENT, n), encoding="utf-8") as f: return json.load(f)

class Registry(unittest.TestCase):
    def test_00_no_automatic_ner_promotion(self):
        m = jd("registry_manifest.json")
        self.assertTrue(m["no_automatic_ner_promotion"])
        self.assertEqual(m["method"], "DETERMINISTIC_ALIAS_MATCH")
        # reviewed 必须达到阈值；candidate 不得混入 reviewed
        thr = m["min_mentions_threshold"]
        for doc in ("person_registry.json", "case_registry.json"):
            d = jd(doc)
            for r in d["reviewed"]:
                self.assertGreaterEqual(r["mention_count"], thr, r["id"])
                self.assertEqual(r["review_status"], "reviewed")
            for c in d["candidates_not_promoted"]:
                self.assertEqual(c["review_status"], "candidate_insufficient_evidence")

    def test_01_reviewed_entities_have_provenance(self):
        for doc in ("person_registry.json", "case_registry.json"):
            for r in jd(doc)["reviewed"]:
                self.assertTrue(r.get("provenance"), r["id"])
                self.assertTrue(r.get("mention_sample_passage_ids"), r["id"])

    def test_02_person_and_case_are_distinct_namespaces(self):
        p = {r["id"] for r in jd("person_registry.json")["reviewed"]}
        c = {r["id"] for r in jd("case_registry.json")["reviewed"]}
        self.assertFalse(p & c, "Person/Case 命名空间不得交叉")

    def test_03_schreber_separation(self):
        sp = E.get_person("person.schreber"); sc = E.get_case("case.schreber")
        self.assertNotEqual(sp["id"], sc["id"])
        self.assertEqual(sp["kind"], "person"); self.assertEqual(sc["kind"], "case")
        self.assertEqual(sc["subject_person"], "person.schreber")
        self.assertTrue(sc["subject_person_link"]["evidence_passage_ids"])
        self.assertTrue(sc["person_case_are_distinct_entities"])

    def test_04_mention_never_asserts_influence_or_analysis(self):
        for doc in ("person_registry.json", "case_registry.json"):
            for r in jd(doc)["reviewed"]:
                self.assertEqual(r["evidence_kind"], "MENTION_ONLY")
                self.assertFalse(r["asserts_influence"])
                self.assertFalse(r["asserts_theoretical_relation"])
                self.assertFalse(r["asserts_case_analysis"])

    def test_05_inference_endpoints_are_forbidden_not_missing(self):
        for op in ("influence", "relations", "case_analysis", "collapse", "synonym",
                   "theoretical_relation"):
            with self.assertRaises(E.InferenceNotSupported):
                E.guarded(op)
        with self.assertRaises(E.InferenceNotSupported):
            E.get_person("case.schreber")
        with self.assertRaises(E.InferenceNotSupported):
            E.get_case("person.schreber")

    def test_06_mention_index_rows_carry_no_inference(self):
        n = 0
        with open(os.path.join(ENT, "mention_index.jsonl"), encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                r = json.loads(line); n += 1
                self.assertFalse(r["asserts_influence"])
                self.assertFalse(r["asserts_theoretical_relation"])
                self.assertFalse(r["asserts_case_analysis"])
                self.assertTrue(r["passage_id"].startswith("passage."))
                if n >= 500: break
        self.assertGreater(n, 0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
