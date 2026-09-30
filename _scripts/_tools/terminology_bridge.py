#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
terminology_bridge.py — Phase 3C §5 Cross-lingual Terminology Bridge 的**读取 API**

`X` 从 benchmark 里的几行代码升为一级组件，所以它必须有稳定的 API：

    import terminology_bridge as tb
    tb.load()                                   # 全部映射
    tb.expand("小客体a", target_langs=("fr",))   # → [(target_form, entity_id, term_id)]
    tb.distinct_pairs()                         # §6 的 7 组「必须区分」
    tb.is_distinct("Autre", "autre")            # → True
    tb.lexical_forms_for_entity(eid)            # 该 entity 的全部 surface forms

三条硬规则（写进代码，不只是写进文档）
──────────────────────────────────────
1. **只有 `relation_type == equivalent` 才可扩展查询。**
   `distinct_from` 记录**永远**不出现在 `expand()` 的结果里。
2. **equivalent 必须两侧 `entity_id` 相同。** 没有同一 entity 的字符串相似
   一律不生成 equivalent（见 `build_terminology_bridge.py`）。
3. `expand()` 返回值**保留 entity_id**，调用方必须能据此审计
   「这个法文词是从哪个中文词、经哪条记录扩出来的」。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
BRIDGE = os.path.join(VAULT, "_data", "terminology_bridge.jsonl")

_CACHE = None


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s.lower()).strip()


def load():
    global _CACHE
    if _CACHE is None:
        rows = []
        with open(BRIDGE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        _CACHE = rows
    return _CACHE


def reload():
    global _CACHE
    _CACHE = None
    return load()


def equivalents():
    return [r for r in load() if r["relation_type"] == "equivalent"]


def distinct_pairs():
    return [r for r in load() if r["relation_type"] == "distinct_from"]


def expand(form, target_langs=None, source_lang=None):
    """把 surface form 扩成目标语言的写法。

    → [{"target_form", "target_language", "entity_id", "term_id", "source_form"}]

    ⚠️ 只走 equivalent。distinct_from 在此被**结构性排除** ——
    不是靠调用方记得不要用，而是这个函数根本不返回它们。
    """
    f = fold(form)
    out, seen = [], set()
    for r in equivalents():
        if fold(r["source_form"]) != f:
            continue
        if source_lang and r["source_language"] != source_lang:
            continue
        if target_langs and r["target_language"] not in target_langs:
            continue
        k = (fold(r["target_form"]), r["entity_id"])
        if k in seen:
            continue
        seen.add(k)
        out.append({"target_form": r["target_form"],
                    "target_language": r["target_language"],
                    "entity_id": r["entity_id"],
                    "term_id": r["term_id"],
                    "source_form": r["source_form"]})
    return out


def is_distinct(a, b):
    fa, fb = fold(a), fold(b)
    for r in distinct_pairs():
        x, y = fold(r["source_form"]), fold(r["target_form"])
        if (fa == x and fb == y) or (fa == y and fb == x):
            return True
    return False


def distinct_partner(form):
    """给定一侧，返回与它「必须区分」的另一侧（用于 Guard 建 lane）。"""
    f = fold(form)
    for r in distinct_pairs():
        if fold(r["source_form"]) == f:
            return r["target_form"]
        if fold(r["target_form"]) == f:
            return r["source_form"]
    return None


def lexical_forms_for_entity(entity_id):
    """该 entity 在 bridge 里出现过的全部 surface form（跨语言）。"""
    out = []
    for r in load():
        if r["entity_id"] != entity_id:
            continue
        for f in (r["source_form"], r["target_form"]):
            if f not in out:
                out.append(f)
    return out


def common_forms(entity_a, entity_b):
    """两个 entity 共用的 surface form —— 非空就意味着「知识库自己也没分开」。"""
    sa = {fold(x) for x in lexical_forms_for_entity(entity_a)}
    sb = {fold(x) for x in lexical_forms_for_entity(entity_b)}
    return sorted(sa & sb)


def stats():
    rows = load()
    eq = [r for r in rows if r["relation_type"] == "equivalent"]
    return {
        "rows": len(rows),
        "equivalent": len(eq),
        "distinct_from": len(rows) - len(eq),
        "entities": len({r["entity_id"] for r in eq if r["entity_id"]}),
        "languages": sorted({r["source_language"] for r in eq} |
                            {r["target_language"] for r in eq}),
        "hash": __import__("hashlib").sha256(open(BRIDGE, "rb").read()).hexdigest(),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 2 and sys.argv[1] == "--expand":
        print(json.dumps(expand(sys.argv[2]), ensure_ascii=False, indent=1))
    else:
        for r in distinct_pairs():
            print("%-16s %-22s %s" % (r["term_id"], r["source_form"] + "/" + r["target_form"],
                                      r.get("entity_binding")))
