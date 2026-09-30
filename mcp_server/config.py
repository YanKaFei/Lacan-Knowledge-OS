#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_server.config — 4D.1 常量、上限、超时、provider 策略（全部可环境变量覆盖）。"""
from __future__ import annotations

import hashlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)

SERVER_NAME = "lacan-research"
SERVER_VERSION = "1.0.0"
MCP_VERSION = "mcp/v1"
API_VERSION = "scholarly-api/v1"

# 与 DSH 侧 MCP client（SDK 1.30.0）对齐；沿用项目既有约定
PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26",
                               "2024-11-05", "2024-10-07"]

# ── 工具上限（防止一次拖走整个 seminar）
MAX_CONTEXT_BEFORE = 20
MAX_CONTEXT_AFTER = 20
MAX_SEARCH_LIMIT = 100
DEFAULT_SEARCH_LIMIT = 10
# 带后置过滤时，先多取一些再过滤（并在 meta 里如实报告 post_filtered）
POST_FILTER_OVERFETCH = 4

# ── 超时（§28：分类超时，不用统一 10 秒）
def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


LOOKUP_TIMEOUT_S = _env_int("LACAN_MCP_LOOKUP_TIMEOUT_S", 30)
SEARCH_TIMEOUT_S = _env_int("LACAN_MCP_SEARCH_TIMEOUT_S", 60)
RESEARCH_TIMEOUT_MOCK_S = _env_int("LACAN_MCP_RESEARCH_TIMEOUT_MOCK_S", 300)
RESEARCH_TIMEOUT_LLM_S = _env_int("LACAN_MCP_RESEARCH_TIMEOUT_LLM_S", 1800)

# ── provider 策略：默认 mock；llm 必须显式请求
DEFAULT_PROVIDER = "mock"
ALLOWED_PROVIDERS = ("mock", "llm")

# ── audit（§19）
AUDIT_DIR = os.path.join(VAULT, "_data", "product_audit", "mcp")
AUDIT_ENABLED = os.environ.get("LACAN_MCP_AUDIT", "1") not in ("0", "false", "False")
# 默认只记 question_hash；置 1 才记全文
AUDIT_RECORD_QUESTION = os.environ.get("LACAN_MCP_AUDIT_QUESTION", "0") in (
    "1", "true", "True")

# ── core freeze guard（§27）
FREEZE_MANIFEST = os.path.join(VAULT, "_data", "core_freeze",
                               "scholarly_core_freeze_v1.json")
FREEZE_TOOL = os.path.join(VAULT, "_scripts", "_tools", "core_freeze.py")
FREEZE_GUARD_ENABLED = os.environ.get("LACAN_MCP_FREEZE_GUARD", "1") not in (
    "0", "false", "False")

# ── 领域 id 语法（§30：只接受领域参数，禁止路径/命令/SQL）
PASSAGE_ID_RE = r"^passage\.[A-Za-z0-9][A-Za-z0-9._-]{0,120}$"
CONCEPT_ID_RE = r"^(concept|term)\.[a-z0-9][a-z0-9._-]{0,80}$"
SEMINAR_ID_RE = r"^seminar\.[A-Za-z0-9][A-Za-z0-9._-]{0,20}$"
SESSION_ID_RE = r"^session\.[A-Za-z0-9][A-Za-z0-9._-]{0,40}$"


def question_hash(q: str) -> str:
    return hashlib.sha256((q or "").encode("utf-8")).hexdigest()
