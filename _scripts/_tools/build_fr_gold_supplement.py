#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_fr_gold_supplement.py — §16 方向 C / D 的**补充** gold（独立分母，不动原 45 条）

为什么需要它
───────────
四方向里 A（ZH→ZH）与 B（ZH→FR）能测，但 **C（FR→FR）与 D（FR→ZH）的 n = 0**：
原 gold 45 条里只有 2 条法语 query，且它们的目标证据**跨 zh/fr 两种语言**，
按规则归入 `MUL_mixed`。**没有法语-only 的样本 → 方向 C/D 无法测量。**

这不是「测出来是 0」，是「没有样本」。要测它只能补标注。

与原 45 条的关系（**严格遵守，不得混淆**）
──────────────────────────────────────────
* 原 `retrieval_gold_adjudicated.jsonl` / `_answerable` / `_unanswerable`
  **一个字节都不改**（本脚本只读）。
* 本补充集写进**单独的文件** `retrieval_gold_fr_supplement.jsonl`，
  每条带 `supplementary_for: ["C_fr2fr"]` 或 `["D_fr2zh"]`。
* **分母独立**：它不参与、也不改变主 benchmark 的 n=40。
  报告里必须分开写，禁止把两边的数字平均。

标注方法：与 `build_adjudicated_gold.py` **完全同一套**
──────────────────────────────────────────────────────
1. 查询由人（这里由 agent，与主集同等状态）用**法语**写，是研究性问题而非关键词；
2. 目标语言由 spec 显式指定（`target_language: fr` 或 `zh`）——
   这是本补充集**唯一**新增的维度，因为「方向」本来就是用语言定义的；
3. passage 由脚本从 canonical store 解析：同一 concept 命中 ≥2 个不同写法 → `required`，
   命中 1 个高区分度写法 → `strong`；
4. 全部逐个验证存在于 store；解析不出来就**留空并如实记录**，不虚构；
5. `review_status = adjudicated_script_assisted`（无第二标注者，**不是** `reviewed`）。

用法
────
    python3 _scripts/_tools/build_fr_gold_supplement.py            # 生成
    python3 _scripts/_tools/build_fr_gold_supplement.py --stats    # 只看统计
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
STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
LEX = os.path.join(IDX, "lexical.sqlite")
SPEC = os.path.join(VAULT, "_data", "fr_gold_supplement_spec.jsonl")
OUT = os.path.join(VAULT, "retrieval_gold_fr_supplement.jsonl")

