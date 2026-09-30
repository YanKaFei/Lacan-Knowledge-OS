#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
full_corpus_retrieval.py — Phase 3C §11–§18 Full-Corpus Retrieval Validation

必须用 `.venv-embedding/bin/python` 跑（需要 numpy + onnxruntime）。

    .venv-embedding/bin/python _scripts/_tools/full_corpus_retrieval.py --run
    python3 _scripts/_tools/full_corpus_retrieval.py --verify

与 Phase 3B.2 的**根本区别**
────────────────────────────
3B.2 在 **6,305 条候选池**上评测（因为 gold evidence 只有 6 条落在 6,000 corpus 里）。
那是 **development benchmark**，§11 明确要求：**不得把它称为 production retrieval result**。

本工具在**完整 249,105 条**上评测：
* 词法 = 全库 FTS5（不再按池过滤）
* 向量 = 全量 MiniLM 索引（249,105 × 384，精确暴力余弦）
* 候选集 = 全库 —— gold evidence 天然在内

产出标记为 **production-scale benchmark**。

§13 的 10 个配置
────────────────
L · V · E+L · L+V · E+L+V · E+L+X · E+L+V+X · E+L+V+X+M · ROUTED（+ L_raw 诊断）

其中 **ROUTED** 由 `query_routing_policy` 自动选路：
向量按 query class 关闭（§10）、contrastive/concept-comparison 走独立 lane（§8）、
歧义不静默解析（§9）。最终最重要的比较是
**ROUTED vs STATIC E+L+V+X** 与 **ROUTED vs L**。

§15 分量归因（留一法）
──────────────────────
    X 的边际 = (E+L+V+X) − (E+L+V)
    V 的边际 = (E+L+V+X) − (E+L+X)
另外单独报 X-only / V-only 的绝对召回。若主要还是 X，报告必须写明
「Terminology Bridge is the principal cross-language mechanism」。

§16 反例评测分两份
──────────────────
* **Raw Vector Contrastive Pass** —— 纯 embedding 在候选集内能不能排对；
* **System Contrastive Pass** —— ROUTED + Semantic Guard 之后，
  正例 lane 内是否保住区分（硬负例不得混进正例 lane 的 top-k）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")

GOLD_ANS = os.path.join(VAULT, "retrieval_gold_answerable.jsonl")
GOLD_UNANS = os.path.join(VAULT, "retrieval_gold_unanswerable.jsonl")
CONTRAST = os.path.join(VAULT, "lacan_contrastive_eval.jsonl")
FR_SUPP = os.path.join(VAULT, "retrieval_gold_fr_supplement.jsonl")

RESULTS = os.path.join(VECDIR, "full_corpus_results.json")
ABLATION = os.path.join(VECDIR, "full_corpus_ablation.json")
REPORT = os.path.join(VAULT, "FULL_CORPUS_RETRIEVAL_RESULTS.md")
ABL_REPORT = os.path.join(VAULT, "FULL_CORPUS_ABLATION.md")
ROUTED_REPORT = os.path.join(VAULT, "ROUTED_RETRIEVAL_EVALUATION.md")

CONFIGS = ["L", "V", "E+L", "L+V", "E+L+V", "E+L+X", "E+L+V+X", "E+L+V+X+M", "ROUTED"]
# 诊断配置：**不进入 §13 的十配置主表**，只用来检验一个具体假设。
#
# 假设：全量语料下 `E` / `X` 各自能产出数百条候选，RRF 的 1/(k+rank) 会让
# 大量弱候选累积，把词法的强信号**稀释掉** —— 而在 6,305 池里这些列表很短，
# 所以池内看不到这个效应。若假设成立，给每个分量**各自设上限**后
# 混合配置应恢复到接近 `L` 的水平。
DIAG = ["L_raw", "E_cap+L_cap+V_cap+X_cap", "ROUTED_cap"]
COMPONENT_CAP = 50
TOPK_RETURN = 100
RRF_K = 60
GRADE = {"required": 3, "strong": 2, "contextual": 1}

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


