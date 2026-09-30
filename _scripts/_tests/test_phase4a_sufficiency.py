#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4a_sufficiency.py — Phase 4A §7–§10：Evidence Sufficiency 引擎的边界

这一套钉的是**判断规则本身**，所以大部分用例直接构造 payload，
不依赖语料当前状态（语料会变，规则不该跟着漂）。

重点（都是实测踩过的坑）
────────────────────────
* **禁止 cosine 阈值**：method 固定、signals 里不得有相似度分数（§7）
* **一致性信号必须按「独立检索族」判适用性**：只跑词法族时不能因为
  「没有第二个分量」而把状态降级 —— 那等于用「我们没跑向量」指控证据不足，
  与 Phase 3C「向量是辅助、不得强制启用」的结论直接冲突
* **session 多样性按请求范围判定**：法语 Staferla 语料没有课次级 id，
  单个研讨班的段共用一个 session —— 那是溯源粒度，不是证据单薄
* ENTITY_COLLISION → CONFLICTING_EVIDENCE（不是「不足」而是「无法归属」）
* SOURCE_TRACE_INCOMPLETE **不降级但必须报告**
* 实体型操作没有解析出实体 → INSUFFICIENT_EVIDENCE
* 输出**不得**是 0–1 confidence（§7）
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
MCP = os.path.join(VAULT, "_scripts", "_tools", "lacan_mcp")
sys.path.insert(0, MCP)

import evidence_sufficiency as es  # noqa: E402


def ev(pid, session="s1", seminar="seminar.S11", period="1964", comps=("lexical",),
       authority="L1", trace="COMPLETE", lang="fr"):
    return {"passage_id": pid, "session_id": session, "seminar_id": seminar,
            "period": period, "language": lang, "authority_level": authority,
            "trace_status": trace,
            "component_contribution": {c: 1 for c in comps}}


def payload(evidence, counts=None, entities=None, warnings=None, request=None,
            collisions=None, gaps=None, unresolved=None):
    return {
        "evidence": evidence,
        "resolution": {"entities": entities if entities is not None
                       else [{"entity_id": "concept.x", "required": True}],
                       "collisions": collisions or [],
                       "ontology_gaps": gaps or [],
                       "unresolved_terms": unresolved or []},
        "retrieval": {"component_counts": counts if counts is not None
                      else {"lexical": len(evidence)}},
        "coverage": {}, "provenance": {},
        "warnings": warnings or [],
        "request": request or {},
    }


