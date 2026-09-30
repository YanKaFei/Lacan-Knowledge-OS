#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4e_core_semantic_hashes.py — Phase 4E §17/§18/§19：语义漂移 = 0 的机器证据

断言（全部确定性、只读）：

1. 与 4D.2（RC1 之前的最后一段）相比，**4E 段的 manifest** 只有一个组件变化：
   `scholarly_api_core_hash`（产品边界）；
2. 所有**冻结学术语义**组件逐字节未变（prompt / judge / boundary / claim / entailment /
   repair / citation / source-role / abstention / Gate13/19/20/21 / Gold / human review /
   readiness gate / D2 frozen identity …）；
3. 4C.1-D2 真实 provider run 的 10 个 engine 文件与当前工作树**逐字节相同**
   （= CCR-0001 的修复是 reuse，不是重写已验证 engine）；
4. `phase4e_freeze_record.py --check` 通过（父/新 hash、语义影响评估一致）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
sys.path.insert(0, TOOLS)

FREEZE_DIR = os.path.join(VAULT, "_data", "core_freeze")
LIVE = os.path.join(FREEZE_DIR, "scholarly_core_freeze_v1.json")
PARENT = os.path.join(FREEZE_DIR, "history",
                      "scholarly_core_freeze_v1.4d2-workspace-registered.json")
# ★ Phase 5A 起 LIVE 不再等于 4E 段的字节（后续阶段会继续追加段）。
#   本套件的主体（只允许产品边界变化 / 语义漂移 = 0）讲的是 **4E 段**，
#   所以被测对象是 4E 段自己的 history 快照，而不是"当前 live"。
#   "live 必须与谱系末段一致" 由 test_05 单独断言（不放松）。
FOUR_E = os.path.join(FREEZE_DIR, "history",
                      "scholarly_core_freeze_v1.4e-ccr0001-remediation.json")

try:
    import core_freeze as _CF
    _CLASS_SEMANTIC = _CF.CLASS_SCHOLARLY
    DATA_VERSION_KEYS = tuple(_CF.DATA_VERSION_KEYS)

    def class_of(key, manifest=None):
        """组件类：manifest 声明优先，否则回落到 SPEC 分类。"""
        declared = ((manifest or {}).get("component_classes") or {}).get(key)
        return declared or _CF.component_class(key)
except Exception:                                                          # noqa: BLE001
    _CLASS_SEMANTIC = "scholarly_semantic"
    DATA_VERSION_KEYS = ("passage_store_version", "passage_store_passages_sha256",
                         "retrieval_index_lexical", "retrieval_index_vector",
                         "ontology_version", "corpus_inventory_hash")

    def class_of(key, manifest=None):
        if key in PRODUCT_BOUNDARY_KEYS or key in DATA_VERSION_KEYS:
            return "not_semantic"
        return _CLASS_SEMANTIC
RECORD = os.path.join(VAULT, "_data", "phase4e", "freeze_remediation.json")
D2_RUN = os.path.join(VAULT, "_data", "eval", "runs",
                      "4c1d2_llm_20260924T190203Z_50de1609")

