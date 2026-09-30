#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.server — Phase 4D.1：MCP 兼容服务端（JSON-RPC 2.0 over stdio）

协议面（沿用本项目既有约定 `_scripts/_tools/lacan_mcp/server.py`，§3）：
    initialize / tools/list / tools/call / ping
    * line-delimited JSON，stdout **只**出协议消息；日志走 stderr
    * `capabilities` 只声明 `tools`（resources / prompts 本阶段不提供，§22 optional）
    * 协议版本协商对齐 DSH 侧 SDK 1.30.0：`2025-11-25`

启动即做 core freeze 校验（§27）；不通过 → 所有 tools/call 返回
`CORE_FROZEN_MISMATCH`（fail closed），**不在漂移状态下服务**。

本包**只**依赖 `scholarly_api`（静态测试守着），不 import 任何 core internals。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from mcp_server import config as C                 # noqa: E402
from mcp_server import schemas as S                # noqa: E402
from mcp_server import tools as T                  # noqa: E402
from mcp_server.errors import (                    # noqa: E402
    INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST, METHOD_NOT_FOUND,
    PARSE_ERROR, McpError, ProtocolError,
)
from mcp_server.guard import verify_core_freeze    # noqa: E402

_FREEZE_STATE = {"ok": None, "detail": None}


def log(*a):
    print("[lacan-research-mcp]", *a, file=sys.stderr, flush=True)


# ─────────────────────────────────────────────────────────── 协议方法
def rpc_initialize(params):
    client_ver = (params or {}).get("protocolVersion")
    negotiated = (client_ver if client_ver in C.SUPPORTED_PROTOCOL_VERSIONS
                  else C.PROTOCOL_VERSION)
    log("initialize: client=%r → negotiated=%r" % (client_ver, negotiated))
    guard = _FREEZE_STATE.get("detail") or {}
    return {
        "protocolVersion": negotiated,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": C.SERVER_NAME, "version": C.SERVER_VERSION},
        "instructions": (
            "Lacan Knowledge OS 的**冻结学术研究核心**的产品接口（只读）。"
            "所有工具只调用冻结的 Scholarly Core：返回 validated claims / citations / "
            "provenance / limitations，或在语料无法支持时返回 abstention —— "
            "**弃权会原样传播，任何调用方都不得用自身知识补答**。"
            "引用必须使用返回的真实 passage_id，并可用 lacan.get_passage / "
            "lacan.trace_source 逐级核对；SOURCE_TRACE_INCOMPLETE 必须保留可见。"
            "provider 默认 mock（确定性、离线）；provider=llm 必须显式请求，"
            "凭据缺失时返回 PROVIDER_UNAVAILABLE，而不会回退到模型自身知识。"),
        "meta": {"api_version": C.API_VERSION, "mcp_version": C.MCP_VERSION,
                 "core_freeze": guard},
    }


def rpc_tools_list(params):
    out = []
    for t in S.TOOLS:
        out.append({
            "name": t["name"],
            "title": t["title"],
            "description": "%s\n\n不用它做什么：%s" % (t["purpose"], t["not_for"]),
            "inputSchema": t["inputSchema"],
            # 不声明 outputSchema：结构化内容放在 structuredContent（与既有 server 一致），
            # 输出仍由本服务内部按稳定对象 schema 强校验（§20 fail closed）
        })
    return {"tools": out}


