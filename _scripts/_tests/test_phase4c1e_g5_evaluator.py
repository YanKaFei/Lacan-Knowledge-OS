#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1e_g5_evaluator.py — Phase 4C.1-E：G5 evaluator 语义纠正的回归测试

背景（evaluator implementation defect，**不是**规则变更）
────────────────────────────────────────────────────────
冻结的 Scholarly Readiness Gate v1 中 G5 的语义是：

    弃权题不因模型知识越界 → required violation count = 0

而 evaluator v1 的实现把 Round 2 error taxonomy 的
`ABSTENTION_FAILURE` **关键词命中频次** 直接当作 violation counter。taxonomy 的
冻结用途本身写明是 "issue-focus frequency / 非互斥 / diagnostic"，不是 pass/fail
classifier —— 因此「评论里**提到**弃权」被误判成「弃权完整性失败」。

本测试先钉住正确语义，再允许重算：
  * 肯定式 / 中性提及 → violation = false
  * 明确报告违反 → violation = true
  * 否定控制 → violation = false
  * G5 **不得**读取 taxonomy 频次，**不得**要求 scholarly_usable == NO
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))

import round2_review as R  # noqa: E402


def _row(task_id, usable, comment, citation="PARTIAL"):
    return {"task_id": task_id, "scholarly_usable": usable,
            "citation_support": citation,
            "reviewer_comment": {"raw": comment}, "requested_changes": []}


class AbstentionViolationDetector(unittest.TestCase):
    # ---- ① 肯定式 / 中性提及：不得计为 violation（§5 明确列出者）
    NON_VIOLATIONS = [
        "这一题执行了正确且有信息价值的学术弃权。",
        "这是一个高质量的 scholarly abstention。",
        "若仍拿不到 L1，则当前答案应继续维持为有根据的部分弃权。",
        "答案证据不足，因此弃权合理。",
        "它实际上没有完成历时比较，只完成了一个有根据的 abstention/limitation。",
        "最值得保留的是，这一版采取了非常干净的元数据型学术弃权。",
    ]

    # ---- ② 真正的 violation
    VIOLATIONS = [
        "本应弃权，但答案使用模型自身知识补写了结论。",
        "虽然标记 ABSTAINED，但正文包含 corpus 外事实。",
        "缺乏证据却仍然回答了具体事实。",
    ]

    # ---- ③ 否定控制
    NEGATION_CONTROLS = [
        "不存在弃权失败。",
        "没有发现模型知识越界。",
    ]

    def test_00_positive_mentions_are_not_violations(self):
        for text in self.NON_VIOLATIONS:
            self.assertEqual(R.abstention_violation_reports([_row("rt-X", "NO", text)]),
                             [], "肯定/中性提及被误判为 violation：%s" % text)

    def test_01_true_violations_detected(self):
        for text in self.VIOLATIONS:
            reps = R.abstention_violation_reports([_row("rt-X", "YES", text)])
            self.assertTrue(reps, "真正的违反未被识别：%s" % text)

    def test_02_negation_controls_not_violations(self):
        for text in self.NEGATION_CONTROLS:
            self.assertEqual(R.abstention_violation_reports([_row("rt-X", "YES", text)]),
                             [], "否定控制被误判：%s" % text)

    def test_03_detector_ignores_scholarly_usable(self):
        """G5 是 abstention integrity，不是 overall usability：同一句在两个 usable 下同判。"""
        text = "本应弃权，但答案使用模型自身知识补写了结论。"
        for usable in ("NO", "WITH_REVISION", "YES"):
            self.assertTrue(R.abstention_violation_reports([_row("rt-X", usable, text)]),
                            "usable=%s 时漏判" % usable)

    # ---- ④ 真实数据：0 份明确违反报告；原先被 v1 误命中的 4 题必须是非 violation
    def test_10_real_reviews_have_no_violation_report(self):
        if not os.path.isfile(R.DATASET):
            self.skipTest("尚无 Round 2 数据集")
        rows = [r for r in R.load_jsonl(R.DATASET) if r["review_status"] == "REVIEWED"]
        if not rows:
            self.skipTest("尚无已评审记录")
        self.assertEqual(R.abstention_violation_reports(rows), [],
                         "真实评论中出现弃权完整性违反报告（若有，G5 应真失败）")

    def test_11_v1_false_positives_are_non_violations(self):
        """v1 曾把 rt-C03 / rt-J01 / rt-J02 / rt-J03 的**提及**计为 ABSTENTION_FAILURE。"""
        rows = {r["task_id"]: r for r in R.load_jsonl(R.DATASET)}
        for tid in ("rt-C03", "rt-J01", "rt-J02", "rt-J03"):
            if tid not in rows:
                continue
            reps = R.abstention_violation_reports([rows[tid]])
            self.assertEqual(reps, [], "%s 被误判为弃权完整性违反" % tid)


