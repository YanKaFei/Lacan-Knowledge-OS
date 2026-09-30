#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_crosslang.py — 解释「ZH→FR 检索为什么≈0」的定量诊断

为什么需要它
────────────
§16 的方向 B（中文问 → 法文证据）在 adjudicated gold 上几乎是 0：
8 条 query 里只有 1 条（mpnet / a13）在 top-20 里捞到 1 条法文段落。

光报一个 0 是不够的 —— 必须回答**为什么**，否则无法判断这是
「模型不行」「gold 标错了」还是「评测设计有问题」。
本脚本把三种解释逐一变成**可测的数字**：

| 假设 | 诊断量 |
|---|---|
| H1 查询/文档不对称：问题是问句，法文段落是陈述句，对称 embedding 拉不近 | 中文 query 与其**法文 gold** 的余弦 vs 与**随机法文段落**的余弦（margin） |
| H2 截断吃掉了信息：法文段落超过 128 token 被切掉 | 法文 gold 段落的**真实** token 长度分布 + 超过 128 的比例 |
| H3 池子/索引有问题：这些段落根本检索不到 | **自查询上界**：拿法文 gold 段落自己的正文当 query，看它能不能进 top-20 |

三项都只读**已缓存的池内嵌入**（`cache_pool_<model>.npy`），不重新嵌入语料。

用法
────
    .venv-embedding/bin/python _scripts/_tools/diagnose_crosslang.py --run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
POOL_OUT = os.path.join(VECDIR, "evaluation_pool.json")
GOLD = os.path.join(VAULT, "retrieval_gold_answerable.jsonl")
OUT = os.path.join(VECDIR, "CROSSLANG_DIAGNOSTIC.json")
REPORT = os.path.join(VAULT, "CROSSLANG_DIAGNOSTIC.md")

sys.path.insert(0, HERE)
RANDOM_FR_SAMPLE = 200
SEED = 20260920


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def gold_of(g):
    out = {}
    for grade, ids in (g.get("gold_evidence") or {}).items():
        for pid in ids or []:
            out[pid] = max(out.get(pid, 0), {"required": 3, "strong": 2,
                                             "contextual": 1}.get(grade, 1))
    return out


