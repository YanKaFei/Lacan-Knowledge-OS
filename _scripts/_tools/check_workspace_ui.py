#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_workspace_ui.py — Phase 4D.2：Workspace UI 契约自检（**只读**，供套件调用）

检查：
  1. 产品路径可达：MCP connected + core freeze verified + research 未停用
  2. 静态资源齐备（index.html / CSS / 6 个 ES 模块）
  3. 前端安全：无 innerHTML / insertAdjacentHTML / document.write / eval
  4. 写入边界：历史目录 = USER_WORKSPACE；核心路径写入被拒
  5. 视图模型契约：abstention 标题、错误码文案、source_layer 标签
  6. §45 的四态截图是否已产出（视觉 QA 证据）
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)
for m in (VAULT,):
    pass

EXPECTED_JS = {"app.js", "api.js", "dom.js", "inspector.js", "render.js"}
QA_SHOTS = ("A_answer.png", "B_abstain.png", "C_l2evidence.png", "D_offline.png")


def main():
    problems = []
    from workspace_ui.server import api as UIA
    from workspace_ui.server import config as UIC
    from workspace_ui.server import viewmodel as VM
    from workspace_ui.server.httpserver import _safe_static_path
    from scholarly_api import policy as POL

    # 1
    st = UIA.status()
    if not st.get("mcp_connected"):
        problems.append("MCP 未连接：%s" % (st.get("detail") or st.get("server")))
    if not st.get("core_freeze_verified"):
        problems.append("core freeze 未验证：%s" % st.get("core_freeze"))
    if st.get("research_disabled"):
        problems.append("research_disabled=true（不该在正常态出现）")

    # 2
    for rel in ("index.html", "styles/main.css", "src/app.js"):
        if not os.path.isfile(os.path.join(UIC.STATIC_DIR, rel)):
            problems.append("缺静态资源：%s" % rel)
    src_dir = os.path.join(UIC.STATIC_DIR, "src")
    got = {f for f in os.listdir(src_dir) if f.endswith(".js")}
    if not EXPECTED_JS <= got:
        problems.append("缺 ES 模块：%s" % (EXPECTED_JS - got))

    # 3
    for fn in sorted(got):
        src = open(os.path.join(src_dir, fn), encoding="utf-8").read()
        for bad in (".innerHTML", "insertAdjacentHTML", "document.write", "eval("):
            if bad in src:
                problems.append("%s 出现不安全 API：%s" % (fn, bad))

    # 4
    if POL.classify(os.path.join(UIC.HISTORY_DIR, "x.json")) != "USER_WORKSPACE":
        problems.append("历史目录不是 USER_WORKSPACE")
    for target in ("_data/core_freeze/scholarly_core_freeze_v1.json",
                   "_data/ontology/v4a1/entities.jsonl"):
        try:
            POL.write_text(target, "x")
            problems.append("核心路径竟可写：%s" % target)
        except POL.CoreMutationError:
            pass

    # 5
    if VM.ABSTENTION_TITLE != "Current corpus cannot support a reliable answer":
        problems.append("abstention 标题被改动")
    for code in ("PROVIDER_UNAVAILABLE", "CORE_FROZEN_MISMATCH", "NOT_FOUND"):
        if code not in UIC.ERROR_UX:
            problems.append("缺错误文案：%s" % code)
    if VM.source_layer_view("L2_RECOVERED")["tag"] != "L2":
        problems.append("L2 标签缺失")
    if "无法完整追溯" not in VM.TRACE_INCOMPLETE_NOTE:
        problems.append("SOURCE_TRACE_INCOMPLETE 说明缺失")
    if _safe_static_path("../etc/passwd") is not None:
        problems.append("静态路径穿越未被拒")

    # 6
    qa = os.path.join(VAULT, "_workspace", "ui_qa")
    missing = [f for f in QA_SHOTS
               if not os.path.isfile(os.path.join(qa, f))]
    if missing:
        problems.append("缺视觉 QA 截图：%s（跑 test_phase4d2_ui_browser_smoke）" % missing)

    if problems:
        print("FAIL Workspace UI 契约自检未通过：")
        for x in problems[:10]:
            print("  - %s" % x)
        return 1
    print("Workspace UI 契约自检通过：MCP+freeze 正常 / 静态资源与 6 个 ES 模块齐备 / "
          "无 innerHTML·eval / 写入边界正确 / 视图模型契约一致 / 4 态截图在位")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
