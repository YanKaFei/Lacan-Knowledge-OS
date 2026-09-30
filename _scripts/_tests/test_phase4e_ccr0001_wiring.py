#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4e_ccr0001_wiring.py — Phase 4E §7/§8/§9/§10/§12/§13/§14（确定性，无网络）

纪律：
* 本套件**不发真实网络请求**：用一个只实现 `complete()` 的**假 completion provider**
  替换 `OpenAICompatibleProvider`，从而在**离线**条件下复现/验证 CCR-0001 的 wiring 契约。
* provider 故障的分类/脱敏断言使用**假异常**，不依赖任何真实凭据。
* 真实 provider 调用在 `test_phase4e_real_provider_smoke.py`（需要凭据，可跳过）。

CCR-0001：`provider="llm"` 时核心把低层 completion provider 当成 synthesis adapter 用。
本套件在修复前**必须红**（红的原因即 CCR-0001），修复后全绿。
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))
sys.path.insert(0, VAULT)

import synthesis_adapters as sad             # noqa: E402
import run_synthesis_4c1d as rd              # noqa: E402
from scholarly_api import core               # noqa: E402

QUESTION = "Seminar XI 中 gaze 与 objet a 是什么关系？"
LEGAL_STATES = ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "PARTIALLY_SUPPORTED",
                "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "ABSTAINED")


class FakeCompletionProvider:
    """transport 级 provider：**只有** `complete()`（与 OpenAICompatibleProvider 同契约）。"""

    name = "fake_completion"
    model = "fake-model"
    deterministic = False

    def __init__(self, timeout=60, payload=None, raises=None):
        self.timeout = timeout
        self.calls = 0
        self.payload = payload if payload is not None else {
            "claims": [], "sections": {"brief_answer": "(fake)"}, "abstention": None,
            "_usage": {"model": "fake-model", "latency_s": 0.0}}
        self.raises = raises

    @property
    def available(self):
        return True

    def complete(self, system, user, schema):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.payload


def _patch_provider(fake):
    """把核心会构造的 provider 替换成假 provider（两种 wiring 都覆盖）。"""
    return mock.patch.object(sad, "OpenAICompatibleProvider", lambda timeout=60: fake)


class TestAdapterContract(unittest.TestCase):
    """§8/§9/§10：provider 与 adapter 是两种 abstraction，仓库里已有正确 adapter。"""

    def test_00_completion_provider_is_not_a_synthesis_adapter(self):
        p = sad.OpenAICompatibleProvider(timeout=1)
        self.assertTrue(hasattr(p, "complete"), "completion provider 必须有 complete()")
        for attr in ("synthesize", "provider"):
            self.assertFalse(hasattr(p, attr),
                             "completion provider 不该有 %s —— 它只是 transport 层" % attr)

    def test_01_adapter_contract_accepts_any_completion_provider(self):
        fake = FakeCompletionProvider()
        adapter = sad.make_adapter("llm", fake)
        self.assertTrue(callable(getattr(adapter, "synthesize", None)),
                        "llm adapter 必须提供 synthesize()")
        self.assertIs(getattr(adapter, "provider", None), fake,
                      "adapter 必须把 completion provider 暴露为 .provider（judge 要用）")
        # synthesize() 必须真的经由 provider.complete()（transport 只发生一次）
        out = adapter.synthesize(QUESTION, {"status": "READY",
                                            "answer_permission": "ANSWER",
                                            "task_type": "concept_definition"},
                                 strict=False)
        self.assertEqual(fake.calls, 1, "adapter 必须调用 provider.complete() 恰好一次")
        self.assertTrue(out.get("ok"), "raw 模式下 provider 返回可解析 JSON 即应 ok")

    def test_02_provider_factory_is_the_only_selection_point(self):
        self.assertIsInstance(sad.make_adapter("mock"), sad.MockSynthesisAdapter)
        self.assertIsInstance(sad.make_adapter("llm", FakeCompletionProvider()),
                              sad.ScholarlySynthesisAdapter)
        with self.assertRaises(ValueError):
            sad.make_adapter("nope")