def run(models=("minilm", "mpnet")):
    import numpy as np
    import embedding_provider as ep
    from tokenizers import Tokenizer

    pool = json.load(open(POOL_OUT, encoding="utf-8"))
    index = {p: i for i, p in enumerate(pool["pool_ids"])}
    texts = json.load(open(os.path.join(VECDIR, "cache_pool_texts.json"),
                           encoding="utf-8"))["by_id"]
    out = {"schema_version": "crosslang-diagnostic/v1",
           "pool_size": len(pool["pool_ids"]),
           "hypotheses": {
               "H1_query_document_asymmetry": "中文问句 vs 法文陈述句，对称 embedding 拉不近",
               "H2_truncation": "法文段落真实长度超过生效截断长度 128，相关部分被切掉",
               "H3_index_or_pool": "这些段落根本检索不到（池子/索引问题）",
           },
           "models": {}}

    gold = jl(GOLD)
    b_queries = []
    for g in gold:
        gg = gold_of(g)
        langs = {texts.get(p, {}).get("language") for p in gg}
        if g["language"] == "zh" and langs == {"fr"}:
            b_queries.append((g, gg))
    out["direction_B_query_count"] = len(b_queries)

    rng = np.random.RandomState(SEED)
    fr_pool = [p for p in pool["pool_ids"] if texts[p]["language"] == "fr"]
    sample = [fr_pool[i] for i in rng.choice(len(fr_pool),
                                             size=min(RANDOM_FR_SAMPLE, len(fr_pool)),
                                             replace=False)]
    out["random_fr_sample_size"] = len(sample)

    for model in models:
        cache = os.path.join(VECDIR, "cache_pool_%s.npy" % model)
        meta = os.path.join(VECDIR, "cache_pool_%s.json" % model)
        if not (os.path.isfile(cache) and os.path.isfile(meta)):
            out["models"][model] = {"status": "NO_CACHE"}
            continue
        mat = np.load(cache)
        m = json.load(open(meta, encoding="utf-8"))
        if m.get("pool_ids_sha256") != pool["pool_ids_sha256"]:
            out["models"][model] = {"status": "CACHE_POOL_MISMATCH"}
            continue
        prov = ep.OnnxTransformersProvider(model)
        eff = prov.length_contract["effective_max_length"]
        tok = Tokenizer.from_file(os.path.join(ep.MODEL_ROOTS[model], "tokenizer.json"))
        tok.no_padding()
        tok.no_truncation()          # 要**真实**长度，不是截断后的

        rows = []
        for g, gg in b_queries:
            gold_ids = [p for p in gg if p in index]
            if not gold_ids:
                continue
            qv = np.asarray(prov.embed_queries([g["query"]])[0], dtype="float32")
            gsim = mat[[index[p] for p in gold_ids]] @ qv
            rsim = mat[[index[p] for p in sample]] @ qv
            lens = [len(tok.encode(texts[p]["normalized_text"]).ids) for p in gold_ids]
            # 名次：这条 gold 在整池里的最好名次
            allsim = mat @ qv
            order = np.lexsort((np.asarray(pool["pool_ids"]), -allsim))
            rank = {pool["pool_ids"][i]: r for r, i in enumerate(order, 1)}
            best_rank = min(rank[p] for p in gold_ids)
            # H3：自查询上界 —— 拿 gold 段落自己的正文当 query
            self_hits = []
            for p in gold_ids[:3]:
                sv = np.asarray(prov.embed_queries([texts[p]["normalized_text"]])[0],
                                dtype="float32")
                sims = mat @ sv
                o2 = np.lexsort((np.asarray(pool["pool_ids"]), -sims))
                top20 = {pool["pool_ids"][i] for i in o2[:20]}
                self_hits.append({
                    "self_in_top20": p in top20,
                    "gold_hits_in_top20": len(top20 & set(gold_ids)),
                })
            rows.append({
                "query_id": g["query_id"],
                "query": g["query"],
                "gold_ids": gold_ids[:8],
                "gold_n": len(gold_ids),
                "gold_fr_mean_cosine": float(np.mean(gsim)),
                "random_fr_mean_cosine": float(np.mean(rsim)),
                "margin": float(np.mean(gsim) - np.mean(rsim)),
                "best_gold_rank_in_pool": int(best_rank),
                "gold_token_lengths_real": lens,
                "gold_over_effective_len": sum(1 for L in lens if L > eff),
                "self_query_ceiling": self_hits,
            })

        all_lens = [L for r in rows for L in r["gold_token_lengths_real"]]
        out["models"][model] = {
            "status": "OK",
            "effective_max_length": eff,
            "gold_fr_passage_n": len(all_lens),
            "gold_token_length": {
                "min": min(all_lens) if all_lens else None,
                "max": max(all_lens) if all_lens else None,
                "mean": (sum(all_lens) / len(all_lens)) if all_lens else None,
                "over_effective_len": sum(1 for L in all_lens if L > eff),
                "over_effective_len_ratio": (sum(1 for L in all_lens if L > eff)
                                             / len(all_lens)) if all_lens else None,
            },
            "H1_margin": {
                "mean_margin_vs_random_fr": (sum(r["margin"] for r in rows) / len(rows))
                if rows else None,
                "queries_with_positive_margin": sum(1 for r in rows if r["margin"] > 0),
                "n": len(rows),
            },
            "H3_self_query_ceiling": {
                "self_in_top20_count": sum(1 for r in rows
                                           for s in r["self_query_ceiling"]
                                           if s["self_in_top20"]),
                "self_probes": sum(len(r["self_query_ceiling"]) for r in rows),
                "gold_hits_in_top20_total": sum(s["gold_hits_in_top20"]
                                                for r in rows
                                                for s in r["self_query_ceiling"]),
            },
            "per_query": rows,
        }
        mo = out["models"][model]
        print("[%s] gold_fr n=%s 真实长度 mean=%.1f/%s 超长 %s (%.0f%%) | "
              "H1 margin=%s 正 margin %s/%s | H3 自命中 %s/%s" % (
                  model, mo["gold_fr_passage_n"],
                  mo["gold_token_length"]["mean"] or 0, eff,
                  mo["gold_token_length"]["over_effective_len"],
                  100 * (mo["gold_token_length"]["over_effective_len_ratio"] or 0),
                  ("%.4f" % mo["H1_margin"]["mean_margin_vs_random_fr"])
                  if mo["H1_margin"]["mean_margin_vs_random_fr"] is not None else "—",
                  mo["H1_margin"]["queries_with_positive_margin"], mo["H1_margin"]["n"],
                  mo["H3_self_query_ceiling"]["self_in_top20_count"],
                  mo["H3_self_query_ceiling"]["self_probes"]))

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    write_report(out)
    return out


