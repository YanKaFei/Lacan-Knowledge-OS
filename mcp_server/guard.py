#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_server.guard — 4D.1 §27：启动期 core freeze 校验（fail closed）。

实现方式：**子进程**调用冻结校验器（不是 import 核心模块），因此本包仍然
只依赖 scholarly_api，不破坏 §5 的 import 边界。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from . import config as C
from .errors import McpError


def core_freeze_version():
    if not os.path.isfile(C.FREEZE_MANIFEST):
        return None
    try:
        with open(C.FREEZE_MANIFEST, encoding="utf-8") as f:
            return json.load(f).get("freeze_version")
    except Exception:  # noqa: BLE001
        return None


def core_status():
    if not os.path.isfile(C.FREEZE_MANIFEST):
        return None
    try:
        with open(C.FREEZE_MANIFEST, encoding="utf-8") as f:
            return json.load(f).get("scholarly_status")
    except Exception:  # noqa: BLE001
        return None


def verify_core_freeze(timeout_s=180):
    """→ (ok, detail)。子进程跑 `core_freeze.py --verify`；任何异常都算 fail。"""
    if not os.path.isfile(C.FREEZE_TOOL):
        return False, {"reason": "MISSING_FREEZE_TOOL", "path": C.FREEZE_TOOL}
    try:
        r = subprocess.run([sys.executable, C.FREEZE_TOOL, "--verify"],
                           capture_output=True, text=True, cwd=C.VAULT,
                           timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001
        return False, {"reason": "FREEZE_VERIFY_EXCEPTION", "error": str(exc)[:200]}
    if r.returncode != 0:
        return False, {"reason": "FREEZE_DRIFT",
                       "stdout": (r.stdout or "").strip()[-600:],
                       "stderr": (r.stderr or "").strip()[-300:]}
    return True, {"freeze_version": core_freeze_version(),
                  "scholarly_status": core_status()}


def assert_core_frozen(state=None):
    """未通过即抛 CORE_FROZEN_MISMATCH（工具 fail closed）。"""
    if not C.FREEZE_GUARD_ENABLED:
        return {"checked": False, "reason": "GUARD_DISABLED_BY_ENV"}
    if state is not None and state.get("ok"):
        return state.get("detail") or {"checked": True}
    ok, detail = verify_core_freeze()
    if not ok:
        raise McpError("CORE_FROZEN_MISMATCH",
                       "Scholarly Core 冻结校验未通过，已拒绝服务（fail closed）",
                       detail=detail,
                       resolution="运行 core_freeze.py --verify 定位漂移；"
                                  "核心改动必须走 CORE_CHANGE_REQUEST + 新的 "
                                  "remediation phase")
    return detail
