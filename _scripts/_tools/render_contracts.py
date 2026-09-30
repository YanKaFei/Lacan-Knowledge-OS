#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_contracts.py — Phase 4A §25：把 tool 契约从**代码**渲染成文档与机器可读 JSON

为什么要生成而不是手写
──────────────────────
`schemas.py` 是契约的**唯一来源**。如果 `MCP_TOOL_CONTRACTS.md` 手写，
它和实现迟早会分叉 —— 而「文档说能写、代码其实只读」这种分叉，
正是 §21（只读硬门）最危险的失效方式。

所以：**文档由代码渲染**，并且 `--check` 模式在 CI 里校验文档没有过期。

产物
────
    MCP_TOOL_CONTRACTS.md          # 人读：10 个 tool 的 purpose / not_for / 参数 / 输出段
    _data/mcp/tool_schemas.json    # 机读：MCP `tools/list` 的原始契约 + 输出段 + 责任矩阵

用法
────
    python3 _scripts/_tools/render_contracts.py            # 写文件
    python3 _scripts/_tools/render_contracts.py --check    # 只校验是否最新（过期则 exit 1）
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import schemas  # noqa: E402

DOC = os.path.join(VAULT, "MCP_TOOL_CONTRACTS.md")
JSON_OUT = os.path.join(VAULT, "_data", "mcp", "tool_schemas.json")

HEADER = """# MCP Tool Contracts — Lacanian Knowledge OS（Phase 4A）

> ⚠️ **本文件由 `_scripts/_tools/render_contracts.py` 从 `schemas.py` 渲染生成。**
> 不要手改：`--check` 会在文档与代码分叉时报错。改契约请改 `schemas.py`。
>
> 生成命令：`python3 _scripts/_tools/render_contracts.py`

## 这一层是什么（§1）

MCP 在这里是 **Knowledge Access Layer（知识访问层）**，**不是 Answer Generator**：
它返回**结构化证据**（passage + 出处 + 权威层级 + 覆盖度 + 告警 + 证据状态），
由调用它的 LLM 去组织答案。所以：

* 每个 tool 的输出都含同一套 **8 段 schema**（§6）；
* 每个 tool 都**只读**（§2/§21）：没有任何写入型参数；
* 「证据够不够」由**结构性**信号判定（§7–§10），**禁止** cosine 阈值；
* `evidence_state` 判的是「知识库是否支持这次研究操作」，**不判理论对错**（§10）。

## 共享输出 schema（§6）

所有 tool 的返回都是这 8 段（顺序固定，缺一不可）：

{shared}

| 段 | 含义 |
|---|---|
"""


def _fmt_default(p):
    d = p.get("default")
    if d is None:
        return ""
    if isinstance(d, bool):
        return "`%s`" % ("true" if d else "false")
    return "`%s`" % d


def _param_rows(schema):
    rows = []
    props = schema.get("properties") or {}
    req = set(schema.get("required") or [])
    for name, p in props.items():
        t = p.get("type") or ("enum" if p.get("enum") else "any")
        if p.get("enum"):
            t = "enum(%s)" % "\\|".join(str(x) for x in p["enum"])
        lo, hi = p.get("minimum"), p.get("maximum")
        if lo is not None or hi is not None:
            t += " %s..%s" % ("" if lo is None else lo, "" if hi is None else hi)
        rows.append("| `%s` | %s | %s | %s | %s |" % (
            name, t, "是" if name in req else "否", _fmt_default(p),
            (p.get("description") or "").replace("|", "\\|")))
    return rows


