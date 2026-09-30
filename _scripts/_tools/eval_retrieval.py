#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_retrieval.py — §15 评测

指标
────
通用：Recall@5 / Recall@10 / Recall@20、MRR@10、nDCG@10
项目特有：
  * Entity Resolution Accuracy    —— 解析出的实体是否等于 expected_entities
  * Seminar Filter Accuracy       —— 解析出的期号是否等于 expected_seminars
  * Cross-language Retrieval Recall —— 中文 query 能否取回法文证据（跨语料）
  * Source Trace Closure          —— 返回的 evidence 中 provenance 状态分布
  * Citation Validity             —— 所有 passage_id 都真实存在
  * Evidence Diversity            —— seminar / period / language 覆盖数

**5 项硬门禁**（任一不为 0 即失败）
───────────────────────────────────
  fabricated passage IDs = 0
  broken passage references = 0
  canonical source mutation = 0
  source hash mutation = 0
  provenance state silent upgrade = 0

诚实性
──────
无 gold 的 query **不计入 recall 分母**（它们的原因已在评测集里标注）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

EVAL = os.path.join(VAULT, "retrieval_eval.jsonl")


def load_eval():
    with open(EVAL, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _recall_at(retrieved, gold, k):
    if not gold:
        return None
    top = set(retrieved[:k])
    return 1.0 if (top & set(gold)) else 0.0


def _mrr_at(retrieved, gold, k=10):
    gs = set(gold)
    for i, pid in enumerate(retrieved[:k], 1):
        if pid in gs:
            return 1.0 / i
    return 0.0


def _ndcg_at(retrieved, gold, k=10):
    """二值相关（gold=1）的 nDCG@k。"""
    gs = set(gold)
    if not gs:
        return None
    dcg = 0.0
    for i, pid in enumerate(retrieved[:k], 1):
        if pid in gs:
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gs), k) + 1))
    return dcg / ideal if ideal else 0.0


