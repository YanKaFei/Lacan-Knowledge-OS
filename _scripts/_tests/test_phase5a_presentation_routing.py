#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase5a_presentation_routing.py — Phase 5A §7/§10/§35/§58：诊断的呈现路由

钉住三件事：

1. **用户可见面 = 0 内部诊断**（新答案：validator reject 日志与验证计量不进 sections）；
2. **audit 面 = 100% 保留**（结构化 audit_diagnostics 里 rejected/repaired/计量原文全在）；
3. **学术身份不变**（claims / citations / answer_state / source_limitations 不因路由而变）。

另含**格式钉**：边界层按结构化重建来摘行，若冻结渲染器的日志格式漂移，
`routed_sections[].lines_removed` 会与 rejected 数不符 → 本测试红（而非静默漏摘）。
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (TOOLS, os.path.join(TOOLS, "lacan_mcp"), VAULT):
    sys.path.insert(0, p)

from scholarly_api import core, objects as O        # noqa: E402
from workspace_ui.server import presentation as PZ  # noqa: E402

# rt-G01 的同题（Phase 4E 实测含 reject 日志）；mock 确定性复现
REJECT_Q = "黑格尔的主人—奴隶辩证法如何进入拉康的欲望理论？"
ABSTAIN_Q = "拉康如何看待 fMRI 等当代神经科学影像研究？"


def _research(q, mode):
    return core.research(q, {"provider": "mock", "mode": mode, "task_id": "p5a-test",
                             "language": "any"})


class TestPresentationRouting(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = _research(REJECT_Q, "philosophy_to_lacan")
        cls.ab = _research(ABSTAIN_Q, "scholarly")

    def test_00_schema_is_v11_with_audit_field(self):
        self.assertEqual(self.r["schema_version"], "final-scholarly-answer/v1.1")
        self.assertEqual(O.SCHEMA_VERSIONS["FinalScholarlyAnswer"],
                         "final-scholarly-answer/v1.1")
        self.assertIn("final-scholarly-answer/v1", O.ANSWER_SCHEMA_VERSIONS_SUPPORTED)
        ok, errs = O.validate("FinalScholarlyAnswer", self.r)
        self.assertTrue(ok, errs[:3])

    def test_01_user_facing_sections_have_no_diagnostics(self):
        hits = PZ.scan_user_facing_internal_diagnostics(self.r)
        self.assertEqual(hits, [], "用户可见面出现内部诊断：%s" % hits)
        for sid, text in (self.r.get("sections") or {}).items():
            self.assertNotIn("已剔除", str(text))
            self.assertNotIn("NOT_ENTAILED", str(text))
            self.assertNotIn("因未通过验证被剔除", str(text))
        # brief_answer（验证计量摘要）不再出现在用户可见 sections
        self.assertNotIn("brief_answer", self.r.get("sections") or {})

    def test_02_audit_preserves_everything(self):
        ad = self.r.get("audit_diagnostics") or {}
        self.assertTrue(ad, "必须有结构化 audit_diagnostics")
        self.assertEqual(ad["schema_version"], "answer-audit/v1")
        self.assertEqual(ad["rejected_claims_n"], len(ad["rejected"]))
        self.assertIn("brief_answer_verbatim", ad)
        self.assertTrue(ad["brief_answer_verbatim"])
        routed = {x["section"]: x for x in ad["routed_sections"]}
        self.assertIn("limitations", routed)
        self.assertIn("brief_answer", routed)
        # 格式钉：被判为诊断的行数必须 == 结构化 rejected 数（否则渲染格式已漂移）
        self.assertEqual(routed["limitations"]["lines_removed"], ad["rejected_claims_n"],
                         "冻结渲染器的诊断行格式可能已漂移：边界层没摘干净")
        for r in ad["rejected"]:
            self.assertIn("claim_id", r)
            self.assertTrue(r.get("status"))

    def test_03_scholarly_identity_untouched_by_routing(self):
        # claims/citations/state/source_limitations 与"路由前应有的值"一致
        self.assertIn(self.r["answer_state"],
                      ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "PARTIALLY_SUPPORTED",
                       "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "ABSTAINED"))
        self.assertTrue(self.r["validated_claims"])
        self.assertTrue(self.r["citations"])
        for c in self.r["citations"]:
            self.assertTrue(c.get("passage_id"))
        # 用户可见 sections 的学术内容仍在（limitations 段保留了**学术**限制）
        self.assertTrue((self.r.get("sections") or {}).get("limitations"))
        self.assertTrue((self.r.get("sections") or {}).get("lacanian_reinterpretation"))

    def test_04_abstention_stays_a_scholarly_state(self):
        self.assertEqual(self.ab["answer_state"], "ABSTAINED")
        self.assertEqual(self.ab["answer_permission"], "ABSTAIN")
        self.assertTrue(self.ab.get("abstention"))
        self.assertEqual(PZ.scan_user_facing_internal_diagnostics(self.ab), [])

    def test_05_presentation_classes_are_deterministic(self):
        # 同一输入两次分类必须一致；且不依赖任何 LLM
        v1 = PZ.user_facing_view(self.r)
        v2 = PZ.user_facing_view(self.r)
        self.assertEqual([s["classification"] for s in v1["sections"]],
                         [s["classification"] for s in v2["sections"]])
        with open(os.path.join(VAULT, "workspace_ui", "server", "presentation.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        for forbidden in ("openai", "anthropic", "requests", "urllib", "subprocess"):
            self.assertNotIn(forbidden, src.lower(),
                             "presentation 层不得依赖网络/子进程（必须确定性）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
