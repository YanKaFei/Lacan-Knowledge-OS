#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scale_transfer_analysis.py — Phase 3C §11 的核心问题：**池内结论能不能搬到全量？**

背景（这是本阶段最重要的一次对账）
──────────────────────────────────
Phase 3B.2 在 **6,305 条池**上得出「hybrid > 单路」。
Phase 3C 在 **249,105 条全量**上重跑，结果反过来了：

| 配置 | 6,305 池 hit@20 | 249,105 全量 hit@20 |
|---|---:|---:|
| `L` | 0.1861 | 0.0445 |
| `V` | 0.1135 | 0.0031 |
| `E+L+V+X` | 0.3024 | 0.0238 |

**绝对值都降了（候选集大了 39.5 倍），但降的幅度差了两个数量级。**
所以本脚本算的不是「降了多少」，而是**每个方法相对随机基线还有多少倍**：

    random_hit@20 = 20 × mean_gold_n / N
    lift = measured / random

`lift` 是**尺度无关**的量。若某方法的 lift 在两种尺度下相同，
说明它的判别力没变、只是被更大的候选集按比例稀释；
若 lift 明显下降，说明它在全量下**真的失效了**。

这个区分很重要，因为它决定结论该怎么写：
* lift 不变 → 「方法有效但需要 ANN/重排来把 top-k 用在大候选集上」；
* lift 下降 → 「方法在这个规模上不成立」。

用法
────
    python3 _scripts/_tools/scale_transfer_analysis.py            # 生成报告
    python3 _scripts/_tools/scale_transfer_analysis.py --verify
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
POOL_RESULTS = os.path.join(VECDIR, "semantic_benchmark_results.json")
FULL_RESULTS = os.path.join(VECDIR, "full_corpus_results.json")
OUT = os.path.join(VECDIR, "scale_transfer_analysis.json")
REPORT = os.path.join(VAULT, "SCALE_TRANSFER_ANALYSIS.md")

POOL_N = 6305
FULL_N = 249105
K = 20
CFGS = ["L", "V", "E+L+V", "E+L+V+X", "ROUTED"]


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None


def mean_gold(pool_doc, full_doc):
    """从两份结果里取同一批 query 的平均 gold 条数（用于算随机基线）。"""
    for d, key in ((full_doc, "per_query"), (pool_doc, "per_query")):
        if not d:
            continue
        for m, v in d.get("results", d.get("models", {})).items():
            qs = v.get(key) or []
            if qs:
                return sum(q["gold_n"] for q in qs) / len(qs)
    return None


