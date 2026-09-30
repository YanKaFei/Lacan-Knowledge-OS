#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
entity_resolution.py — Phase 3C §5 共享实体解析层（Terminology Bridge 的上游）

为什么需要它
───────────
`X`（Cross-lingual Terminology Bridge）的每一次扩展都从**实体解析**开始：
把查询里的词映射到 concept entity，再取该 entity 的跨语言别名。

而 Phase 3C 实测发现：`query_router.route()` 在**中文查询**上解析率很差 ——

    40 条 adjudicated gold query：
      router 解析出            32 个实体
      中文子串别名扫描额外找到   22 个（涉及 14/40 条 query）

原因很直接：中文没有词边界，router 的分词/整词匹配在
「大他者是怎么被定义的」这种句子上匹配不到 `大他者`。
**这 14 条 query 恰恰是 `X` 为空、ZH→FR 召回≈0 的那些。**

所以这不是「调参」，而是补上一个真实缺失的组件。本模块是 3C 的新增层，
**不改 `query_router` 的既有行为** —— 3A/3B 已交付的数字因此仍然可复现；
3C 的路由与评测使用 `resolve()`（router ∪ CJK 扫描），并可分别归因。

规则
────
* CJK 别名：**去空格子串匹配**（中文无词边界），folded 长度 ≥ 2。
* 拉丁别名：**词边界匹配**，folded 长度 ≥ 3（避免 Phase 3A 踩过的单字母噪声，
  例如 `concept.l-autre` 的别名 `A`）。
* **最长匹配优先**，同一 entity 只保留一次。
* **歧义如实上报**：一个 surface form 命中多个 entity → 记进 `ambiguous`，
  不替调用方选。
* 解析结果保留 `origin`（`router` / `cjk_scan`），这样跨语言增益可以**按来源归因**。

⚠️ 诚实的边界：本模块只解决「**找得到实体**」。
它**不能**解决知识库本身的 entity 合并问题（例如 Autre/autre 共用一个 entity）——
那由 `lacanian_semantic_guard` 显式报 `ENTITY_COLLISION`。

用法
────
    import entity_resolution as er
    er.resolve("大他者是怎么被定义的")
    er.stats_over_gold()
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
ALIASES = os.path.join(VAULT, "_data", "index", "alias_index.jsonl")

MIN_CJK = 2
MIN_LATIN = 3
MAX_ENTITIES = 8

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

_ROWS = None


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s.lower()).strip()


def _rows_cached():
    global _ROWS
    if _ROWS is None:
        rows = []
        with open(ALIASES, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                a = r.get("alias")
                if not a or not str(a).strip():
                    continue
                fa = fold(a)
                if CJK_RE.search(fa):
                    if len(fa.replace(" ", "")) < MIN_CJK:
                        continue
                elif len(fa) < MIN_LATIN:
                    continue
                rows.append({"alias": str(a), "folded": fa, "entity_id": r["entity_id"],
                             "entity_type": r.get("entity_type"),
                             "is_cjk": bool(CJK_RE.search(fa))})
        # 最长别名优先，稳定排序
        rows.sort(key=lambda r: (-len(r["folded"]), r["folded"], r["entity_id"]))
        _ROWS = rows
    return _ROWS


def cjk_scan(query):
    """→ {entity_id: matched_alias}；只用 CJK 别名做去空格子串匹配。"""
    fq = fold(query)
    packed = fq.replace(" ", "")
    out = {}
    for r in _rows_cached():
        if not r["is_cjk"]:
            continue
        if r["folded"].replace(" ", "") in packed:
            out.setdefault(r["entity_id"], r["alias"])
    return out


def latin_scan(query):
    """→ {entity_id: matched_alias}；拉丁别名用词边界匹配。"""
    fq = fold(query)
    out = {}
    for r in _rows_cached():
        if r["is_cjk"]:
            continue
        if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(r["folded"]), fq):
            out.setdefault(r["entity_id"], r["alias"])
    return out


def resolve(query, plan=None, max_entities=MAX_ENTITIES):
    """router 实体 ∪ CJK 扫描 ∪ 拉丁扫描，按来源归因，歧义如实上报。"""
    import query_router
    if plan is None:
        plan = query_router.route(query)

    # router 可能对**同一个 entity** 给出多条命中（如 "grand Autre" 与 "Autre"
    # 都指向 concept.l-autre）。必须按 entity 去重，否则下游会把
    # 「一个概念」误判成「两个概念」→ 错误地走 CONCEPT_COMPARISON 分道。
    router_ents = []
    seen_router = {}                      # entity_id -> 那个 dict 本身（不是下标）
    for e in (plan.get("entities") or []):
        eid = e["entity_id"]
        al = e.get("matched_alias") or ""
        prev = seen_router.get(eid)
        if prev is None:
            prev = {"entity_id": eid, "matched_alias": al, "origin": "router",
                    "entity_type": e.get("entity_type")}
            seen_router[eid] = prev
            router_ents.append(prev)
        elif len(fold(al)) > len(fold(prev["matched_alias"] or "")):
            prev["matched_alias"] = al      # 保留最长（最有信息量）的写法
    have = {e["entity_id"] for e in router_ents}

    extra = []
    for src, table in (("cjk_scan", cjk_scan(query)), ("latin_scan", latin_scan(query))):
        for eid, alias in sorted(table.items()):
            if eid in have:
                continue
            have.add(eid)
            extra.append({"entity_id": eid, "matched_alias": alias,
                          "origin": src, "entity_type": None})

    entities = (router_ents + extra)[:max_entities]

    # 歧义：同一 surface form 命中多个 entity
    fq = fold(query)
    packed = fq.replace(" ", "")
    by_form = {}
    for r in _rows_cached():
        hit = (r["folded"].replace(" ", "") in packed) if r["is_cjk"] else \
            bool(re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(r["folded"]), fq))
        if hit:
            by_form.setdefault(r["alias"], set()).add(r["entity_id"])
    ambiguous = [{"alias": a, "entity_ids": sorted(v)}
                 for a, v in sorted(by_form.items()) if len(v) > 1]

    return {
        "schema_version": "entity-resolution/v1",
        "query": query,
        "entities": entities,
        "router_entities": router_ents,
        "extra_from_scan": extra,
        "counts": {"router": len(router_ents), "extra": len(extra),
                   "total": len(entities), "ambiguous": len(ambiguous)},
        "ambiguous": ambiguous,
        "note": ("本层只补「找得到实体」。知识库自身把两侧概念合并成一个 entity 的问题"
                 "（如 Autre/autre）由 lacanian_semantic_guard 报 ENTITY_COLLISION。"),
    }


def stats_over_gold(path=None):
    """在 gold 上量化这一层的贡献 —— 用于报告里给出**真实**的提升数字。"""
    path = path or os.path.join(VAULT, "retrieval_gold_answerable.jsonl")
    import query_router
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    base = extra = 0
    q_extra = 0
    detail = []
    for g in rows:
        p = query_router.route(g["query"])
        r = resolve(g["query"], p)
        b, e = r["counts"]["router"], r["counts"]["extra"]
        base += b
        extra += e
        if e:
            q_extra += 1
            detail.append({"query_id": g["query_id"], "query": g["query"],
                           "router": b, "extra": e,
                           "extra_entities": [x["entity_id"] for x in r["extra_from_scan"]]})
    return {"queries": len(rows), "router_entities": base, "extra_entities": extra,
            "queries_gaining_entities": q_extra, "detail": detail}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        print(json.dumps(stats_over_gold(), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 1:
        print(json.dumps(resolve(" ".join(sys.argv[1:])), ensure_ascii=False, indent=1))