PRODUCT_BOUNDARY_KEYS = ("scholarly_api_core_hash", "scholarly_api_objects_hash",
                         "scholarly_api_policy_hash")


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class TestCoreSemanticHashes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.live = load(LIVE)
        cls.four_e = load(FOUR_E)
        cls.parent = load(PARENT)
        cls.lc = cls.four_e["components"]          # 4E 段（被测对象）
        cls.pc = cls.parent["components"]

    def test_01_only_product_boundary_component_changed(self):
        changed = sorted(k for k in set(self.pc) | set(self.lc)
                         if self.pc.get(k) != self.lc.get(k))
        self.assertEqual(changed, ["scholarly_api_core_hash"],
                         "Phase 4E 只允许改产品边界的 provider/adapter wiring；"
                         "实际变化：%s" % changed)

    def test_02_frozen_semantic_components_unchanged(self):
        # 用 core_freeze 的组件类判定「学术语义」（data_version 与 product_boundary
        # 都不算语义）—— 不再用「非产品边界即语义」的旧二分（那正是 P5A-006 的根因）。
        drift = sorted(k for k in self.pc
                       if class_of(k, self.four_e) == _CLASS_SEMANTIC
                       and self.pc.get(k) != self.lc.get(k))
        self.assertEqual(drift, [], "冻结学术语义发生漂移：%s" % drift)
        # 逐条点名最关键的语义单元，避免「整表相等但漏看」的错觉
        for k in ("synthesis_prompt_hash", "judge_prompt_hash", "synthesis_boundary_hash",
                  "claim_atom_hash", "entailment_validator_hash", "repair_rules_hash",
                  "citation_policy_hash", "source_role_policy_hash",
                  "abstention_policy_hash", "gate13_hash", "gate19_hash", "gate20_hash",
                  "gate21_hash", "gold_v2_tasks_hash", "human_review_round1_hash",
                  "human_review_round2_hash", "scholarly_readiness_gate_hash",
                  "frozen_identity_hash"):
            self.assertEqual(self.pc.get(k), self.lc.get(k), "%s 漂移" % k)
        self.assertEqual(len(self.lc), 39)
        self.assertEqual(self.live.get("scholarly_status"), "SCHOLARLY_CORE_READY")

    def test_03_d2_validated_engine_is_byte_identical(self):
        """CCR-0001 是 wiring 缺陷，不是 engine 缺陷：D2 的 engine 必须原样复用。"""
        man = load(os.path.join(D2_RUN, "run_manifest.json"))
        drift = []
        for fn, h in sorted((man.get("engine_hashes") or {}).items()):
            p = os.path.join(VAULT, "_scripts", "_tools", fn)
            if not os.path.isfile(p) or sha_file(p) != h:
                drift.append(fn)
        self.assertEqual(drift, [], "D2 已验证 engine 被改动：%s" % drift)
        self.assertGreaterEqual(len(man.get("engine_hashes") or {}), 10)

    def test_04_freeze_remediation_record_is_consistent(self):
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "phase4e_freeze_record.py"), "--check"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = load(RECORD)
        self.assertEqual(rec["ccr"], "CCR-0001")
        self.assertFalse(rec["semantic_impact_assessment"]["scholarly_semantics_changed"])
        self.assertTrue(rec["semantic_impact_assessment"]["runtime_wiring_changed"])
        self.assertEqual([c["component"] for c in rec["changed_components"]],
                         ["scholarly_api_core_hash"])
        # 记录描述的是 **4E 段**，其 new_freeze 必须等于该段的真实字节
        self.assertEqual(rec["new_freeze"]["sha256"], sha_file(FOUR_E))
        # 且 live 必须与谱系末段一致（追加段不得让 4E 记录失真）
        lin = load(os.path.join(FREEZE_DIR, "freeze_lineage.json"))
        self.assertTrue(lin.get("live_matches_last_segment"))
        self.assertEqual(rec["parent_freeze"]["sha256"], sha_file(PARENT))

    def test_05_lineage_has_phase4e_segment_with_ccr(self):
        """4E 段必须存在且 ccr=CCR-0001、语义变化 0。

        ★ Phase 5A 起，末段不再必然是 4E（后续阶段会继续追加段）。
          这里改为**按 ccr 标签定位**该段 —— 断言强度不变（仍要求它存在、
          仍要求组件变化集合与语义变化数为 0），只是不再依赖"它在最后"这个
          与 4E 无关的位置假设。
        """
        lin = load(os.path.join(FREEZE_DIR, "freeze_lineage.json"))
        segs = lin.get("segments") or []
        self.assertTrue(lin.get("all_segments_semantic_changes_zero"))
        self.assertTrue(lin.get("live_matches_last_segment"))
        self.assertTrue(lin.get("all_segments_status_pass"),
                        "谱系存在未通过的段：%s" % lin.get("failure_codes"))
        e4 = [e for e in segs if e.get("ccr") == "CCR-0001"]
        self.assertTrue(e4, "谱系里找不到 ccr=CCR-0001 的 4E 段")
        self.assertEqual(e4[-1].get("phase"), "4E")
        self.assertEqual(e4[-1].get("changed_components"), ["scholarly_api_core_hash"])
        self.assertEqual(e4[-1].get("scholarly_semantic_changes"), 0)
        # 4E 段之后追加的段（5A）同样不得有语义变化
        after = segs[segs.index(e4[-1]) + 1:]
        for e in after:
            self.assertEqual(e.get("scholarly_semantic_changes"), 0,
                             "4E 之后的段 %s 出现语义变化" % e.get("manifest"))
            self.assertEqual(e.get("status"), "PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
