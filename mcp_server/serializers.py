#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_server.serializers — 4D.1 §7/§25：MCP 信封与跨层同一性。

硬不变式（§7/§25）：

    core final answer  ==  api final answer  ==  MCP result 中的学术载荷

因此 `envelope_ok(result, ...)` 把 scholarly_api 的返回**原样**放入
`result`；transport 信息（request_id / duration / versions / provider /
dense_available / post_filtered …）只能出现在 `meta`。**不得**重排、裁剪、
摘要或改写任何 scholarly 字段。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import config as C


def new_request_id():
    return "mcp-%s" % uuid.uuid4().hex[:16]


def base_meta(tool, request_id, duration_ms=None, provider=None, extra=None):
    meta = {
        "tool": tool,
        "request_id": request_id,
        "api_version": C.API_VERSION,
        "mcp_version": C.MCP_VERSION,
        "server": {"name": C.SERVER_NAME, "version": C.SERVER_VERSION},
        "core_freeze_version": _freeze_version(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if duration_ms is not None:
        meta["duration_ms"] = int(duration_ms)
    if provider is not None:
        meta["provider"] = provider
    if extra:
        meta.update(extra)
    return meta


def envelope_ok(result, meta):
    return {"ok": True, "result": result, "meta": meta}


def envelope_err(error_dict, meta):
    return {"ok": False, "error": error_dict, "meta": meta}


def tool_response(envelope):
    """→ MCP tools/call 结果形状（与项目既有 server.py 约定一致）。"""
    is_err = not envelope.get("ok", False)
    payload = json.dumps(envelope, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": payload[:120000]}],
        "structuredContent": envelope,
        "isError": bool(is_err),
    }


def scholarly_payload(envelope):
    """跨层同一性测试用：取出**纯学术载荷**（不含 meta）。"""
    return envelope.get("result")


def _freeze_version():
    try:
        from .guard import core_freeze_version
        return core_freeze_version()
    except Exception:                            # noqa: BLE001
        return None
