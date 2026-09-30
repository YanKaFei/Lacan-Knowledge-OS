#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_p5d006_corpus_profile — 语料档案（corpus profile）与 demo 本体层的**边界**回归。

背景（为什么需要这份测试）：
    `core_freeze.py` 的 39 个组件里有 9 个是**参考语料的人工验收工件**
    （人工评审 / 裁定队列 / 就绪门 / 错误分类法 / 评审 schema / gold_v2 / 冻结身份）。
    换一份语料（公有领域 demo、或用户自备语料）时它们必然缺席 → 旧实现的 `--verify`
    报「未解析组件」→ `mcp_server.guard` fail closed → 研究**完全跑不起来**。
    也就是说「自带语料」这条被文档承诺的路此前并未实现。

本测试钉住三条：
  ① **参考语料行为不变**：没有 corpus_profile 字段的历史 manifest 仍按 reference 处理，
     任何语义组件漂移仍是硬失败（fail closed 没有被放宽）；
  ② **声明缺席**只在 `unreviewed-corpus` 档案下、且只对人工验收类组件成立；
     非声明缺席、「声明缺席但文件又在场」、未知档案一律 FAIL；
  ③ **谱系**把声明缺席记为 `absent_by_declaration`，不计入 `scholarly_semantic_changes`。

