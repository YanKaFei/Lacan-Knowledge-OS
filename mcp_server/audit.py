#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_server.audit — 4D.1 §19：产品级 MCP 审计日志（append-only JSONL）。

* 逐月一个文件：`_data/product_audit/mcp/audit-YYYY-MM.jsonl`
* **默认只记 question_hash**；`LACAN_MCP_AUDIT_QUESTION=1` 才记全文。
* 永不记录 API key / 凭据 / 完整环境变量。
* 写入前走 `scholarly_api.policy.assert_writable()`（该目录已登记为产品自产数据）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from scholarly_api import policy as P

from . import config as C
from .errors import McpError


def audit_path(now=None):
    now = now or datetime.now(timezone.utc)
    return os.path.join(C.AUDIT_DIR, "audit-%s.jsonl" % now.strftime("%Y-%m"))


def record(tool, request_id, success, duration_ms, provider=None,
           answer_state=None, citation_count=None, error_code=None,
           question=None, required_schema=None, extra=None,
           question_sha256=None):
    """写一条审计记录。审计失败**不得**让工具的学术结果失败（尽力而为）。

    `question_sha256`：调用方在「不落问题原文」时给出的**不可逆指纹**
    （§45 `LACAN_AUDIT_LOG_QUESTION=0`）。它优先于本地复算的 `question_hash`，
    这样关掉全文日志时仍可对账。"""
    if question_sha256 is None and question:
        question_sha256 = C.question_hash(question)
    if not C.AUDIT_ENABLED:
        return None
    entry = {
        "schema_version": "mcp-audit/v1",
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "request_schema_version": required_schema or "mcp-tool-input/v1",
        "api_version": C.API_VERSION,
        "mcp_version": C.MCP_VERSION,
        "core_freeze_version": _freeze_version(),
        "provider": provider,
        "success": bool(success),
        "answer_state": answer_state,
        "citation_count": citation_count,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "error_code": error_code,
        "question_hash": question_sha256,
        "question_recorded": bool(question and C.AUDIT_RECORD_QUESTION),
    }
    if C.AUDIT_RECORD_QUESTION and question:
        entry["question"] = question
    if extra:
        entry["extra"] = extra
    path = audit_path()
    try:
        P.assert_writable(path)                 # 闸门：未登记分类即拒绝
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except McpError:
        raise
    except Exception:                            # noqa: BLE001 —— 审计尽力而为
        return None
    return entry


def _freeze_version():
    try:
        from .guard import core_freeze_version   # 局部 import，避免循环
        return core_freeze_version()
    except Exception:                            # noqa: BLE001
        return None
