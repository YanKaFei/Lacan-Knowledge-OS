#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evaluate_fr_directions.py — §16 方向 C（FR→FR）与 D（FR→ZH）的**独立**评测

背景
────
主 gold 45 条里只有 2 条法语 query，且目标证据跨 zh/fr → 全部归入 `MUL_mixed`，
于是方向 **C/D 的 n = 0（没有样本，不是测得 0）**。
`build_fr_gold_supplement.py` 用**同一套标注方法**补了 12 条法语 query
（6 条金标 FR-only → C；6 条金标 ZH-only → D）。本脚本在这 12 条上评测。

**隔离设计（重要）**
────────────────────
* 主 benchmark 的池 `evaluation_pool.json`（6,305 条）**不动**，它的
  `pool_ids_sha256` 不变 —— 否则主表所有数字都要重跑重写。
* 本评测用**自己的池** `evaluation_pool_fr.json`：
  `benchmark corpus(6,000)` ∪ `补充 gold 段落(96)`，独立 sha256。
* 分母也独立：12 条，不与主 benchmark 的 n=40 平均。
* 嵌入**复用**主池缓存的前 6,000 行（构造顺序保证 bench_ids 在前），
  只对新增的 96 条现算 —— 否则要为每模型重嵌 6,000 条（mpnet 约 18 分钟）。

用法
────
    .venv-embedding/bin/python _scripts/_tools/evaluate_fr_directions.py --run
    python3 _scripts/_tools/evaluate_fr_directions.py --verify
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
STORE = os.path.join(VAULT, "_data", "passage_store")

SUPP = os.path.join(VAULT, "retrieval_gold_fr_supplement.jsonl")
POOL = os.path.join(VECDIR, "evaluation_pool.json")
POOL_FR = os.path.join(VECDIR, "evaluation_pool_fr.json")
OUT_JSON = os.path.join(VECDIR, "fr_directions.json")
REPORT = os.path.join(VAULT, "FR_DIRECTIONS_REPORT.md")
BENCH = os.path.join(VECDIR, "vector_benchmark_corpus.jsonl")