def render():
    out = [HEADER.format(shared="  ".join("`%s`" % s for s in schemas.OUTPUT_SECTIONS)).rstrip("\n")]
    for sec, desc in schemas.SHARED_OUTPUT["sections"].items():
        out.append("| `%s` | %s |" % (sec, desc.replace("|", "\\|")))
    out.append("")
    out.append("## Tool 一览（%d 个，§4「克制」）\n" % len(schemas.TOOLS))
    out.append("| # | tool | 职责一句话 | 每概念 lane | 实体约束 | 历时分组 |")
    out.append("|---|---|---|---|---|---|")
    for i, t in enumerate(schemas.TOOLS, 1):
        m = schemas.RESPONSIBILITY_MATRIX.get(t["name"], {})
        out.append("| %d | `%s` | %s | %s | %s | %s |" % (
            i, t["name"], t["title"].replace("|", "\\|"),
            m.get("lanes", "—"), m.get("entity_constrained", "—"),
            m.get("diachronic_grouping", "—")))
    out.append("")
    out.append("> 责任矩阵的作用（§5）：三个「看起来都像检索」的 tool "
               "（`search_passages` / `find_concept_evidence` / `trace_concept`）")
    out.append("> 必须**职责不同**，不能互为别名。上表就是它们的区别，"
               "并由 `test_phase4a_mcp.py` 断言。\n")

    for i, t in enumerate(schemas.TOOLS, 1):
        m = schemas.RESPONSIBILITY_MATRIX.get(t["name"], {})
        out.append("## %d. `%s`\n" % (i, t["name"]))
        out.append("**%s**\n" % t["title"])
        out.append("**用途（purpose）**：%s\n" % t["purpose"])
        out.append("**不要用它来做（not_for）**：%s\n" % t["not_for"])
        out.append("**责任范围**：scope=%s · entity_constrained=%s · "
                   "diachronic_grouping=%s · lanes=%s\n"
                   % (m.get("scope", "—"), m.get("entity_constrained", "—"),
                      m.get("diachronic_grouping", "—"), m.get("lanes", "—")))
        out.append("**输入**\n")
        out.append("| 参数 | 类型 | 必填 | 默认 | 说明 |")
        out.append("|---|---|---|---|---|")
        out.extend(_param_rows(t["inputSchema"]))
        out.append("")
        out.append("**输出**：共享 8 段 schema 全给；"
                   "`evidence_state` 由 `evidence_sufficiency` 结构性判定。\n")
    out.append("## 只读保证（§21）\n")
    out.append("以下词根一旦出现在**任何**参数名里，契约测试直接失败：\n")
    out.append("`%s`\n" % "`, `".join(schemas.FORBIDDEN_PARAM_PATTERNS))
    out.append("唯一会落盘的内容是 `_data/ontology_gap_queue.jsonl`（§22），"
               "它由 **Research Agent** 写，且只写 `status: candidate` 的发现记录 —— "
               "不属于 canonical knowledge，MCP tool 本身不写任何文件。\n")
    return "\n".join(out) + "\n"


def machine():
    return {
        "schema_version": "mcp-contracts/v1",
        "server": {"name": "lacan-kb", "transport": "stdio",
                   "protocol_version": "2025-11-25"},
        "read_only": True,
        "forbidden_param_patterns": schemas.FORBIDDEN_PARAM_PATTERNS,
        "output_sections": schemas.OUTPUT_SECTIONS,
        "shared_output": schemas.SHARED_OUTPUT,
        "responsibility_matrix": schemas.RESPONSIBILITY_MATRIX,
        "tools": schemas.TOOLS,
        "count": len(schemas.TOOLS),
    }


def main(argv):
    check = "--check" in argv
    doc, js = render(), json.dumps(machine(), ensure_ascii=False, indent=1) + "\n"
    if check:
        bad = []
        for path, want in ((DOC, doc), (JSON_OUT, js)):
            have = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
            if have != want:
                bad.append(path)
        if bad:
            print("契约文档已过期（请重跑 render_contracts.py）：")
            for b in bad:
                print("  ✗ %s" % b)
            return 1
        print("契约文档与 schemas.py 一致：%s / %s"
              % (os.path.relpath(DOC, VAULT), os.path.relpath(JSON_OUT, VAULT)))
        return 0
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    open(DOC, "w", encoding="utf-8").write(doc)
    open(JSON_OUT, "w", encoding="utf-8").write(js)
    print("wrote %s（%d 行）" % (os.path.relpath(DOC, VAULT), doc.count("\n")))
    print("wrote %s（%d 个 tool）" % (os.path.relpath(JSON_OUT, VAULT),
                                      len(schemas.TOOLS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
