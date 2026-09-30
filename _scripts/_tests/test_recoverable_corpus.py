#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_recoverable_corpus.py — 保护「唯一副本」的回归测试

背景（这是本项目最重要的一条风险）：
    `.lacan-build/atlas/segments.jsonl` 里的 82,578 段中译，其上游源目录
    （`<HOME>`）**已经消失**。
    也就是说这个文件是那批中译的**唯一副本**，且从未备份。

    对一个知识库来说，「唯一副本悄悄消失」是最致命的失败 —— 而且它是静默的：
    没有报错、没有测试红，只是某天发现段数少了一半。

    所以这条不能被当作「Phase 2 的事」。本测试在 Phase 1 就把它锁住：
    只要 atlas 里的段数低于历史基线、或 28 期覆盖不全、或出现坏行 → 立即失败。

设计取舍：
    * 断言用**基线下限**（>= 82,578）而非精确相等 —— 未来合法地补入新语料时
      不应让测试变红；但**变少**必须红。
    * 若 `.lacan-build/` 整体不在（例如换机器），跳过并**显式说明**，
      而不是静默通过 —— 静默通过就等于没有保护。
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
AUDIT = os.path.join(VAULT, "_scripts", "_tools", "audit_recoverable_corpus.py")
SNAPSHOT = os.path.join(VAULT, "_data", "recoverable_corpus.json")
LACAN_BUILD = os.path.expanduser("<HOME>")

# 历史基线（来自 2026-09-20 实测；见 PHASE1_FINDINGS.md §2.1）
ZH_BASELINE = 82578
FR_BASELINE = 166527
SEMINARS_EXPECTED = 28


class RecoverableCorpusGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(LACAN_BUILD):
            cls.report = None
            return
        proc = subprocess.run(
            [sys.executable, AUDIT, "--json"],
            capture_output=True, text=True, cwd=VAULT)
        cls.proc = proc
        try:
            cls.report = json.loads(proc.stdout)
        except Exception:
            cls.report = None

    def test_00_audit_script_runs(self):
        if not os.path.isdir(LACAN_BUILD):
            self.skipTest(
                f".lacan-build 不在（{LACAN_BUILD}）—— 无法验证唯一副本，"
                "请在持有该目录的机器上运行本测试")
        self.assertEqual(self.proc.returncode, 0,
                         f"审计脚本失败:\n{self.proc.stderr[-500:]}")
        self.assertIsNotNone(self.report, "审计脚本未输出可解析的 JSON")

    def test_01_zh_segments_never_shrink(self):
        """中译段数只能增不能减 —— 它是唯一副本。"""
        if self.report is None:
            self.skipTest("审计不可用")
        got = self.report["layers"]["zh_translation"]["records"]
        self.assertGreaterEqual(
            got, ZH_BASELINE,
            f"中译段数从基线 {ZH_BASELINE} 掉到 {got} —— 唯一副本疑似丢失/被截断！")

    def test_02_fr_segments_never_shrink(self):
        if self.report is None:
            self.skipTest("审计不可用")
        got = self.report["layers"]["fr_transcription"]["records"]
        self.assertGreaterEqual(
            got, FR_BASELINE,
            f"法语转录段数从基线 {FR_BASELINE} 掉到 {got}")

    def test_03_seminar_coverage_complete(self):
        """28 期必须齐全（S1–S27 + s19b）。"""
        if self.report is None:
            self.skipTest("审计不可用")
        for layer in ("zh_translation", "fr_transcription"):
            with self.subTest(layer=layer):
                got = self.report["layers"][layer]["seminars"]
                self.assertEqual(got, SEMINARS_EXPECTED,
                                 f"{layer} 期数 {got} != {SEMINARS_EXPECTED}")

    def test_04_no_malformed_lines(self):
        if self.report is None:
            self.skipTest("审计不可用")
        for layer in ("zh_translation", "fr_transcription"):
            with self.subTest(layer=layer):
                self.assertEqual(self.report["layers"][layer]["malformed_lines"], 0,
                                 f"{layer} 出现坏行（JSON 解析失败）")

    def test_05_passage_mapping_prerequisites(self):
        """Passage 映射的两个前提必须仍成立。

        没有 seminar 就归不了期；没有 lesson 就归不了课次 ——
        这两条一旦丢失，Phase 2 的 R0.3 映射做不了。
        """
        if self.report is None:
            self.skipTest("审计不可用")
        fields = self.report["layers"]["zh_translation"]["fields"]
        self.assertIn("seminar", fields, "中译缺少 seminar 字段，无法按期归位")
        self.assertIn("lesson", fields, "中译缺少 lesson 字段，无法映射课次")
        self.assertIn("id", fields, "中译缺少段号 id 字段，无法建立稳定映射")
        meta = self.report["layers"]["seminar_metadata"]
        self.assertTrue(meta["has_lesson_numbers"],
                        "seminars.json 缺少 lesson_numbers，无法补日期")

    def test_06_second_copy_of_fr_exists(self):
        """法语转录有第二道保险（staferla 原始下载）—— 确认它还在。"""
        if self.report is None:
            self.skipTest("审计不可用")
        raw = self.report["layers"]["staferla_raw"]
        self.assertGreaterEqual(raw["docx"], SEMINARS_EXPECTED,
                                f"staferla 原始 docx 不足: {raw}")

    def test_07_snapshot_file_is_committed(self):
        """审计快照应入库，让「唯一副本当时是什么样」有历史记录。"""
        self.assertTrue(os.path.exists(SNAPSHOT),
                        f"缺少 {os.path.relpath(SNAPSHOT, VAULT)}；"
                        f"运行 python3 _scripts/_tools/audit_recoverable_corpus.py --write")
        with open(SNAPSHOT, encoding="utf-8") as f:
            snap = json.load(f)
        self.assertEqual(snap["schema"], "recoverable-corpus/v1")
        self.assertGreaterEqual(snap["totals"]["combined"], ZH_BASELINE + FR_BASELINE,
                                "快照中的合计段数低于基线")

    def test_08_audit_is_read_only(self):
        """审计脚本不得改动 .lacan-build 下任何文件的 mtime。"""
        if not os.path.isdir(LACAN_BUILD):
            self.skipTest("审计不可用")
        atlas = os.path.join(LACAN_BUILD, "atlas")
        before = {}
        for dp, _, fns in os.walk(atlas):
            for fn in fns:
                fp = os.path.join(dp, fn)
                before[fp] = os.stat(fp).st_mtime_ns
        subprocess.run([sys.executable, AUDIT, "--json"],
                       capture_output=True, text=True, cwd=VAULT)
        after = {}
        for dp, _, fns in os.walk(atlas):
            for fn in fns:
                fp = os.path.join(dp, fn)
                after[fp] = os.stat(fp).st_mtime_ns
        self.assertEqual(before, after, ".lacan-build/atlas 被改动了（审计应只读）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