def rpc_tools_call(params):
    """tools/call。

    协议错误（未知 tool / 参数不合 schema）→ JSON-RPC error；
    执行结果（含 NOT_FOUND / PROVIDER_UNAVAILABLE / CORE_FROZEN_MISMATCH）
    → 正常 result，`isError: true` + 结构化 error（§17）。
    """
    name = (params or {}).get("name")
    args = (params or {}).get("arguments") or {}
    if S.tool_by_name(name) is None:
        raise ProtocolError(INVALID_PARAMS, "unknown tool: %r" % (name,),
                            {"code": "UNKNOWN_TOOL", "tool": name,
                             "available": S.TOOL_NAMES})
    if not isinstance(args, dict):
        raise ProtocolError(INVALID_PARAMS, "arguments 必须是 object",
                            {"code": "INVALID_ARGS", "tool": name})
    try:
        envelope = T.call_tool(name, args, freeze_state=_FREEZE_STATE)
    except ProtocolError:
        raise
    except Exception:                                  # noqa: BLE001
        log("tool %s crashed:\n%s" % (name, traceback.format_exc()[-1500:]))
        raise ProtocolError(INTERNAL_ERROR, "tools/call 内部错误",
                            {"code": "INTERNAL_ERROR", "tool": name})
    from mcp_server.serializers import tool_response
    return tool_response(envelope)


METHODS = {
    "initialize": rpc_initialize,
    "tools/list": rpc_tools_list,
    "tools/call": rpc_tools_call,
    "ping": lambda params: {},
    "notifications/initialized": lambda params: None,
}


def handle(msg):
    """单条 JSON-RPC 消息 → 响应（通知返回 None）。"""
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": INVALID_REQUEST, "message": "消息必须是 object"}}
    mid = msg.get("id")
    method = msg.get("method")
    if not method:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": INVALID_REQUEST, "message": "缺 method"}}
    if method.startswith("notifications/"):
        return None
    fn = METHODS.get(method)
    if fn is None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": METHOD_NOT_FOUND, "message": "未知方法：%s" % method}}
    try:
        result = fn(msg.get("params") or {})
        if result is None:
            return None
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except ProtocolError as e:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": e.code, "message": e.message, "data": e.data}}
    except McpError as e:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": INVALID_PARAMS, "message": e.message,
                          "data": e.to_dict()}}
    except Exception as e:                             # noqa: BLE001
        log("method %s crashed:\n%s" % (method, traceback.format_exc()[-1500:]))
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": INTERNAL_ERROR,
                          "message": "内部错误：%s" % type(e).__name__}}


def startup_freeze_check(force=False):
    """启动期 core freeze 校验（§27）。结果缓存，供每个 tools/call 复用。"""
    if _FREEZE_STATE["ok"] is not None and not force:
        return _FREEZE_STATE
    ok, detail = verify_core_freeze()
    _FREEZE_STATE["ok"] = bool(ok)
    _FREEZE_STATE["detail"] = detail
    if ok:
        log("core freeze OK：%s（%s）" % (detail.get("freeze_version"),
                                          detail.get("scholarly_status")))
    else:
        log("core freeze FAILED：%s" % json.dumps(detail, ensure_ascii=False)[:400])
    return _FREEZE_STATE


def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    startup_freeze_check()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:                              # noqa: BLE001
            stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": PARSE_ERROR, "message": "JSON 解析失败"}},
                ensure_ascii=False) + "\n")
            stdout.flush()
            continue
        resp = handle(msg)
        if resp is None:
            continue
        stdout.write(json.dumps(resp, ensure_ascii=False, separators=(",", ":")) + "\n")
        stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lacan Research MCP server (stdio)")
    ap.add_argument("--selftest", action="store_true",
                    help="打印工具清单并做一次 freeze 校验后退出")
    ap.add_argument("--no-freeze-guard", action="store_true")
    a = ap.parse_args(argv)
    if a.no_freeze_guard:
        os.environ["LACAN_MCP_FREEZE_GUARD"] = "0"
        C.FREEZE_GUARD_ENABLED = False
    if a.selftest:
        st = startup_freeze_check()
        print(json.dumps({"server": C.SERVER_NAME, "version": C.SERVER_VERSION,
                          "protocol": C.PROTOCOL_VERSION,
                          "tools": S.TOOL_NAMES,
                          "core_freeze_ok": st["ok"]},
                         ensure_ascii=False, indent=1))
        return 0 if st["ok"] else 3
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