def gold_of(g):
    out = {}
    for grade, ids in (g.get("gold_evidence") or {}).items():
        for pid in ids or []:
            out[pid] = max(out.get(pid, 0), GRADE.get(grade, 1))
    return out


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def recall_at(ranked, gold, k):
    if not gold:
        return None
    return sum(1 for p in ranked[:k] if p in gold) / len(gold)


def mrr_at(ranked, gold, k=10):
    if not gold:
        return None
    for i, p in enumerate(ranked[:k], 1):
        if p in gold:
            return 1.0 / i
    return 0.0


def ndcg_at(ranked, grades, k=10):
    if not grades:
        return None
    dcg = sum((2 ** grades.get(p, 0) - 1) / math.log2(i + 1)
              for i, p in enumerate(ranked[:k], 1) if grades.get(p, 0))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2 ** r - 1) / math.log2(i + 1) for i, r in enumerate(ideal, 1))
    return dcg / idcg if idcg else 0.0


def rrf(rank_lists, k=RRF_K):
    scores = {}
    for lst in rank_lists:
        for i, pid in enumerate(lst, 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + i)
    return [p for p, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))]


class Index:
    """全量 MiniLM 索引的只读封装。"""

    def __init__(self):
        import numpy as np
        import build_full_vector_index as bfvi
        self.mat, self.ids, self.man = bfvi.load_index()
        self.index = {p: i for i, p in enumerate(self.ids)}
        self.np = np

    def search(self, qvec, limit=TOPK_RETURN):
        np = self.np
        sims = self.mat @ qvec
        # stable argsort：并列时保持 store 顺序 —— 确定性来自固定顺序，不靠 id 排序
        order = np.argsort(-sims, kind="stable")[:limit]
        return [self.ids[i] for i in order], [float(sims[i]) for i in order]

    def vec(self, pid):
        return self.mat[self.index[pid]]


# ────────────────────────────────────────────────────────────── 组件

def comp_lexical(query, language, limit=TOPK_RETURN, expand_entities=True,
                 res=None):
    """`L`：查询原文 + 实体别名（与 3B.2 同口径），但**全库**检索。"""
    import lacan_search
    queries = [query]
    if expand_entities and res is not None:
        for e in res["entities"][:4]:
            al = e.get("matched_alias")
            if al and len(al.strip()) >= 2:
                queries.append(al)
    seen, out = set(), []
    for q in queries:
        try:
            rows = lacan_search.lexical_search(q, language=language, limit=400)
        except Exception:
            rows = []
        for h in rows:
            pid = h["passage_id"]
            if pid not in seen:
                seen.add(pid)
                out.append(pid)
    return out[:limit]


def comp_lexical_raw(query, language, limit=TOPK_RETURN):
    """诊断用：只用查询原文做 BM25。"""
    import lacan_search
    try:
        rows = lacan_search.lexical_search(query, language=language, limit=limit)
    except Exception:
        rows = []
    return [h["passage_id"] for h in rows]


def comp_exact(query, res, limit=TOPK_RETURN):
    """`E`：查询命中的别名/术语当**精确短语**全库检索。"""
    import lacan_search
    import re
    terms = [w for w in re.split(r"[\s，。！？、；：,.!?;:'\"()（）]+", query) if len(w) >= 2]
    for e in res["entities"][:4]:
        al = e.get("matched_alias")
        if al and al not in terms:
            terms.append(al)
    terms = terms[:8]
    scored = {}
    for q in terms:
        try:
            rows = lacan_search.lexical_search(q, phrase=True, limit=300)
        except Exception:
            rows = []
        for i, h in enumerate(rows):
            pid = h["passage_id"]
            scored[pid] = max(scored.get(pid, 0.0), 1.0 / (1 + i))
    return [p for p, _ in sorted(scored.items(), key=lambda x: (-x[1], x[0]))][:limit]


