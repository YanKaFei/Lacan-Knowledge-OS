#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase5a_lineage_classification.py — P5A-006 §13/§14：谱系三类变化判定

覆盖用户点名的六条 + 当前真实 fixture（语料 143 → 144）：

    test_lineage_semantic_change_fails
    test_lineage_declared_data_version_change_passes
    test_lineage_unknown_change_fails
    test_lineage_data_change_without_manifest_fails
    test_lineage_data_change_with_stale_index_fails
    test_lineage_product_runtime_change_classified
    test_real_corpus_143_144_fixture

纪律：本套件**只读**真实冻结工件；判定逻辑用纯函数 `classify_segment`
喂合成 manifest，绝不去改动 `_data/core_freeze/` 下的任何真实文件。
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (VAULT, os.path.join(VAULT, "_scripts", "_tools")):
    sys.path.insert(0, p)

import core_freeze as CF                                                    # noqa: E402
import freeze_lineage as FL                                                 # noqa: E402

HIST = os.path.join(VAULT, "_data", "core_freeze", "history")
PREV_5A = os.path.join(HIST, "scholarly_core_freeze_v1.5a-presentation-hardening.json")
NEW_5A = os.path.join(HIST, "scholarly_core_freeze_v1.5a-p6-data-version-separation.json")


def _manifest(overrides=None, decl=None):
    """一个极小的合成 manifest：三个类各一个组件。"""
    m = {
        "freeze_version": CF.FREEZE_VERSION,
        "scholarly_status": CF.SCHOLARLY_STATUS,
        "components": {
            "synthesis_prompt_hash": "S0",          # scholarly_semantic
            "scholarly_api_core_hash": "P0",        # product_boundary
            "corpus_inventory_hash": "D0",          # data_version
        },
        "component_classes": {
            "synthesis_prompt_hash": CF.CLASS_SCHOLARLY,
            "scholarly_api_core_hash": CF.CLASS_PRODUCT,
            "corpus_inventory_hash": CF.CLASS_DATA,
        },
        "data_version_declarations": [decl] if decl else [],
    }
    if overrides:
        m["components"].update(overrides)
    return m


def _decl(before="D0", after="D1", **kw):
    d = {
        "component": "corpus_inventory_hash",
        "before_hash": before, "after_hash": after,
        "reason": "外部语料目录新增 1 文件（测试用合成事实）",
        "source_diff": {"added": 1, "removed": 0, "modified": 0, "unchanged": 143},
        "ingestion_status": "SOURCE_INVENTORY_ONLY",
        "canonical_passage_store_changed": False,
        "dependent_artifacts": {
            "passage_store": "UNCHANGED_BY_DESIGN",
            "lexical_index": "UNCHANGED_BY_DESIGN",
            "vector_index": "UNCHANGED_BY_DESIGN",
            "graph_cache": "UNCHANGED_BY_DESIGN",
            "corpus_inventory": "CHANGED",
        },
        "verified_at": "2026-09-27T03:00:00+00:00",
        "scholarly_semantic_hashes_unchanged": True,
    }
    d.update(kw)
    return d


