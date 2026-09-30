#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1e_round2_review.py — Phase 4C.1-E：盲评准备与记录的契约测试

守的是这几条**硬纪律**（不是功能测试）：
  1. 被评答案必须钉死到 D2 封存 run（逐题 answer_hash 与封存 run 复算一致）；
  2. 盲评不得泄漏 Round 1 分数/评论、旧状态、修复历史、内部 debug（泄漏门）；
  3. 系统**不得**代填任何人工评分（结构上：NOT_REVIEWED 行不得有任何评分字段；
     REVIEWED 行必须带人类 provenance）；
  4. acceptance rule / taxonomy / schema 在评审开始前冻结，之后不得被改；
  5. Round 1 基线永久冻结（sha256 不变）；
  6. 14/14 之前不得汇总。
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
sys.path.insert(0, TOOLS)

import round2_review as R  # noqa: E402


class Round2Preparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.man = R.load_json(R.MANIFEST) if os.path.isfile(R.MANIFEST) else None
        cls.gate = R.load_json(R.GATE_P)
        cls.tax = R.load_json(R.TAXONOMY_P)
        cls.rows = R.load_jsonl(R.DATASET) if os.path.isfile(R.DATASET) else []
        cls.ptr, cls.run_id, cls.run_dir = R.sealed_run()
        cls.res = R.load_json(os.path.join(cls.run_dir, "results.json"))
        cls.by_id = {r["task_id"]: r for r in cls.res["rows"]}
        cls.ids = [t["task_id"] for t in (cls.man or {}).get("tasks", [])]

    # ---- 1 封存 run 校验
    def test_00_sealed_run_verification(self):
        v = R.verify_sealed_run()
        bad = [c for c in v["checks"] if not c["ok"]]
        self.assertEqual(bad, [], f"D2 封存 run 校验失败项：{bad}")
        self.assertTrue(v["ok"])

    def test_01_same_14_tasks_as_round1(self):
        """Round 2 必须与 Round 1 完全同一批 14 题（可比性前提）。"""
        r1 = [it["task_id"] for it in R.load_json(R.ROUND1_SET)["items"]]
        self.assertEqual(self.ids, r1)

    # ---- 2 packet 完整性 + 钉死到封存 run
    def test_02_packets_14_of_14(self):
        self.assertEqual(len(self.ids), 14)
        for t in self.ids:
            for ext in ("json", "md"):
                p = os.path.join(R.PACKETS, "%s.%s" % (t, ext))
                self.assertTrue(os.path.isfile(p), f"缺 packet {p}")

    def test_03_answer_hash_matches_sealed_run(self):
        for t in self.ids:
            pkt = R.load_json(os.path.join(R.PACKETS, "%s.json" % t))
            self.assertEqual(pkt["integrity"]["answer_hash"],
                             R.canon_hash(self.by_id[t]["answer"]),
                             f"{t}: answer_hash 与封存 run 不一致")

    def test_04_packet_view_hash_recomputable(self):
        for t in self.ids:
            pkt = R.load_json(os.path.join(R.PACKETS, "%s.json" % t))
            h = R.canon_hash({"final_answer": pkt["final_answer"],
                              "claims": pkt["claims"],
                              "citations": pkt["citations"],
                              "source_limitations": pkt["source_limitations"]})
            self.assertEqual(h, pkt["integrity"]["packet_view_hash"],
                             f"{t}: packet_view_hash 不可复算")

    def test_05_all_citations_resolve(self):
        for t in self.ids:
            pkt = R.load_json(os.path.join(R.PACKETS, "%s.json" % t))
            self.assertEqual(pkt["integrity"]["missing_passages"], [],
                             f"{t}: 有 citation 未解析")
            for c in pkt["citations"]:
                self.assertTrue(c.get("passage_id"))
                self.assertTrue(c.get("source_layer"))
                self.assertTrue(c.get("provenance_status"))

    def test_06_packet_has_required_sections(self):
        """§7：task / final answer / claims / citations / source limitations / answer state。"""
        for t in self.ids:
            pkt = R.load_json(os.path.join(R.PACKETS, "%s.json" % t))
            self.assertTrue(pkt["task"]["question"])
            self.assertIn("answer_state", pkt["answer_state"])
            # 弃权题（如 rt-J03）的正文就是弃权说明本身，允许 sections 为空但必须有内容
            self.assertTrue(pkt["final_answer"].get("sections")
                            or pkt["final_answer"].get("abstention"),
                            f"{t}: 无正文也无弃权说明")
            self.assertIsInstance(pkt["claims"], list)
            self.assertIsInstance(pkt["citations"], list)
            self.assertIsInstance(pkt["source_limitations"], list)
            self.assertTrue(pkt["review_form"]["system_may_not_score"])

    def test_07_no_round1_or_debug_leakage(self):
        """§14 盲评泄漏门：packet/json+md 都不得出现黑名单词。"""
        for t in self.ids:
            pkt = R.load_json(os.path.join(R.PACKETS, "%s.json" % t))
            hits = R.blindness_scan(pkt)
            self.assertEqual(hits, [], f"{t}: 盲评泄漏 {hits}")

    def test_08_no_round1_scores_in_packet_file(self):
        """Round 1 的分数/评论原文不得出现在任何 packet 文件里。"""
        r1 = R.load_jsonl(R.ROUND1_RECORDS)
        needles = []
        for rec in r1:
            c = (rec.get("reviewer_comment") or {}).get("raw")
            if c:
                needles.append(c[:60])
        for t in self.ids:
            blob = ""
            for ext in ("json", "md"):
                with open(os.path.join(R.PACKETS, "%s.%s" % (t, ext)),
                          encoding="utf-8") as f:
                    blob += f.read()
            for n in needles:
                if len(n) >= 24:
                    self.assertNotIn(n, blob, f"{t}: 泄漏 Round 1 评论原文")

    # ---- 3 系统不得代填评分
    def test_10_dataset_rows_and_no_system_scores(self):
        self.assertEqual(len(self.rows), 14)
        for r in self.rows:
            self.assertIn(r["review_status"], ("NOT_REVIEWED", "REVIEWED"))
            if r["review_status"] == "NOT_REVIEWED":
                for k in ("human_scores", "citation_support", "scholarly_usable",
                          "reviewer_comment"):
                    self.assertFalse(r.get(k), f"{r['task_id']}: 未评审却有 {k}")
            else:
                self.assertEqual(r.get("reviewer_type"), "human")
                self.assertTrue((r.get("provenance") or {}).get("submitted_by"))
                self.assertEqual((r.get("provenance") or {}).get("written_by"),
                                 "review recorder (no scoring by system)")

    def test_11_schema_validates_every_record(self):
        for r in self.rows:
            ok, errs = R.validate_record(r)
            self.assertTrue(ok, f"{r['task_id']}: schema 违规 {errs[:3]}")

    def test_12_reviewed_record_requires_all_dimensions(self):
        """结构上不可能「缺项也算评审完成」。"""
        bad = {"schema_version": R.RECORD_SCHEMA, "review_round": 2,
               "review_status": "REVIEWED", "task_id": "rt-A01", "question": "q",
               "source_run_id": "x", "source_answer_hash": "h",
               "human_scores": {"clarity": 3}, "citation_support": "PASS",
               "scholarly_usable": "YES", "reviewer_comment": {"raw": "..."},
               "reviewed_at": "2026-01-01T00:00:00Z", "reviewer_type": "human",
               "provenance": {"written_by": "review recorder (no scoring by system)",
                              "submitted_by": "human", "validated": True}}
        ok, errs = R.validate_record(bad)
        self.assertFalse(ok, "缺维度的 REVIEWED 记录竟通过校验")
        self.assertTrue(any("theoretical_coherence" in e for e in errs))

    # ---- 4 冻结件
    def test_20_gate_frozen_before_any_score(self):
        self.assertTrue(self.gate.get("frozen_before_any_round2_score"))
        self.assertEqual((self.man["dataset_state_at_freeze"] or {}).get("reviewed"), 0)
        self.assertFalse((self.man["dataset_state_at_freeze"] or {})
                         .get("any_human_score_present"))
        for key, path in (("gate", R.GATE_P), ("taxonomy", R.TAXONOMY_P),
                          ("schema", R.SCHEMA_P)):
            self.assertEqual(R.sha_file(path),
                             self.man["frozen_artifacts"][key]["sha256"],
                             f"{key} 在冻结后被改动")

    def test_21_gate_thresholds_present(self):
        ids = {c["id"] for c in self.gate["criteria"]}
        self.assertEqual(ids, {"G1_no_majority_NO", "G2_citation_fail_drop",
                               "G3_no_source_role_violation",
                               "G4_no_unsupported_claim_in_final",
                               "G5_abstention_integrity",
                               "G6_explicit_human_support",
                               "G7_no_dimension_regression"})
        self.assertIn("overclaiming", self.gate["aggregation"]["dimensions"])
        self.assertIn("不得", self.gate["machine_metrics_disclaimer"])

    def test_22_gate_evaluator_binds_to_frozen_ids(self):
        """实现必须覆盖 gate 文件里**全部且仅有**的判据 id（规则不可被静默增删）。"""
        gate = self.gate
        good = {"YES": 6, "WITH_REVISION": 6, "NO": 2}
        cit = {"PASS": 8, "PARTIAL": 4, "FAIL": 2}
        dims = {d: {"mean": 4.0} for d in R.DIMENSIONS}
        cmpd = {d: {"round1_mean": 2.0, "round2_mean": 4.0, "delta": 2.0}
                for d in R.DIMENSIONS}
        tax2 = {c: 0 for c in self.tax["classes"]}
        res = R._evaluate_gate(gate, good, cit, dims, cmpd, {}, tax2, [])
        self.assertEqual([c["id"] for c in res["criteria"]],
                         [c["id"] for c in gate["criteria"]])
        self.assertEqual(res["verdict"], "SCHOLARLY_CORE_READY")
        # 负例：NO 占多数 → 不通过
        res2 = R._evaluate_gate(gate, {"YES": 1, "WITH_REVISION": 5, "NO": 8},
                                {"PASS": 8, "PARTIAL": 5, "FAIL": 1}, dims, cmpd, {},
                                tax2, [])
        self.assertEqual(res2["verdict"], "SCHOLARLY_CORE_NOT_READY")
        # 负例：单一维度大幅退步 → 不通过
        cmpd_bad = {d: {"round1_mean": 3.0, "round2_mean": 2.0, "delta": -1.0}
                    for d in R.DIMENSIONS}
        res3 = R._evaluate_gate(gate, good, cit, dims, cmpd_bad, {}, tax2, [])
        self.assertEqual(res3["verdict"], "SCHOLARLY_CORE_NOT_READY")

    def test_23_taxonomy_complete_and_frozen(self):
        classes = self.tax["classes"]
        self.assertEqual(len(classes), 12)
        m = self.tax["round1_issue_code_map"]
        r1 = R.load_json(R.ROUND1_RESULTS)
        for code in (r1.get("issue_code_frequency") or {}):
            self.assertIn(code, m, f"Round 1 issue code 未映射：{code}")
            self.assertIn(m[code], classes)

    def test_24_round1_baseline_untouched(self):
        self.assertEqual(R.sha_file(R.ROUND1_RECORDS), R.ROUND1_RECORDS_SHA)
        for p in (R.ROUND1_RESULTS, R.ROUND1_SET,
                  os.path.join(R.EVAL, "human_adjudication_queue.jsonl")):
            self.assertTrue(os.path.isfile(p), f"缺 Round 1 基线件 {p}")

    # ---- 5 aggregate 门控
    def test_30_aggregate_refuses_until_14_of_14(self):
        reviewed = sum(1 for r in self.rows if r["review_status"] == "REVIEWED")
        if reviewed < 14:
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):   # 拒绝是预期行为，不进套件日志
                rc_quiet = R.aggregate(quiet=True)
                rc_loud = R.aggregate(quiet=False)
            self.assertEqual((rc_quiet, rc_loud), (2, 2),
                             "未满 14/14 时 aggregate 竟未拒绝")
            self.assertEqual(buf.getvalue().count("NOT_READY"), 1,
                             "quiet=False 时应打印一次 NOT_READY；quiet=True 不应打印")
        else:
            self.assertTrue(os.path.isfile(R.RESULTS_V2),
                            "14/14 后应已生成 human_review_results_v2.json")

    def test_31_check_passes(self):
        self.assertEqual(R.check(quiet=True), 0)

    def test_32_manifest_records_engine_and_prompt_hashes(self):
        self.assertEqual(self.man["source_run_id"], self.run_id)
        self.assertEqual(self.man["source_run_manifest_hash"],
                         R.sha_file(os.path.join(self.run_dir, "run_manifest.json")))
        self.assertEqual(len(self.man["engine_hashes"]), 10)
        self.assertEqual(len(self.man["prompt_hashes"]), 2)
        self.assertEqual(len(self.man["answer_hash_per_task"]), 14)


if __name__ == "__main__":
    unittest.main()
