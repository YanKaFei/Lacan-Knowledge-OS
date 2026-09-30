#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_mcp_testlib.py — Phase 4D.1 测试共享工具（**下划线开头 → 不被 unittest 收集**）

提供：
  * `call(tool, args)`           进程内调用 MCP 工具（走完整 envelope/校验/审计链）
  * `api_call(fn, *a, **kw)`     进程内调用 scholarly_api
  * `cached_research(q, opts)`   跨进程缓存的重研究调用（让多个测试文件共享同一次计算）
  * `stdio_session(requests)`    真实 MCP 协议会话（spawn server.py，JSON-RPC over stdio）
  * `core_freeze_ok()`           核心冻结状态
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for p in (VAULT,):
    if p not in sys.path:
        sys.path.insert(0, p)

import scholarly_api as api                                  # noqa: E402
from mcp_server import server as mcp_server                  # noqa: E402
from mcp_server import tools as mcp_tools                    # noqa: E402
from mcp_server.guard import verify_core_freeze              # noqa: E402

CACHE_DIR = os.path.join(tempfile.gettempdir(), "lacan_mcp_test_cache")
FROZEN_QUESTIONS = {
    "relation": "Seminar XI 中 gaze 与 objet a 是什么关系？",
    "terminology": "Réel 与 réalité 为什么要区分？",
    "formalism": "$ ◊ a 表示什么？",
    "diachronic": "jouissance 在 S7 到 S20 如何变化？",
    "abstain_topic": "拉康如何看待 fMRI？",
    "abstain_metadata": "拉康 1953 年 11 月 18 日那场报告的确切地点和出席者是谁？",
}


def call(tool, args, audit=False, freeze_state=None):
    """进程内 MCP 工具调用 → envelope。默认关闭审计以免污染生产审计日志。"""
    return mcp_tools.call_tool(tool, args, freeze_state=freeze_state, audit=audit)


def mcp_roundtrip(method, params=None, rid=1):
    """单条协议消息（不 spawn 进程）→ 响应 dict。"""
    return mcp_server.handle({"jsonrpc": "2.0", "id": rid, "method": method,
                              "params": params or {}})


def stdio_session(requests, cwd=None):
    """真实 MCP 会话：spawn `mcp_server/server.py`，按序收发 JSON-RPC。

    requests: [(method, params), ...] → [response, ...]
    """
    p = subprocess.Popen([sys.executable, os.path.join("mcp_server", "server.py")],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, cwd=cwd or VAULT)
    out = []
    try:
        for i, (method, params) in enumerate(requests, 1):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method,
                                      "params": params or {}}) + "\n")
            p.stdin.flush()
            line = p.stdout.readline()
            out.append(json.loads(line) if line.strip() else None)
    finally:
        try:
            p.stdin.close()
        except Exception:                                    # noqa: BLE001
            pass
        try:
            p.wait(timeout=30)
        except Exception:                                    # noqa: BLE001
            p.kill()
    return out


def _cache_identity():
    """缓存身份：**答案 schema 版本 + 冻结语料版本**。

    为什么必须进 key（Phase 5A 实测踩过）：缓存原实现只按 (question, options) 取 key，
    于是 schema v1 → v1.1 之后，跨层同一性套件读到的是**上一代 payload**（没有
    `audit_diagnostics`），把「产品变了」误报成「跨层不一致」。缓存必须随
    schema 与冻结身份一起失效。
    """
    ident = {"api": None, "schema": None, "freeze": None}
    try:
        import scholarly_api as _api
        ident["api"] = getattr(_api, "API_VERSION", None)
    except Exception:                                                     # noqa: BLE001
        pass
    try:
        from scholarly_api import objects as _objs
        ident["schema"] = _objs.SCHEMA_VERSIONS.get("FinalScholarlyAnswer")
    except Exception:                                                     # noqa: BLE001
        pass
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        vault = os.path.normpath(os.path.join(here, "..", ".."))
        with open(os.path.join(vault, "_data", "core_freeze",
                              "scholarly_core_freeze_v1.json"), encoding="utf-8") as fh:
            ident["freeze"] = (json.load(fh).get("components") or {}).get(
                "corpus_inventory_hash")
    except Exception:                                                     # noqa: BLE001
        pass
    return ident


def cache_key(question, options):
    blob = json.dumps({"q": question,
                       "o": {k: options.get(k) for k in sorted(options)},
                       "id": _cache_identity()},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def cached_research(question, options=None):
    """跨进程磁盘缓存：同一 (question, options) 只真正跑一次核心。"""
    options = dict(options or {})
    options.setdefault("provider", "mock")
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "%s.json" % cache_key(question, options))
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    res = api.research(question, options)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    return res


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def core_freeze_ok():
    return verify_core_freeze()[0]
