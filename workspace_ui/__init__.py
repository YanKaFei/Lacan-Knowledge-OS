#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui — Phase 4D.2：Research Workspace MVP（产品层）

    Browser  →  workspace_ui.server（HTTP + ViewModel）  →  MCP（stdio）  →  scholarly_api  →  FROZEN CORE

纪律
────
* UI 只是**可视化与交互层**：`core == api == MCP == UI scholarly content`。
* ViewModel 由 Python 侧计算（可测），前端只做**哑渲染**（textContent，禁止 innerHTML 注入）。
* 历史/笔记只写 `USER_WORKSPACE`（`_workspace/**`），永不写核心。
"""
WORKSPACE_VERSION = "workspace-ui/v1"
__all__ = ["WORKSPACE_VERSION"]