def comp_bridge(res, target_langs, limit=TOPK_RETURN):
    """`X`：Cross-lingual Terminology Bridge 扩展（**只走 equivalent**）。

    ⚠️ 必须对**目标写法去重**：一个 concept 的多个别名会展开到同一批目标词
    （例如 `小客体a` / `对象a` / `objet a` 都指向 `objet petit a`）。
    不去重的话每个 query 会打上千次 FTS，40 条 query 就是几万次 —— 白跑。
    """
    import lacan_search
    import terminology_bridge as tb
    seen, out = set(), []
    searched = set()                      # 已检索过的 (目标写法, 语言)
    for e in res["entities"][:4]:
        forms = [e.get("matched_alias")] + tb.lexical_forms_for_entity(e["entity_id"])[:8]
        for form in forms:
            if not form:
                continue
            for m in tb.expand(form, target_langs=target_langs):
                key = (m["target_form"], m["target_language"])
                if key in searched:
                    continue
                searched.add(key)
                lang = m["target_language"] if m["target_language"] in ("fr", "zh") else None
                try:
                    rows = lacan_search.lexical_search(m["target_form"], language=lang,
                                                       limit=200)
                except Exception:
                    rows = []
                for h in rows:
                    pid = h["passage_id"]
                    if pid not in seen:
                        seen.add(pid)
                        out.append(pid)
    return out[:limit]


