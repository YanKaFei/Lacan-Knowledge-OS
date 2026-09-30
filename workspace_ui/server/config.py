#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace_ui.server.config — 4D.2 常量（路径 / 上限 / 超时 / provider 策略）。"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_UI = os.path.dirname(HERE)
VAULT = os.path.dirname(WORKSPACE_UI)

WORKSPACE_VERSION = "workspace-ui/v1"
STATIC_DIR = os.path.join(WORKSPACE_UI, "static")

# 历史/工作区数据：**USER_WORKSPACE**（§24/§42），永不写核心
HISTORY_DIR = os.path.join(VAULT, "_workspace", "history")
# 产品级请求缓存（同一冻结输入 → 同一输出；进程内，可重建）
CACHE_ENABLED = os.environ.get("LACAN_UI_CACHE", "1") not in ("0", "false", "False")

# 服务
DEFAULT_HOST = os.environ.get("LACAN_UI_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("LACAN_UI_PORT", "3090"))

# 上限（§41：永不把 249k passages 塞进浏览器）
MAX_QUESTION_LEN = 2000
MAX_CONTEXT_BEFORE = 20
MAX_CONTEXT_AFTER = 20
DEFAULT_CONTEXT = 3
MAX_HISTORY_ITEMS = 200
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024

# MCP server
MCP_SERVER = os.environ.get("LACAN_UI_MCP_SERVER",
                            os.path.join(VAULT, "mcp_server", "server.py"))
MCP_TIMEOUT_S = int(os.environ.get("LACAN_UI_MCP_TIMEOUT_S", "900"))

# ── Explorer（Phase 4D.4 §38/§44/§62）
#    分页是强制的：249,105 段语料，绝不允许浏览器预载全量。
EXPLORER_VERSION = "explorer/v1"
EXPLORER_PAGE_MAX = 50              # 硬上限（服务端夹紧，客户端无法绕过）
EXPLORER_PAGE_DEFAULT = 20
EXPLORER_READING_PAGE = 10          # 阅读模式每页段数
EXPLORER_EVIDENCE_LIMIT = 20        # 概念详情里的 ontology evidence 样本上限
EXPLORER_SEED_CHARS = 400           # Research from passage 的 seed 长度上限
EXPLORER_CONTEXT_DEFAULT = 2

# provider（§10）：开发默认 mock；真实 LLM 必须显式选择
DEFAULT_PROVIDER = "mock"
ALLOWED_PROVIDERS = ("mock", "llm")

# UI 可见 mode（§9）：Auto / Quick / Scholarly + Advanced
SIMPLE_MODES = ("auto", "quick", "scholarly")
ADVANCED_MODES = ("concept_definition", "concept_relation", "comparison",
                  "diachronic", "seminar_specific", "case_research",
                  "freud_to_lacan", "philosophy_to_lacan", "topology_matheme",
                  "translation_terminology")

# 错误 → 用户可见文案（§29）
ERROR_UX = {
    "PROVIDER_UNAVAILABLE": {
        "title": "Real LLM provider is unavailable.",
        "body": ("The Scholarly Core needs an explicitly configured provider "
                 "credential for real-LLM research. It will not answer from model "
                 "knowledge instead."),
        "research_disabled": False,
    },
    "CORE_FROZEN_MISMATCH": {
        "title": "Scholarly Core integrity verification failed.",
        "body": ("The frozen core hashes no longer match the freeze manifest, so "
                 "research has been disabled. Browsing saved history is still "
                 "available. Core changes must go through a CORE_CHANGE_REQUEST and "
                 "a new scholarly remediation phase."),
        "research_disabled": True,
    },
    "NOT_FOUND": {
        "title": "Passage not found.",
        "body": "That passage id does not exist in the corpus store.",
        "research_disabled": False,
    },
    "SCHEMA_VALIDATION_FAILED": {
        "title": "The request did not pass schema validation.",
        "body": "Check the question and the research options, then try again.",
        "research_disabled": False,
    },
    "POLICY_DENIED": {
        "title": "The request contained a disallowed value.",
        "body": "Only domain parameters are accepted (no paths, commands or SQL).",
        "research_disabled": False,
    },
    "INDEX_UNAVAILABLE": {
        "title": "The search index is unavailable.",
        "body": "The lexical index can be rebuilt from the corpus (rebuildable data).",
        "research_disabled": False,
    },
    "TIMEOUT": {
        "title": "The research call timed out.",
        "body": "Stopping the wait does not terminate backend execution.",
        "research_disabled": False,
    },
    "INTERNAL_ERROR": {
        "title": "An internal error occurred.",
        "body": "No traceback is shown here by design; see Advanced / Audit.",
        "research_disabled": False,
    },
    "INVALID_REQUEST": {
        "title": "The research request is invalid.",
        "body": "Provide a question of at least 4 characters.",
        "research_disabled": False,
    },
}
DEFAULT_ERROR_UX = {
    "title": "The research call failed.",
    "body": "See Advanced / Audit for the structured error.",
    "research_disabled": False,
}
