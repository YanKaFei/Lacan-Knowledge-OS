#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server — Phase 4D.1：Scholarly Research MCP Service（产品层）

    DeepSeek Harness / Agent / UI / Obsidian
                    ↓  MCP（JSON-RPC 2.0 over stdio）
              mcp_server/            ← 本包：transport + schema + audit
                    ↓  只允许 import scholarly_api
              scholarly_api v1       ← Phase 4D.0 冻结的稳定访问层
                    ↓
              FROZEN SCHOLARLY CORE

MCP 层**不是**研究引擎：它只做 transport / schema 校验 / 编排 / 审计。
静态测试断言本包不得 import 任何 scholarly core internals。
"""
MCP_VERSION = "mcp/v1"
__all__ = ["MCP_VERSION"]
