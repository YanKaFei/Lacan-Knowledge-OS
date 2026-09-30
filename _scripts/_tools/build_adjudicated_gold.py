#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_adjudicated_gold.py — §2–§4 Adjudicated Research Gold Set

与 proxy 集的**根本区别**
─────────────────────────
`retrieval_eval.jsonl`（proxy）的 gold 是「词面子串匹配 + 抽样」自动推导的
—— 它服务于 parser / tokenizer / filter 的**回归测试**，
且**存在期内采样偏差**，因此**不得单独作为 embedding model selection 的 ground truth**。

本文件产出的 adjudicated gold 走另一条路：

  1. 查询由**人**写（研究性问题，不是关键词），带 primary_intent + secondary_intents
  2. gold evidence 逐条**验证存在**（从 canonical store 查出来），
     并按 §3 分三级：`required` / `strong` / `contextual`
  3. `required` 可以为空 —— **不得为了填 schema 而虚构 evidence**（§3 明确要求）
  4. 每条带 `annotation`（怎么定的、依据什么）与 `review_status`

`review_status` 的诚实取值
──────────────────────────
本阶段没有第二个独立标注者，因此**不能声称已人审**。取值：

  * `adjudicated_script_assisted` —— 查询与分级由人设计，passage 由脚本从
    canonical store 解析并逐个验证存在。这是**诚实的中间态**，
    不是 `reviewed`。文档里必须这样写。

用法
    python3 build_adjudicated_gold.py
    python3 build_adjudicated_gold.py --stats
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from deterministic import add_stamp_flag, apply_stamp  # noqa: E402

STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
LEX = os.path.join(IDX, "lexical.sqlite")
SPEC = os.path.join(VAULT, "_data", "adjudicated_gold_spec.jsonl")
OUT = os.path.join(VAULT, "retrieval_gold_adjudicated.jsonl")

MIN_QUERIES, MAX_QUERIES = 40, 60

_APOS = re.compile(r"['\u2019\u02bc]")
_HYPH = re.compile(r"[-\u2010-\u2015]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s):
    s = unicodedata.normalize("NFKC", str(s))
    s = _APOS.sub("", s)
    s = _HYPH.sub("", s)
    s = strip_accents(s)
    s = _NONWORD.sub("", s)
    return s.lower()


def load_spec():
    with open(SPEC, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def build(quiet=False, stamp=False):
    spec = load_spec()
    concepts = {}
    with open(os.path.join(STORE, "concepts.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                concepts[c["id"]] = c

    con = sqlite3.connect(LEX)
    con.row_factory = sqlite3.Row
    try:
        meta = {r["id"]: dict(r) for r in
                con.execute("SELECT id, seminar_id, session_id, language, "
                            "authority_level, trace_status FROM passage_meta")}
    finally:
        con.close()

    # 为每个概念收集「含其高区分度写法」的 passage，用于分级
    rows = []
    unresolved = []
    for q in spec:
        concept_needles = {}
        for eid in q.get("expected_entities") or []:
            c = concepts.get(eid)
            if not c:
                continue
            needles = set()
            for k in ("canonical_name", "fr", "en", "zh"):
                v = c.get(k)
                if v:
                    for part in re.split(r"[/／|]", str(v)):
                        part = part.strip()
                        if len(norm(part)) >= 3:
                            needles.add(norm(part))
            for a in (c.get("aliases") or []):
                if len(norm(a)) >= 3:
                    needles.add(norm(a))
            if needles:
                concept_needles[eid] = sorted(needles, key=lambda x: -len(x))

        required, strong, contextual = [], [], []
        # 脚本只做「候选解析」：按 needles 在 benchmark 子集之外的**全库**里找
        # 但为可控，这里只扫 gold 相关的 seminar 范围（若有约束）
        want_sems = set(q.get("expected_seminars") or [])
        pool = [pid for pid, m in meta.items()
                if (not want_sems or m["seminar_id"] in want_sems)]
        if concept_needles and pool:
            # 读全文做判定（一次读全库，按需筛选）
            with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    pid = d["id"]
                    if pid not in meta:
                        continue
                    if want_sems and d["seminar_id"] not in want_sems:
                        continue
                    body = norm(d["raw_text"])
                    if not body:
                        continue
                    # 命中「最长 needle」且长度足够 → strong 候选；
                    # 命中 ≥2 个不同 needle（多写法共现）→ required 候选
                    hits = 0
                    for eid, needles in concept_needles.items():
                        for n in needles[:6]:
                            if n in body:
                                hits += 1
                                break
                    if hits >= 2:
                        required.append(pid)
                    elif hits == 1:
                        strong.append(pid)
                    if len(required) >= 8 and len(strong) >= 12:
                        break

        # 分级裁剪（确定性：按 passage_id 排序）
        required = sorted(set(required))[:5]
        strong = sorted(set(strong) - set(required))[:8]
        contextual = sorted(set(contextual))[:5]

        # 校验存在性
        for pid in required + strong + contextual:
            if pid not in meta:
                unresolved.append({"query_id": q["query_id"], "passage_id": pid})

        rows.append({
            "query_id": q["query_id"],
            "query": q["query"],
            "language": q.get("language") or "und",
            "primary_intent": q["primary_intent"],
            "secondary_intents": q.get("secondary_intents") or [],
            "expected_entities": q.get("expected_entities") or [],
            "expected_seminars": q.get("expected_seminars") or [],
            "constraints": q.get("constraints") or {},
            "gold_evidence": {
                "required": required,
                "strong": strong,
                "contextual": contextual,
            },
            "annotation": {
                "method": ("查询与分级维度由人设计；passage 由脚本从 canonical store "
                           "解析：命中 ≥2 个不同写法→required，命中 1 个高区分度"
                           "写法→strong。全部逐个验证存在于 store。"),
                "grading_rule": ("required = 多重写法共现（更可能真的在讨论该概念）；"
                                 "strong = 单一高区分度写法命中；"
                                 "contextual = 未自动填充（留空，不虚构）"),
                "substring_matching_used": True,
                "note": ("⚠️ 与 proxy 集的差别在于**查询是人写的、分级是显式的**；"
                         "但 passage 仍是词面匹配推导的，不是逐段人工通读。"
                         "因此 gold_evidence 仍是**可争议的**，见 review_status。"),
            },
            "review_status": "adjudicated_script_assisted",
        })

    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    stats = {
        "queries": len(rows),
        "with_required": sum(1 for r in rows if r["gold_evidence"]["required"]),
        "with_any_gold": sum(1 for r in rows
                             if any(r["gold_evidence"][k]
                                    for k in ("required", "strong", "contextual"))),
        "without_any_gold": sum(1 for r in rows
                                if not any(r["gold_evidence"][k]
                                           for k in ("required", "strong",
                                                     "contextual"))),
        "unresolved_ids": len(unresolved),
    }
    if not quiet:
        print(f"[gold] queries={stats['queries']} "
              f"with_required={stats['with_required']} "
              f"with_any={stats['with_any_gold']} "
              f"without={stats['without_any_gold']}", file=sys.stderr)
        print(f"[gold] -> {OUT}", file=sys.stderr)
    return stats


def main():
    ap = argparse.ArgumentParser(description="生成 adjudicated gold（§2–§4）")
    ap.add_argument("--stats", action="store_true")
    add_stamp_flag(ap)
    args = ap.parse_args()
    st = build(quiet=args.stats, stamp=args.stamp)
    if args.stats:
        print(json.dumps(st, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
