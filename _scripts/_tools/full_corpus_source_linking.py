#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
full_corpus_source_linking.py — Phase 3C §20 全量索引建成后的溯源候选重跑

§20 要求：全量 MiniLM index 建成以后，对 **43 unresolved Gold Concepts**
重新跑 candidate source linking，并**比较**两种策略的候选质量：

    A) lexical-only            —— 3B.2 已经在做的：别名精确短语 + 词法 + 词法前 200 条内向量重排
    B) lexical + X + vector    —— 本轮新增：加 Terminology Bridge 扩展 +
                                  **全量索引**上的全局向量检索

**仍然只输出 candidate。** 不得自动 canonical（硬门禁）。

「候选质量」怎么比（都用可核的代理指标，不编 precision）
───────────────────────────────────────────────────────
| 指标 | 定义 | 说明 |
|---|---|---|
| `top5_coverage` | 有 ≥1 候选的 concept 比例 | 召回广度 |
| `top1_verbatim_rate` | top-1 正文里字面出现该 concept 某个别名的比例 | **代理指标**，只能排除部分假命中 |
| `cross_language_yield` | 候选语言 ≠ concept 主语言的条数占比 | 术语桥的**可测贡献** |
| `candidate_set_jaccard` | 两策略候选集合的 Jaccard | 两者是否在找同一批东西 |
| `multi_component_rate` | 候选被 ≥2 个分量同时召回的比例 | 证据稳健性代理 |

⚠️ **没有人工标注，所以没有 precision。** 报告里必须这样写。

用法
────
    .venv-embedding/bin/python _scripts/_tools/full_corpus_source_linking.py --run
    python3 _scripts/_tools/full_corpus_source_linking.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
CONCEPTS = os.path.join(STORE, "concepts.jsonl")
PASSAGES = os.path.join(STORE, "passages.jsonl")

OUT_A = os.path.join(VAULT, "concept_source_link_candidates.jsonl")
OUT_B = os.path.join(VAULT, "concept_source_link_candidates_fullcorpus.jsonl")
OUT_JSON = os.path.join(VECDIR, "source_linking_fullcorpus.json")
REPORT = os.path.join(VAULT, "SOURCE_LINKING_FULL_CORPUS_REPORT.md")

RRF_K = 60
TOP_K = 5
LEX_CANDIDATES = 200
MIN_ALIAS_LEN = 3

sys.path.insert(0, HERE)


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def concept_terms(c):
    terms = []
    for k in ("canonical_name", "zh", "fr", "en"):
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            terms.append(v.strip())
    for a in c.get("aliases") or []:
        if isinstance(a, str) and a.strip():
            terms.append(a.strip())
    seen, out = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return " ".join(out[:4]), out


def primary_language(c):
    langs = []
    if (c.get("zh") or "").strip():
        langs.append("zh")
    if (c.get("fr") or "").strip():
        langs.append("fr")
    if (c.get("en") or "").strip():
        langs.append("en")
    return langs[0] if langs else "und"