_APOS = re.compile(r"['\u2019\u02bc]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s):
    s = strip_accents(str(s or "")).lower()
    s = _APOS.sub(" ", s)
    s = _NONWORD.sub(" ", s)
    return " ".join(s.split())


def load_spec():
    with open(SPEC, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def build(quiet=False):
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

    rows = []
    unresolved = []

    # ── 阶段 ①：先算好每个 query 的 needle（不碰正文）
    plans = []
    for q in spec:
        target = q["target_language"]
        needles = {}
        for eid in q.get("expected_entities") or []:
            c = concepts.get(eid)
            if not c:
                continue
            ns = set()
            for k in ("canonical_name", "fr", "en", "zh"):
                v = c.get(k)
                if v:
                    for part in re.split(r"[/／|]", str(v)):
                        part = part.strip()
                        if len(norm(part)) >= 3:
                            ns.add(norm(part))
            for a in (c.get("aliases") or []):
                if len(norm(a)) >= 3:
                    ns.add(norm(a))
            if ns:
                needles[eid] = sorted(ns, key=lambda x: -len(x))
        plans.append((q, target, needles))

    # ── 阶段 ②：**单次**扫描 passages.jsonl，同时判定全部 query
    # ⚠️ 第一版把这次扫描放在 per-query 循环里 = 12 次全表扫描（实测 >5 分钟）。
    # passages.jsonl 有 249,105 行 / 1.2 GB，只能扫一遍。
    acc = {q["query_id"]: {"required": [], "strong": []} for q in spec}
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            pid = d["id"]
            m = meta.get(pid)
            if not m:
                continue
            body = norm(d["raw_text"])
            if not body:
                continue
            for q, target, needles in plans:
                if m["language"] != target or not needles:
                    continue
                hits = 0
                for eid, ns in needles.items():
                    for n in ns[:6]:
                        if n in body:
                            hits += 1
                            break
                a = acc[q["query_id"]]
                if hits >= 2:
                    a["required"].append(pid)
                elif hits == 1:
                    a["strong"].append(pid)

    for q, target, needles in plans:
        a = acc[q["query_id"]]
        required = sorted(set(a["required"]))[:5]
        strong = sorted(set(a["strong"]) - set(required))[:8]
        for pid in required + strong:
            if pid not in meta:
                unresolved.append({"query_id": q["query_id"], "passage_id": pid})

        rows.append({
            "query_id": q["query_id"],
            "query": q["query"],
            "language": "fr",
            "target_language": target,
            "supplementary_for": [q["direction"]],
            "primary_intent": q["primary_intent"],
            "secondary_intents": q.get("secondary_intents") or [],
            "expected_entities": q.get("expected_entities") or [],
            "expected_seminars": [],
            "constraints": {"target_language": target},
            "gold_evidence": {"required": required, "strong": strong,
                              "contextual": []},
            "annotation": {
                "method": ("与主 gold **完全同一套**：查询人写；passage 由脚本从 canonical "
                           "store 解析（命中 ≥2 个不同写法→required，命中 1 个→strong），"
                           "并逐个验证存在。本补充集唯一新增的维度是 "
                           "`target_language` —— 因为「方向」本来就是用语言定义的。"),
                "grading_rule": "同主集：多写法共现=required；单一高区分度写法=strong；contextual 留空不虚构",
                "substring_matching_used": True,
                "why_supplementary": ("主 gold 里没有「法语 query + 单一语言证据」的样本，"
                                      "导致方向 C/D 的 n=0（**没有样本**，不是测得 0）。"
                                      "要测这两个方向只能补标注。"),
                "not_merged_into_primary": True,
            },
            "review_status": "adjudicated_script_assisted",
            "evaluation_role": "answerable",
            "scored_in": ["Recall@5/10/20", "MRR@10", "nDCG@10"],
            "denominator_note": ("**独立分母**：本补充集不参与主 benchmark 的 n=40，"
                                 "两边数字不得平均。"),
        })

    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    stats = {
        "queries": len(rows),
        "by_direction": {d: sum(1 for r in rows if r["supplementary_for"] == [d])
                         for d in ("C_fr2fr", "D_fr2zh")},
        "by_target_language": {t: sum(1 for r in rows if r["target_language"] == t)
                              for t in ("fr", "zh")},
        "with_any_gold": sum(1 for r in rows
                             if r["gold_evidence"]["required"] or r["gold_evidence"]["strong"]),
        "without_any_gold": sum(1 for r in rows
                                if not (r["gold_evidence"]["required"]
                                        or r["gold_evidence"]["strong"])),
        "gold_passages_total": sum(len(r["gold_evidence"]["required"])
                                   + len(r["gold_evidence"]["strong"]) for r in rows),
        "unresolved_ids": len(unresolved),
    }
    if not quiet:
        print("[fr-supplement] %s" % json.dumps(stats, ensure_ascii=False))
        print("[fr-supplement] -> %s" % OUT)
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args(argv)
    if a.stats:
        if not os.path.isfile(OUT):
            print("尚未生成"); return 1
        rows = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
        print(json.dumps({"queries": len(rows),
                          "by_direction": {d: sum(1 for r in rows
                                                  if r["supplementary_for"] == [d])
                                           for d in ("C_fr2fr", "D_fr2zh")},
                          "without_any_gold": sum(
                              1 for r in rows
                              if not (r["gold_evidence"]["required"]
                                      or r["gold_evidence"]["strong"]))},
                         ensure_ascii=False, indent=1))
        return 0
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
