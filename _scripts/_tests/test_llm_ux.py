#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P5D-005 §LLM-UX：真实 LLM 接口的**产品层**可用性（设置 / 自检 / 重试 / 作业 / 溯源）。

纪律（本套件守着的东西）：
  * 密钥**永不**经过产品 API，也永不写进任何输出（本套件会扫一遍返回值确认）；
  * **只**对基础设施类失败（PROVIDER_UNAVAILABLE / PROVIDER_CALL_FAILED）重试一次；
    学术判定类结果（VALIDATION_FAILED / ABSTAINED / …）**永不重试**；
  * 溯源字段全部来自产品层自己的计时/缓存/尝试计数（不改冻结核心的任何语义）；
  * 设置只写 `_workspace/settings/provider.json`（USER_WORKSPACE），且只写 model/base_url。

全程不联网（连通性自检用不可达端点，或直接 stub）。
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)
sys.path.insert(0, HERE)

from workspace_ui.server import api as A               # noqa: E402
from workspace_ui.server import jobs as JB             # noqa: E402
from workspace_ui.server import provider_view as PV    # noqa: E402

SETTINGS = PV.SETTINGS_PATH
ENV_KEYS = ("DSH_SYNTHESIS_MODEL", "DSH_SYNTHESIS_BASE_URL")


class _SettingsSandbox(unittest.TestCase):
    """产品设置/环境变量的沙箱：跑完**逐字节还原**，不留痕。"""

    def setUp(self):
        self.had = os.path.isfile(SETTINGS)
        self.backup = None
        if self.had:
            with open(SETTINGS, encoding="utf-8") as fh:
                self.backup = fh.read()
        self.env = {k: os.environ.get(k) for k in ENV_KEYS}
        self.key = os.environ.pop("DSH_SYNTHESIS_API_KEY", None)

    def tearDown(self):
        if self.had:
            os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
            with open(SETTINGS, "w", encoding="utf-8") as fh:
                fh.write(self.backup)
        elif os.path.isfile(SETTINGS):
            os.remove(SETTINGS)
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if self.key is not None:
            os.environ["DSH_SYNTHESIS_API_KEY"] = self.key


