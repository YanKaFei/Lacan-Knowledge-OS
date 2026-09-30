#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui.server.mcp_client — 产品路径的 MCP 客户端（stdio, JSON-RPC 2.0）

正式产品路径（§5）：`UI → workspace_ui.server → MCP → scholarly_api → FROZEN CORE`。
本模块**只**通过 MCP 协议访问核心（不 import scholarly_api，也不 import core），
因此 UI 侧的每一次学术取数都经过 4D.1 的同一道门（schema/freeze/audit/errors）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from . import config as C


class McpUnavailable(RuntimeError):
    def __init__(self, detail):
        super().__init__("MCP server unavailable")
        self.detail = detail


class McpClient:
    """常驻一个 MCP server 子进程；串行请求（§29 safe serial execution）。"""

    def __init__(self, server_path=None, timeout_s=None, python=None):
        self.server_path = server_path or C.MCP_SERVER
        self.timeout_s = timeout_s or C.MCP_TIMEOUT_S
        self.python = python or sys.executable
        self._proc = None
        self._lock = threading.Lock()
        # ⚠️ P5D-001：spawn 必须有自己的锁。`_lock` 用于**串行请求**（call() 会取它），
        #    而 start() 里要调用 call("initialize") —— 用同一把锁会死锁。
        self._start_lock = threading.Lock()
        self._rid = 0
        self._stderr_tail = []
        self.server_info = None
        self.freeze = None

    # ── 生命周期
    def start(self):
        """幂等启动：并发首次调用**不得** spawn 出第二个 MCP 子进程（P5D-001）。"""
        with self._start_lock:
            if self._proc and self._proc.poll() is None:
                return self
            self._proc = subprocess.Popen(
                [self.python, self.server_path], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=C.VAULT, bufsize=1)
            threading.Thread(target=self._drain_stderr, daemon=True).start()
            init = self.call("initialize", {"protocolVersion": "2025-11-25"})
            self.server_info = (init or {}).get("result", {}).get("serverInfo")
            self.freeze = ((init or {}).get("result", {}).get("meta") or {}).get(
                "core_freeze")
            return self

    def _drain_stderr(self):
        try:
            for line in self._proc.stderr:
                self._stderr_tail.append(line.rstrip())
                del self._stderr_tail[:-40]
        except Exception:                                    # noqa: BLE001
            pass

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.stdin.close()
                except Exception:                            # noqa: BLE001
                    pass
                try:
                    self._proc.wait(timeout=10)
                except Exception:                            # noqa: BLE001
                    self._proc.kill()
            self._proc = None

    # ── 协议
    def call(self, method, params=None):
        if not self._proc or self._proc.poll() is not None:
            raise McpUnavailable({"reason": "MCP_PROCESS_NOT_RUNNING",
                                  "stderr": self._stderr_tail[-5:]})
        with self._lock:
            self._rid += 1
            msg = {"jsonrpc": "2.0", "id": self._rid, "method": method,
                   "params": params or {}}
            try:
                self._proc.stdin.write(json.dumps(msg) + "\n")
                self._proc.stdin.flush()
                line = self._proc.stdout.readline()
            except Exception as exc:                         # noqa: BLE001
                raise McpUnavailable({"reason": "MCP_IO_ERROR", "error": str(exc)[:200],
                                      "stderr": self._stderr_tail[-5:]})
        if not line.strip():
            raise McpUnavailable({"reason": "MCP_EMPTY_RESPONSE",
                                  "stderr": self._stderr_tail[-5:]})
        return json.loads(line)

    def tools(self):
        r = self.call("tools/list")
        return ((r or {}).get("result") or {}).get("tools") or []

    def call_tool(self, name, arguments, timeout_s=None):
        """→ envelope `{ok, result|error, meta}`（协议错误抛 McpUnavailable）。"""
        r = self.call("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in (r or {}):
            raise McpUnavailable({"reason": "MCP_PROTOCOL_ERROR", "error": r["error"]})
        return (r.get("result") or {}).get("structuredContent")

    # ── 状态（§28）
    def status(self):
        try:
            self.start()
        except McpUnavailable as exc:
            return {"connected": False, "detail": exc.detail,
                    "core_freeze_verified": False,
                    "server": None, "checked_at": _now()}
        freeze = self.freeze or {}
        status = freeze.get("scholarly_status")
        profile = freeze.get("corpus_profile") or "reference"
        # 冻结状态有两种**已核验**的取值（core_freeze.py 的 corpus profile）：
        #   SCHOLARLY_CORE_READY                   参考语料：全部组件（含人工验收工件）一致
        #   CORPUS_HUMAN_REVIEW_NOT_AVAILABLE      非参考语料：人工验收工件按**声明缺席**处理
        # 两者都表示「哈希复算通过、核心未漂移」；差别在于**有没有人工验收背书**，
        # 这一差别必须显示给用户，而不是被折成一个 READY。
        verified = bool(freeze.get("freeze_version")) and status in (
            "SCHOLARLY_CORE_READY", "CORPUS_HUMAN_REVIEW_NOT_AVAILABLE")
        return {"connected": True,
                "server": self.server_info,
                "core_freeze": freeze,
                "core_freeze_verified": verified,
                "core_freeze_profile": profile,
                "core_human_review": ("NOT_AVAILABLE"
                                      if status == "CORPUS_HUMAN_REVIEW_NOT_AVAILABLE"
                                      else "AVAILABLE"),
                "core_freeze_note": ("本语料没有人工验收证据（人工评审/金标/就绪门工件"
                                     "按声明缺席处理）：研究可运行，但答案不携带人工验收背书；"
                                     "claim 的说话人归属模板是为参考语料写的，对本语料不适用。"
                                     if status == "CORPUS_HUMAN_REVIEW_NOT_AVAILABLE" else None),
                "checked_at": _now(),
                "stderr_tail": self._stderr_tail[-5:]}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_SHARED = {"client": None}
_SHARED_LOCK = threading.Lock()


def shared_client():
    """进程内共享客户端（HTTP server 与测试共用；避免每请求起子进程）。

    ⚠️ P5D-001（实测缺陷）：`ThreadingHTTPServer` 下首次并发请求会同时进入这里，
    两边都看到 `None` → **各 spawn 一个 MCP 子进程**，其中一个变成泄漏的孤儿
    （父进程仍是本 UI）。因此这里必须双重检查加锁。
    """
    cl = _SHARED["client"]
    if cl is not None:
        return cl
    with _SHARED_LOCK:
        if _SHARED["client"] is None:
            client = McpClient()
            try:
                client.start()
            except Exception:
                # P5D-001 的第二条路径：`start()` 已经 Popen 过子进程后才失败时，
                # 若不收掉就**永远泄漏**（且下次请求会再 spawn 一个）。
                try:
                    client.stop()
                except Exception:                                          # noqa: BLE001
                    pass
                raise
            _SHARED["client"] = client
        return _SHARED["client"]


def reset_shared_client():
    """清空共享客户端并停掉其子进程。

    ⚠️ 指针的清除必须在锁内完成（否则与 `shared_client()` 竞争会留下孤儿），
    而 `stop()`（可能等 10s）放在锁外，避免把启动路径一起堵住。
    """
    with _SHARED_LOCK:
        cl = _SHARED.get("client")
        _SHARED["client"] = None
    if cl:
        cl.stop()
