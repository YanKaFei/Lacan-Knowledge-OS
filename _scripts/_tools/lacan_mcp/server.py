#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — Phase 4A §3 `lacan-kb-mcp`：MCP stdio server（**零依赖**）

为什么手写而不是装 `mcp` Python SDK
────────────────────────────────────
1. 项目对**离线可复现**有硬要求：MCP server 必须能在只有标准库的
   `python3` 下启动（向量路径可以缺席）。多一个依赖就多一个装不上的风险。
2. 本阶段需要的协议面很小：`initialize` / `tools/list` / `tools/call` / `ping`。
3. 手写实现可以被 `mcp-selftest` **逐条测**，协议行为全部可见。

协议事实（**从 DSH 实际使用的 SDK 里读出来的，不是猜的**）
──────────────────────────────────────────────────────────
* DSH 侧：`@deepseek-ai/dsh-mcp-client` 0.1.5-rc.2，依赖
  `@modelcontextprotocol/sdk` **1.30.0**。
* 支持的协议版本：`2025-11-25`（latest）、`2025-06-18`、`2025-03-26`、
  `2024-11-05`、`2024-10-07`。
* stdio 分帧：**一行一条 JSON**（`JSON.stringify(msg) + "\n"`），
  读取端按 `\n` 切分并去掉结尾 `\r`；**不是** LSP 的 Content-Length 头。
* server 必须在 `initialize` 结果里声明 `capabilities.tools`，
  否则 client 会拒绝 `tools/list` / `tools/call`。

本实现**只做 tools**（不做 resources / prompts / sampling / roots）——
`dsh-mcp-client` 的 README 也明确写它只桥接 tools。
本文件顶部列出这一限制，测试也断言 `capabilities` 只有 `tools`。