class G5EvaluatorSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = R.load_json(R.GATE_P)
        cls.tax = R.load_json(R.TAXONOMY_P)

    def _eval(self, reviewed, g21=None, tax2=None):
        dims = {d: {"mean": 4.0} for d in R.DIMENSIONS}
        cmpd = {d: {"round1_mean": 2.0, "round2_mean": 4.0, "delta": 2.0}
                for d in R.DIMENSIONS}
        t2 = tax2 if tax2 is not None else {c: 0 for c in self.tax["classes"]}
        t2 = dict(t2)
        t2.setdefault("ABSTENTION_FAILURE", 0)
        res = R._evaluate_gate(self.gate, {"YES": 6, "WITH_REVISION": 6, "NO": 2},
                               {"PASS": 8, "PARTIAL": 4, "FAIL": 2}, dims, cmpd,
                               g21 or {}, t2, reviewed)
        return next(c for c in res["criteria"] if c["id"] == "G5_abstention_integrity")

    def test_20_taxonomy_frequency_is_not_a_counter(self):
        """taxology 命中 4 次但无明确违反 + 机器 0 → G5 必须通过。"""
        g5 = self._eval([_row("rt-J02", "YES", "正确且有信息价值的学术弃权")],
                        g21={}, tax2={"ABSTENTION_FAILURE": 4})
        self.assertTrue(g5["ok"], "G5 仍在读 taxonomy 频次：%s" % g5["observed"])
        self.assertEqual(g5["observed"]["diagnostic_taxonomy_ABSTENTION_FAILURE_mentions"], 4)

    def test_21_usable_no_is_not_required(self):
        """WITH_REVISION + 无违反 → G5 通过（不把 usability 当 abstention integrity）。"""
        g5 = self._eval([_row("rt-J01", "WITH_REVISION", "继续维持为有根据的部分弃权")])
        self.assertTrue(g5["ok"])

    def test_22_usable_no_plus_no_violation_still_passes_g5(self):
        g5 = self._eval([_row("rt-X", "NO", "理论综合不足，未能完成核心任务。")])
        self.assertTrue(g5["ok"], "NO 被错误地当成 G5 失败")

    def test_23_explicit_violation_fails_g5_regardless_of_usable(self):
        for usable in ("YES", "WITH_REVISION", "NO"):
            g5 = self._eval([_row("rt-X", usable, "缺乏证据却仍然回答了具体事实。")])
            self.assertFalse(g5["ok"], "usable=%s 时明确违反却未判失败" % usable)

    def test_24_machine_field_fails_g5(self):
        g5 = self._eval([], g21={"D_ABSTENTION_CONTAINS_SUBSTANTIVE_CLAIM": 1})
        self.assertFalse(g5["ok"], "机器侧 Gate 21 字段未参与判定")
        self.assertEqual(g5["observed"]["machine_fields_used"],
                         ["D_ABSTENTION_CONTAINS_SUBSTANTIVE_CLAIM"])

    def test_25_evaluator_version_recorded(self):
        self.assertEqual(R.G5_EVALUATOR_VERSION, "gate-evaluator/2")

    def test_26_gate_rule_file_unchanged(self):
        """acceptance rule 文件本身与其冻结哈希一致（规则语义未变）。"""
        man = R.load_json(R.MANIFEST)
        self.assertEqual(R.sha_file(R.GATE_P),
                         man["frozen_artifacts"]["gate"]["sha256"],
                         "G5 修复不得改动冻结的 gate 规则文件")

    def test_27_v1_history_preserved(self):
        self.assertTrue(os.path.isfile(R.G5_V1_SNAPSHOT),
                        "第一次（evaluator v1）的 NOT_READY 判定必须留档")
        v1 = R.load_json(R.G5_V1_SNAPSHOT)
        self.assertEqual(v1["verdict"], "SCHOLARLY_CORE_NOT_READY")
        self.assertEqual(v1["failed_criteria_ids"], ["G5_abstention_integrity"])


if __name__ == "__main__":
    unittest.main()
