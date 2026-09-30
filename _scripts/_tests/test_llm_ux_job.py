#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_llm_ux_job — 长研究请求的**作业化 + 真实进度**（HTTP 级，本地 stub provider）。

为什么用本地 stub：真实 LLM 的一次往返要 45–60s 且依赖网络/额度，做不了确定性回归。
这里起一个**本地 OpenAI 兼容端点**（`/v1/chat/completions`，故意 sleep 3s），
把 `DSH_SYNTHESIS_BASE_URL` 指过去 —— 走的是**和真实 LLM 完全同一条产品路径**
（MCP → core → synthesis adapter → HTTP），只是端点换成本地而已。

断言的是产品层的**可观测性**，不是学术结论：
  * `POST /api/research/job` 立刻返回 202（HTTP 不再挂住几十秒）；
  * 轮询期间状态是 RUNNING，`elapsed_ms` **单调递增**（真实计时，不是假进度）；
  * DONE 后按需取回结果；`provider_model` / `wall_ms` 是产品层实测；
  * 真实端点收到**恰好一次**请求（成功路径不重发）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for _p in (VAULT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from workspace_ui.server import httpserver as H                            # noqa: E402
from workspace_ui.server import provider_view as PV                        # noqa: E402
from workspace_ui.server.mcp_client import reset_shared_client             # noqa: E402

STUB_MODEL = "stub-model-p5d005"
STUB_SLEEP_S = 3.0
STUB_KEY = "stub-key-not-a-real-secret"
QUESTION = "jouissance 在 S7 到 S20 如何变化？"
HITS = []


class _StubProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                                             # noqa: D102
        return

    def do_POST(self):                                                     # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        HITS.append({"auth_present": bool(self.headers.get("Authorization")),
                     "at": time.time()})
        time.sleep(STUB_SLEEP_S)
        doc = {"id": "stub-resp-1", "model": STUB_MODEL,
               "choices": [{"index": 0, "message": {"role": "assistant",
                                                    "content": "{}"},
                            "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 11, "completion_tokens": 2,
                         "total_tokens": 13}}
        body = json.dumps(doc).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class JobMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.had = os.path.isfile(PV.SETTINGS_PATH)
        cls.backup = None
        if cls.had:
            with open(PV.SETTINGS_PATH, encoding="utf-8") as fh:
                cls.backup = fh.read()
        cls.env = {k: os.environ.get(k) for k in
                   ("DSH_SYNTHESIS_BASE_URL", "DSH_SYNTHESIS_MODEL",
                    "DSH_SYNTHESIS_API_KEY")}
        cls.stub = ThreadingHTTPServer(("127.0.0.1", 0), _StubProvider)
        cls.stub_port = cls.stub.server_address[1]
        threading.Thread(target=cls.stub.serve_forever, daemon=True).start()
        cls.stub_url = "http://127.0.0.1:%d/v1" % cls.stub_port

        def pin_fixture():
            os.environ["DSH_SYNTHESIS_BASE_URL"] = cls.stub_url
            os.environ["DSH_SYNTHESIS_MODEL"] = STUB_MODEL
            os.environ["DSH_SYNTHESIS_API_KEY"] = STUB_KEY
            reset_shared_client()

        pin_fixture()
        cls.srv = H.make_server("127.0.0.1", 0)
        # ★ P5D-005 实测教训：`make_server()` 会应用 `_workspace/settings/provider.json`
        #   （用户设置，或**别的套件**留下的设置），可能把端点从本地 stub 改到别处 ——
        #   那样这个测试就不再是在测它自己声明的东西（曾经表现为 attempts=2 的假象）。
        #   所以启动服务后**再钉一次** fixture，并当场断言它确实生效。
        pin_fixture()
        eff = PV.effective()
        if eff["base_url"] != cls.stub_url or eff["model"] != STUB_MODEL:
            raise AssertionError("stub fixture 未生效（持久化设置偷改了端点）：%s"
                                 % json.dumps({k: eff[k] for k in ("base_url", "model")},
                                              ensure_ascii=False))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        try:
            cls.srv.shutdown()
        except Exception:                                                  # noqa: BLE001
            pass
        try:
            cls.stub.shutdown()
        except Exception:                                                  # noqa: BLE001
            pass
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if cls.had:
            with open(PV.SETTINGS_PATH, "w", encoding="utf-8") as fh:
                fh.write(cls.backup)
        elif os.path.isfile(PV.SETTINGS_PATH):
            os.remove(PV.SETTINGS_PATH)
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        PV.apply_persisted()
        reset_shared_client()
        # 测试绝不改变用户/后续套件看到的设置文件状态
        assert os.path.isfile(PV.SETTINGS_PATH) == cls.had, \
            "provider 设置文件状态与开始前不一致（泄漏）"

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, path, payload):
        req = urllib.request.Request(self.base + path,
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_01_job_returns_immediately_and_reports_real_elapsed(self):
        HITS.clear()
        t0 = time.time()
        status, body = self._post("/api/research/job",
                                  {"question": QUESTION, "provider": "llm",
                                   "mode": "scholarly"})
        submit_s = time.time() - t0
        self.assertEqual(status, 202)
        self.assertEqual(body["kind"], "job")
        self.assertEqual(body["status"], "RUNNING")
        # ★ 关键：提交**立刻**返回（不是等 45s 的一次阻塞往返）
        self.assertLess(submit_s, 2.0, "作业提交不得阻塞：%.2fs" % submit_s)
        jid = body["job_id"]

        seen, done = [], None
        deadline = time.time() + 900
        while time.time() < deadline:
            st, cur = self._get("/api/research/job?id=" + urllib.parse.quote(jid))
            self.assertEqual(st, 200)
            seen.append({"status": cur.get("status"), "elapsed_ms": cur.get("elapsed_ms")})
            if cur.get("status") == "DONE":
                done = cur
                break
            if cur.get("status") == "FAILED":
                self.fail("job failed: %s" % cur.get("error"))
            time.sleep(0.4)

        self.assertIsNotNone(done, "作业未在 900s 内完成")
        running = [s for s in seen if s["status"] == "RUNNING"]
        self.assertTrue(running, "至少应观察到一次 RUNNING（长请求不该瞬间完成）")
        self.assertTrue(all(s["elapsed_ms"] >= 0 for s in seen))
        elapsed = [s["elapsed_ms"] for s in running]
        self.assertEqual(elapsed, sorted(elapsed), "elapsed_ms 必须单调不减（真实计时）")

        self.assertNotIn("result", done)                    # 轮询很轻，默认不带结果
        _, full = self._get("/api/research/job?id=%s&result=1" % urllib.parse.quote(jid))
        self.assertIn("result", full)
        view = full["result"]["view"]
        self.assertTrue(view.get("kind"), view)
        adv = view.get("advanced") or {}
        self.assertEqual(adv.get("provider"), "llm")
        self.assertEqual(adv.get("provider_model"), STUB_MODEL)
        self.assertGreaterEqual(adv.get("wall_ms", 0), STUB_SLEEP_S * 1000 * 0.9)
        self.assertEqual(adv.get("attempts"), 1)            # 成功路径不重发
        self.assertIsNone(adv.get("retry_reason"))
        self.assertEqual(len(HITS), 1, "真实端点应恰好收到一次请求")
        self.assertTrue(HITS[0]["auth_present"])
        self.assertNotIn(STUB_KEY, json.dumps(full, ensure_ascii=False))
        with open(os.path.join(VAULT, "_workspace", "ui_qa",
                               "p5d005_job_evidence.json"), "w", encoding="utf-8") as fh:
            json.dump({"submit_s": round(submit_s, 3), "polls": seen[:40],
                       "state": view.get("state"), "advanced": adv,
                       "stub_hits": len(HITS), "model": STUB_MODEL,
                       "stub_sleep_s": STUB_SLEEP_S},
                      fh, ensure_ascii=False, indent=1, sort_keys=True)

    def test_02_unknown_job_is_reported_not_faked(self):
        status, body = self._get("/api/research/job?id=job_does_not_exist")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("code"), "JOB_NOT_FOUND")
        self.assertEqual(body.get("view"), "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
