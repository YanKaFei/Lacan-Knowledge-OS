#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alias_index.py — §4 alias 精确查询接口

供 retrieval 层调用（也被测试直接调用）：

    exact_lookup(alias, case_sensitive=False) -> [ {entity_id, match_type, ...} ]
    lookup_ambiguous(alias) -> [ 带 ambiguous_with 的条目 ]

设计要点
────────
* **折叠只用于召回**：`alias_folded` 是 NFKC + casefold 的结果，仅作候选召回键；
  返回的永远是**原文大小写**。
* **不自动合并**：折叠后指向多个实体时全部返回（用户 §4 硬要求），
  并附带 `ambiguous_with` 与 `ambiguity_reason`，让调用方看见冲突。
* `case_sensitive=True` 时只匹配原文完全一致的条目。
"""

from __future__ import annotations

import json
import os
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
ALIAS_FILE = os.path.join(VAULT, "_data", "index", "alias_index.jsonl")

_CACHE = None


def fold(s):
    return unicodedata.normalize("NFKC", str(s)).casefold().strip()


def _load():
    global _CACHE
    if _CACHE is None:
        rows = []
        if os.path.isfile(ALIAS_FILE):
            with open(ALIAS_FILE, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rows.append(json.loads(line))
        _CACHE = rows
    return _CACHE


def reload():
    """测试用：清缓存。"""
    global _CACHE
    _CACHE = None


def exact_lookup(alias, case_sensitive=False, limit=None):
    """精确别名查询。返回候选列表（**可能多义**）。"""
    rows = _load()
    q = str(alias).strip()
    if not q:
        return []
    if case_sensitive:
        hits = [r for r in rows if r["alias"] == q]
    else:
        qf = fold(q)
        hits = [r for r in rows if r["alias_folded"] == qf]
    out = []
    for r in hits:
        exact_case = r["alias"] == q
        # 含 `case_sensitive` 标记的条目（Autre/autre 这类理论词）：
        # 大小写不完全一致时**不得算 exact** —— 降级为 case_variant，
        # 让人看见「你要的写法本库没有，只有另一种大小写」。
        if r.get("case_sensitive") and not exact_case:
            match_type = "case_variant"
        else:
            match_type = "exact"
        out.append({
            "entity_id": r["entity_id"],
            "entity_type": r["entity_type"],
            "matched_alias": r["alias"],
            "language": r["language"],
            "source": r["source"],
            "review_status": r["review_status"],
            "match_type": match_type,
            "exact_case": exact_case,
            "case_sensitive": bool(r.get("case_sensitive")),
            "case_variant_of": r.get("case_variant_of"),
            "case_note": r.get("case_note"),
            "ambiguous_with": r.get("ambiguous_with") or [],
            "ambiguity_reason": r.get("ambiguity_reason"),
        })
    # 确定序：先精确大小写命中，再按 entity_id
    out.sort(key=lambda x: (not x["exact_case"], x["entity_id"]))
    return out[:limit] if limit else out


def lookup_ambiguous(alias):
    """只返回被标记为歧义的条目。"""
    return [h for h in exact_lookup(alias) if h.get("ambiguous_with")]


def stats():
    rows = _load()
    return {
        "aliases": len(rows),
        "entities": len({r["entity_id"] for r in rows}),
        "ambiguous": sum(1 for r in rows if r.get("ambiguous_with")),
        "languages": sorted({r["language"] for r in rows}),
    }