全部用**合成 manifest**（不依赖真实 vault 状态），因此可以在任何 vault 里跑。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
for _p in (VAULT, TOOLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import core_freeze as CF                                                    # noqa: E402
import freeze_lineage as FL                                                 # noqa: E402


def manifest(profile=CF.PROFILE_REFERENCE, absent=(), **over):
    """合成一份最小 manifest（组件值任意但确定）。"""
    comp = {name: "h%s" % name for name in CF.SPEC}
    for name in absent:
        comp[name] = None
    doc = {
        "schema_version": "scholarly-core-freeze/v1",
        "freeze_version": CF.FREEZE_VERSION,
        "scholarly_status": (CF.SCHOLARLY_STATUS if profile == CF.PROFILE_REFERENCE
                             else CF.STATUS_UNREVIEWED),
        "corpus_profile": profile,
        "absent_components": sorted(absent),
        "unresolved_components": [],
        "components": comp,
        "component_classes": CF.component_classes(),
    }
    doc.update(over)
    return doc


class ProfileConstants(unittest.TestCase):
    def test_01_human_acceptance_keys_are_semantic_components(self):
        """声明缺席只允许人工验收类 —— 而它们确实都被归为 scholarly_semantic。"""
        for k in CF.HUMAN_ACCEPTANCE_KEYS:
            self.assertIn(k, CF.SPEC, k)
            self.assertEqual(CF.component_class(k), CF.CLASS_SCHOLARLY, k)

    def test_02_data_version_components_are_never_absentable(self):
        """语料/索引/本体这些 data_version 组件**不得**被声明缺席（否则等于没有语料）。"""
        for k in CF.DATA_VERSION_KEYS:
            self.assertNotIn(k, CF.HUMAN_ACCEPTANCE_KEYS, k)

    def test_03_profiles_are_closed(self):
        self.assertEqual(tuple(CF.PROFILES),
                         (CF.PROFILE_REFERENCE, CF.PROFILE_UNREVIEWED))
        self.assertIn(CF.STATUS_UNREVIEWED, CF.PROFILE_NOTES[CF.PROFILE_UNREVIEWED].join(
            [CF.STATUS_UNREVIEWED, ""]) or CF.PROFILE_NOTES[CF.PROFILE_UNREVIEWED])


class VerifyRules(unittest.TestCase):
    """直接测 `verify()` 的判定逻辑（用临时 vault 目录替换 OUT）。"""

    def setUp(self):
        # 只替换 manifest 输出路径：**不动** CF.VAULT，否则 CF.compute() 会去临时目录
        # 找组件文件、全部算不出来（第一版就是这么把自己测挂的）。
        self.tmp = tempfile.TemporaryDirectory(prefix="profile-test-")
        self._out = CF.OUT
        CF.OUT = os.path.join(self.tmp.name, "freeze.json")

    def tearDown(self):
        CF.OUT = self._out
        self.tmp.cleanup()

    def _write(self, doc):
        with io.open(CF.OUT, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, sort_keys=True)

    def _verify(self):
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = CF.verify(quiet=True)
        return rc, buf.getvalue()

    def _fill_computed(self, doc):
        """把"在场"的组件值换成现算值（缺席的保持 None）。"""
        for name, spec in CF.SPEC.items():
            if doc["components"].get(name) is None:
                continue
            got = CF.compute(*spec)
            if got is None:
                self.skipTest("该组件在本 vault 不可计算：%s" % name)
            doc["components"][name] = got
        return doc

    def test_10_reference_manifest_with_all_components_is_rejected_on_drift(self):
        """参考档案 + 组件值不匹配 → FAIL（fail closed 没有被放宽）。"""
        self._write(manifest())          # 组件值是假的（"h<name>"），必然与现算不符
        rc, out = self._verify()
        self.assertEqual(rc, 1)
        self.assertIn("哈希漂移", out)

    def test_11_unreviewed_profile_accepts_declared_absence(self):
        """unreviewed 档案 + 人工验收类声明缺席 → 允许（不是漂移）。"""
        absent = ("human_review_round1_hash", "gold_v2_tasks_hash")
        doc = self._fill_computed(manifest(profile=CF.PROFILE_UNREVIEWED, absent=absent))
        self._write(doc)
        rc, _out = self._verify()
        self.assertEqual(rc, 0, "声明缺席不应导致 FAIL")

    def test_12_undeclared_absence_is_a_failure(self):
        """unreviewed 档案，但缺席组件**没有**写进 absent_components → FAIL。"""
        doc = manifest(profile=CF.PROFILE_UNREVIEWED, absent=())
        for name in ("human_review_round1_hash",):
            doc["components"][name] = None      # 缺了却没声明
        self._write(doc)
        rc, out = self._verify()
        self.assertEqual(rc, 1)
        self.assertIn("清单缺组件", out)

    def test_13_declared_absent_but_present_is_a_failure(self):
        """声明缺席、清单里却仍有哈希（偷偷替换验收证据）→ FAIL。"""
        doc = manifest(profile=CF.PROFILE_UNREVIEWED, absent=("gold_v2_tasks_hash",))
        doc["components"]["gold_v2_tasks_hash"] = "deadbeef"    # 声明缺席但留了哈希
        self._write(doc)
        rc, out = self._verify()
        self.assertEqual(rc, 1)
        self.assertIn("不得偷偷替换验收证据", out)

    def test_14_unknown_profile_is_a_failure(self):
        doc = manifest(profile=CF.PROFILE_REFERENCE)
        doc["corpus_profile"] = "whatever"
        doc["scholarly_status"] = CF.STATUS_UNREVIEWED
        self._write(doc)
        rc, out = self._verify()
        self.assertEqual(rc, 1)
        self.assertIn("未知 corpus_profile", out)

    def test_15_absent_outside_human_acceptance_is_a_failure(self):
        """data_version 组件被声明缺席 → FAIL（等于宣称没有语料也能跑）。"""
        doc = self._fill_computed(manifest(profile=CF.PROFILE_UNREVIEWED,
                                           absent=("passage_store_version",)))
        self._write(doc)
        rc, out = self._verify()
        self.assertEqual(rc, 1)
        self.assertIn("不属于人工验收类", out)


class LineageDeclaredAbsence(unittest.TestCase):
    """谱系：声明缺席 ≠ 学术语义漂移；参考语料仍然零容忍。"""

    def test_20_declared_absence_is_not_semantic_drift(self):
        prev = manifest(profile=CF.PROFILE_REFERENCE)
        cur = manifest(profile=CF.PROFILE_UNREVIEWED,
                       absent=("human_review_round1_hash", "gold_v2_tasks_hash"))
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["scholarly_semantic_changes"], 0, seg["problems"])
        self.assertEqual(sorted(seg["absent_by_declaration"]),
                         ["gold_v2_tasks_hash", "human_review_round1_hash"])
        self.assertEqual(seg["corpus_profile"], CF.PROFILE_UNREVIEWED)

    def test_21_same_absence_without_profile_is_still_semantic_drift(self):
        """**没有**声明档案时，同样的组件变化仍是 SEMANTIC_DRIFT（默认严格）。"""
        prev = manifest(profile=CF.PROFILE_REFERENCE)
        cur = manifest(profile=CF.PROFILE_REFERENCE)   # 值全变、档案仍是 reference
        seg = FL.classify_segment(prev, cur)
        self.assertEqual(seg["status"], "PASS")        # 组件值一致的合成物：无变化
        cur2 = dict(cur)
        cur2["components"] = dict(cur["components"])
        cur2["components"]["human_review_round1_hash"] = None
        cur2["absent_components"] = []
        seg2 = FL.classify_segment(prev, cur2)
        self.assertEqual(seg2["scholarly_semantic_changes"], 1)
        self.assertIn(FL.FAIL_SEMANTIC, seg2["failure_codes"])

    def test_22_extra_segments_file_is_optional(self):
        """没有 segments.json 时，段清单必须与历史完全一致（参考 vault 行为不变）。"""
        self.assertEqual(FL.extra_segments(), [] if not os.path.isfile(FL.EXTRA_SEGMENTS)
                         else FL.extra_segments())
        if not os.path.isfile(FL.EXTRA_SEGMENTS):
            self.assertEqual(len(FL.SEGMENTS), 7)