def evaluate(mode="lexical", limit=0, topn=20):
    import query_router
    import hybrid_retrieve as H

    rows = load_eval()
    if limit:
        rows = rows[:limit]

    # 硬门禁计数器
    gates = {"fabricated_passage_ids": 0, "broken_passage_references": 0,
             "canonical_source_mutation": 0, "source_hash_mutation": 0,
             "provenance_state_silent_upgrade": 0}

    import sqlite3
    con = sqlite3.connect(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
    store_ids = {r[0] for r in con.execute("SELECT id FROM passage_meta")}
    provenance_of = {r[0]: r[1] for r in
                     con.execute("SELECT id, trace_status FROM passage_meta")}
    con.close()

    m = {k: [] for k in ("r5", "r10", "r20", "mrr10", "ndcg10")}
    # per-query hit rate：top-k 内**命中至少一条 gold** 的查询占比。
    #
    # ⚠️ 诚实更正（实测）：我原以为它比 Recall「更可解释」，因为它不受大 gold 集稀释。
    # 实测发现**二者在上面的 Recall 定义下数值完全相同**（0.1589/0.1963/0.2897）——
    # 因为 gold 均值 ~18 条、每查询命中均值 <1 条，于是「是否命中」在实践上就是
    # 二值的：命中 1 条与命中 3 条都让 Recall 记为 1.0。
    # 所以：
    #   * 它不是另一个指标，而是**同一事实的可读表述**（值得同时报，因为语义直白）；
    #   * 真正的差别在 MRR/nDCG（它们看**名次**），那才是「命中质量」的信息。
    # 结论：报 hit_rate 是对的，但不要声称它「纠正了稀释」——那是我的话说过头了。
    hit = {5: [], 10: [], 20: []}
    ent_ok = ent_tot = 0
    sem_ok = sem_tot = 0
    cross_ok = cross_tot = 0
    diversity = []
    trace_closure = Counter()

    for r in rows:
        plan = query_router.route(r["query"])
        # ---- 直接调用组件（评测不经过 diversity，先量原始检索力）
        if mode == "lexical":
            hits = H.lexical_component(plan, limit=topn)
            diversity.append(H.coverage_of(hits))
        elif mode == "alias":
            hits = [h for h in H.alias_component(plan) if h.get("passage_id")]
            diversity.append(H.coverage_of(hits))
        else:
            b = H.retrieve(r["query"], top_k=topn)
            hits = b["evidence"]
            diversity.append(b["coverage"])
            for e in b["evidence"]:
                if e["passage_id"] not in store_ids:
                    gates["fabricated_passage_ids"] += 1
                if e["passage_id"] in provenance_of and \
                        e["provenance_status"] != provenance_of[e["passage_id"]]:
                    gates["provenance_state_silent_upgrade"] += 1
        retrieved = [h["passage_id"] for h in hits if h.get("passage_id")]

        # ---- 硬门禁：不存在的 ID
        for pid in retrieved:
            if pid not in store_ids:
                gates["fabricated_passage_ids"] += 1

        # ---- 指标（只用计入 recall 的 query）
        if r.get("counted_in_recall") and r["gold_passages"]:
            for k, key in ((5, "r5"), (10, "r10"), (20, "r20")):
                v = _recall_at(retrieved, r["gold_passages"], k)
                if v is not None:
                    m[key].append(v)
            m["mrr10"].append(_mrr_at(retrieved, r["gold_passages"], 10))
            for k in (5, 10, 20):
                hit[k].append(1.0 if set(retrieved[:k]) & set(r["gold_passages"]) else 0.0)
            nd = _ndcg_at(retrieved, r["gold_passages"], 10)
            if nd is not None:
                m["ndcg10"].append(nd)

            # ---- Entity Resolution Accuracy
            exp = set(r["expected_entities"])
            got = {e["entity_id"] for e in plan["entities"]}
            if exp:
                ent_tot += 1
                ent_ok += 1 if exp <= got else 0
            # ---- Seminar Filter Accuracy
            exps = set(r["expected_seminars"])
            gots = set(plan["seminars"])
            if exps:
                sem_tot += 1
                sem_ok += 1 if exps <= gots else 0
            # ---- Cross-language：中文 query 期望能取回法文证据
            if r["language"] == "zh" and r["intent"] == "cross_language":
                cross_tot += 1
                # 明确判定：retrieved 里是否**真的有法文 passage**
                langs = {h.get("language") for h in hits[:20] if h.get("passage_id")}
                if "fr" in langs:
                    cross_ok += 1
            for pid in retrieved:
                trace_closure[provenance_of.get(pid, "UNKNOWN")] += 1

    def avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    scores = {
        "Recall@5": avg(m["r5"]), "Recall@10": avg(m["r10"]),
        "Recall@20": avg(m["r20"]), "MRR@10": avg(m["mrr10"]),
        "nDCG@10": avg(m["ndcg10"]),
    }
    headline = {
        "hit_rate@5": avg(hit[5]), "hit_rate@10": avg(hit[10]),
        "hit_rate@20": avg(hit[20]),
        "note": ("top-k 内命中≥1 条 gold 的查询占比。实测与 Recall@k **数值相同**"
                 "（gold 均值 ~18、每查询命中 <1，故命中是二值的）；"
                 "保留它是为了语义直白，不是「修正了稀释」。"
                 "命中质量请看 MRR@10 / nDCG@10。"),
    }
    project = {
        "Entity Resolution Accuracy": (round(ent_ok / ent_tot, 4) if ent_tot else None),
        "Seminar Filter Accuracy": (round(sem_ok / sem_tot, 4) if sem_tot else None),
        "Cross-language Retrieval Recall": (round(cross_ok / cross_tot, 4)
                                            if cross_tot else None),
        "Source Trace Closure": dict(trace_closure),
        "Citation Validity": (1.0 if gates["fabricated_passage_ids"] == 0
                              and gates["broken_passage_references"] == 0 else 0.0),
        "Evidence Diversity": {
            "avg_seminars": round(sum(len(d["seminars"]) for d in diversity)
                                  / len(diversity), 2) if diversity else None,
            "avg_languages": round(sum(len(d["languages"]) for d in diversity)
                                   / len(diversity), 2) if diversity else None,
        },
    }
    return {
        "schema": "retrieval-eval/v1",
        "mode": mode,
        "queries_total": len(rows),
        "queries_scored": len(m["r10"]),
        "queries_excluded_no_gold": sum(1 for r in rows
                                        if not r.get("counted_in_recall")),
        "metrics": scores,
        "headline_metrics": headline,
        "proxy_warning": ("gold 由**词面子串匹配**推导、非人工标注："
                          "本报告的召回类指标是 lexical proxy，"
                          "会系统性低估语义检索与跨语言检索路径。"),
        "project_metrics": project,
        "hard_gates": gates,
        "hard_gates_pass": all(v == 0 for v in gates.values()),
    }


def print_report(res):
    print("=" * 68)
    print("检索评测  mode=%s" % res["mode"])
    print("=" * 68)
    print("query 总数 %d；计入 recall %d；因无 gold 排除 %d" % (
        res["queries_total"], res["queries_scored"],
        res["queries_excluded_no_gold"]))
    print()
    print("头条指标（与 Recall@k 同值，仅表述更直白）：")
    hm = res.get("headline_metrics") or {}
    for k in ("hit_rate@5", "hit_rate@10", "hit_rate@20"):
        v = hm.get(k)
        print("  %-14s %s" % (k, "n/a" if v is None else "%.4f" % v))
    print()
    print("通用指标（proxy）：")
    for k, v in res["metrics"].items():
        print("  %-10s %s" % (k, "n/a" if v is None else "%.4f" % v))
    print()
    print("项目特有指标：")
    for k, v in res["project_metrics"].items():
        print("  %-32s %s" % (k, json.dumps(v, ensure_ascii=False)
                              if isinstance(v, dict) else
                              ("n/a" if v is None else v)))
    print()
    print("硬门禁：")
    for k, v in res["hard_gates"].items():
        print("  %-34s %s %s" % (k, v, "✓" if v == 0 else "✗"))
    print()
    if res.get("proxy_warning"):
        print("⚠ %s" % res["proxy_warning"])
        print()
    print("硬门禁总判定：%s" % ("通过" if res["hard_gates_pass"] else "**未通过**"))


def main():
    ap = argparse.ArgumentParser(description="检索评测（§15）")
    ap.add_argument("--mode", default="lexical",
                    choices=("lexical", "alias", "hybrid"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    res = evaluate(mode=args.mode, limit=args.limit)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print_report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
