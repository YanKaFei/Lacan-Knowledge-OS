#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_mcp_contract.py — Phase 4D.1：MCP 契约自检（**只读**，供套件调用）

检查：
  1. 工具集正好是 v1 的 10 个，且每个工具描述/输入 schema 齐备、additionalProperties=false
  2. initialize 只声明 capabilities.tools，协议版本协商正确
  3. 默认 provider = mock（真实 LLM 必须显式请求）
  4. 进程内 tools/call 的信封形状（ok/result/meta）与 meta 版本字段
  5. fail closed：未知工具是协议错误；越界参数是 SCHEMA_VALIDATION_FAILED
  6. 审计日志可解析、字段齐备、不含凭据样式字符串
  7. core freeze 校验通过（MCP 不在漂移状态下服务）
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)

EXPECTED = ["lacan.research", "lacan.search_passages", "lacan.get_passage",
            "lacan.get_context", "lacan.get_concept", "lacan.get_seminar",
            "lacan.trace_source", "lacan.compare_terms",
            "lacan.research_diachronic", "lacan.research_translation"]
AUDIT_MIN_FIELDS = ("request_id", "timestamp", "tool", "request_schema_version",
                    "api_version", "mcp_version", "provider", "success",
                    "answer_state", "citation_count", "duration_ms", "error_code",
                    "question_hash")
SECRETISH = re.compile(r"(sk-[A-Za-z0-9]{8,}|DEEPSEEK_API_KEY\s*[:=]|API_KEY\s*[:=])")


def main():
    problems = []
    from mcp_server import schemas as S
    from mcp_server import server as SRV
    from mcp_server import tools as T
    from mcp_server.guard import verify_core_freeze

    # 1
    if S.TOOL_NAMES != EXPECTED:
        problems.append("工具集不符：%s" % S.TOOL_NAMES)
    for t in S.TOOLS:
        if not t.get("description") and not (t.get("purpose") and t.get("not_for")):
            problems.append("%s 缺描述" % t["name"])
        if t["inputSchema"].get("additionalProperties", True):
            problems.append("%s inputSchema 非严格" % t["name"])
        if "inputSchema" not in t:
            problems.append("%s 缺 inputSchema" % t["name"])

    # 2
    r = SRV.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25"}})
    res = r.get("result") or {}
    if list((res.get("capabilities") or {}).keys()) != ["tools"]:
        problems.append("capabilities 只应声明 tools：%s" % res.get("capabilities"))
    if res.get("protocolVersion") != "2025-11-25":
        problems.append("协议协商失败：%s" % res.get("protocolVersion"))
    tl = SRV.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    if len((tl.get("result") or {}).get("tools") or []) != 10:
        problems.append("tools/list 数量不是 10")

    # 3
    ok, errs, filled = S.validate_input("lacan.research", {"question": "objet a 是什么？"})
    if not ok or filled.get("provider") != "mock":
        problems.append("provider 默认值不是 mock：%s %s" % (ok, errs))

    # 4
    env = T.call_tool("lacan.get_passage",
                      {"passage_id": "passage.S11.unknown.P2253"}, audit=False)
    if not env.get("ok"):
        problems.append("get_passage 失败：%s" % env.get("error"))
    else:
        for k in ("request_id", "api_version", "mcp_version", "core_freeze_version"):
            if k not in env["meta"]:
                problems.append("meta 缺 %s" % k)
        if env["result"].get("passage_id") != "passage.S11.unknown.P2253":
            problems.append("get_passage 返回错 passage")

    # 5
    bad = SRV.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": "lacan.nope", "arguments": {}}})
    if (bad.get("error") or {}).get("code") != -32602:
        problems.append("未知工具未按协议错误返回：%s" % bad)
    over = T.call_tool("lacan.get_context",
                       {"passage_id": "passage.S11.unknown.P2253", "before": 999},
                       audit=False)
    if over.get("ok") or over["error"]["code"] != "SCHEMA_VALIDATION_FAILED":
        problems.append("越界参数未 fail closed：%s" % over.get("error"))

    # 6
    from mcp_server import config as C
    files = []
    if os.path.isdir(C.AUDIT_DIR):
        files = sorted(f for f in os.listdir(C.AUDIT_DIR) if f.endswith(".jsonl"))
    if not files:
        problems.append("尚无 MCP 审计日志")
    else:
        p = os.path.join(C.AUDIT_DIR, files[-1])
        with open(p, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
        if not rows:
            problems.append("审计日志为空")
        for r0 in rows[:200]:
            missing = [k for k in AUDIT_MIN_FIELDS if k not in r0]
            if missing:
                problems.append("审计缺字段 %s" % missing)
                break
            if SECRETISH.search(json.dumps(r0, ensure_ascii=False)):
                problems.append("审计日志疑似记录了凭据")
                break

    # 7
    fok, fdetail = verify_core_freeze()
    if not fok:
        problems.append("core freeze 校验失败：%s" % fdetail)

    if problems:
        print("FAIL MCP 契约自检未通过：")
        for x in problems[:10]:
            print("  - %s" % x)
        return 1
    print("MCP 契约自检通过：10 工具 / 严格输入 schema / provider 默认 mock / "
          "信封与错误契约一致 / 审计 %d 文件 / core freeze OK" % len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
