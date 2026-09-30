#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_server.errors — 4D.1 错误契约（§17）：统一 ApiError 形状，绝不外泄 traceback。"""
from __future__ import annotations

# JSON-RPC 标准错误码（协议级）
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# 工具级错误码（§17）
CODES = (
    "INVALID_REQUEST",
    "NOT_FOUND",
    "SCHEMA_VALIDATION_FAILED",
    "PROVIDER_UNAVAILABLE",
    "CORE_FROZEN_MISMATCH",
    "INDEX_UNAVAILABLE",
    "POLICY_DENIED",
    "INTERNAL_ERROR",
    "TIMEOUT",
)

# scholarly_api 的 error_code → 本层错误码
_API_TO_MCP = {
    "INVALID_RESEARCH_REQUEST": "INVALID_REQUEST",
    "INVALID_PROVIDER": "INVALID_REQUEST",
    "PASSAGE_NOT_FOUND": "NOT_FOUND",
    "SEMINAR_NOT_FOUND": "NOT_FOUND",
    "PROVIDER_UNAVAILABLE": "PROVIDER_UNAVAILABLE",
    "SEARCH_FAILED": "INDEX_UNAVAILABLE",
    "CORE_EXECUTION_FAILED": "INTERNAL_ERROR",
    "PROVIDER_CALL_FAILED": "INTERNAL_ERROR",
    "SYNTHESIS_FAILED": "INTERNAL_ERROR",
    "VALIDATION_PIPELINE_FAILED": "INTERNAL_ERROR",
}


class McpError(Exception):
    """工具级错误 → 结构化 `{ok:false, error:{...}}`（**不是** traceback）。"""

    def __init__(self, code, message, detail=None, resolution=None):
        super().__init__(message)
        self.code = code if code in CODES else "INTERNAL_ERROR"
        self.message = message
        self.detail = detail or {}
        self.resolution = resolution or ""

    def to_dict(self):
        return {"code": self.code, "message": self.message,
                "detail": self.detail, "resolution": self.resolution}


class ProtocolError(Exception):
    """协议级错误 → JSON-RPC error 对象（未知 tool / 输入不合 schema）。"""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def from_api_error(err):
    """scholarly_api 的 ApiError dict → McpError。"""
    code = _API_TO_MCP.get(err.get("error_code"), "INTERNAL_ERROR")
    return McpError(code, err.get("message") or "核心返回错误",
                    detail={"api_error_code": err.get("error_code"),
                            "detail": err.get("detail") or {}},
                    resolution=err.get("resolution") or "")