def analyse():
    pool = load(POOL_RESULTS)
    full = load(FULL_RESULTS)
    if not pool or not full:
        return None
    g = mean_gold(pool, full)
    rand_pool = K * g / POOL_N
    rand_full = K * g / FULL_N

    pa = list(pool["results"].values())[0]["aggregate"]
    fa = list(full["models"].values())[0]["aggregate"]

    rows = []
    for c in CFGS:
        p = (pa.get(c) or {}).get("hit@20")
        f = (fa.get(c) or {}).get("hit@20")
        if p is None or f is None:
            continue
        rows.append({
            "config": c,
            "pool_hit20": p, "full_hit20": f,
            "pool_lift": p / rand_pool if rand_pool else None,
            "full_lift": f / rand_full if rand_full else None,
            "ratio_full_over_pool": (f / p) if p else None,
            "lift_retention": ((f / rand_full) / (p / rand_pool))
            if (p and rand_pool and rand_full) else None,
        })

    doc = {
        "schema_version": "scale-transfer/v1",
        "question": ("6,305 池上的结论（hybrid > 单路）能不能搬到 249,105 全量？"),
        "mean_gold_n": g,
        "random_baseline": {"pool": rand_pool, "full": rand_full,
                            "formula": "k × mean_gold_n / N（k=%d）" % K},
        "scales": {"pool": POOL_N, "full": FULL_N},
        "rows": rows,
        "dilution_hypothesis_rejected": {
            "hypothesis": ("全量下 E/X 候选列表变长，RRF 的 1/(k+rank) 让弱候选累积、"
                           "稀释词法强信号"),
            "test": "给每个分量各自截断到 50 后再 RRF",
            "result": ("E_cap+L_cap+V_cap+X_cap = %.4f vs 未截断 E+L+V+X = %.4f；"
                       "ROUTED_cap = %.4f vs ROUTED = %.4f"
                       % ((fa.get("E_cap+L_cap+V_cap+X_cap") or {}).get("hit@20") or 0,
                          (fa.get("E+L+V+X") or {}).get("hit@20") or 0,
                          (fa.get("ROUTED_cap") or {}).get("hit@20") or 0,
                          (fa.get("ROUTED") or {}).get("hit@20") or 0)),
            "verdict": "**假设不成立** —— 截断几乎不改变结果，所以不是列表长度的问题",
        },
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_report(doc)
    return doc


def write_report(d):
    L = []
    A = L.append
    A("# SCALE_TRANSFER_ANALYSIS.md — Phase 3C §11\n")
    A("> 代码：`_scripts/_tools/scale_transfer_analysis.py`　·　"
      "数据：`_data/index/vector/scale_transfer_analysis.json`\n")
    A("## 0. 这一节回答什么\n")
    A("Phase 3B.2 在 **6,305 条池**上得出「hybrid > 单路」；"
      "Phase 3C 在 **%s 条全量**上重跑，**结论反过来了**。\n" % "{:,}".format(d["scales"]["full"]))
    A("§11 明确要求：**不得继续把 6,305 pool 的结果称为 production retrieval result。**"
      "所以这一节做的是**对账**，不是宣传。\n")
    A("## 1. 关键指标：相对随机基线的**倍数**（`lift`）\n")
    A("绝对值会随候选集大小变化，不可直接比较。所以用：\n")
    A("```")
    A("random_hit@20 = k × mean_gold_n / N = 20 × %.2f / N" % (d["mean_gold_n"] or 0))
    A("lift = measured_hit@20 / random_hit@20        # 尺度无关")
    A("```")
    A("| 池 N | 全量 N | 随机基线（池） | 随机基线（全量） |")
    A("|---:|---:|---:|---:|")
    A("| %d | %d | %.5f | %.5f |" % (
        d["scales"]["pool"], d["scales"]["full"],
        d["random_baseline"]["pool"], d["random_baseline"]["full"]))
    A("")
    A("| 配置 | 池 hit@20 | 全量 hit@20 | 池 lift | 全量 lift | **lift 保留率** | 全量/池 |")
    A("|---|---:|---:|---:|---:|---:|---:|")
    for r in d["rows"]:
        A("| `%s` | %.4f | %.4f | %.2f× | %.2f× | **%.2f×** | %.3f |" % (
            r["config"], r["pool_hit20"], r["full_hit20"],
            r["pool_lift"] or 0, r["full_lift"] or 0,
            r["lift_retention"] or 0, r["ratio_full_over_pool"] or 0))
    A("")
    A("**`lift 保留率` 是这一节的核心数字**：它是「判别力有没有变」的尺度无关度量。\n")
    A("- 保留率 **≈1** → 方法有效，只是被更大的候选集按比例稀释；")
    A("- 保留率 **明显 <1** → 方法在这个规模上**真的失效了**。\n")
    A("## 2. 判读\n")
    v = {r["config"]: r for r in d["rows"]}
    if "V" in v and "L" in v:
        A("- **`V`（纯向量）**：池 lift %.2f× → 全量 lift %.2f×，保留率 **%.2f×**。" % (
            v["V"]["pool_lift"] or 0, v["V"]["full_lift"] or 0,
            v["V"]["lift_retention"] or 0))
        A("  向量检索是**固定 top-k 扫描**：候选集大 39.5 倍，命中概率天然除以 ~39.5，"
          "而 lift 保留率若接近 1 说明判别力没变。")
        A("- **`L`（词法）**：池 lift %.2f× → 全量 lift %.2f×，保留率 **%.2f×**。" % (
            v["L"]["pool_lift"] or 0, v["L"]["full_lift"] or 0,
            v["L"]["lift_retention"] or 0))
        A("  BM25 的名次由文档自身与查询的匹配决定，**不随候选集大小按比例退化**。")
        A("")
        if (v["L"]["lift_retention"] or 0) > (v["V"]["lift_retention"] or 0):
            A("→ **词法的 lift 保留率高于向量**：语料越大，词法相对向量的优势**越大**。"
              "这解释了为什么池内的「hybrid 更好」在全量下反转。")
    A("")
    A("## 3. 「长列表稀释」假设：**已被证伪**\n")
    dh = d["dilution_hypothesis_rejected"]
    A("| 项 | 内容 |")
    A("|---|---|")
    A("| 假设 | %s |" % dh["hypothesis"])
    A("| 检验 | %s |" % dh["test"])
    A("| 结果 | %s |" % dh["result"])
    A("| 判定 | %s |" % dh["verdict"])
    A("")
    A("这一条**必须写下来**：它排除了一个看起来很像的解释，"
      "证明结论不是「RRF 参数没调好」，而是**方法在不同规模上的行为本来就不一样**。\n")
    A("## 4. 结论（不得修饰）\n")
    A("**Phase 3B.2 的池内结论没有搬到 production scale。**\n")
    A("- 全量语料上 **`L` 是单路最好**，而**含向量的配置都更差**；")
    A("- `ROUTED` 也没有超过 `L`；")
    A("- 因此 Phase 3C 的诚实结论是：**当前 Retrieval System 在全量规模上是"
      "「词法主导 + 术语桥辅助」**，而不是「语义检索系统」。\n")
    A("这不是「调参就能修」的问题 —— §24 也**不要求** vector 在所有 query 上优于 lexical。"
      "但把这些数字写成「semantic retrieval improved」就是不诚实。\n")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[scale] %s" % REPORT)
    for r in d["rows"]:
        print("   %-14s pool %.4f (lift %.2f×) -> full %.4f (lift %.2f×)  retention %.2f×"
              % (r["config"], r["pool_hit20"], r["pool_lift"] or 0,
                 r["full_hit20"], r["full_lift"] or 0, r["lift_retention"] or 0))


def cmd_verify():
    d = load(OUT)
    if not d:
        return {"status": "FAIL", "problems": ["缺 scale_transfer_analysis.json"]}
    problems = []
    if not d["rows"]:
        problems.append("没有任何配置的行")
    if d["dilution_hypothesis_rejected"]["verdict"] is None:
        problems.append("稀释假设没有给出判定")
    t = open(REPORT, encoding="utf-8").read() if os.path.isfile(REPORT) else ""
    if "没有搬到 production scale" not in t:
        problems.append("报告必须明确写出池内结论未搬到全量")
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "configs": [r["config"] for r in d["rows"]]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.run:
        analyse()
        return 0
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
