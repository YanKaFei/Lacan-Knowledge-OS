#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1d_llm_integration.py — Phase 4C.1-D §4：**真实 LLM 集成测试**

纪律（§4）：
* CI / 单元测试**不得**因为没有 API key 而失败；
* provider 未配置 → `SKIPPED_PROVIDER_UNAVAILABLE`（**不是** PASS，也**不是** FAIL）；
* 只有显式集成测试才允许真实调用（小样本、低 token）。

运行方式（需要 key）：
    DSH_SYNTHESIS_API_KEY=... python3 -m unittest test_phase4c1d_llm_integration
或本机 DSH 凭据库已配置时自动加载（同 run_synthesis_4c1d.load_dsh_key）。
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
EVAL = os.path.join(VAULT, "_data", "eval")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))

import research_answer as ans               # noqa: E402
import synthesis_contract as sc             # noqa: E402
import synthesis_adapters as sad            # noqa: E402
import synthesis_entailment as se           # noqa: E402
import synthesis_validation as sv           # noqa: E402
import run_synthesis_4c1d as rd             # noqa: E402

rd.load_dsh_key()
PROVIDER = sad.OpenAICompatibleProvider(timeout=60)
AVAILABLE = PROVIDER.available
SKIP_REASON = "SKIPPED_PROVIDER_UNAVAILABLE：未配置 provider（DSH_SYNTHESIS_API_KEY）"


def _task(tid):
    for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"), encoding="utf-8"):
        if l.strip():
            d = json.loads(l)
            if d["task_id"] == tid:
                return d
    raise KeyError(tid)


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class TestRealLLMIntegration(unittest.TestCase):
    """最小真实调用：一次 synthesis + 一次 judge，验证接口契约（不评质量）。"""

    @classmethod
    def setUpClass(cls):
        t = _task("rt-D01")
        run = ans.run_task({k: t[k] for k in ("task_id", "question", "language",
                                             "task_type", "required_capabilities",
                                             "split")}, record_gaps=False)
        cls.contract = sc.build_synthesis_input_contract(run)
        cls.question = t["question"]

    def test_01_real_synthesis_returns_claims(self):
        adm = sad.ScholarlySynthesisAdapter(provider=PROVIDER) \
            if hasattr(sad, "ScholarlySynthesisAdapter") else \
            sad.ScholarlySynthesisAdapter(provider=PROVIDER)
        out = adm.synthesize(self.question, self.contract, strict=False)
        self.assertTrue(out["ok"], out.get("failure_mode"))
        self.assertIsInstance(out["claims"], list)
        self.assertTrue(out["claims"], "真实 LLM 应当至少给出一条 claim")
        for c in out["claims"][:3]:
            self.assertIn("claim_type", c)
            self.assertIn("evidence_ids", c)

    def test_02_real_pipeline_validates_and_renders(self):
        adm = sad.ScholarlySynthesisAdapter(provider=PROVIDER)
        draft = adm.synthesize(self.question, self.contract, strict=False)
        judge = se.EntailmentJudge(provider=PROVIDER, enabled=True)
        pipe = sv.run_validation_pipeline(None, self.contract, draft, judge=judge,
                                          question=self.question)
        self.assertIn(pipe["answer_state"], sv.VALIDATED_ANSWER_STATES)
        # 关键安全边界：最终答案里的每条 claim 都在 validated set 里
        ids = {c.get("claim_id") for c in pipe["validated_claims"]}
        for c in (pipe["answer"] or {}).get("claims") or []:
            self.assertIn(c.get("claim_id"), ids)

    def test_03_provider_metadata_is_recordable(self):
        self.assertTrue(PROVIDER.name)
        self.assertTrue(getattr(PROVIDER, "model", None))


if __name__ == "__main__":
    if not AVAILABLE:
        print(SKIP_REASON)
    unittest.main(verbosity=2)