class TestSufficiency(unittest.TestCase):

    def test_01_no_cosine_threshold_anywhere(self):
        r = es.evaluate(payload([ev("p1"), ev("p2", session="s2")]))
        self.assertEqual(r["method"], "structural_only_no_cosine_threshold")
        self.assertIn("cosine", r["prohibited"].lower())
        for k, v in r["signals"].items():
            self.assertNotIn("cosine", k)
            self.assertNotIn("similarity", k)
            if isinstance(v, float):
                self.assertIn(k, ("component_agreement", "provenance_completeness",
                                  "duplicate_concentration",
                                  "resolved_entity_coverage"))
        self.assertNotIn("confidence", r)

    def test_02_four_states_are_reachable(self):
        seen = set()
        seen.add(es.evaluate(payload([]))["state"])
        seen.add(es.evaluate(payload([ev("p1", comps=("lexical", "vector")),
                                      ev("p2", session="s2",
                                         comps=("lexical", "vector"))],
                                     counts={"lexical": 2, "vector": 2,
                                             "exact": 2}))["state"])
        seen.add(es.evaluate(payload([ev("p1")],
                                     collisions=[{"code": "ENTITY_COLLISION"}]))["state"])
        seen.add(es.evaluate(payload([ev("p1")], entities=[],
                                     request={"expect_entity": True}))["state"])
        # 有证据、但两族互不重合 → PARTIALLY
        seen.add(es.evaluate(payload([ev("p1", session="s1"),
                                      ev("p2", session="s2")],
                                     counts={"lexical": 2, "vector": 2}))["state"])
        self.assertEqual(seen, {"SUPPORTED", "PARTIALLY_SUPPORTED",
                                "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"})

    def test_03_single_family_agreement_not_applicable(self):
        # 只跑词法族：一致性信号必须 N/A，且**不因此降级**
        r = es.evaluate(payload([ev("p1"), ev("p2", session="s2")],
                                counts={"exact": 2, "lexical": 3}))
        self.assertEqual(r["state"], "SUPPORTED")
        self.assertIsNone(r["signals"]["component_agreement"])
        self.assertFalse(r["signals"]["component_agreement_applicable"])
        self.assertEqual(r["signals"]["independent_families_executed"], ["lexical"])
        self.assertEqual(r["state"], "SUPPORTED")
        self.assertTrue(any("不适用" in n for n in r["notes"]))

    def test_04_two_families_low_agreement_downgrades(self):
        r = es.evaluate(payload([ev("p1", session="s1", comps=("lexical",)),
                                 ev("p2", session="s2", comps=("lexical",)),
                                 ev("p3", session="s3", comps=("lexical",)),
                                 ev("p4", session="s4", comps=("lexical",))],
                                counts={"lexical": 4, "vector": 4}))
        self.assertEqual(r["signals"]["component_agreement"], 0.0)
        self.assertEqual(r["state"], "PARTIALLY_SUPPORTED")
        self.assertTrue(any("独立分量" in x for x in r["reasons"]))

    def test_05_exact_and_lexical_are_one_family(self):
        # exact + lexical 不是两个独立族（高度相关），不得据此判定一致性
        r = es.evaluate(payload([ev("p1"), ev("p2", session="s2")],
                                counts={"exact": 2, "lexical": 2}))
        self.assertEqual(r["signals"]["independent_families_executed"], ["lexical"])
        self.assertIsNone(r["signals"]["component_agreement"])

    def test_06_collision_is_conflicting_not_insufficient(self):
        r = es.evaluate(payload([ev("p1")], collisions=[{"code": "ENTITY_COLLISION",
                                                         "message": "Autre/autre"}]))
        self.assertEqual(r["state"], "CONFLICTING_EVIDENCE")
        self.assertTrue(any("无法归属" in x for x in r["reasons"]))

    def test_07_collision_without_evidence_is_not_conflicting(self):
        # 没有证据时，「碰撞」不成立为冲突证据 —— 仍是证据不足
        r = es.evaluate(payload([], collisions=[{"code": "ENTITY_COLLISION"}]))
        self.assertEqual(r["state"], "INSUFFICIENT_EVIDENCE")

    def test_08_source_trace_incomplete_never_downgrades_but_is_reported(self):
        r = es.evaluate(payload([ev("p1", trace="SOURCE_TRACE_INCOMPLETE",
                                    comps=("lexical", "vector")),
                                 ev("p2", session="s2", trace="SOURCE_TRACE_INCOMPLETE",
                                    comps=("lexical", "vector"))],
                                counts={"lexical": 2, "vector": 2, "exact": 2}))
        self.assertEqual(r["state"], "SUPPORTED")
        self.assertEqual(r["signals"]["source_trace_incomplete_n"], 2)
        self.assertTrue(any("SOURCE_TRACE_INCOMPLETE" in x for x in r["reasons"]))

    def test_09_entity_seeking_without_entity_is_insufficient(self):
        r = es.evaluate(payload([ev("p1")], entities=[],
                                request={"expect_entity": True}))
        self.assertEqual(r["state"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(any("实体" in x for x in r["reasons"]))

    def test_10_scoped_request_relaxes_session_diversity(self):
        # 请求限定 seminar：法语语料单研讨班只有一个 session —— 不得据此降级
        p = payload([ev("p1", session="session.S07.unknown", seminar="seminar.S07",
                        comps=("lexical", "terminology_bridge")),
                     ev("p2", session="session.S07.unknown", seminar="seminar.S07",
                        comps=("lexical", "terminology_bridge")),
                     ev("p3", session="session.S07.unknown", seminar="seminar.S07",
                        comps=("lexical", "terminology_bridge"))],
                    counts={"lexical": 3, "terminology_bridge": 1, "exact": 3},
                    request={"seminar": "seminar.S07"})
        r = es.evaluate(p)
        self.assertTrue(r["signals"]["request_scoped"])
        self.assertEqual(r["state"], "SUPPORTED")
        self.assertTrue(any("限定了范围" in n for n in r["notes"]))

    def test_11_unscoped_request_still_requires_diversity(self):
        p = payload([ev("p1", session="s1"), ev("p2", session="s1")],
                    counts={"lexical": 2, "vector": 2, "exact": 2}, request={})
        r = es.evaluate(p)
        self.assertFalse(r["signals"]["request_scoped"])
        self.assertEqual(r["state"], "PARTIALLY_SUPPORTED")
        self.assertTrue(any("session" in x for x in r["reasons"]))

    def test_12_duplicate_concentration_is_reported(self):
        p = payload([ev("p%d" % i, session="s1") for i in range(10)],
                    counts={"lexical": 10, "vector": 10, "exact": 10})
        r = es.evaluate(p)
        self.assertEqual(r["signals"]["duplicate_concentration"], 1.0)

    def test_13_ontology_gap_does_not_downgrade_but_is_reported(self):
        p = payload([ev("p1", comps=("lexical", "vector")),
                     ev("p2", session="s2", comps=("lexical", "vector"))],
                    counts={"lexical": 2, "vector": 2, "exact": 2},
                    gaps=[{"code": "COUNTERPART_ENTITY_MISSING"}])
        r = es.evaluate(p)
        self.assertEqual(r["state"], "SUPPORTED")
        self.assertTrue(r["signals"]["ontology_gap"])
        self.assertTrue(any("ontology gap" in x for x in r["reasons"]))

    def test_14_constraint_violation_downgrades(self):
        p = payload([ev("p1", session="s1", comps=("lexical", "vector")),
                     ev("p2", session="s2", comps=("lexical", "vector"))],
                    counts={"lexical": 2, "vector": 2, "exact": 2},
                    request={"seminar": "seminar.S20"})
        r = es.evaluate(p)
        self.assertEqual(r["state"], "PARTIALLY_SUPPORTED")
        self.assertTrue(any("约束未被满足" in x for x in r["reasons"]))

    def test_15_all_required_signals_are_present(self):
        """§8 列出的 14 类信号必须**逐个**存在（用真实键，不靠叙述）。

        说明两处命名映射（引擎键名比 spec 的说法更具体，但语义一一对应）：
        * `primary_vs_secondary` → `has_primary_evidence` + `authority_levels`
        * `passage_count`        → `passage_count`
        """
        r = es.evaluate(payload([ev("p1", comps=("lexical", "vector")),
                                 ev("p2", session="s2", comps=("lexical", "vector"))],
                                counts={"lexical": 2, "vector": 2, "exact": 2},
                                request={"seminar": "seminar.S11"}))
        sig = r["signals"]
        required = {
            "resolved_entity_coverage": "resolved_entity_coverage",
            "required_entity_missing": "required_entity_missing",
            "passage_count": "passage_count",
            "distinct_session_count": "distinct_session_count",
            "distinct_seminar_count": "distinct_seminar_count",
            "distinct_period_count": "distinct_period_count",
            "exact_lexical_support": "exact_lexical_support",
            "terminology_bridge_support": "terminology_bridge_support",
            "provenance_completeness": "provenance_completeness",
            "primary_vs_secondary": "has_primary_evidence",
            "duplicate_concentration": "duplicate_concentration",
            "contradictory_evidence": "contradictory_evidence",
            "ontology_gap": "ontology_gap",
            "entity_collision": "entity_collision",
            "constraint_satisfaction": "constraint_satisfaction",
        }
        self.assertGreaterEqual(len(required), 14, "§8 要求至少 14 类信号")
        for spec_name, key in required.items():
            self.assertIn(key, sig, "§8 信号 %s 缺失（键 %s）" % (spec_name, key))
        # primary_vs_secondary 需要**两个**件：层级分布 + 是否有 primary
        self.assertIn("authority_levels", sig)
        self.assertIsInstance(sig["authority_levels"], dict)
        # 额外信号（本相位为修正判据而加）也必须可见
        for extra in ("component_agreement_applicable",
                      "independent_families_executed", "request_scoped",
                      "source_trace_incomplete_n"):
            self.assertIn(extra, sig)

    def test_16_signals_and_reasons_are_structured_not_prose_only(self):
        r = es.evaluate(payload([ev("p1", comps=("lexical", "vector")),
                                 ev("p2", session="s2",
                                    comps=("lexical", "vector"))],
                                counts={"lexical": 2, "vector": 2, "exact": 2}))
        self.assertIsInstance(r["signals"], dict)
        self.assertIsInstance(r["reasons"], list)
        self.assertIsInstance(r["notes"], list)
        # 判「是否支持本次研究操作」，不判理论对错
        self.assertIn("研究操作", r["scope_note"])
        self.assertIn("不判断", r["scope_note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
