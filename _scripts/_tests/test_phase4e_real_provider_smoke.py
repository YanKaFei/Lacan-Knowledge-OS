#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4e_real_provider_smoke.py — Phase 4E §15/§16/§27：真实 provider 最小冒烟

**一次**真实调用（rt-D01 的问题，mode=seminar_specific），四个断言面共享它：

1. §15 冒烟：无 AttributeError / 无 error_code / 合法 answer_state；
2. §16 身份：审计接收器里必须有 contract hash、synthesis payload hash、
   final answer hash、provider/model（**不**记录凭据）；
3. §27 citation/evidence 绑定：每条 citation 都能在语料里查到，
   每条 claim 的 evidence_ids 都必须落在 input contract 的 usable evidence 内；
4. §12/§68：返回值里不得出现凭据。

凭据不可用时按仓库既有惯例 SKIP（`SKIPPED_PROVIDER_UNAVAILABLE`）；
凭据可用但 provider 暂时不可用 → **不跳过**，如实报错（fail closed）。
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))
sys.path.insert(0, VAULT)

import synthesis_adapters as sad              # noqa: E402
import run_synthesis_4c1d as rd               # noqa: E402
import browse_api as BA                       # noqa: E402
from scholarly_api import core                # noqa: E402

rd.load_dsh_key()
PROBE = sad.OpenAICompatibleProvider(timeout=10)
AVAILABLE = PROBE.available
SKIP_REASON = "SKIPPED_PROVIDER_UNAVAILABLE：未配置 provider（DSH_SYNTHESIS_API_KEY）"

QUESTION = "Seminar XI 中 gaze/regard 是如何与 objet a 发生关系的？"
LEGAL_STATES = ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "PARTIALLY_SUPPORTED",
                "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "ABSTAINED")


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class TestRealProviderSmoke(unittest.TestCase):
    """真实 provider 经**产品边界**（scholarly_api.core.research）跑一次完整流水线。"""

    @classmethod
    def setUpClass(cls):
        cls.sink = {}
        t0 = datetime.now(timezone.utc)
        cls.result = core.research(QUESTION, {"provider": "llm",
                                              "mode": "seminar_specific",
                                              "judge": True, "task_id": "phase4e-smoke",
                                              "_audit_sink": cls.sink})
        cls.seconds = (datetime.now(timezone.utc) - t0).total_seconds()
        print("\n[4E smoke] %.1fs | state=%s | claims=%s | citations=%s"
              % (cls.seconds, cls.result.get("answer_state"),
                 len(cls.result.get("validated_claims") or []),
                 len(cls.result.get("citations") or [])))

    def test_01_smoke_reaches_pipeline_without_wiring_error(self):
        blob = json.dumps(self.result, ensure_ascii=False)
        self.assertNotIn("has no attribute 'synthesize'", blob)
        self.assertIsNone(self.result.get("error_code"),
                          "真实 provider 冒烟不得返回错误：%s" % blob[:400])
        self.assertIn(self.result.get("answer_state"), LEGAL_STATES)
        self.assertEqual(self.result.get("provenance", {}).get("provider"), "llm")

    def test_02_audit_identities_are_recorded(self):
        s = self.sink
        for key in ("input_contract_hash", "final_answer_hash", "evidence_ids",
                    "pipeline", "synthesis"):
            self.assertIn(key, s, "审计接收器缺 %s（§16 要求可审计）" % key)
        self.assertTrue(s["synthesis"].get("ok"), "synthesis 必须成功")
        self.assertEqual(s["synthesis"].get("provider"), "openai_compatible")
        self.assertTrue(s["synthesis"].get("raw_payload_hash"))
        self.assertTrue(s["input_contract_hash"])
        self.assertTrue(s["final_answer_hash"])
        self.assertTrue(s.get("judge_enabled"), "真实 provider 下 judge 必须开启（§29）")

    def test_03_citations_and_claim_bindings_are_real(self):
        contract = self.sink.get("input_contract") or {}
        usable = {e.get("passage_id") for e in (contract.get("usable_evidence") or [])}
        self.assertTrue(usable, "input contract 必须有 usable evidence")
        citations = self.result.get("citations") or []
        if self.result.get("answer_state") != "ABSTAINED":
            self.assertTrue(citations, "非弃权答案必须带 citation")
        for c in citations:
            pid = c.get("passage_id")
            self.assertIn(pid, usable, "citation %s 不在 input contract 的 usable evidence 内" % pid)
            self.assertIsNotNone(BA.get_passage(pid), "citation %s 在语料里查不到" % pid)
            self.assertTrue(c.get("source_layer"), "citation 必须带 source_layer")
        for claim in self.result.get("validated_claims") or []:
            for eid in claim.get("evidence_ids") or []:
                self.assertIn(eid, usable,
                              "claim %s 的证据 %s 不在 input contract 内（citation binding 违规）"
                              % (claim.get("claim_id"), eid))

    def test_04_no_credentials_in_result(self):
        blob = json.dumps(self.result, ensure_ascii=False)
        key = os.environ.get("DSH_SYNTHESIS_API_KEY") or ""
        if len(key) >= 8:
            self.assertNotIn(key, blob)
        self.assertNotIn("Bearer ", blob)
        self.assertNotIn("Authorization", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
