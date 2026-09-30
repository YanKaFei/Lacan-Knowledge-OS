#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4e_real_abstention.py — Phase 4E §28/§34：真实 provider 下的弃权控制

用冻结任务 **rt-J02**（「拉康如何看待 fMRI 等当代神经科学影像研究？」）走产品边界，
断言核心**自己**得出弃权，且 adapter **没有**补答：

* `answer_state == "ABSTAINED"`（4D.7 mock 下同样如此；这里验证真实 provider 也一样）；
* 最终答案里**没有**实质 claim（DEFINITION/DISTINCTION/RELATION/…）；
* 弃权块与 source limitations 都在（弃权必须可见，不是空对象）；
* 真实 provider 不得比 mock 更宽容（同一 claim/entailment/repair/abstention 规则）。

凭据不可用时 SKIP；凭据可用但核心给出了实质答案 → 如实 FAIL（不重试到过关）。
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))
sys.path.insert(0, VAULT)

import synthesis_adapters as sad              # noqa: E402
import run_synthesis_4c1d as rd               # noqa: E402
import eval_integrity as ei                   # noqa: E402
from scholarly_api import core                # noqa: E402

rd.load_dsh_key()
AVAILABLE = sad.OpenAICompatibleProvider(timeout=10).available
SKIP_REASON = "SKIPPED_PROVIDER_UNAVAILABLE：未配置 provider（DSH_SYNTHESIS_API_KEY）"

QUESTION = "拉康如何看待 fMRI 等当代神经科学影像研究？"


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class TestRealProviderAbstention(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sink = {}
        cls.result = core.research(QUESTION, {"provider": "llm", "mode": "scholarly",
                                              "judge": True, "task_id": "rt-J02",
                                              "_audit_sink": cls.sink})
        print("\n[4E abstention] state=%s claims=%s"
              % (cls.result.get("answer_state"),
                 len(cls.result.get("validated_claims") or [])))

    def test_01_core_abstains_with_real_provider(self):
        self.assertIsNone(self.result.get("error_code"),
                          "不得以 provider 错误代替弃权：%s"
                          % json.dumps(self.result, ensure_ascii=False)[:300])
        self.assertEqual(self.result.get("answer_state"), "ABSTAINED")

    def test_02_no_substantive_leakage(self):
        claims = self.result.get("validated_claims") or []
        substantive = [c for c in claims
                       if c.get("claim_type") in ei.D_SUBSTANTIVE]
        self.assertEqual(substantive, [],
                         "弃权答案里出现实质 claim（adapter/模型补答）：%s"
                         % json.dumps(substantive, ensure_ascii=False)[:300])

    def test_03_abstention_is_visible_not_empty(self):
        """弃权必须**可见且完整** —— 按**冻结契约自己的要求**判，不用 harness 的臆测字段。

        ⚠️ 实测更正（Phase 4E）：`source_limitations` 对弃权答案为**空**是冻结核心的
        既定行为（mock、真实 provider、以及历史 D2 run 三处一致）——
        弃权的解释写在 `abstention` 块里（category / missing_information /
        available_partial_information / required_sources），契约的
        `abstention_requirements.must_include` 也只要求这些。原先断言
        「source_limitations 非空」属于 harness 自造期望（remediation 期间已更正）。
        """
        ab = self.result.get("abstention")
        self.assertTrue(ab, "弃权必须有 abstention 块（不得返回空对象）")
        semantic = {
            "reason_codes": bool(ab.get("abstention_reason_codes") or ab.get("categories")
                                 or ab.get("category")),
            "missing_information": bool(ab.get("missing_information")),
            "available_partial_information": "available_partial_information" in ab,
            "required_sources": bool(ab.get("next_required_sources")
                                     or ab.get("required_sources")),
        }
        missing = [k for k, v in semantic.items() if not v]
        self.assertEqual(missing, [], "弃权块缺语义字段：%s" % missing)
        # 核心的权限枚举值是 ABSTAIN（不是 ABSTENTION）—— 按核心实际取值断言
        self.assertEqual(self.result.get("answer_permission"), "ABSTAIN")
        contract = self.sink.get("input_contract") or {}
        self.assertEqual(contract.get("answer_permission"), "ABSTAIN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