class TestCoreWiring(unittest.TestCase):
    """§7：CCR-0001 的确定性复现 + §9/§12/§13/§14 的契约守卫。"""

    def test_03_ccr0001_llm_branch_reaches_provider_through_adapter(self):
        """CCR-0001 复现：llm 分支必须把 completion provider 包进 synthesis adapter。

        修复前：core 直接把 provider 当 adapter → AttributeError，provider.complete()
        从未被调用 → 本测试红。
        修复后：provider 经 adapter 被调用一次，返回结构化 FinalScholarlyAnswer。
        """
        fake = FakeCompletionProvider()
        with _patch_provider(fake), mock.patch.object(rd, "load_dsh_key",
                                                      lambda: True):
            res = core.research(QUESTION, {"provider": "llm", "mode": "scholarly"})
        blob = json.dumps(res, ensure_ascii=False)
        self.assertGreaterEqual(fake.calls, 1,
                                "真实 provider 必须经 adapter 被调用（CCR-0001：为 0 即为旧 wiring）")
        self.assertNotIn("has no attribute 'synthesize'", blob,
                         "不得再出现 CCR-0001 的 AttributeError")
        # 成功形态是 FinalScholarlyAnswer（没有 ok 字段；失败形态才有 error_code）
        self.assertNotIn("error_code", res, "修复后应走完流水线，而不是 provider 错误：%s"
                         % blob[:300])
        # Phase 5A：答案 schema 升至 v1.1（新增 audit_diagnostics）；两者都必须可接受
        self.assertIn(res.get("schema_version"),
                      ("final-scholarly-answer/v1", "final-scholarly-answer/v1.1"))
        self.assertIn(res.get("answer_state"), LEGAL_STATES)
        self.assertEqual(res.get("provenance", {}).get("provider"), "llm")

    def test_04_provider_unavailable_when_no_credentials(self):
        fake = FakeCompletionProvider()
        with _patch_provider(fake), mock.patch.object(rd, "load_dsh_key",
                                                      lambda: False):
            res = core.research(QUESTION, {"provider": "llm", "mode": "scholarly"})
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "PROVIDER_UNAVAILABLE")
        self.assertEqual(fake.calls, 0, "无凭据时**不得**发起 provider 调用（fail closed）")

    def test_05_provider_failure_is_translated_and_subclassified(self):
        """§14：provider 失败保持稳定公开错误码 + 内部子分类；§13：不 fallback。"""
        import urllib.error
        err = urllib.error.HTTPError("https://api.example/v1/chat/completions", 401,
                                     "Unauthorized", {}, None)
        fake = FakeCompletionProvider(raises=err)
        with _patch_provider(fake), mock.patch.object(rd, "load_dsh_key",
                                                      lambda: True):
            res = core.research(QUESTION, {"provider": "llm", "mode": "scholarly"})
        self.assertGreaterEqual(fake.calls, 1, "provider 必须真的被调用过")
        self.assertFalse(res.get("ok"), "provider 失败不得产出答案")
        # 公开错误码：与修复前同一契约（产品层据此映射成 PROVIDER_UNAVAILABLE）
        self.assertIn(res.get("error_code"),
                      ("PROVIDER_CALL_FAILED", "PROVIDER_UNAVAILABLE"),
                      "provider 失败必须是 provider 类错误码，不能是 INTERNAL_ERROR")
        diag = (res.get("detail") or {}).get("provider_diagnostic")
        self.assertEqual(diag, "PROVIDER_AUTH_FAILED",
                         "§14 要求内部可区分 auth/timeout/rate-limit/bad-response")
        # §13：不得 fallback 到 mock
        self.assertNotIn("(fake)", json.dumps(res, ensure_ascii=False))
        self.assertIsNone(res.get("answer_state"))
        self.assertIsNone(res.get("validated_claims"))

    def test_06_provider_bad_response_is_subclassified(self):
        fake = FakeCompletionProvider(raises=ValueError("provider returned non-JSON body"))
        with _patch_provider(fake), mock.patch.object(rd, "load_dsh_key",
                                                      lambda: True):
            res = core.research(QUESTION, {"provider": "llm", "mode": "scholarly"})
        self.assertFalse(res.get("ok"))
        diag = (res.get("detail") or {}).get("provider_diagnostic")
        self.assertIn(diag, ("PROVIDER_BAD_RESPONSE", "SYNTHESIS_ADAPTER_ERROR"),
                      "无法解析/结构化失败必须有自己的子分类，不能混进 auth/timeout")

    def test_07_credentials_never_leak_into_result(self):
        """§12：API key 不得进入返回值（因此也不会进日志/UI/MCP 响应/工件）。"""
        canary = "sk-CANARY-4e-should-never-appear-0123456789"
        fake = FakeCompletionProvider(
            raises=RuntimeError("HTTP 401 from provider (Authorization: Bearer %s)" % canary))
        with _patch_provider(fake), mock.patch.object(rd, "load_dsh_key", lambda: True), \
                mock.patch.dict(os.environ, {"DSH_SYNTHESIS_API_KEY": canary}):
            res = core.research(QUESTION, {"provider": "llm", "mode": "scholarly"})
        blob = json.dumps(res, ensure_ascii=False)
        self.assertGreaterEqual(fake.calls, 1, "provider 必须真的被调用过（否则脱敏断言无意义）")
        self.assertNotIn(canary, blob, "API key 泄漏进了核心返回值")
        self.assertNotIn("Bearer " + canary, blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