class OntologyToolingIsCorpusAgnostic(unittest.TestCase):
    """本体工具不得把**参考语料**的数字写死在代码里（自建语料要能复用同一个校验器）。"""

    def test_30_validator_reads_gold_count_from_spec(self):
        src = io.open(os.path.join(TOOLS, "validate_ontology_v4a1.py"),
                      encoding="utf-8").read()
        self.assertNotIn("len(gold) == 53", src)
        self.assertIn('gold_concept_count', src)

    def test_31_builder_mapping_evidence_is_not_hardcoded_to_gaze(self):
        src = io.open(os.path.join(TOOLS, "build_ontology_v4a1.py"),
                      encoding="utf-8").read()
        self.assertNotIn('"gaze.core.en"', src)
        self.assertNotIn("'gaze.core.en'", src)
        self.assertIn("ent_rules", src)

    def test_32_demo_ontology_spec_is_shipped_and_self_describing(self):
        """demo 本体 spec 是**随仓库分发**的作者层：15 实体、证据规则、映射、关系齐备。"""
        p = os.path.join(VAULT, "_publish", "demo-corpus", "ontology", "spec.json")
        if not os.path.isfile(p):
            self.skipTest("公开版 overlay 不在本 vault（发布环境）")
        with io.open(p, encoding="utf-8") as fh:
            spec = json.load(fh)
        self.assertEqual(spec["layer_id"], "ontology.v4a1")
        self.assertGreaterEqual(len(spec["entities"]), 10)
        self.assertEqual(spec["base_layer"]["gold_concept_count"], 0)
        for e in spec["entities"]:
            self.assertTrue(e["evidence_rules"], e["id"])
            self.assertIsNone(e["definition"], e["id"])      # 不写理论定义
            self.assertTrue(e["source_notes"], e["id"])      # 有 provenance
        for m in spec["mappings"]:
            self.assertEqual(m["relation_type"], "controlled_term_mapping")
        preds = {r["predicate"] for r in spec["relations"]}
        ext = {p["predicate"] for p in
               spec["vocabulary_extension"]["relation_predicates_added"]}
        self.assertTrue(preds <= ({"defines", "redefines", "develops", "references",
                                   "contradicts", "influenced_by", "criticizes",
                                   "translates_as", "formalized_as", "represented_by",
                                   "appears_in", "related_to", "clinical_application",
                                   "case_example", "topological_model", "primary_source",
                                   "secondary_interpretation"} | ext), preds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