def comp_metadata(plan, ids_order):
    """`M`：只用 query_router 从查询文本解析出的约束（不用 gold）。"""
    sems = (plan or {}).get("seminars") or []
    if not sems:
        return None
    import sqlite3
    con = sqlite3.connect(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
    try:
        keep = {r[0] for r in con.execute(
            "SELECT id FROM passage_meta WHERE seminar_id IN (%s)"
            % ",".join("?" * len(sems)), sems)}
    finally:
        con.close()
    return keep


# ────────────────────────────────────────────────────────────── 单条 query

def run_query(g, idx, model_prov, plan, res, route, np):
    gg = gold_of(g)
    qlang = g.get("language")
    lex_lang = qlang if qlang in ("fr", "zh") else None
    qv = np.asarray(model_prov.embed_queries([g["query"]])[0], dtype="float32")

    t = {}
    t0 = time.time(); L = comp_lexical(g["query"], lex_lang, res=res); t["L"] = time.time() - t0
    t0 = time.time(); Lraw = comp_lexical_raw(g["query"], lex_lang); t["L_raw"] = time.time() - t0
    t0 = time.time(); E = comp_exact(g["query"], res); t["E"] = time.time() - t0
    t0 = time.time(); V, Vsim = idx.search(qv); t["V"] = time.time() - t0
    t0 = time.time()
    X = comp_bridge(res, target_langs=("fr",) if qlang == "zh" else
                    (("zh",) if qlang == "fr" else ("fr", "zh")))
    t["X"] = time.time() - t0

    mfilter = comp_metadata(plan, None)
    base = rrf([E, L, V, X])

    # ── 诊断：每分量各自截断后再 RRF（检验「长列表稀释」假设）
    cap = COMPONENT_CAP
    Ec, Lc, Vc, Xc = E[:cap], L[:cap], V[:cap], X[:cap]
    capped = rrf([Ec, Lc, Vc, Xc])
    comp_lens = {"E": len(E), "L": len(L), "V": len(V), "X": len(X)}

    cands = {
        "L": L, "V": V, "E+L": rrf([E, L]), "L+V": rrf([L, V]),
        "E+L+V": rrf([E, L, V]),
        "E+L+X": rrf([E, L, X]),
        "E+L+V+X": base,
        "E+L+V+X+M": ([p for p in base if p in mfilter] or base) if mfilter else base,
        "L_raw": Lraw,
        "E_cap+L_cap+V_cap+X_cap": capped,
    }

    # ── ROUTED：按 routing policy 执行（向量可关；lane 独立；歧义不解析）
    route_cfg = route
    comp_used = []
    if route_cfg["vector_enabled"]:
        comp_used.append("vector")
    else:
        V = None
    if route_cfg["lanes_count"] > 1:
        per_lane = []
        for lane in route_cfg["lanes"]:
            lq = " ".join(lane.get("query_forms") or [lane["surface_form"]])
            lane_lex = comp_lexical(lq, lex_lang, res={"entities": []})
            lane_exact = comp_exact(lq, {"entities": []})
            lists = [lane_exact, lane_lex]
            if V is not None:
                lists.append(V)
            per_lane.append(rrf(lists))
        # 分道后**交替合并**，保证每条 lane 都有代表，而不是让强 lane 吞掉弱 lane
        merged, seen = [], set()
        for rank in range(TOPK_RETURN):
            for lst in per_lane:
                if rank < len(lst) and lst[rank] not in seen:
                    seen.add(lst[rank])
                    merged.append(lst[rank])
        routed = merged[:TOPK_RETURN]
        routed_note = "per_lane_interleaved"
    else:
        lists = [E, L]
        if V is not None:
            lists.append(V)
        if "x" in route_cfg["components"]:
            lists.append(X)
        routed = rrf(lists)
        routed_note = "single_lane_fusion"
    cands["ROUTED"] = routed
    # 诊断版 ROUTED：所有分量先各自截断（单 lane 情形）；多 lane 情形沿用交替合并
    if route_cfg["lanes_count"] > 1:
        cands["ROUTED_cap"] = routed
    else:
        lists_c = [E[:cap], L[:cap]]
        if V is not None:
            lists_c.append(V[:cap])
        if "x" in route_cfg["components"]:
            lists_c.append(X[:cap])
        cands["ROUTED_cap"] = rrf(lists_c)

    metrics = {}
    for c, ranked in cands.items():
        metrics[c] = {
            "hit@5": recall_at(ranked, gg, 5),
            "hit@10": recall_at(ranked, gg, 10),
            "hit@20": recall_at(ranked, gg, 20),
            "mrr@10": mrr_at(ranked, gg, 10),
            "ndcg@10": ndcg_at(ranked, gg),
            "top1_in_gold": bool(ranked and ranked[0] in gg),
            "top20": ranked[:20],
        }
    return {
        "query_id": g["query_id"], "query": g["query"], "language": qlang,
        "primary_intent": g.get("primary_intent"),
        "gold_n": len(gg), "gold_languages": sorted({_lang_of(idx, p) for p in gg}),
        "route": route_cfg["route"], "vector_enabled": route_cfg["vector_enabled"],
        "lanes_count": route_cfg["lanes_count"], "routed_note": routed_note,
        "entity_resolution": route_cfg["entity_resolution"],
        "metrics": metrics, "latency": t, "component_list_lengths": comp_lens,
    }


_LANG_CACHE = {}


def _lang_of(idx, pid):
    global _LANG_CACHE
    if not _LANG_CACHE:
        import sqlite3
        con = sqlite3.connect(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
        try:
            for r in con.execute("SELECT id, language FROM passage_meta"):
                _LANG_CACHE[r[0]] = r[1]
        finally:
            con.close()
    return _LANG_CACHE.get(pid)


def query_class(entry):
    """§14：分 query class。"""
    r = entry["route"]
    if r == "CONTRASTIVE_TERMINOLOGY":
        return "contrastive_terminology"
    if r == "EXACT_QUOTATION":
        return "exact_quotation"
    if r == "EXACT_SOURCE_LOOKUP":
        return "exact_source_lookup"
    if r == "SEMINAR_SPECIFIC":
        return "seminar_specific"
    if r == "DIACHRONIC":
        return "diachronic"
    if r == "CONCEPT_COMPARISON":
        return "concept_relation"
    if r == "AMBIGUOUS_ENTITY":
        return "ambiguous_entity"
    if entry["language"] == "fr":
        return "fr_monolingual"
    if entry["language"] == "zh":
        gl = set(entry["gold_languages"])
        return "zh_to_fr" if gl == {"fr"} else "zh_monolingual"
    if entry["language"] == "mul":
        gl = set(entry["gold_languages"])
        return "zh_to_fr" if gl == {"fr"} else "conceptual_paraphrase"
    return "conceptual_paraphrase"


def run(models=("minilm",)):
    import numpy as np
    import embedding_provider as ep
    import query_router
    import query_routing_policy as rp
    import entity_resolution as er

    idx = Index()
    man = idx.man
    print("[full] 索引：%d 条 × %d 维（%s）" % (
        man["passage_count"], man["dimensions"], man["index_version"]))

    gold = jl(GOLD_ANS)
    unans = jl(GOLD_UNANS)
    contrast = jl(CONTRAST)
    frsupp = jl(FR_SUPP) if os.path.isfile(FR_SUPP) else []
    out = {
        "schema_version": "full-corpus-retrieval/v1",
        "scale": "production-scale benchmark（完整 249,105 条语料）",
        "development_benchmark_note": ("6,305 池上的 Phase 3B.2 结果保留为 "
                                       "**development benchmark**，不得与本节数字混用。"),
        "index": {"passage_count": man["passage_count"], "dimensions": man["dimensions"],
                  "index_version": man["index_version"],
                  "index_artifact_hash": man["index_artifact_hash"],
                  "corpus_hash": man["corpus_hash"]},
        "answerable_n": len(gold), "unanswerable_n": len(unans),
        "models": {},
    }

    for model in models:
        prov = ep.OnnxTransformersProvider(model)
        if not prov.available:
            raise SystemExit("provider %s 不可用" % model)
        per = []
        for g in gold:
            plan = query_router.route(g["query"])
            res = er.resolve(g["query"], plan)
            route = rp.plan_for(g["query"], plan)
            per.append(run_query(g, idx, prov, plan, res, route, np))
        # 汇总
        agg = {}
        for c in CONFIGS + DIAG:
            agg[c] = {k: avg([q["metrics"][c][k] for q in per])
                      for k in ("hit@5", "hit@10", "hit@20", "mrr@10", "ndcg@10")}
            agg[c]["top1_precision"] = avg(
                [1.0 if q["metrics"][c]["top1_in_gold"] else 0.0 for q in per])
        # 分 class
        classes = {}
        for q in per:
            classes.setdefault(query_class(q), []).append(q)
        by_class = {}
        for cls, sel in sorted(classes.items()):
            by_class[cls] = {"n": len(sel)}
            for c in CONFIGS:
                by_class[cls][c] = {k: avg([q["metrics"][c][k] for q in sel])
                                    for k in ("hit@20", "mrr@10", "ndcg@10")}
        out["models"][model] = {
            "aggregate": agg, "by_class": by_class, "per_query": per,
            "vector_disabled_queries": sum(1 for q in per if not q["vector_enabled"]),
            "multi_lane_queries": sum(1 for q in per if q["lanes_count"] > 1),
        }
        print("[full] %s aggregate  E+L+V+X hit@20=%.4f  ROUTED hit@20=%.4f  L=%.4f  "
              "(向量关闭 %d/%d 条)" % (
                  model, agg["E+L+V+X"]["hit@20"], agg["ROUTED"]["hit@20"],
                  agg["L"]["hit@20"], out["models"][model]["vector_disabled_queries"],
                  len(per)))

    json.dump(out, open(RESULTS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_report(out)
    write_ablation(out)
    # ⚠️ 第一版声明了 ABLATION 却没写 —— 下游 completion gate 第 11 条因此读到 None
    #    而静默判 False（detail 是空的 {}）。声明的产物必须真的产出。
    abl = {
        "schema_version": "full-corpus-ablation/v1",
        "scale": out["scale"],
        "index": out["index"],
        "configs": CONFIGS,
        "diagnostic_configs": DIAG,
        "component_cap_used_for_diagnostic": COMPONENT_CAP,
        "models": {m: {"aggregate": v["aggregate"], "by_class": v["by_class"],
                       "vector_disabled_queries": v["vector_disabled_queries"],
                       "multi_lane_queries": v["multi_lane_queries"]}
                   for m, v in out["models"].items()},
        "headline_comparisons": {
            m: {"ROUTED_vs_STATIC_E_L_V_X":
                (v["aggregate"]["ROUTED"]["hit@20"] or 0)
                - (v["aggregate"]["E+L+V+X"]["hit@20"] or 0),
                "ROUTED_vs_L": (v["aggregate"]["ROUTED"]["hit@20"] or 0)
                - (v["aggregate"]["L"]["hit@20"] or 0)}
            for m, v in out["models"].items()},
        "dilution_diagnostic": {
            m: {"E_cap+L_cap+V_cap+X_cap": v["aggregate"]["E_cap+L_cap+V_cap+X_cap"]["hit@20"],
                "E+L+V+X": v["aggregate"]["E+L+V+X"]["hit@20"],
                "ROUTED_cap": v["aggregate"]["ROUTED_cap"]["hit@20"],
                "ROUTED": v["aggregate"]["ROUTED"]["hit@20"]}
            for m, v in out["models"].items()},
        "note": ("`ROUTED` 与静态配置的差异是**真实数字**，不修饰。"
                 "全量规模上 `L` 优于所有含向量的配置 —— 见 SCALE_TRANSFER_ANALYSIS.md。"),
    }
    json.dump(abl, open(ABLATION, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


# ────────────────────────────────────────────────────────────── 报告

def fmt(x, nd=4):
    return "—" if x is None else ("%.*f" % (nd, x))


def write_report(out):
    L = []
    A = L.append
    A("# FULL_CORPUS_RETRIEVAL_RESULTS.md — Phase 3C §11–§12\n")
    A("> **production-scale benchmark**：候选集 = 完整 **249,105** 条语料。")
    A("> Phase 3B.2 的 6,305 池结果保留为 **development benchmark**，两者不得混用。\n")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 索引 | `%s` |" % out["index"]["index_version"])
    A("| passage 数 | **%d** |" % out["index"]["passage_count"])
    A("| 维度 | %d |" % out["index"]["dimensions"])
    A("| answerable n | %d |" % out["answerable_n"])
    A("| unanswerable n | %d（**独立分母**，不进入下列任何指标） |" % out["unanswerable_n"])
    A("")
    for m, v in out["models"].items():
        A("## `%s`\n" % m)
        A("| 配置 | hit@5 | hit@10 | hit@20 | MRR@10 | nDCG@10 | top1 命中率 |")
        A("|---|---:|---:|---:|---:|---:|---:|")
        for c in CONFIGS + DIAG:
            a = v["aggregate"][c]
            A("| `%s` | %s | %s | %s | %s | %s | %s |" % (
                c, fmt(a["hit@5"]), fmt(a["hit@10"]), fmt(a["hit@20"]),
                fmt(a["mrr@10"]), fmt(a["ndcg@10"]), fmt(a["top1_precision"], 3)))
        A("")
        A("- 向量被关闭的 query：**%d / 40**（按 query class 自动决定）"
          % v["vector_disabled_queries"])
        A("- 走多 lane 的 query：**%d / 40**" % v["multi_lane_queries"])
        A("")
        A("## 分 query class（`%s`）\n" % m)
        A("| class | n | `L` hit@20 | `E+L+V+X` hit@20 | `ROUTED` hit@20 | `ROUTED` MRR@10 |")
        A("|---|---:|---:|---:|---:|---:|")
        for cls, d in sorted(v["by_class"].items()):
            A("| `%s` | %d | %s | %s | %s | %s |" % (
                cls, d["n"], fmt(d["L"]["hit@20"]), fmt(d["E+L+V+X"]["hit@20"]),
                fmt(d["ROUTED"]["hit@20"]), fmt(d["ROUTED"]["mrr@10"])))
        A("")
    A("## 边界（不得越界声称）\n")
    A("- gold 是 `adjudicated_script_assisted`（无第二标注者）→ 绝对数值有争议空间，"
      "**方法间比较**才是主要用途。")
    A("- 全库检索意味着词法命中池从 6,305 扩到 249,105："
      "**同样的 query 在全库里的名次天然更低**，所以本表数字**不能**直接与 3B.2 的池内数字比较。")
    A("- `E+L+V+X+M` 的 `M` 依赖 `query_router` 解析出的研讨班约束；"
      "实测 40 条 gold 里能解析出 seminar 的仍很少，`M` 多数时候是空操作。")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT)


def write_ablation(out):
    m = list(out["models"])[0]
    v = out["models"][m]
    a = v["aggregate"]
    L = []
    A = L.append
    A("# FULL_CORPUS_ABLATION.md — Phase 3C §13–§15\n")
    A("> 全量 249,105 条语料上的 10 配置消融 + 分量归因 + 分 class。\n")
    A("## 0. 最重要的两个对比（§13）\n")
    A("| 对比 | 结果 |")
    A("|---|---|")
    A("| **`ROUTED` vs `STATIC E+L+V+X`** | hit@20 %s vs %s（Δ %s） |" % (
        fmt(a["ROUTED"]["hit@20"]), fmt(a["E+L+V+X"]["hit@20"]),
        fmt((a["ROUTED"]["hit@20"] or 0) - (a["E+L+V+X"]["hit@20"] or 0))))
    A("| **`ROUTED` vs `L`** | hit@20 %s vs %s（Δ %s） |" % (
        fmt(a["ROUTED"]["hit@20"]), fmt(a["L"]["hit@20"]),
        fmt((a["ROUTED"]["hit@20"] or 0) - (a["L"]["hit@20"] or 0))))
    A("")
    A("判定规则（**先写下来再套数字**）：")
    A("- `ROUTED` > `STATIC` → 按 query class 路由**有收益**；")
    A("- `ROUTED` ≈ `STATIC` → 路由是**中性**的（但它仍带来延迟收益与可解释性）；")
    A("- `ROUTED` < `STATIC` → 路由**有害**，必须重新设计，不得含糊过去。\n")
    A("## 1. 十配置全表\n")
    A("| 配置 | hit@5 | hit@10 | hit@20 | MRR@10 | nDCG@10 |")
    A("|---|---:|---:|---:|---:|---:|")
    for c in CONFIGS + DIAG:
        x = a[c]
        A("| `%s` | %s | %s | %s | %s | %s |" % (
            c, fmt(x["hit@5"]), fmt(x["hit@10"]), fmt(x["hit@20"]),
            fmt(x["mrr@10"]), fmt(x["ndcg@10"])))
    A("")
    A("## 2. §15 分量归因（留一法边际）\n")
    def marg(full, without):
        return (a[full]["hit@20"] or 0) - (a[without]["hit@20"] or 0)
    A("| 分量 | 边际定义 | hit@20 边际 | 说明 |")
    A("|---|---|---:|---|")
    A("| `X`（术语桥） | `E+L+V+X` − `E+L+V` | **%+.4f** | 加上术语桥带来的净变化 |"
      % marg("E+L+V+X", "E+L+V"))
    A("| `V`（向量） | `E+L+V+X` − `E+L+X` | **%+.4f** | 加上向量带来的净变化 |"
      % marg("E+L+V+X", "E+L+X"))
    A("| `E`（精确/别名） | `E+L` − `L` | **%+.4f** | |" % marg("E+L", "L"))
    A("")
    A("**绝对召回（不是边际）**：")
    A("| 路径 | hit@20 |")
    A("|---|---:|")
    for c in ("L", "V", "E+L", "E+L+X", "E+L+V", "E+L+V+X"):
        A("| `%s` | %s |" % (c, fmt(a[c]["hit@20"])))
    A("")
    x_m, v_m = marg("E+L+V+X", "E+L+V"), marg("E+L+V+X", "E+L+X")
    if x_m > v_m:
        A("→ **Terminology Bridge is the principal cross-language mechanism.**")
        A("  中文问句连到法文原文，主要靠术语桥而不是 embedding。")
    elif v_m > x_m:
        A("→ 本轮 `V` 的边际大于 `X` 的边际。")
    else:
        A("→ 两者边际相同，无法区分主次。")
    A("")
    A("## 3. 分 query class\n")
    A("| class | n | `L` | `V` | `E+L+V` | `E+L+V+X` | `ROUTED` |")
    A("|---|---:|---:|---:|---:|---:|---:|")
    for cls, d in sorted(v["by_class"].items()):
        A("| `%s` | %d | %s | %s | %s | %s | %s |" % (
            cls, d["n"], fmt(d["L"]["hit@20"]), fmt(d["V"]["hit@20"]),
            fmt(d["E+L+V"]["hit@20"]), fmt(d["E+L+V+X"]["hit@20"]),
            fmt(d["ROUTED"]["hit@20"])))
    A("")
    A("## 3.5 与池内结论的对账\n")
    A("**不得只看这张表。** 6,305 池与 249,105 全量的差异见 "
      "`SCALE_TRANSFER_ANALYSIS.md`：池内「hybrid > 单路」**没有搬到全量**，"
      "原因是 `L` 的 lift 随规模增长（保留率 9.44×）而 `V` 的 lift 尺度不变（1.09×）。\n")
    A("## 4. §10 向量按 class 关闭的实际效果\n")
    A("- 关闭向量的 query：**%d / 40**。" % v["vector_disabled_queries"])
    A("- 依据是实测而非先验：FR 单语上 `L` 明显优于含向量的配置。")
    A("- 这条同时是**延迟**收益：全量向量检索在 249,105×384 上约几十毫秒，关掉即省掉。")
    with open(ABL_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % ABL_REPORT)


def cmd_verify():
    problems = []
    for p in (RESULTS, REPORT, ABL_REPORT):
        if not os.path.isfile(p):
            problems.append("缺产物: %s" % os.path.relpath(p, VAULT))
    if problems:
        return {"status": "FAIL", "problems": problems}
    d = json.load(open(RESULTS, encoding="utf-8"))
    for m, v in d["models"].items():
        for c in CONFIGS:
            if c not in v["aggregate"]:
                problems.append("%s 缺配置 %s" % (m, c))
        if v["aggregate"]["ROUTED"]["hit@20"] is None:
            problems.append("%s ROUTED 无数字" % m)
        for q in v["per_query"]:
            if q["metrics"]["ROUTED"]["top20"] and \
                    not all(p.startswith(("passage.", "session.", "seminar."))
                            for p in q["metrics"]["ROUTED"]["top20"][:3]):
                problems.append("%s/%s ROUTED 返回了非 passage 形状的 id"
                                % (m, q["query_id"]))
    if d["answerable_n"] != 40 or d["unanswerable_n"] != 5:
        problems.append("分母不是 40/5")
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "scale": d["scale"], "answerable_n": d["answerable_n"],
            "unanswerable_n": d["unanswerable_n"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--models", default="minilm")
    a = ap.parse_args(argv)
    if a.run:
        run(tuple(a.models.split(",")))
        return 0
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