def run():
    import numpy as np
    import lacan_search
    import embedding_provider as ep
    import terminology_bridge as tb
    import full_corpus_retrieval as fcr

    concepts = jl(CONCEPTS)
    unresolved = [c for c in concepts if not c.get("passages")]
    idx = fcr.Index()
    prov = ep.OnnxTransformersProvider("minilm")

    # 一次扫描取正文与语言
    meta, texts = {}, {}
    want = set()
    for c in unresolved:
        _, terms = concept_terms(c)
        want |= {t for t in terms if len(re.sub(r"\W", "", t)) >= MIN_ALIAS_LEN}
    with open(PASSAGES, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            meta[d["id"]] = d.get("language")
            texts[d["id"]] = d.get("normalized_text") or ""

    def strategy_A(c, terms):
        """lexical-only：别名精确短语 + 词法 + 词法前 200 内向量重排。"""
        exact = {}
        for a in terms:
            if len(re.sub(r"\W", "", a)) < MIN_ALIAS_LEN:
                continue
            try:
                for i, h in enumerate(lacan_search.lexical_search(a, phrase=True, limit=200)):
                    exact[h["passage_id"]] = max(exact.get(h["passage_id"], 0.0), 1.0 / (1 + i))
            except Exception:
                pass
        query = " ".join(terms[:4])
        try:
            lex = [h["passage_id"] for h in lacan_search.lexical_search(query, limit=LEX_CANDIDATES)]
        except Exception:
            lex = []
        cand_ids = lex[:LEX_CANDIDATES]
        vec = []
        if cand_ids:
            qv = np.asarray(prov.embed_queries([query])[0], dtype="float32")
            sub = np.asarray([idx.mat[idx.index[p]] for p in cand_ids if p in idx.index],
                             dtype="float32")
            keep = [p for p in cand_ids if p in idx.index]
            sims = sub @ qv
            order = np.argsort(-sims, kind="stable")
            vec = [keep[i] for i in order]
        scores = {}
        for i, (pid, _) in enumerate(sorted(exact.items(), key=lambda x: (-x[1], x[0])), 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)
        for i, pid in enumerate(lex, 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)
        for i, pid in enumerate(vec, 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)
        ranked = [p for p, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))][:TOP_K]
        comps = {}
        for p in ranked:
            cs = []
            if p in exact:
                cs.append("exact")
            if p in lex:
                cs.append("lexical")
            if p in vec:
                cs.append("vector_lexical_rerank")
            comps[p] = cs
        return ranked, comps

    def strategy_B(c, terms):
        """lexical + X（术语桥）+ **全量索引**上的全局向量检索。"""
        exact = {}
        for a in terms:
            if len(re.sub(r"\W", "", a)) < MIN_ALIAS_LEN:
                continue
            try:
                for i, h in enumerate(lacan_search.lexical_search(a, phrase=True, limit=200)):
                    exact[h["passage_id"]] = max(exact.get(h["passage_id"], 0.0), 1.0 / (1 + i))
            except Exception:
                pass
        query = " ".join(terms[:4])
        try:
            lex = [h["passage_id"] for h in lacan_search.lexical_search(query, limit=400)]
        except Exception:
            lex = []
        # ── X：术语桥扩展（只走 equivalent）
        bridge = {}
        for t in terms[:6]:
            for m in tb.expand(t, target_langs=("fr", "zh", "en")):
                tf = m["target_form"]
                try:
                    for i, h in enumerate(lacan_search.lexical_search(tf, limit=300)):
                        bridge[h["passage_id"]] = max(bridge.get(h["passage_id"], 0.0),
                                                      1.0 / (1 + i))
                except Exception:
                    pass
        # ── 全量索引上的全局向量检索
        qv = np.asarray(prov.embed_queries([query])[0], dtype="float32")
        vids, _ = idx.search(qv, limit=300)
        scores = {}
        for i, (pid, _) in enumerate(sorted(exact.items(), key=lambda x: (-x[1], x[0])), 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)
        for i, pid in enumerate(lex, 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)
        for i, (pid, _) in enumerate(sorted(bridge.items(), key=lambda x: (-x[1], x[0])), 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)
        for i, pid in enumerate(vids, 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)
        ranked = [p for p, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))][:TOP_K]
        comps = {}
        for p in ranked:
            cs = []
            if p in exact:
                cs.append("exact")
            if p in lex:
                cs.append("lexical")
            if p in bridge:
                cs.append("terminology_bridge")
            if p in set(vids):
                cs.append("vector_full_index")
            comps[p] = cs
        return ranked, comps

    rows_a, rows_b = [], []
    stats = {"A": {"with": 0, "verbatim_top1": 0, "cross_lang": 0, "multi": 0, "total": 0},
             "B": {"with": 0, "verbatim_top1": 0, "cross_lang": 0, "multi": 0, "total": 0}}
    jac, detail = [], []
    for c in unresolved:
        query, terms = concept_terms(c)
        pl = primary_language(c)
        sets = {}
        for tag, fn, rows in (("A", strategy_A, rows_a), ("B", strategy_B, rows_b)):
            ranked, comps = fn(c, terms)
            sets[tag] = set(ranked)
            if ranked:
                stats[tag]["with"] += 1
            for rank, pid in enumerate(ranked, 1):
                body = texts.get(pid, "")
                verbatim = any(len(re.sub(r"\W", "", t)) >= MIN_ALIAS_LEN and t in body
                               for t in terms)
                lang = meta.get(pid)
                cross = bool(lang and lang != pl)
                cs = comps.get(pid, [])
                if tag == "A":
                    stats["A"]["total"] += 1
                    stats["A"]["verbatim_top1"] += 1 if (rank == 1 and verbatim) else 0
                    stats["A"]["cross_lang"] += 1 if cross else 0
                    stats["A"]["multi"] += 1 if len(cs) >= 2 else 0
                else:
                    stats["B"]["total"] += 1
                    stats["B"]["verbatim_top1"] += 1 if (rank == 1 and verbatim) else 0
                    stats["B"]["cross_lang"] += 1 if cross else 0
                    stats["B"]["multi"] += 1 if len(cs) >= 2 else 0
                rows.append({
                    "schema_version": "concept-source-link-candidate/v1",
                    "strategy": "lexical_only" if tag == "A" else "lexical_plus_X_plus_full_vector",
                    "concept_id": c["id"], "concept_name": c.get("canonical_name"),
                    "concept_primary_language": pl,
                    "query_used": query,
                    "candidate_passage_id": pid, "rank": rank,
                    "candidate_sources": cs,
                    "verbatim_match": verbatim,
                    "passage_language": lang,
                    "cross_language": cross,
                    "review_status": "candidate", "canonical": False,
                    "promotion_rule": "脚本产出的候选**永不**自动晋级为 canonical；必须人工审阅。",
                    "proposed_by": "script:full_corpus_source_linking.py",
                    "proposal_reason": "concept 卡片无任何 passage 锚点（SOURCE_TRACE_INCOMPLETE）",
                })
        inter = len(sets["A"] & sets["B"])
        union = len(sets["A"] | sets["B"])
        j = inter / union if union else 1.0
        jac.append(j)
        detail.append({"concept_id": c["id"], "A": sorted(sets["A"]), "B": sorted(sets["B"]),
                       "jaccard": j, "only_B": sorted(sets["B"] - sets["A"])})

    with open(OUT_B, "w", encoding="utf-8") as f:
        for r in rows_b:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    def summarize(tag):
        s = stats[tag]
        return {
            "candidates": s["total"],
            "concepts_with_candidates": s["with"],
            "top5_coverage": s["with"] / max(1, len(unresolved)),
            "top1_verbatim_rate_proxy": s["verbatim_top1"] / max(1, s["with"]),
            "cross_language_yield": s["cross_lang"] / max(1, s["total"]),
            "multi_component_rate": s["multi"] / max(1, s["total"]),
        }

    doc = {
        "schema_version": "source-linking-fullcorpus/v1",
        "unresolved_concepts": len(unresolved),
        "strategy_A": {"name": "lexical_only（3B.2 口径：别名精确 + 词法 + 词法前200内向量重排）",
                       "output": os.path.relpath(OUT_A, VAULT),
                       "metrics": summarize("A")},
        "strategy_B": {"name": "lexical + X（术语桥）+ 全量索引全局向量检索",
                       "output": os.path.relpath(OUT_B, VAULT),
                       "metrics": summarize("B")},
        "comparison": {
            "candidate_set_jaccard_mean": sum(jac) / len(jac) if jac else None,
            "concepts_where_B_adds_new": sum(1 for d in detail if d["only_B"]),
            "note": ("**没有人工标注 → 没有 precision。** 上表的 verbatim 率是**代理指标**，"
                     "只能排除部分假命中，不能证明语义正确。"),
            "detail": detail,
        },
        "hard_gates": {
            "automatic_source_link_canonicalization": 0,
            "non_candidate_review_status": 0,
        },
        "hashes": {"concepts_jsonl": sha256_file(CONCEPTS),
                   "strategy_B_output": sha256_file(OUT_B)},
    }
    json.dump(doc, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_report(doc)
    print("[srclink] A: %s" % json.dumps(doc["strategy_A"]["metrics"], ensure_ascii=False))
    print("[srclink] B: %s" % json.dumps(doc["strategy_B"]["metrics"], ensure_ascii=False))
    return doc


def write_report(d):
    A = ["# SOURCE_LINKING_FULL_CORPUS_REPORT.md — Phase 3C §20\n"]
    A.append("> 代码：`_scripts/_tools/full_corpus_source_linking.py`　·　"
             "数据：`_data/index/vector/source_linking_fullcorpus.json`\n")
    A.append("## 0. 仍然是 candidate，一个字都没晋级\n")
    A.append("| 项 | 值 |")
    A.append("|---|---:|")
    A.append("| 未溯源 Gold Concept | **%d** |" % d["unresolved_concepts"])
    A.append("| 策略 A 候选条数 | %d |" % d["strategy_A"]["metrics"]["candidates"])
    A.append("| 策略 B 候选条数 | %d |" % d["strategy_B"]["metrics"]["candidates"])
    A.append("| `automatic_source_link_canonicalization` | **%d** |"
             % d["hard_gates"]["automatic_source_link_canonicalization"])
    A.append("")
    A.append("策略 A 的候选仍写在原文件 `concept_source_link_candidates.jsonl`"
             "（3B.2 口径，未改动）；策略 B 单独写 "
             "`concept_source_link_candidates_fullcorpus.jsonl`。\n")
    A.append("## 1. 两种策略的质量比较\n")
    A.append("| 指标 | 策略 A（lexical-only） | 策略 B（lexical + X + 全量向量） |")
    A.append("|---|---:|---:|")
    keys = [("top5_coverage", "top-5 覆盖率"),
            ("top1_verbatim_rate_proxy", "top-1 字面命中率（**代理**）"),
            ("cross_language_yield", "跨语言候选占比"),
            ("multi_component_rate", "被 ≥2 分量同时召回的比例"),
            ("candidates", "候选条数")]
    for k, label in keys:
        a = d["strategy_A"]["metrics"].get(k)
        b = d["strategy_B"]["metrics"].get(k)
        A.append("| %s | %s | %s |" % (
            label,
            ("%d" % a) if isinstance(a, int) else ("%.4f" % a if a is not None else "—"),
            ("%d" % b) if isinstance(b, int) else ("%.4f" % b if b is not None else "—")))
    A.append("")
    cmp_ = d["comparison"]
    A.append("- 候选集合平均 Jaccard：**%s**" % (
        "%.4f" % cmp_["candidate_set_jaccard_mean"]
        if cmp_["candidate_set_jaccard_mean"] is not None else "—"))
    A.append("- 策略 B 带来**新候选**的 concept 数：**%d / %d**"
             % (cmp_["concepts_where_B_adds_new"], d["unresolved_concepts"]))
    A.append("")
    A.append("## 2. 为什么这里没有 precision\n")
    A.append("43 个 concept **没有人工标注的相关性判断**，所以任何「precision」都是编的。"
             "上表的 `top-1 字面命中率` 是**代理指标**：它只看 top-1 正文里有没有字面出现"
             "该概念的某个别名，能排除一部分明显假命中，**不能证明语义正确**。\n")
    A.append("## 3. 边界\n")
    A.append("- 策略 B 的向量检索是**全量索引上的全局检索**（249,105 条），"
             "这比 3B.2 的「词法前 200 内重排」召回上限高得多 —— "
             "但它的候选**质量**仍然只能由人判定。")
    A.append("- 两条策略都是脚本产物，`review_status = candidate`，"
             "`canonical = false`。43 个 concept 的 `trace_status` 依旧是 "
             "`SOURCE_TRACE_INCOMPLETE`，除非有人**逐条人工确认**。")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(A) + "\n")
    print("[report] %s" % REPORT)


def cmd_verify():
    problems = []
    for p in (OUT_B, OUT_JSON, REPORT):
        if not os.path.isfile(p):
            problems.append("缺产物: %s" % os.path.relpath(p, VAULT))
    if problems:
        return {"status": "FAIL", "problems": problems}
    d = json.load(open(OUT_JSON, encoding="utf-8"))
    rows = jl(OUT_B)
    for r in rows:
        if r["review_status"] != "candidate" or r["canonical"] is not False:
            problems.append("出现可晋级的候选记录")
            break
    if d["hard_gates"]["automatic_source_link_canonicalization"] != 0:
        problems.append("硬门禁 automatic_source_link_canonicalization != 0")
    if d["strategy_B"]["metrics"]["candidates"] == 0:
        problems.append("策略 B 无候选")
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "concepts": d["unresolved_concepts"],
            "candidates_B": d["strategy_B"]["metrics"]["candidates"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.run:
        run()
        return 0
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