日志一律走 **stderr**。stdout **只**能出现协议消息，否则 client 解析会炸。
"""

from __future__ import annotations

import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(TOOLS_DIR))
sys.path.insert(0, TOOLS_DIR)
sys.path.insert(0, HERE)

import argcheck                      # noqa: E402
import knowledge_api as api          # noqa: E402
from schemas import TOOL_NAMES, TOOLS  # noqa: E402

SERVER_NAME = "lacan-kb"
SERVER_VERSION = "0.1.0"
# 与 DSH 侧 SDK 1.30.0 的 LATEST_PROTOCOL_VERSION 对齐
PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26",
                               "2024-11-05", "2024-10-07"]

# JSON-RPC 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def log(*a):
    print("[lacan-kb-mcp]", *a, file=sys.stderr, flush=True)


def _tool_by_name(name):
    for t in TOOLS:
        if t["name"] == name:
            return t
    return None


# ─────────────────────────────────────────────────────────── 协议方法

def rpc_initialize(params):
    client_ver = (params or {}).get("protocolVersion")
    negotiated = (client_ver if client_ver in SUPPORTED_PROTOCOL_VERSIONS
                  else PROTOCOL_VERSION)
    log("initialize: client=%r → negotiated=%r" % (client_ver, negotiated))
    return {
        "protocolVersion": negotiated,
        "capabilities": {
            # 只声明 tools —— resources / prompts 本实现不提供
            "tools": {"listChanged": False},
        },
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": (
            "Lacan Knowledge OS 的**只读知识访问层**。"
            "所有 tool 只返回结构化证据（passage_id / provenance / warnings / "
            "evidence_state），**不生成理论文章**。"
            "引用必须使用返回的真实 passage_id；SOURCE_TRACE_INCOMPLETE 与 "
            "ENTITY_COLLISION 会作为 warnings 出现，不要隐藏它们。"),
    }


def rpc_tools_list(params):
    out = []
    for t in TOOLS:
        out.append({
            "name": t["name"],
            "title": t["title"],
            "description": "%s\n\n不用它做什么：%s" % (t["purpose"], t["not_for"]),
            "inputSchema": t["inputSchema"],
            # ⚠️ 不声明 outputSchema：返回的是嵌套的 8-section 结构，
            #    声明了就会让 client 做严格校验，反而容易因小差异失败。
            #    结构化内容放在 structuredContent 里，同时给 text 兜底。
        })
    return {"tools": out}


def rpc_tools_call(params):
    """tools/call。

    ⚠️ 错误分两类，**不能混**（MCP 规范 + 本相位的只读纪律）：

    * **协议错误**（未知 tool、参数不合 schema）→ JSON-RPC error（-32602）。
      规范明确把它们列为 protocol errors；混进 `isError: true` 的结果里，
      客户端就没法区分「你调错了」和「查了但没查到」。
    * **执行结果**（查不到证据、PASSAGE_NOT_FOUND）→ 正常 result，
      用 `warnings` + `evidence_state` 表达 —— 这是**有效回答**，不是错误。
    """
    name = (params or {}).get("name")
    args = (params or {}).get("arguments") or {}
    t = _tool_by_name(name)
    if t is None:
        raise ProtocolError(INVALID_PARAMS,
                            "unknown tool: %r" % (name,),
                            {"code": "UNKNOWN_TOOL", "tool": name,
                             "available": TOOL_NAMES})
    ok, errors = argcheck.validate(args, t["inputSchema"])
    if not ok:
        raise ProtocolError(INVALID_PARAMS,
                            "invalid arguments for %s" % name,
                            {"code": "INVALID_ARGS", "tool": name,
                             "details": errors})
    filled = argcheck.apply_defaults(args, t["inputSchema"])
    try:
        result = api.call(name, filled)
    except Exception as e:
        log("tool %s failed: %s" % (name, traceback.format_exc()[-1200:]))
        return {"content": [{"type": "text", "text": json.dumps(
                    {"error": "TOOL_EXECUTION_ERROR", "tool": name,
                     "message": "%s: %s" % (type(e).__name__, e)},
                    ensure_ascii=False)}],
                "isError": True,
                "structuredContent": {"error": {
                    "code": "TOOL_EXECUTION_ERROR", "tool": name,
                    "message": "%s: %s" % (type(e).__name__, e)}}}
    return {
        "content": [{"type": "text",
                     "text": json.dumps(result, ensure_ascii=False)[:120000]}],
        "structuredContent": result,
        "isError": False,
    }


class ProtocolError(Exception):
    """协议级错误 → JSON-RPC error（区别于 tool 执行结果）。"""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


METHODS = {
    "initialize": rpc_initialize,
    "tools/list": rpc_tools_list,
    "tools/call": rpc_tools_call,
    "ping": lambda params: {},
}


def handle(msg):
    """→ response dict 或 None（通知不需要回应）。"""
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": INVALID_REQUEST, "message": "not an object"}}
    mid = msg.get("id")
    method = msg.get("method")
    if method is None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": INVALID_REQUEST, "message": "missing method"}}
    is_notification = mid is None
    if method.startswith("notifications/"):
        return None
    fn = METHODS.get(method)
    if fn is None:
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": METHOD_NOT_FOUND,
                          "message": "method not found: %s" % method}}
    try:
        result = fn(msg.get("params") or {})
    except ProtocolError as pe:
        if is_notification:
            return None
        err = {"code": pe.code, "message": pe.message}
        if pe.data is not None:
            err["data"] = pe.data
        return {"jsonrpc": "2.0", "id": mid, "error": err}
    except Exception as e:
        log("method %s failed: %s" % (method, traceback.format_exc()[-1200:]))
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": INTERNAL_ERROR,
                          "message": "%s: %s" % (type(e).__name__, e)}}
    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=None, stdout=None):
    """stdio 主循环。**一行一条 JSON**；stdout 只写协议消息。→ 处理的输入行数。"""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    handled = 0
    log("ready (protocol=%s, tools=%d, vector=%s)"
        % (PROTOCOL_VERSION, len(TOOLS),
           api.KB_.vector_status.get("available")))
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": PARSE_ERROR, "message": str(e)}}
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
            continue
        resp = handle(msg)
        handled += 1
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False, separators=(",", ":")) + "\n")
            stdout.flush()
    log("stdin closed, exiting")
    return handled


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--selftest" in argv:
        import selftest
        return selftest.run()
    if "--list-tools" in argv:
        print(json.dumps(rpc_tools_list({}), ensure_ascii=False, indent=1))
        return 0
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