sys.path.insert(0, HERE)


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def sha256_join(items):
    h = hashlib.sha256()
    for x in items:
        h.update(str(x).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def gold_of(g):
    out = {}
    for grade, ids in (g.get("gold_evidence") or {}).items():
        for pid in ids or []:
            out[pid] = max(out.get(pid, 0), {"required": 3, "strong": 2,
                                             "contextual": 1}.get(grade, 1))
    return out


def load_bodies(ids):
    want = set(ids)
    out = {}
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not want:
                break
            d = json.loads(line)
            if d["id"] in want:
                out[d["id"]] = d
                want.discard(d["id"])
    return out


def build_pool_fr():
    """独立池：benchmark corpus 原序在前（以便复用缓存） + 补充 gold 段落。"""
    import semantic_benchmark as sb
    bench_ids = [json.loads(l)["passage_id"] for l in open(BENCH, encoding="utf-8")]
    supp = jl(SUPP)
    need = []
    for g in supp:
        for pid in gold_of(g):
            if pid not in need:
                need.append(pid)
    added = [p for p in need if p not in set(bench_ids)]
    pool = bench_ids + added
    doc = {
        "schema_version": "evaluation-pool/v1",
        "purpose": ("§16 方向 C/D 的**独立**评测池。与主池 `evaluation_pool.json` 隔离，"
                    "以免改动它而让主 benchmark 全部数字失效。"),
        "components": {
            "vector_benchmark_corpus": {"path": os.path.relpath(BENCH, VAULT),
                                        "count": len(bench_ids),
                                        "reused_from_main_cache_rows": "0..%d" % (len(bench_ids) - 1)},
            "supplement_gold_union": {"path": os.path.relpath(SUPP, VAULT),
                                      "count": len(need), "added": len(added)},
        },
        "pool_size": len(pool),
        "pool_ids_sha256": sha256_join(pool),
        "pool_ids": pool,
        "isolated_from_main_pool": True,
    }
    json.dump(doc, open(POOL_FR, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return doc, added


def get_matrix(model, pool_fr, added):
    """主池缓存前 6,000 行（= benchmark corpus）+ 现算新增段落。"""
    import numpy as np
    import embedding_provider as ep
    main = json.load(open(POOL, encoding="utf-8"))
    bench_ids = [json.loads(l)["passage_id"] for l in open(BENCH, encoding="utf-8")]
    # 构造顺序保证 bench_ids 在主池最前面 —— 断言它，不能假设
    assert main["pool_ids"][:len(bench_ids)] == bench_ids, \
        "主池前 %d 条不是 benchmark corpus 原序，缓存复用不成立" % len(bench_ids)
    cache = os.path.join(VECDIR, "cache_pool_%s.npy" % model)
    if not os.path.isfile(cache):
        raise SystemExit("缺主池缓存 %s（先跑 semantic_benchmark.py --run）" % cache)
    mat = np.load(cache)[:len(bench_ids)]
    if added:
        prov = ep.OnnxTransformersProvider(model)
        bodies = load_bodies(added)
        texts = [bodies[p]["normalized_text"] for p in added]
        fresh = np.asarray(prov.embed_documents(texts, batch_size=16), dtype="float32")
        mat = np.vstack([mat, fresh])
        np.save(os.path.join(VECDIR, "cache_pool_fr_%s.npy" % model), fresh)
    return mat


def run(models=("minilm", "mpnet")):
    import numpy as np
    import semantic_benchmark as sb
    import embedding_provider as ep
    import query_router

    pool_fr, added = build_pool_fr()
    index = {p: i for i, p in enumerate(pool_fr["pool_ids"])}
    bodies = load_bodies(pool_fr["pool_ids"])
    pool_fr["_index"] = index
    pool_fr["_text"] = {p: (bodies[p].get("normalized_text") or "") for p in pool_fr["pool_ids"]}
    pool_fr["_lang"] = {p: bodies[p].get("language") for p in pool_fr["pool_ids"]}

    gold = jl(SUPP)
    out = {"schema_version": "fr-directions/v1",
           "supplement_queries": len(gold),
           "pool_fr_size": pool_fr["pool_size"],
           "pool_fr_ids_sha256": pool_fr["pool_ids_sha256"],
           "denominator_note": ("**独立分母**：本表 n=12（C 6 条 + D 6 条），"
                                "与主 benchmark 的 n=40 不得平均。"),
           "models": {}}

    for model in models:
        mat = get_matrix(model, pool_fr, added)
        prov = ep.OnnxTransformersProvider(model)
        per = []
        for g in gold:
            gg = gold_of(g)
            in_pool = {p for p in gg if p in index}
            qlang = "fr"
            plan = query_router.route(g["query"])
            L = sb.lexical_rank(g["query"], None, pool_fr, plan=plan)
            E = sb.alias_exact_rank(g["query"], pool_fr)
            qv = np.asarray(prov.embed_queries([g["query"]])[0], dtype="float32")
            V = sb.vector_rank(qv, mat, pool_fr)
            X = sb.crosslang_alias_rank(g["query"], pool_fr, plan, qlang)
            cands = {"L": L, "V": V, "E+L+V": sb.rrf([E, L, V]),
                     "E+L+V+X": sb.rrf([E, L, V, X])}
            m = {}
            for c, ranked in cands.items():
                m[c] = {"hit@5": sb.recall_at(ranked, in_pool, 5),
                        "hit@10": sb.recall_at(ranked, in_pool, 10),
                        "hit@20": sb.recall_at(ranked, in_pool, 20),
                        "mrr@10": sb.mrr_at(ranked, in_pool, 10),
                        "ndcg@10": sb.ndcg_at(ranked, gg, 10),
                        "top20": ranked[:20]}
            per.append({"query_id": g["query_id"], "direction": g["supplementary_for"][0],
                        "query": g["query"], "target_language": g["target_language"],
                        "gold_n": len(gg), "gold_in_pool_n": len(in_pool),
                        "metrics": m})
        agg = {}
        for d in ("C_fr2fr", "D_fr2zh"):
            sel = [q for q in per if q["direction"] == d]
            agg[d] = {"n": len(sel)}
            for c in ("L", "V", "E+L+V", "E+L+V+X"):
                agg[d][c] = {k: sb.avg([q["metrics"][c][k] for q in sel])
                             for k in ("hit@5", "hit@10", "hit@20", "mrr@10", "ndcg@10")}
        out["models"][model] = {"pool_size": len(pool_fr["pool_ids"]),
                                "aggregate": agg, "per_query": per}
        print("[%s] C n=%d | D n=%d" % (model, agg["C_fr2fr"]["n"], agg["D_fr2zh"]["n"]))

    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_report(out)
    return out


def write_report(d):
    L = []
    A = L.append
    A("# FR_DIRECTIONS_REPORT.md — §16 方向 C（FR→FR）与 D（FR→ZH）\n")
    A("> 生成：`_scripts/_tools/evaluate_fr_directions.py`　·　"
      "原始数据：`_data/index/vector/fr_directions.json`　·　"
      "补充 gold：`retrieval_gold_fr_supplement.jsonl`　·　"
      "独立池：`_data/index/vector/evaluation_pool_fr.json`\n")
    A("## 0. 为什么需要这份补充评测\n")
    A("主 gold 45 条里只有 **2 条法语 query**，且它们的目标证据**跨 zh/fr 两种语言**，"
      "按规则归入 `MUL_mixed`。于是方向 C/D 的 **n = 0** —— "
      "**不是测得 0，是根本没有样本**。\n")
    A("因此用**与主 gold 完全同一套标注方法**补了 **%d 条法语 query**"
      "（6 条金标 FR-only → C；6 条金标 ZH-only → D）。\n" % d["supplement_queries"])
    A("**隔离设计（否则会污染已交付的数字）**：\n")
    A("- 主池 `evaluation_pool.json`（6,305 条）**一个字节没动**，`pool_ids_sha256` 不变；")
    A("- 本评测用自己的池 `evaluation_pool_fr.json`（**%d 条**：benchmark corpus 6,000 ∪ 补充 gold 段落），独立 sha256；" % d["pool_fr_size"])
    A("- **分母独立**：n=12，与主 benchmark 的 n=40 **不得平均**；")
    A("- 嵌入复用主池缓存的前 6,000 行，只对新增段落现算（省掉为每模型重嵌 6,000 条）。\n")
    A("## 1. 结果\n")
    for m, v in d["models"].items():
        A("### `%s`\n" % m)
        A("| 方向 | n | 配置 | hit@5 | hit@10 | hit@20 | MRR@10 | nDCG@10 |")
        A("|---|---:|---|---:|---:|---:|---:|---:|")
        for dv, name in (("C_fr2fr", "C：FR 问 → FR 证据"), ("D_fr2zh", "D：FR 问 → ZH 证据")):
            a = v["aggregate"][dv]
            for c in ("L", "V", "E+L+V", "E+L+V+X"):
                mm = a[c]
                A("| %s | %d | `%s` | %.4f | %.4f | %.4f | %.4f | %.4f |" % (
                    name, a["n"], c, mm["hit@5"] or 0, mm["hit@10"] or 0,
                    mm["hit@20"] or 0, mm["mrr@10"] or 0, mm["ndcg@10"] or 0))
        A("")
        A("| query | 方向 | 目标语言 | gold n | `L` hit@20 | `V` hit@20 | `E+L+V+X` hit@20 |")
        A("|---|---|---|---:|---:|---:|---:|")
        for q in v["per_query"]:
            A("| `%s` | %s | %s | %d | %.4f | %.4f | %.4f |" % (
                q["query_id"], q["direction"], q["target_language"], q["gold_n"],
                q["metrics"]["L"]["hit@20"] or 0, q["metrics"]["V"]["hit@20"] or 0,
                q["metrics"]["E+L+V+X"]["hit@20"] or 0))
        A("")
    A("## 2. 不能声称的东西\n")
    A("- 这 12 条是**补充**标注（`review_status = adjudicated_script_assisted`，无第二标注者），"
      "与主集同一诚实等级，但**不是**独立第三方 gold。")
    A("- 它们**没有**并进主集，主 benchmark 的 n=40 与所有主表数字**未受影响**。")
    A("- 池是 6,096 条，不是全量 249,105 条 → 仍然是方法间相对比较。")
    A("- gold 分级只有 `strong`（脚本按「单一高区分度写法命中」推导），`required` 为空 —— "
      "因为每条 query 只对应 1–2 个 concept，达不到「≥2 个不同写法共现」的 required 门槛。"
      "**不为填 schema 而虚构 required。**")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT)


def cmd_verify():
    problems = []
    for p in (SUPP, POOL_FR, OUT_JSON, REPORT):
        if not os.path.isfile(p):
            problems.append("缺产物: %s" % os.path.relpath(p, VAULT))
    if problems:
        return {"status": "FAIL", "problems": problems}
    d = json.load(open(OUT_JSON, encoding="utf-8"))
    pool_fr = json.load(open(POOL_FR, encoding="utf-8"))
    if sha256_join(pool_fr["pool_ids"]) != pool_fr["pool_ids_sha256"]:
        problems.append("evaluation_pool_fr 的 pool_ids_sha256 不符")
    # 主池必须没被这次评测改动
    mainp = os.path.join(VECDIR, "evaluation_pool.json")
    main = json.load(open(mainp, encoding="utf-8"))
    if sha256_join(main["pool_ids"]) != main["pool_ids_sha256"]:
        problems.append("主池 evaluation_pool 被改动了")
    rows = jl(SUPP)
    if len(rows) != d["supplement_queries"]:
        problems.append("补充 gold 条数与结果不符")
    for m, v in d["models"].items():
        if v["aggregate"]["C_fr2fr"]["n"] == 0 or v["aggregate"]["D_fr2zh"]["n"] == 0:
            problems.append("%s: C 或 D 的 n=0 —— 方向仍未测到" % m)
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "supplement_queries": d["supplement_queries"],
            "pool_fr_size": d["pool_fr_size"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--models", default="minilm,mpnet")
    a = ap.parse_args(argv)
    if a.run:
        run(tuple(a.models.split(",")))
        return 0
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
