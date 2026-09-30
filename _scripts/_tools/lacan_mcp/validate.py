#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py — Phase 4A：**MCP 响应的独立校验器**

它和 `selftest.py` 的分工
─────────────────────────
* `selftest.py` 检查**我们自己**的 server 行为（协议、契约、只读）；
* `validate.py` 检查**任意一份** response 是否满足 §6 的输出契约，
  并且**独立地**去 canonical store 核对每个 `passage_id` 是否真实存在。

第二件事才是关键：§2/§21 要求「不得编造引用」。所以校验器不看 tool 自己怎么说，
而是拿 `evidence[].passage_id` 去 `passages.jsonl` 里对 ——
**对不上就是 fabricated，直接失败**，不看上下文理由。

用法
────
    from validate import validate_response, validate_envelope
    issues = validate_response(doc)        # → [] 表示通过
    python3 validate.py < response.json    # CLI：exit 1 表示不合格
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, HERE)

import schemas  # noqa: E402

STORE = os.path.join(VAULT, "_data", "passage_store")
PASSAGES = os.path.join(STORE, "passages.jsonl")

STATES = ("SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE",
          "CONFLICTING_EVIDENCE")

_PIDS = None


def passage_ids():
    """canonical passage store 里的全部 id（只读，缓存）。"""
    global _PIDS
    if _PIDS is None:
        ids = set()
        if os.path.isfile(PASSAGES):
            with open(PASSAGES, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            ids.add(json.loads(line)["id"])
                        except Exception:
                            pass
        _PIDS = ids
    return _PIDS


def validate_envelope(doc, tool=None, check_passages=True):
    """校验一份 tool 响应。→ issues 列表（空 = 通过）。"""
    issues = []
    if not isinstance(doc, dict):
        return ["response 不是 object"]

    for sec in schemas.OUTPUT_SECTIONS:
        if sec not in doc:
            issues.append("缺输出段：%s" % sec)
    if issues:
        return issues

    if not isinstance(doc["evidence"], list):
        issues.append("evidence 不是数组")
    if not isinstance(doc["warnings"], list):
        issues.append("warnings 不是数组（无告警时必须是 []，不能缺字段）")
    for w in doc["warnings"]:
        if not isinstance(w, dict) or "code" not in w or "message" not in w:
            issues.append("warning 缺 code/message：%r" % (w,))

    st = doc["evidence_state"]
    if not isinstance(st, dict):
        issues.append("evidence_state 不是 object")
    else:
        if st.get("state") not in STATES:
            issues.append("evidence_state.state 不在四状态内：%r" % st.get("state"))
        if "signals" not in st or "reasons" not in st:
            issues.append("evidence_state 缺 signals/reasons")
        if st.get("method") != "structural_only_no_cosine_threshold":
            issues.append("evidence_state.method 必须是 structural_only_no_cosine_threshold，"
                          "实际 %r" % st.get("method"))
        # §7：禁止把 0–1 置信度当结论
        for bad in ("confidence", "score_threshold", "cosine_threshold"):
            if bad in st:
                issues.append("evidence_state 不得含 %s（§7 禁止 0–1 confidence）" % bad)

    if tool and (doc["request"].get("tool") != tool):
        issues.append("request.tool 不匹配：%r != %r"
                      % (doc["request"].get("tool"), tool))

    if check_passages:
        known = passage_ids()
        for e in doc["evidence"] if isinstance(doc["evidence"], list) else []:
            pid = (e or {}).get("passage_id")
            if not pid:
                issues.append("evidence 条目缺 passage_id：%r" % (e,))
                continue
            if known and pid not in known:
                issues.append("**FABRICATED** passage_id 不在 canonical store：%s" % pid)
    # §2：响应里不得出现「已写入」这类声明
    if doc.get("mutations") or doc.get("writes"):
        issues.append("响应声明了写入（§2/§21 只读）")
    return issues


def validate_response(doc):
    """校验 `tools/call` 的**完整** JSON-RPC result（含 content/structuredContent）。"""
    issues = []
    if not isinstance(doc, dict):
        return ["result 不是 object"]
    if doc.get("isError"):
        return ["isError=true（错误响应不当作有效证据响应）"]
    sc = doc.get("structuredContent")
    if not isinstance(sc, dict):
        issues.append("缺 structuredContent（MCP result 必须带结构化证据）")
    else:
        issues += validate_envelope(sc, tool=(sc.get("request") or {}).get("tool"))
    content = doc.get("content")
    if not isinstance(content, list) or not content:
        issues.append("content 必须是非空数组")
    else:
        for c in content:
            if c.get("type") != "text" or not isinstance(c.get("text"), str):
                issues.append("content 条目必须是 {type:'text', text:str}")
    return issues


def main(argv):
    raw = open(argv[0], encoding="utf-8").read() if argv else sys.stdin.read()
    doc = json.loads(raw)
    issues = validate_response(doc)
    if issues:
        print("响应校验失败（%d 项）：" % len(issues))
        for i in issues:
            print("  ✗ %s" % i)
        return 1
    print("响应校验通过：8 段齐、evidence_state 合法、"
          "passage_id 全部存在于 canonical store")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