class SettingsCase(_SettingsSandbox):

    # ── 1. 生效设置：形状 + 不回显密钥
    def test_01_effective_settings_shape_and_no_secret(self):
        s = PV.effective()
        for k in ("provider", "model", "base_url", "credentials_present",
                  "credential_source", "call_timeout_s", "call_timeout_note",
                  "settings_path", "persisted"):
            self.assertIn(k, s)
        self.assertIn(s["provider"], ("mock", "llm"))
        self.assertTrue(s["base_url"].startswith("https://"))
        self.assertEqual(s["call_timeout_s"], 120)          # 冻结核心写死，只读
        self.assertEqual(s["settings_path"], "_workspace/settings/provider.json")
        secret = "sk-" + "SECRET-CANARY-0123456789"
        os.environ["DSH_SYNTHESIS_API_KEY"] = secret
        blob = json.dumps(PV.effective(), ensure_ascii=False)
        self.assertNotIn(secret, blob)                      # 密钥绝不回显
        self.assertTrue(PV.effective()["credentials_present"])
        # 只报**来源名**（哪个渠道找到的），绝不报值
        self.assertEqual(PV.effective()["credential_source"], "DSH_SYNTHESIS_API_KEY")
        probe = json.dumps(PV.test_connection({"base_url": "https://127.0.0.1:9/v1"}),
                           ensure_ascii=False)
        self.assertNotIn(secret, probe)                     # 自检结果同样不回显

    # ── 2. 保存：非法值拒绝；合法值落盘并进环境；密钥不可设
    def test_02_save_validates_and_persists(self):
        ok, out = PV.save({"model": "bad model with spaces"})
        self.assertFalse(ok)
        self.assertEqual(out["code"], "INVALID_REQUEST")
        ok, out = PV.save({"base_url": "http://insecure.example/v1"})
        self.assertFalse(ok)                                # 只接受 https
        ok, out = PV.save({"provider": "openai"})
        self.assertFalse(ok)
        ok, out = PV.save({"model": "deepseek-reasoner",
                           "base_url": "https://api.deepseek.com/v1"})
        self.assertTrue(ok, out)
        self.assertTrue(os.path.isfile(SETTINGS))
        with open(SETTINGS, encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertEqual(disk["model"], "deepseek-reasoner")
        self.assertEqual(os.environ["DSH_SYNTHESIS_MODEL"], "deepseek-reasoner")
        s = PV.effective()
        self.assertEqual(s["model"], "deepseek-reasoner")
        self.assertTrue(s["persisted"])
        # 密钥字段即便被塞进来也**不入盘、不进环境**
        os.environ.pop("DSH_SYNTHESIS_API_KEY", None)
        PV.save({"api_key": "sk-should-be-ignored"})
        with open(SETTINGS, encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertNotIn("api_key", disk)
        self.assertNotIn("DSH_SYNTHESIS_API_KEY", os.environ)

    # ── 3. 自检：不可达端点必须**如实失败**（不装"已配置"）
    def test_03_test_connection_reports_real_failure(self):
        os.environ["DSH_SYNTHESIS_API_KEY"] = "sk-canary-not-a-real-key"
        r = PV.test_connection({"base_url": "https://127.0.0.1:9/v1", "model": "m"})
        self.assertFalse(r["ok"])
        self.assertNotEqual(r.get("code"), "OK")
        self.assertIn("latency_s", r)
        # 无凭据时**不假装**能连：如实报 NO_CREDENTIALS（产品层不接收密钥输入）
        orig = PV._api_key
        PV._api_key = lambda: None
        try:
            r2 = PV.test_connection({"base_url": "https://127.0.0.1:9/v1", "model": "m"})
        finally:
            PV._api_key = orig
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["code"], "NO_CREDENTIALS")
        self.assertFalse(r2["credentials_present"])

    # ── 3b. 坏掉的持久化文件**不得**灌进环境（P5D-005 加固）
    def test_04b_invalid_persisted_settings_are_rejected_not_applied(self):
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump({"model": "bad model with spaces",
                       "base_url": "http://not-https.example/v1"}, fh)
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        applied = PV.apply_persisted()
        self.assertEqual(applied, {})                       # 一个坏值都不写
        self.assertNotIn("DSH_SYNTHESIS_MODEL", os.environ)
        self.assertNotIn("DSH_SYNTHESIS_BASE_URL", os.environ)
        self.assertEqual(set(PV.LAST_APPLY["rejected"]), {"model", "base_url"})
        # 合法值仍然照常应用
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump({"model": "ok-model", "base_url": "https://ok.example/v1"}, fh)
        applied = PV.apply_persisted()
        self.assertEqual(set(applied), set(ENV_KEYS))
        self.assertEqual(PV.LAST_APPLY["rejected"], {})

    # ── 4. 启动应用：只写 model/base_url
    def test_04_apply_persisted_only_touches_two_env_vars(self):
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump({"model": "m-1", "base_url": "https://x.example/v1",
                       "provider": "llm"}, fh)
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        os.environ.pop("DSH_SYNTHESIS_API_KEY", None)
        applied = PV.apply_persisted()
        self.assertEqual(set(applied), set(ENV_KEYS))
        self.assertEqual(os.environ["DSH_SYNTHESIS_MODEL"], "m-1")
        self.assertEqual(os.environ["DSH_SYNTHESIS_BASE_URL"], "https://x.example/v1")
        self.assertNotIn("DSH_SYNTHESIS_API_KEY", os.environ)


class JobCase(unittest.TestCase):
    # ── 5. 作业：真实状态 + 结果按需交付 + 有界
    def test_05_job_lifecycle(self):
        jid = JB.start("q" * 10, lambda: {"view": {"kind": "answer", "state": "ABSTAINED"}})
        snap = None
        for _ in range(200):
            snap = JB.get(jid)
            if snap["status"] != "RUNNING":
                break
        self.assertEqual(snap["status"], "DONE")
        self.assertGreaterEqual(snap["elapsed_ms"], 0)
        light = JB.progress(jid)
        self.assertNotIn("result", light)                    # 轮询很轻：默认不带结果
        full = JB.progress(jid, include_result=True)
        self.assertEqual(full["result"]["view"]["state"], "ABSTAINED")
        self.assertTrue(JB.discard(jid))
        self.assertEqual(JB.progress(jid)["code"], "JOB_NOT_FOUND")

    def test_06_job_failure_is_reported_not_hidden(self):
        jid = JB.start("q" * 10, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        snap = None
        for _ in range(200):
            snap = JB.get(jid)
            if snap["status"] != "RUNNING":
                break
        self.assertEqual(snap["status"], "FAILED")
        self.assertIn("boom", JB.progress(jid)["error"])
        JB.discard(jid)

    def test_07_job_table_is_bounded(self):
        ids = [JB.start("q%d" % i, lambda: {"view": {}}) for i in range(JB.MAX_JOBS + 4)]
        alive = [i for i in ids if JB.get(i) is not None]
        self.assertLessEqual(len(alive), JB.MAX_JOBS)
        self.assertIsNone(JB.get(ids[0]))                    # 最旧的被清掉
        for i in ids:
            JB.discard(i)


class RetryDisciplineCase(unittest.TestCase):
    """★ 本套件的核心：重试只属于基础设施，**不属于**学术判定。"""

    def setUp(self):
        self.calls = []
        self.orig_call = A._call
        self.orig_status = A.status
        self.orig_save = A.H.save

    def tearDown(self):
        A._call = self.orig_call
        A.status = self.orig_status
        A.H.save = self.orig_save

    def _stub(self, envs):
        A.status = lambda: {"research_disabled": False, "mcp_connected": True,
                            "core_freeze_verified": True}

        def fake(tool, args, use_cache=True, trace=None):
            self.calls.append({"use_cache": use_cache})
            if trace is not None:
                trace["cached"] = False
            return envs[min(len(self.calls) - 1, len(envs) - 1)]
        A._call = fake

    def test_08_provider_failure_retries_once_and_records_it(self):
        fail = {"ok": False, "meta": {},
                "error": {"code": "INTERNAL_ERROR",
                          "detail": {"api_error_code": "PROVIDER_CALL_FAILED"},
                          "message": "provider call failed"}}
        self._stub([fail])
        out = A.research("a question with enough length", provider="llm",
                         save_history=False)
        self.assertEqual(len(self.calls), A.MAX_ATTEMPTS)     # 恰好重发一次
        self.assertTrue(self.calls[0]["use_cache"])            # 第一次照常可读缓存
        self.assertFalse(self.calls[1]["use_cache"])           # 重发时**绕过**缓存
        adv = out["view"]["advanced"]
        self.assertEqual(adv["attempts"], 2)
        self.assertEqual(adv["retry_reason"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(adv["provider"], "llm")

    def test_09_scholarly_verdict_is_never_retried(self):
        """VALIDATION_FAILED / ABSTAINED 是**结论**，不是故障 —— 一次都不许重发。"""
        for code in ("VALIDATION_FAILED", "ABSTAINED", "INSUFFICIENT_EVIDENCE"):
            self.calls = []
            env = {"ok": True, "meta": {"request_id": "req_" + code.lower(),
                                        "duration_ms": 1000, "provider": "mock"},
                   "result": {"state": code, "state_label": code,
                              "answer_permission": "ABSTAIN",
                              "question": "q", "summary": {},
                              "sections": [], "claims": [], "citations": [],
                              "limitations": [], "warnings": [],
                              "task_type": "concept_explication"}}
            self._stub([env])
            out = A.research("a question with enough length", provider="llm",
                             save_history=False)
            self.assertEqual(len(self.calls), 1, code)
            self.assertEqual(out["view"]["advanced"]["attempts"], 1, code)
            self.assertIsNone(out["view"]["advanced"]["retry_reason"], code)

    def test_10_retry_can_be_disabled_and_provenance_is_product_measured(self):
        fail = {"ok": False, "meta": {},
                "error": {"code": "INTERNAL_ERROR",
                          "detail": {"api_error_code": "PROVIDER_UNAVAILABLE"},
                          "message": "provider unavailable"}}
        self._stub([fail])
        out = A.research("a question with enough length", provider="llm",
                         save_history=False, retry=False)
        self.assertEqual(len(self.calls), 1)
        adv = out["view"]["advanced"]
        self.assertGreaterEqual(adv["wall_ms"], 0)            # 产品层自己量的墙钟
        self.assertIn("cached", adv)
        self.assertIn("fresh_requested", adv)
        # 重试按钮只出现在基础设施失败之后
        self.assertIn("retry_once", [a["id"] for a in out["view"].get("actions") or []])

    def test_11_mock_provider_reports_no_model_call(self):
        env = {"ok": True, "meta": {"request_id": "req_mock", "duration_ms": 12,
                                    "provider": "mock"},
               "result": {"state": "VALIDATED_WITH_QUALIFICATIONS",
                          "state_label": "VALIDATED_WITH_QUALIFICATIONS",
                          "answer_permission": "ANSWER", "question": "q",
                          "summary": {}, "sections": [], "claims": [],
                          "citations": [], "limitations": [], "warnings": [],
                          "task_type": "concept_explication"}}
        self._stub([env])
        out = A.research("a question with enough length", provider="mock",
                         save_history=False, use_cache=False)
        adv = out["view"]["advanced"]
        self.assertIsNone(adv["provider_model"])              # mock 没有模型
        self.assertIsNotNone(adv["provider_model_note"])
        self.assertTrue(adv["fresh_requested"])

    def test_12_fresh_flag_bypasses_product_cache(self):
        env = {"ok": True, "meta": {"request_id": "req_c", "duration_ms": 5,
                                    "provider": "mock"},
               "result": {"state": "ABSTAINED", "state_label": "ABSTAINED",
                          "answer_permission": "ABSTAIN", "question": "q",
                          "summary": {}, "sections": [], "claims": [],
                          "citations": [], "limitations": [], "warnings": [],
                          "task_type": "concept_explication"}}
        self._stub([env])
        A.research("cache me please now", provider="mock", save_history=False,
                   use_cache=False)
        self.assertTrue(self.calls[0]["use_cache"] is False)
        self.calls = []
        A.research("cache me please now", provider="mock", save_history=False,
                   use_cache=True)
        self.assertTrue(self.calls[0]["use_cache"] is True)


class NoSecretInPayloadCase(_SettingsSandbox):
    """13. 产品 API 的任何响应都不得包含密钥材料。"""

    def test_13_no_credentials_in_api_shapes(self):
        canary = "sk-" + "CANARY-abcdefghijklmnop"
        old = os.environ.get("DSH_SYNTHESIS_API_KEY")
        os.environ["DSH_SYNTHESIS_API_KEY"] = canary
        try:
            blobs = [json.dumps(PV.effective(), ensure_ascii=False),
                     json.dumps(PV.save({"model": "m2"})[1], ensure_ascii=False),
                     json.dumps(PV.test_connection({"base_url": "https://127.0.0.1:9/v1"}),
                                ensure_ascii=False)]
            for b in blobs:
                self.assertNotIn(canary, b)
        finally:
            if old is None:
                os.environ.pop("DSH_SYNTHESIS_API_KEY", None)
            else:
                os.environ["DSH_SYNTHESIS_API_KEY"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
