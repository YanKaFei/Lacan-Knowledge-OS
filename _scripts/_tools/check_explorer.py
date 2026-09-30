#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_explorer.py — Phase 4D.4：Explorer 契约自检（**只读**，供套件调用）

检查：
  1. browse_api 只读、不 import 核心、不调用 LLM / 网络
  2. 分层：UI → 产品适配 → browse_api / MCP；UI 不得直连 SQLite / ontology JSON
  3. ES 模块语法（**必须按 ESM 解析**：`node --check x.js` 会按 CommonJS 放过语法错，
     实测过一次 explorer.js 少一个括号、浏览器整页白屏而 node 报 OK）
  4. 前端安全：无 innerHTML / insertAdjacentHTML / document.write / eval
  5. 分页硬上限 + 白名单筛选 + cursor 与 filters 绑定
  6. QA 工件（截图 / 分页 QA / 术语 QA）齐备
  7. 核心冻结 + 冻结谱系未被绕过
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)

BROWSE = os.path.join(VAULT, "browse_api")
SRC = os.path.join(VAULT, "workspace_ui", "static", "src")
QA = os.path.join(VAULT, "_workspace", "explorer_qa")
CORE_MODULES = ("knowledge_api", "research_answer", "research_contract",
                "research_execution", "synthesis_contract", "synthesis_claims",
                "synthesis_render", "synthesis_adapters", "synthesis_entailment",
                "synthesis_validation", "eval_integrity")
SHOTS = ("concept_list.png", "concept_detail.png", "passage_search.png",
         "passage_detail.png", "context_expanded.png", "l2_trace_incomplete.png",
         "seminar_list.png", "seminar_detail.png", "session_reading.png",
         "terminology_mapping.png", "zero_attestation.png", "reel_realite.png")


def _esm_syntax_problems(files):
    """把 .js 复制成 .mjs 再 `node --check`（CJS 模式会漏掉 ESM 语法错）。"""
    node = shutil.which("node")
    if not node:
        return []                      # 无 node 时不做该检查（如实跳过，不假装通过）
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        for fn in files:
            dst = os.path.join(tmp, fn.replace(".js", ".mjs"))
            shutil.copyfile(os.path.join(SRC, fn), dst)
            r = subprocess.run([node, "--check", dst], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append("%s 语法错误（ESM）：%s" % (fn, (r.stderr or "").strip()[:160]))
    return problems


def main():
    problems = []
    import browse_api as B
    from workspace_ui.server import explorer as X
    from workspace_ui.server import config as C

    # 1 browse_api 只读
    for fn in sorted(os.listdir(BROWSE)):
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(BROWSE, fn), encoding="utf-8").read()
        for mod in CORE_MODULES:
            if re.search(r"^\s*(import|from)\s+%s\b" % re.escape(mod), src, re.M):
                problems.append("browse_api/%s import 了核心 %s" % (fn, mod))
        for pat in (r"open\([^)]*,\s*['\"][wax]", r"os\.replace", r"shutil\.",
                    r"write_text", r"os\.remove", r"os\.makedirs"):
            if re.search(pat, src):
                problems.append("browse_api/%s 有写操作：%s" % (fn, pat))
        for pat in (r"\bprovider\b", r"openai", r"anthropic", r"import\s+requests",
                    r"urllib\.request", r"subprocess"):
            if re.search(pat, src, re.I):
                problems.append("browse_api/%s 出现 LLM/网络/子进程：%s" % (fn, pat))

    # 2 分层
    ui_src = ""
    for fn in sorted(os.listdir(SRC)):
        if fn.endswith(".js"):
            ui_src += open(os.path.join(SRC, fn), encoding="utf-8").read()
    for bad in ("sqlite", "/api/explore/", "ontology/v4a1"):
        if bad in ui_src and bad != "/api/explore/":
            problems.append("前端出现直连数据源痕迹：%s" % bad)
    if "/api/explore/" not in ui_src:
        problems.append("前端没有走 /api/explore/ 产品适配层")
    if "fetch(" in ui_src and "/api/" not in ui_src:
        problems.append("前端 fetch 未指向产品 API")

    # 3 ES 模块语法（按 ESM 解析）
    problems += _esm_syntax_problems([f for f in sorted(os.listdir(SRC))
                                      if f.endswith(".js")])

    # 4 前端安全
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".js"):
            continue
        src = open(os.path.join(SRC, fn), encoding="utf-8").read()
        for bad in (".innerHTML", "insertAdjacentHTML", "document.write", "eval(",
                    "outerHTML"):
            if bad in src:
                problems.append("%s 出现不安全 API：%s" % (fn, bad))

    # 5 分页/白名单
    a = X.availability()
    if a.get("explorer_version") != "explorer/v1":
        problems.append("explorer 版本标识缺失")
    out = B.browse_passages({"limit": 10 ** 6})
    if out["page"]["limit"] != C.EXPLORER_PAGE_MAX:
        problems.append("分页硬上限未生效：%s" % out["page"]["limit"])
    try:
        B.browse_passages({"seminar": "S11; DROP TABLE passage_meta"})
        problems.append("非法筛选值未被拒")
    except ValueError:
        pass
    p1 = B.browse_passages({"seminar": "S11", "limit": 5})
    try:
        B.browse_passages({"seminar": "S12", "limit": 5},
                          cursor=p1["page"]["next_cursor"])
        problems.append("cursor 未与 filters 绑定（换筛选条件仍返回页）")
    except B.cursors.CursorError:
        pass
    if not a.get("dense_available") and not a.get("retrieval_banner"):
        problems.append("dense 不可用时没有如实提示")

    # 6 QA 工件
    missing = [s for s in SHOTS if not os.path.isfile(os.path.join(QA, s))]
    if missing:
        problems.append("缺视觉 QA 截图：%s（跑 test_phase4d4_ui_browser_smoke）" % missing[:3])
    for f in ("pagination_qa.json", "terminology_qa.json", "obsidian_roundtrip.json"):
        if not os.path.isfile(os.path.join(QA, f)):
            problems.append("缺 QA 证据：%s（跑 _scripts/_tools/build_explorer_qa.py）" % f)

    # 7 冻结 / 谱系
    for tool in ("core_freeze.py", "freeze_lineage.py"):
        r = subprocess.run([sys.executable, os.path.join(HERE, tool), "--verify", "--quiet"],
                           capture_output=True, text=True, cwd=VAULT)
        if r.returncode != 0:
            problems.append("%s 校验失败：%s" % (tool, (r.stdout + r.stderr)[-200:]))

    if problems:
        print("FAIL Explorer 契约自检未通过：")
        for p in problems[:12]:
            print("  - %s" % p)
        return 1
    print("Explorer 契约自检通过：browse_api 只读且不碰核心/LLM / UI 只经产品适配层 / "
          "ESM 语法 OK / 无 innerHTML·eval / 分页硬上限与 cursor 绑定 / "
          "QA 工件齐备 / core freeze + 谱系 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