class TestLineageClassification(unittest.TestCase):

    # ── 情形 1：学术语义变化 → 硬失败
    def test_lineage_semantic_change_fails(self):
        prev = _manifest()
        cur = _manifest({"synthesis_prompt_hash": "S1"})
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["status"], "FAIL")
        self.assertIn(FL.FAIL_SEMANTIC, seg["failure_codes"])
        self.assertEqual(seg["scholarly_semantic_change_keys"], ["synthesis_prompt_hash"])
        self.assertEqual(seg["data_version_changes_n"], 0)

    # ── 情形 2：已声明且一致的数据版本变化 → PASS
    def test_lineage_declared_data_version_change_passes(self):
        prev = _manifest()
        cur = _manifest({"corpus_inventory_hash": "D1"}, decl=_decl())
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["failure_codes"], [])
        self.assertEqual(seg["status"], "PASS")
        self.assertEqual(seg["scholarly_semantic_changes"], 0)
        self.assertEqual(seg["data_version_changes_n"], 1)
        d = seg["data_version_changes"][0]
        self.assertTrue(d["declared"] and d["consistent"])
        for k in ("component", "before_hash", "after_hash", "reason", "source_diff",
                  "ingestion_status", "dependent_artifacts", "verified_at"):
            self.assertIn(k, d, "声明缺少 §12 要求的字段 %s" % k)

    # ── 情形 3：无法定位类的哈希变化 → UNCLASSIFIED_DRIFT
    def test_lineage_unknown_change_fails(self):
        prev = _manifest()
        cur = copy.deepcopy(prev)
        cur["components"]["brand_new_component_hash"] = "X1"
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["status"], "FAIL")
        self.assertIn(FL.FAIL_UNCLASSIFIED, seg["failure_codes"])
        self.assertEqual(seg["unclassified_changes"], ["brand_new_component_hash"])

    # ── §4：数据版本组件变化但**没有声明** → UNDECLARED_DATA_DRIFT
    def test_lineage_data_change_without_manifest_fails(self):
        prev = _manifest()
        cur = _manifest({"corpus_inventory_hash": "D1"})          # 无声明
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["status"], "FAIL")
        self.assertIn(FL.FAIL_UNDECLARED, seg["failure_codes"])
        self.assertFalse(seg["data_version_changes"][0]["declared"])
        self.assertFalse(seg["all_data_version_changes_declared_and_consistent"])

    # ── 情形 4：数据变化但依赖构件状态不一致（stale index）→ INCONSISTENT
    def test_lineage_data_change_with_stale_index_fails(self):
        """声明说 passage store 也变了，但冻结组件没动 → 自相矛盾（stale index 风险）。"""
        prev = _manifest()
        decl = _decl(dependent_artifacts={
            "passage_store": "CHANGED",                 # 声称动了
            "lexical_index": "UNCHANGED_BY_DESIGN",
            "vector_index": "UNCHANGED_BY_DESIGN",
            "graph_cache": "UNCHANGED_BY_DESIGN",
            "corpus_inventory": "CHANGED",
        }, canonical_passage_store_changed=True)
        cur = _manifest({"corpus_inventory_hash": "D1"}, decl=decl)
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["status"], "FAIL")
        self.assertIn(FL.FAIL_INCONSISTENT, seg["failure_codes"])
        detail = " ".join(p["detail"] for p in seg["problems"])
        self.assertIn("passage_store", detail)

        # 反向：声明 UNCHANGED_BY_DESIGN，但组件其实变了 → 同样 INCONSISTENT
        prev2 = _manifest()
        cur2 = copy.deepcopy(prev2)
        cur2["components"]["corpus_inventory_hash"] = "D1"
        cur2["components"]["passage_store_version"] = "PS1"     # 偷偷变了
        cur2["component_classes"]["passage_store_version"] = CF.CLASS_DATA
        cur2["data_version_declarations"] = [_decl()]
        seg2 = FL.classify_segment(prev2, cur2)
        self.assertEqual(seg2["status"], "FAIL")
        self.assertIn(FL.FAIL_INCONSISTENT, seg2["failure_codes"])

        # 声称 INGESTED 但 passage store 没动 → 不得宣称可检索
        cur3 = _manifest({"corpus_inventory_hash": "D1"},
                         decl=_decl(ingestion_status="INGESTED"))
        seg3 = FL.classify_segment(prev, cur3)
        self.assertEqual(seg3["status"], "FAIL")
        self.assertIn(FL.FAIL_INCONSISTENT, seg3["failure_codes"])

    # ── 产品边界变化 → 归类为 product_runtime_changes，**不失败**
    def test_lineage_product_runtime_change_classified(self):
        prev = _manifest()
        cur = _manifest({"scholarly_api_core_hash": "P1"})
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["failure_codes"], [])
        self.assertEqual(seg["status"], "PASS")
        self.assertEqual(seg["product_runtime_changes"], ["scholarly_api_core_hash"])
        self.assertEqual(seg["product_runtime_changes_n"], 1)
        self.assertEqual(seg["scholarly_semantic_changes"], 0)
        self.assertTrue(seg["runtime_wiring_changed"])        # 兼容旧字段

    # ── §14 真实 fixture：143 → 144
    def test_real_corpus_143_144_fixture(self):
        """当前真实 fixture：语料清单 143 → 144，必须 semantic=0 且 data_version>0。"""
        with open(PREV_5A, encoding="utf-8") as fh:
            prev = json.load(fh)
        with open(NEW_5A, encoding="utf-8") as fh:
            cur = json.load(fh)
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["status"], "PASS", seg.get("problems"))
        self.assertEqual(seg["scholarly_semantic_changes"], 0)
        self.assertEqual(seg["scholarly_semantic_change_keys"], [])
        self.assertGreater(seg["data_version_changes_n"], 0)
        self.assertEqual(seg["changed_components"], ["corpus_inventory_hash"])
        self.assertEqual(seg["unclassified_changes"], [])
        d = seg["data_version_changes"][0]
        self.assertTrue(d["declared"] and d["consistent"])
        self.assertEqual(d["before_hash"],
                         prev["components"]["corpus_inventory_hash"])
        self.assertEqual(d["after_hash"], cur["components"]["corpus_inventory_hash"])
        self.assertEqual(d["ingestion_status"], "SOURCE_INVENTORY_ONLY")
        self.assertFalse(d["canonical_passage_store_changed"])

    # ── 不允许 wildcard 豁免：任一 data_version 组件都要各自声明
    def test_lineage_no_wildcard_data_exemption(self):
        prev = _manifest()
        cur = copy.deepcopy(prev)
        cur["components"]["corpus_inventory_hash"] = "D1"
        cur["components"]["ontology_version"] = "O1"
        cur["component_classes"]["ontology_version"] = CF.CLASS_DATA
        cur["data_version_declarations"] = [_decl()]        # 只声明了 corpus
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["status"], "FAIL")
        self.assertIn(FL.FAIL_UNDECLARED, seg["failure_codes"])
        self.assertEqual(seg["data_version_changes_n"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