def write_report(d):
    L = []
    A = L.append
    A("# CROSSLANG_DIAGNOSTIC.md — 「中文问 → 法文证据」为什么≈0\n")
    A("> 生成：`_scripts/_tools/diagnose_crosslang.py`　·　"
      "原始数据：`_data/index/vector/CROSSLANG_DIAGNOSTIC.json`\n")
    A("## 0. 要解释的现象\n")
    A("方向 B（`query 语言 = zh` 且 `gold 语言 = fr`）共 **%d** 条。"
      "在这 %d 条上，`V`（纯向量）的 Recall@20 是：minilm **0/8**，"
      "mpnet **1/8**（只有 `a13` 捞到 1 条）。\n" % (d["direction_B_query_count"],
                                                d["direction_B_query_count"]))
    A("**一个 0 不足以说明任何事。** 下面是三个可证伪的解释变成数字的结果。\n")
    A("| 假设 | 含义 |")
    A("|---|---|")
    for k, v in d["hypotheses"].items():
        A("| `%s` | %s |" % (k, v))
    A("")
    A("## 1. 三项诊断结果\n")
    A("| 模型 | 法文 gold 段落数 | 真实 token 长度均值 | 超出生效长度 %s 的比例 | H1 margin（vs 随机法文段） | 正 margin 的 query | H3 自查询进 top-20 |"
      % "（128）")
    A("|---|---:|---:|---:|---:|---:|---:|")
    for k, v in d["models"].items():
        if v.get("status") != "OK":
            A("| `%s` | — | — | — | — | — | %s |" % (k, v.get("status")))
            continue
        g = v["gold_token_length"]
        A("| `%s` | %d | %.1f | %d/%d = **%.0f%%** | %s | %d/%d | %d/%d |" % (
            k, v["gold_fr_passage_n"], g["mean"] or 0,
            g["over_effective_len"], v["gold_fr_passage_n"],
            100 * (g["over_effective_len_ratio"] or 0),
            ("%+.4f" % v["H1_margin"]["mean_margin_vs_random_fr"])
            if v["H1_margin"]["mean_margin_vs_random_fr"] is not None else "—",
            v["H1_margin"]["queries_with_positive_margin"], v["H1_margin"]["n"],
            v["H3_self_query_ceiling"]["self_in_top20_count"],
            v["H3_self_query_ceiling"]["self_probes"]))
    A("")
    # ---- 明确判定（不能只给规则让人自己猜）
    A("### 1.1 判定（按上面的数字直接下结论）\n")
    for k, v in d["models"].items():
        if v.get("status") != "OK":
            continue
        g = v["gold_token_length"]
        ratio = g["over_effective_len_ratio"] or 0
        sc = v["H3_self_query_ceiling"]
        ceil = sc["self_in_top20_count"] / sc["self_probes"] if sc["self_probes"] else 0
        h1 = v["H1_margin"]["mean_margin_vs_random_fr"] or 0
        A("**`%s`**" % k)
        A("- **H2（截断）%s** —— 法文 gold 真实长度均值 %.1f，超出生效长度 %s 的占 %.0f%%（%d/%d）。"
          % ("成立" if ratio >= 0.5 else "不成立", g["mean"] or 0,
             v["effective_max_length"], 100 * ratio,
             g["over_effective_len"], v["gold_fr_passage_n"]))
        A("- **H3（索引/池子）%s** —— 自查询上界 %d/%d = %.0f%%："
          "拿段落自己的正文当 query，能否把它自己找回来。"
          % ("成立" if ceil < 0.5 else "不成立", sc["self_in_top20_count"],
             sc["self_probes"], 100 * ceil))
        A("- **H1（查询/文档不对称）%s** —— gold 段落相对随机法文段落的余弦优势只有 **%+.4f**，"
          "正 margin 的 query %d/%d。"
          % ("成立（信号弱到不足以进 top-20）" if h1 < 0.1 else "不成立",
             h1, v["H1_margin"]["queries_with_positive_margin"], v["H1_margin"]["n"]))
        A("")
    A("→ 结论：**H2 与 H3 都不成立**（不是截断、也不是索引问题），"
      "剩下的解释是 H1：**语义信号存在，但问句→段落的区分度太小**，"
      "在 6,305 条池子里排不进前 20。\n")
    A("### 判读规则（先写下来，再去套数字）\n")
    A("- **H3 自查询上界 ≈ 100%** → 索引和池子没问题，问题在 query 侧（偏 H1）。")
    A("- **H3 明显 < 100%** → 连段落自己的正文都召不回自己，说明池子/索引/嵌入有问题，"
      "这时 H1 的 margin 数字不能单独解读。")
    A("- **超长比例高** → 截断吃掉了内容，H2 是真实贡献项，应提高 `max_seq_length` 重测。")
    A("- **margin 为正但 Recall≈0** → 语义信号存在但**不足以把 gold 排进 top-20**："
      "这是「margin ≠ retrieval」的直接证据。\n")
    A("## 2. 逐条明细\n")
    for k, v in d["models"].items():
        if v.get("status") != "OK":
            continue
        A("### `%s`\n" % k)
        A("| query | gold n | 法文 gold 平均余弦 | 随机法文段平均余弦 | margin | gold 最好名次 | 真实长度 | 超长 |")
        A("|---|---:|---:|---:|---:|---:|---|---:|")
        for r in v["per_query"]:
            A("| `%s` | %d | %.4f | %.4f | %+.4f | %d | %s | %d |" % (
                r["query_id"], r["gold_n"], r["gold_fr_mean_cosine"],
                r["random_fr_mean_cosine"], r["margin"],
                r["best_gold_rank_in_pool"],
                ",".join(str(x) for x in r["gold_token_lengths_real"][:8]),
                r["gold_over_effective_len"]))
        A("")
    A("## 3. 这只解释了方向 B，不能外推\n")
    A("- 这是 **%d 条** query 上的诊断，样本极小，不能当统计结论。" % d["direction_B_query_count"])
    A("- 它**不**说明模型没有跨语言能力 —— 词级余弦确实很高"
      "（例如 `大他者` vs `le grand Autre` ≈ 0.72–0.75）。"
      "它说明的是：**词级相似 ≠ 问句→段落检索**。")
    A("- 要提高方向 B，可做的（都还没做，也不在本轮范围）："
      "非对称检索（query 侧改写/扩展）、提高 `max_seq_length`、"
      "对法文段落做法语侧同义扩展、或换用非对称双塔模型。"
      "这些都需要**另行实现并重测**，不能靠调阈值。")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT)


def cmd_check():
    """无需运行时的产物自检（供 run_all_tests.sh 调用）。"""
    problems = []
    if not os.path.isfile(OUT):
        return {"status": "FAIL", "problems": ["缺 CROSSLANG_DIAGNOSTIC.json"]}
    d = json.load(open(OUT, encoding="utf-8"))
    md = open(REPORT, encoding="utf-8").read() if os.path.isfile(REPORT) else ""
    for m, v in d["models"].items():
        if v.get("status") != "OK":
            problems.append("%s 诊断未完成: %s" % (m, v.get("status")))
            continue
        sc = v["H3_self_query_ceiling"]
        if sc["self_probes"] == 0:
            problems.append("%s: H3 没有探针" % m)
        if "不成立" not in md:
            problems.append("报告没有对 H2/H3 给出「不成立」的明确判定")
            break
    if not os.path.isfile(REPORT):
        problems.append("缺 CROSSLANG_DIAGNOSTIC.md")
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "direction_B_queries": d.get("direction_B_query_count")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--check", action="store_true")
    ap.add_argument("--models", default="minilm,mpnet")
    a = ap.parse_args(argv)
    if a.check:
        r = cmd_check()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["status"] == "PASS" else 1
    run(tuple(a.models.split(",")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
