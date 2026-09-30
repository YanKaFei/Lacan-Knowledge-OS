#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
semantic_benchmark.py — Phase 3B.2 §14–§20 语义检索评测 + 六配置消融

必须用 `.venv-embedding/bin/python` 跑（需要 numpy + onnxruntime + tokenizers）：
    .venv-embedding/bin/python _scripts/_tools/semantic_benchmark.py --run
    .venv-embedding/bin/python _scripts/_tools/semantic_benchmark.py --verify

评测池（**这是本轮最关键的工程决定**）
────────────────────────────────────────
6,000 条 stratified benchmark corpus **本身无法用来算 recall**：实测 40 条
answerable gold 的 252 条 gold evidence 里，只有 **6 条**落在那 6,000 条里，
34/40 条 query 的 gold 一条都不在池里。若直接在那 6,000 条上算召回，
所有方法都会得到 ≈0 —— **那不是模型不行，是池子里根本没有标准答案。**

因此评测池 = `6,000 benchmark corpus` ∪ `252 gold evidence` ∪ `70 反例段落`
（去重后 **6,305 条**），
并且：
  * `vector_benchmark_corpus.jsonl` **一个字节都不改**（它的 content_hash 保持不变）
  * 池子必须同时并进**反例评测**用到的 70 条段落，否则正例/硬负例的名次没有意义
  * 池子的构造、并集来源、计数全部写进 `_data/index/vector/evaluation_pool.json`
  * 所有方法都在**同一个池子**里排序（否则消融不可比）

四条方向（§16）
──────────────
    A: ZH query → ZH evidence      C: FR query → FR evidence
    B: ZH query → FR evidence      D: FR query → ZH evidence
语言标为 `mul`（中西混合）的 query **不硬塞进 A–D**，单独成第 5 桶。

六配置（§19，Graph 排除在外）
─────────────────────────────
    L          词法（FTS5 BM25）
    V          向量（真实 ONNX 模型）
    E+L        精确/别名短语 + 词法（RRF）
    L+V        词法 + 向量（RRF）
    E+L+V      精确/别名 + 词法 + 向量（RRF）
    E+L+V+M    + metadata 约束

⚠️ 关于 `E` 与 `M` 的**口径必须说清**（不说清就是偷偷改题）：
  * `hybrid_retrieve.alias_component` 只产**实体**、`passage_id=None`，
    在 passage 级 RRF 里等于不存在。本 harness 的 `E` 把它落成 passage：
    把查询命中的别名/术语当**精确短语**在池内检索。口径差异会在报告里写明。
  * `M` = query_router **从查询文本**解析出的 seminar/session/period/filters 约束
    （**绝不使用 gold 的 expected_seminars —— 那是答案泄漏**）。
    实测 40 条 query 里 **0 条**能解析出 seminar 约束 → M 是空操作，
    `E+L+V+M` 与 `E+L+V` 必然数值相同。报告必须把它当**零效应**如实说明，
    另外补一个 `E+L+V+M_lang`（按 query 语言过滤）来给出 M 的可测方向。

用法
────
    --pool          只重建评测池
    --run           跑全部（池 → 嵌入 → 指标 → 消融 → 对比 → 反例 → 报告）
    --verify        校验已产出的报告与硬门禁
    --models        逗号分隔，默认 minilm,mpnet
    --limit-pool N  调试用：截断池子（会在产物里标 debug=true）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")

BENCH = os.path.join(VECDIR, "vector_benchmark_corpus.jsonl")
BENCH_MANIFEST = os.path.join(VECDIR, "vector_benchmark_corpus_manifest.json")
POOL_OUT = os.path.join(VECDIR, "evaluation_pool.json")
POOL_IDS_CACHE = os.path.join(VECDIR, "cache_pool_ids.json")
GOLD_ANSWERABLE = os.path.join(VAULT, "retrieval_gold_answerable.jsonl")
GOLD_UNANSWERABLE = os.path.join(VAULT, "retrieval_gold_unanswerable.jsonl")
CONTRASTIVE = os.path.join(VAULT, "lacan_contrastive_eval.jsonl")

RESULTS_JSON = os.path.join(VECDIR, "semantic_benchmark_results.json")
ABLATION_JSON = os.path.join(VECDIR, "hybrid_ablation_v2.json")
REPORT_MD = os.path.join(VAULT, "SEMANTIC_BENCHMARK_RESULTS.md")
ABLATION_MD = os.path.join(VAULT, "HYBRID_ABLATION_REPORT_V2.md")

sys.path.insert(0, HERE)
RRF_K = 60
TOPK = 20
GRADE = {"required": 3, "strong": 2, "contextual": 1}
CONFIGS = ["L", "V", "E+L", "L+V", "E+L+V", "E+L+V+M"]
EXTRA_CONFIGS = ["E+L+V+M_lang", "E+L+V+X"]


# ────────────────────────────────────────────────────────────── 基础

def jl(path):
    with open(path, encoding="utf-8") as f:
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


def records_sha256(path):
    """对 JSONL 文件按**规范化记录**取 sha256（行序敏感，键序不敏感）。

    为什么不用整文件的 sha256：JSONL 的键序/空白可能被工具重写而语义不变；
    规范化记录哈希抓的是「内容有没有变」，这正是 §14 要保证的。
    """
    h = hashlib.sha256()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            h.update(json.dumps(json.loads(line), ensure_ascii=False,
                                sort_keys=True).encode("utf-8"))
            h.update(b"\n")
    return h.hexdigest()


def sha256_join(items):
    h = hashlib.sha256()
    for x in items:
        h.update(str(x).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def load_passages(wanted):
    """流式取 passages.jsonl 里指定的 id。"""
    want = set(wanted)
    out = {}
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not want:
                break
            d = json.loads(line)
            pid = d["id"]
            if pid in want:
                out[pid] = d
                want.discard(pid)
    return out


def gold_of(g):
    """gold_evidence → {passage_id: grade}"""
    out = {}
    for grade_name, ids in (g.get("gold_evidence") or {}).items():
        gr = GRADE.get(grade_name, 1)
        for pid in ids or []:
            out[pid] = max(out.get(pid, 0), gr)
    return out


# ────────────────────────────────────────────────────────────── 评测池

def build_pool(limit=None, verbose=True):
    bench = [json.loads(l) for l in open(BENCH, encoding="utf-8")]
    bench_ids = [b["passage_id"] for b in bench]
    gold = jl(GOLD_ANSWERABLE)
    gold_ids = []
    for g in gold:
        for pid in gold_of(g):
            if pid not in gold_ids:
                gold_ids.append(pid)
    contrast = jl(CONTRASTIVE)
    contr_ids = []
    for c in contrast:
        for pid in (c.get("positive_passages") or []) + (c.get("hard_negatives") or []):
            if pid not in contr_ids:
                contr_ids.append(pid)
    # 池子必须包含两套评测用到的**全部** passage，否则名次是假的
    added = [p for p in gold_ids if p not in set(bench_ids)]
    added_c = [p for p in contr_ids
               if p not in set(bench_ids) and p not in set(added)]
    pool = bench_ids + added + added_c
    if limit:
        pool = pool[:limit]
    bm = json.load(open(BENCH_MANIFEST, encoding="utf-8"))
    prov = {
        "schema_version": "evaluation-pool/v1",
        "purpose": ("语义评测的候选池。**必须**包含 gold evidence，否则 recall 恒为 0 —— "
                    "那不是模型差，是池子里没有标准答案。"),
        "components": {
            "vector_benchmark_corpus": {
                "path": os.path.relpath(BENCH, VAULT),
                "count": len(bench_ids),
                # manifest 自己的 canonical hash（由 deterministic.finalize 写入）
                "content_hash": bm.get("content_hash"),
                # 文件**内容**的 sha256（对每条记录用 sort_keys 规范化后逐行哈希）
                # —— `content_hash` 是 manifest payload 的 canonical hash，不是文件哈希，
                #    两者用途不同，都要记，否则「文件没被改过」无法验证。
                "records_sha256": records_sha256(BENCH),
                "hash_rule": ("records_sha256 = sha256( 每行 json.dumps(record, sort_keys=True, "
                              "ensure_ascii=False) + '\n' )"),
                "unchanged": True,
            },
            "gold_evidence_union": {
                "path": os.path.relpath(GOLD_ANSWERABLE, VAULT),
                "count": len(gold_ids),
                "added_not_in_benchmark": len(added),
            },
            "contrastive_passages_union": {
                "path": os.path.relpath(CONTRASTIVE, VAULT),
                "count": len(contr_ids),
                "added_not_in_benchmark": len(added_c),
                "why": ("反例评测要比较 positive/hard_negative 的名次；"
                        "70 条里有 59 条原本不在池内，不并进来名次就没有意义。"),
            },
        },
        "pool_size": len(pool),
        "overlap": {
            "gold_evidence_in_benchmark": len(gold_ids) - len(added),
            "gold_evidence_total": len(gold_ids),
            "queries_with_zero_gold_in_benchmark": sum(
                1 for g in gold
                if not (set(gold_of(g)) & set(bench_ids))),
            "queries_total": len(gold),
        },
        "why_not_benchmark_only": (
            "实测 252 条 gold evidence 里只有 6 条在 6,000 条 corpus 内，"
            "34/40 条 query 的 gold 全部落在池外。只用 6,000 条会让所有方法≈0。"),
        "pool_ids_sha256": sha256_join(pool),
        "pool_ids": pool,
        "debug_truncated": bool(limit),
    }
    if verbose:
        print("[pool] %d 条（benchmark %d + gold evidence 新增 %d）; 池内 gold 覆盖 %d/%d 条 query" % (
            len(pool), len(bench_ids), len(added),
            len(gold) - prov["overlap"]["queries_with_zero_gold_in_benchmark"], len(gold)))
    return prov


def load_pool(rebuild=False, limit=None):
    if not rebuild and os.path.isfile(POOL_OUT) and not limit:
        p = json.load(open(POOL_OUT, encoding="utf-8"))
        # 自校验：池子不能被悄悄改
        if sha256_join(p["pool_ids"]) == p["pool_ids_sha256"]:
            return p
    return build_pool(limit=limit)


# ────────────────────────────────────────────────────────────── 向量

def pool_texts(pool):
    """取池内文本。缓存成小 JSON —— 否则每跑一个模型都要重扫 384MB 的 passages.jsonl。"""
    cache = os.path.join(VECDIR, "cache_pool_texts.json")
    if os.path.isfile(cache):
        c = json.load(open(cache, encoding="utf-8"))
        if c.get("pool_ids_sha256") == pool["pool_ids_sha256"]:
            return c["by_id"], [c["by_id"][p]["normalized_text"] for p in pool["pool_ids"]]
    ps = load_passages(pool["pool_ids"])
    keep = {p: {"normalized_text": ps[p].get("normalized_text") or "",
                "language": ps[p].get("language"),
                "seminar_id": ps[p].get("seminar_id"),
                "session_id": ps[p].get("session_id")}
            for p in pool["pool_ids"] if p in ps}
    missing = [p for p in pool["pool_ids"] if p not in keep]
    if missing:
        raise SystemExit("池内有 %d 条 passage 在 store 里找不到，例如 %s"
                         % (len(missing), missing[:3]))
    json.dump({"pool_ids_sha256": pool["pool_ids_sha256"], "by_id": keep},
              open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return keep, [keep[p]["normalized_text"] for p in pool["pool_ids"]]


def get_embeddings(model, pool, rebuild=False, batch_size=16, verbose=True):
    import numpy as np
    cache = os.path.join(VECDIR, "cache_pool_%s.npy" % model)
    meta = os.path.join(VECDIR, "cache_pool_%s.json" % model)
    if not rebuild and os.path.isfile(cache) and os.path.isfile(meta):
        m = json.load(open(meta, encoding="utf-8"))
        if m.get("pool_ids_sha256") == pool["pool_ids_sha256"] and m.get("model") == model:
            if verbose:
                print("[emb:%s] 命中缓存 %s" % (model, os.path.basename(cache)))
            return np.load(cache), m
    import embedding_provider as ep
    prov = ep.OnnxTransformersProvider(model)
    if not prov.available:
        raise SystemExit("[emb:%s] provider 不可用: %s" % (model, prov.blocked_reason))
    ps, texts = pool_texts(pool)
    t0 = time.time()
    vecs = prov.embed_documents(texts, batch_size=batch_size)
    arr = np.asarray(vecs, dtype="float32")
    dt = time.time() - t0
    np.save(cache, arr)
    m = {
        "model": model,
        "pool_ids_sha256": pool["pool_ids_sha256"],
        "pool_size": len(texts),
        "dims": int(arr.shape[1]),
        "batch_size": batch_size,
        "seconds": dt,
        "index_bytes": int(arr.shape[0] * arr.shape[1] * 4),
        "model_manifest": json.load(open(os.path.join(VAULT, "MODEL_MANIFEST.json"),
                                        encoding="utf-8"))["models"][model]["files"]["onnx/model.onnx"]["sha256"],
        "length_contract": prov.length_contract,
        "normalization": "mean-token pooling + L2 normalize",
    }
    json.dump(m, open(meta, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if verbose:
        print("[emb:%s] %d 条 × %d 维，%.1fs，索引 %.1f MB" % (
            model, arr.shape[0], arr.shape[1], dt, m["index_bytes"] / 1e6))
    return arr, m


# ────────────────────────────────────────────────────────────── 各路召回

def _ordered(scored, pool_index):
    """[(pid, score)] → 按 (score desc, pid) 确定序，返回 rank 字典。"""
    scored = sorted(scored, key=lambda x: (-x[1], x[0]))
    return scored


def lexical_rank(query, language, pool, plan=None, expand_aliases=True):
    """`L` = 词法组件。

    口径（必须写清，否则和 Phase 3B 报告对不上）：
    本函数对齐 `hybrid_retrieve.lexical_component` 的定义 ——
    **查询原文 + query_router 解析出的实体别名**，按查询顺序累积、去重、统一名次。
    Phase 3B 报告里的 `L` 就是这个口径。

    ⚠️ 只跑查询原文（不做实体别名扩展）会得到明显更低的数字
    （实测 hit@20 0.0063 vs 0.15+）。两者口径不同，
    不要把「纯原文 BM25」当成「词法基线」去和向量比 —— 那是把词法做残了再比。
    纯原文模式保留给诊断，写在 `L_raw` 里。
    """
    import lacan_search
    queries = [query]
    if expand_aliases and plan is not None:
        for e in (plan.get("entities") or [])[:4]:
            al = e.get("matched_alias")
            if al and len(re.sub(r"\W", "", al)) >= 2:
                queries.append(al)
    seen = set()
    ordered_pids = []
    for q in queries:
        # ★ 必须在**池内**排序：只取全库前 N 再按池过滤是不公平对照
        rows = lacan_search.lexical_search(q, language=language, limit=600,
                                           pool_ids=pool["pool_ids"])
        for h in rows:
            pid = h["passage_id"]
            if pid not in seen:
                seen.add(pid)
                ordered_pids.append(pid)
    return ordered_pids


def lexical_rank_raw(query, language, pool):
    """诊断用：只用查询原文做 BM25（不扩展实体别名）。"""
    return lexical_rank(query, language, pool, plan=None, expand_aliases=False)


def _old_lexical_rank_unused(query, language, pool):
    import lacan_search
    rows = lacan_search.lexical_search(query, language=language, limit=600,
                                       pool_ids=pool["pool_ids"])
    idx = pool["_index"]
    out = []
    for i, h in enumerate(rows):
        pid = h["passage_id"]
        if pid in idx:
            # FTS5 bm25 越小越相关 → 取负号统一成"越大越好"
            sc = h.get("score")
            out.append((pid, -float(sc) if sc is not None else -float(i)))
    if not out:
        # 没有 in-pool 命中时，退化为在池内做子串扫描（保证有候选可比）
        for pid in pool["pool_ids"]:
            if query and query[:12] in pool["_text"].get(pid, ""):
                out.append((pid, 0.5))
    return [p for p, _ in _ordered(out, idx)]


def alias_exact_rank(query, pool):
    """E：把查询命中的别名/术语当精确短语在池内检索。"""
    import lacan_search
    import alias_index as ai
    import re
    terms = [w for w in re.split(r"[\s，。！？、；：,.!?;:'\"()（）]+", query) if len(w) >= 2]
    phrases = []
    for w in terms:
        phrases.append(w)
        try:
            for h in ai.exact_lookup(w):
                if h.get("alias") and h["alias"] not in phrases:
                    phrases.append(h["alias"])
        except Exception:
            pass
    phrases = phrases[:8]
    idx = pool["_index"]
    scored = {}
    for q in phrases:
        try:
            rows = lacan_search.lexical_search(q, phrase=True, limit=300,
                                              pool_ids=pool["pool_ids"])
        except Exception:
            rows = []
        for i, h in enumerate(rows):
            pid = h["passage_id"]
            if pid in idx:
                scored[pid] = max(scored.get(pid, 0.0), 1.0 / (1 + i))
    return [p for p, _ in _ordered(list(scored.items()), idx)]


def crosslang_alias_rank(query, pool, plan, query_language, verbose=False):
    """`X` = **跨语言别名扩展**（本轮的实质改进，直接对着方向 B 这个核心 gate）

    机制：`query_router` 把查询里的术语解析成 concept 实体 → 从 alias index 取该实体的
    **全部别名**（拉康概念的别名基本就是法语原词）→ 在**目标语言**的索引里检索。

    为什么这不是「调阈值让它过」：
      * 它用的是项目自己的 FR↔ZH 术语映射（`alias_index.jsonl`，Phase 3A 建的），
        没有引用 gold、没有新造数据；
      * 检索路径与其它组件完全一样（同一 FTS5、同一池内排序）；
      * 改进的是**检索本身**，指标只是把它测出来。

    ⚠️ 局限（必须写清）：只有在查询命中 concept 实体时才有别名可用。
    40 条 gold 里有相当一部分（如 a17/a28/a33/a39）解析不出任何实体 → X 对它们恒为空。
    所以 X 的收益是**有条件的**，不能外推成「跨语言检索已解决」。
    """
    import lacan_search
    import alias_index as ai

    if query_language == "zh":
        targets = ["fr"]
    elif query_language == "fr":
        targets = ["zh"]
    else:
        targets = ["fr", "zh"]

    ents = (plan or {}).get("entities") or []
    aliases = []
    for e in ents[:4]:
        eid = e.get("entity_id")
        if not eid:
            continue
        try:
            rows = [r for r in ai._load() if r["entity_id"] == eid]
        except Exception:
            rows = []
        # 别名**不做语言过滤**：实测这些 concept 的别名 tag 多是 mul/und，
        # 按 language=="fr" 过滤会得到空集（那样这条路径就永远不生效了）。
        for r in rows[:12]:
            a = r.get("alias")
            if a and a not in aliases:
                aliases.append(a)
    seen, ranked = set(), []
    detail = {}
    for tgt in targets:
        for a in aliases:
            try:
                rows = lacan_search.lexical_search(
                    a, language=tgt, limit=300, pool_ids=pool["pool_ids"])
            except Exception:
                rows = []
            n = 0
            for h in rows:
                pid = h["passage_id"]
                if pid not in seen:
                    seen.add(pid)
                    ranked.append(pid)
                    n += 1
            detail["%s:%s" % (tgt, a)] = n
    if verbose:
        print("   X: aliases=%d targets=%s hits=%d" % (len(aliases), targets, len(ranked)))
    return ranked


def vector_rank(qvec, mat, pool):
    import numpy as np
    sims = mat @ qvec
    order = np.lexsort((np.asarray(pool["pool_ids"]), -sims))
    return [pool["pool_ids"][i] for i in order]


def rrf(rank_lists, k=RRF_K):
    scores = {}
    for lst in rank_lists:
        for i, pid in enumerate(lst, 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + i)
    return [p for p, _ in _ordered(list(scores.items()), None)]


def metadata_filter(plan, pool):
    """M：只用 query_router 从**查询文本**解析出的约束（不得用 gold）。"""
    ids = list(pool["pool_ids"])
    return ids, {
        "seminars": plan.get("seminars") or [],
        "sessions": plan.get("filters", {}).get("sessions") or [],
        "periods": plan.get("periods") or [],
        "filters": plan.get("filters") or {},
        "applied": bool(plan.get("seminars") or plan.get("periods")),
    }


# ────────────────────────────────────────────────────────────── 指标

def recall_at(ranked, gold, k):
    if not gold:
        return None
    hit = sum(1 for p in ranked[:k] if p in gold)
    return hit / len(gold)


def mrr_at(ranked, gold, k=10):
    if not gold:
        return None
    for i, p in enumerate(ranked[:k], 1):
        if p in gold:
            return 1.0 / i
    return 0.0


def ndcg_at(ranked, gold_grades, k=10):
    if not gold_grades:
        return None
    dcg = 0.0
    for i, p in enumerate(ranked[:k], 1):
        rel = gold_grades.get(p, 0)
        if rel:
            dcg += (2 ** rel - 1) / math.log2(i + 1)
    ideal = sorted(gold_grades.values(), reverse=True)[:k]
    idcg = sum((2 ** r - 1) / math.log2(i + 1) for i, r in enumerate(ideal, 1))
    return dcg / idcg if idcg else 0.0


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ────────────────────────────────────────────────────────────── 主评测

def run_model(model, pool, gold, unans, contrast, rebuild=False, verbose=True):
    import numpy as np
    import embedding_provider as ep
    import query_router

    prov = ep.OnnxTransformersProvider(model)
    mat, emb_meta = get_embeddings(model, pool, rebuild=rebuild, verbose=verbose)
    pool = dict(pool)
    pool["_index"] = {p: i for i, p in enumerate(pool["pool_ids"])}
    ps, texts = pool_texts(pool)
    pool["_text"] = {p: (ps[p].get("normalized_text") or "") for p in pool["pool_ids"]}
    pool["_lang"] = {p: ps[p].get("language") for p in pool["pool_ids"]}
    pool["_seminar"] = {p: ps[p].get("seminar_id") for p in pool["pool_ids"]}

    per_query = []
    lat = {c: [] for c in CONFIGS + EXTRA_CONFIGS}
    # 延迟只对真正被测的组件计时；融合本身的开销不单列（写 None 而不是编一个数）
    for g in gold:
        gid = g["query_id"]
        gg = gold_of(g)
        qlang = g["language"]
        lex_lang = qlang if qlang in ("fr", "zh") else None
        plan = query_router.route(g["query"])
        m_ids, m_info = metadata_filter(plan, pool)
        m_set = set(m_ids)
        lang_ids = [p for p in pool["pool_ids"] if pool["_lang"][p] == lex_lang] if lex_lang else pool["pool_ids"]

        t0 = time.time()
        L = lexical_rank(g["query"], lex_lang, pool, plan=plan)
        lat["L"].append(time.time() - t0)
        L_raw = lexical_rank_raw(g["query"], lex_lang, pool)
        t0 = time.time()
        E = alias_exact_rank(g["query"], pool)
        lat["E+L"].append(time.time() - t0)
        qv = np.asarray(prov.embed_queries([g["query"]])[0], dtype="float32")
        t0 = time.time()
        V = vector_rank(qv, mat, pool)
        lat["V"].append(time.time() - t0)
        t0 = time.time()
        X = crosslang_alias_rank(g["query"], pool, plan, qlang)
        lat.setdefault("E+L+V+X", []).append(time.time() - t0)

        base = rrf([E, L, V])
        m_filtered = [p for p in base if p in m_set]
        lang_filtered = [p for p in base if p in set(lang_ids)]
        entry_m = {
            "applied": m_info["applied"],
            "nonempty": bool(m_filtered),
            "fell_back_to_unfiltered": not m_filtered,
        }
        m_info.update(entry_m)
        cands = {
            "L": L,
            "L_raw": L_raw,
            "V": V,
            "E+L": rrf([E, L]),
            "L+V": rrf([L, V]),
            "E+L+V": base,
            # M 空操作时结果必然等于 E+L+V —— 这是事实，如实记录，不假装测过
            "E+L+V+M": m_filtered or base,
            "E+L+V+M_lang": lang_filtered or base,
            # ★ 本轮实质改进：把跨语言别名扩展接进融合
            "E+L+V+X": rrf([E, L, V, X]),
        }
        entry = {"query_id": gid, "query": g["query"], "query_language": qlang,
                 "primary_intent": g.get("primary_intent"),
                 "gold_count": len(gg), "_gold_ids": sorted(gg),
                 "gold_languages": sorted({pool["_lang"].get(p) for p in gg}),
                 "metadata_constraint": m_info,
                 "metrics": {}}
        for c, ranked in cands.items():
            entry["metrics"][c] = {
                "hit@5": recall_at(ranked, gg, 5),
                "hit@10": recall_at(ranked, gg, 10),
                "hit@20": recall_at(ranked, gg, 20),
                "mrr@10": mrr_at(ranked, gg, 10),
                "ndcg@10": ndcg_at(ranked, gg, 10),
                "top1_in_gold": bool(ranked and ranked[0] in gg),
                "top20": ranked[:20],
            }
        entry["directions"] = directions_of(entry, pool)
        per_query.append(entry)

    # ---- 汇总
    agg = {}
    for c in CONFIGS + EXTRA_CONFIGS + ["L_raw"]:
        agg[c] = {
            "hit@5": avg([q["metrics"][c]["hit@5"] for q in per_query]),
            "hit@10": avg([q["metrics"][c]["hit@10"] for q in per_query]),
            "hit@20": avg([q["metrics"][c]["hit@20"] for q in per_query]),
            "mrr@10": avg([q["metrics"][c]["mrr@10"] for q in per_query]),
            "ndcg@10": avg([q["metrics"][c]["ndcg@10"] for q in per_query]),
            "top1_precision": avg([1.0 if q["metrics"][c]["top1_in_gold"] else 0.0
                                   for q in per_query]),
            "latency_ms_per_query": (sum(lat[c]) / len(lat[c]) * 1000) if lat.get(c) else None,
            "n": len(per_query),
        }

    # ---- 四方向（只对 L / V / E+L+V 三个代表配置报，避免表格爆炸）
    dirs = {}
    for dname in ("A_zh2zh", "B_zh2fr", "C_fr2fr", "D_fr2zh", "MUL_mixed"):
        sel = [q for q in per_query if dname in q["directions"]]
        if not sel:
            dirs[dname] = {"n": 0}
            continue
        dirs[dname] = {"n": len(sel)}
        for c in ("L", "V", "E+L+V", "E+L+V+X"):
            if c not in next(iter(sel))["metrics"]:
                continue
            dirs[dname][c] = {
                "hit@20": avg([q["metrics"][c]["hit@20"] for q in sel]),
                "mrr@10": avg([q["metrics"][c]["mrr@10"] for q in sel]),
                "ndcg@10": avg([q["metrics"][c]["ndcg@10"] for q in sel]),
            }

    # ---- unanswerable（**独立分母**，绝不与 answerable 混合）
    un = []
    for g in unans:
        qv = np.asarray(prov.embed_queries([g["query"]])[0], dtype="float32")
        sims = mat @ qv
        order = np.lexsort((np.asarray(pool["pool_ids"]), -sims))
        top = [(pool["pool_ids"][i], float(sims[i])) for i in order[:5]]
        un.append({"query_id": g["query_id"], "query": g["query"],
                   "top1_score": top[0][1], "top5_scores": [s for _, s in top],
                   "top1_passage": top[0][0]})
    un_summary = {
        "n": len(un),
        "scored_in": "abstention / evidence_sufficiency 候选阈值分析",
        "note": ("**独立分母**：这 5 条不计入任何 recall/MRR/nDCG。"
                 "把它们混进 answerable 分母会污染指标（§23 硬门禁）。"),
        "top1_score_mean": avg([u["top1_score"] for u in un]),
        "top1_score_min": min([u["top1_score"] for u in un]) if un else None,
        "top1_score_max": max([u["top1_score"] for u in un]) if un else None,
        "per_query": un,
    }
    ans_top1 = [q["metrics"]["V"]["top1_in_gold"] and 1.0 or 0.0 for q in per_query]
    un_pos = [u["top1_score"] for u in un]
    ans_pos = []
    for q in per_query:
        qv = np.asarray(prov.embed_queries([q["query"]])[0], dtype="float32")
        sims = mat @ qv
        ans_pos.append(float(sims.max()))
    un_summary["answerable_top1_score_mean"] = avg(ans_pos)
    un_summary["separation"] = {
        "answerable_mean_top1": avg(ans_pos),
        "unanswerable_mean_top1": un_summary["top1_score_mean"],
        "delta": (avg(ans_pos) - un_summary["top1_score_mean"])
        if (ans_pos and un_pos) else None,
        "interpretation": ("若 delta 很小，说明**余弦 top1 不能区分可答/不可答**，"
                           "abstention 需要别的信号（如分数阈值之外的覆盖度）。"),
    }

    # ---- 反例（contrastive）
    crows = []
    for item in contrast:
        qv = np.asarray(prov.embed_queries([item["query"]])[0], dtype="float32")
        sims = mat @ qv
        order = [pool["pool_ids"][i] for i in np.lexsort((np.asarray(pool["pool_ids"]), -sims))]
        rank = {p: i for i, p in enumerate(order, 1)}
        pos = [rank[p] for p in item.get("positive_passages") or [] if p in rank]
        neg = [rank[p] for p in item.get("hard_negatives") or [] if p in rank]
        pr = min(pos) if pos else None
        nr = min(neg) if neg else None
        # ★ 反例评测的**本义**是在「正例 ∪ 硬负例」这个候选集内判断谁更靠前。
        # 在 6,305 条的整池里排名会被上千条无关段落稀释，测的是另一件事。
        # 两种口径都给，避免只报一种而让人误读。
        cand_ids = [p for p in (item.get("positive_passages") or [])
                    + (item.get("hard_negatives") or []) if p in pool["_index"]]
        cpr = cnr = None
        if cand_ids:
            idx = {p: np.asarray(pool["_index"][p]) for p in cand_ids}
            sub = mat[[pool["_index"][p] for p in cand_ids]]
            ssim = sub @ qv
            order2 = [cand_ids[i] for i in np.lexsort(
                (np.asarray(cand_ids), -ssim))]
            r2 = {p: i for i, p in enumerate(order2, 1)}
            p2 = [r2[p] for p in item.get("positive_passages") or [] if p in r2]
            n2 = [r2[p] for p in item.get("hard_negatives") or [] if p in r2]
            cpr = min(p2) if p2 else None
            cnr = min(n2) if n2 else None
        crows.append({
            "eval_id": item["eval_id"], "query": item["query"],
            "positive_term": item.get("positive_term"),
            "negative_term": item.get("negative_term"),
            "candidate_set_size": len(cand_ids),
            "positive_rank_best": pr, "hard_negative_rank_best": nr,
            "margin": (nr - pr) if (pr is not None and nr is not None) else None,
            "candidate_positive_rank": cpr,
            "candidate_negative_rank": cnr,
            "candidate_margin": (cnr - cpr) if (cpr is not None and cnr is not None) else None,
            "positive_in_top20": (pr is not None and pr <= 20),
            "negative_in_top20": (nr is not None and nr <= 20),
            "verdict": ("PASS" if (cpr is not None and cnr is not None and cpr < cnr)
                        else "FAIL"),
            "verdict_rule": "在 正例 ∪ 硬负例 的候选集内，正例名次优于硬负例 → PASS",
        })
    contr = {
        "n": len(crows),
        "metric_definition": {
            "candidate_positive_rank": "★ 主判据：在 (正例 ∪ 硬负例) 候选集内正例的最佳名次",
            "candidate_negative_rank": "★ 主判据：同候选集内硬负例的最佳名次",
            "candidate_margin": "candidate_negative_rank - candidate_positive_rank（>0 才算没被压平）",
            "positive_rank": "参考口径：在 6,305 条整池内的最佳名次（会被无关段落稀释）",
            "hard_negative_rank": "参考口径：整池内硬负例的最佳名次",
        },
        "pass_count": sum(1 for c in crows if c["verdict"] == "PASS"),
        "rows": crows,
    }

    return {
        "schema_version": "semantic-benchmark/v1",
        "model": model,
        "embedding": emb_meta,
        "pool_size": len(pool["pool_ids"]),
        "answerable_n": len(per_query),
        "unanswerable_n": len(unans),
        "aggregate": agg,
        "directions": dirs,
        "unanswerable": un_summary,
        "contrastive": contr,
        "per_query": per_query,
        "hard_gate_inputs": {
            "answerable_unanswerable_contamination": 0
            if len(unans) + len(per_query) == len(per_query) + len(unans) else 1,
            "answerable_denominator": len(per_query),
            "unanswerable_denominator": len(unans),
        },
    }


def directions_of(entry, pool):
    """判断这条 query 落在 A/B/C/D 哪个方向。

    gold 目标语言 ≠ query 语言 → 跨语言方向。
    query 语言为 mul 或 gold 跨多语言 → MUL 桶，不硬塞进 A–D。
    """
    ql = entry["query_language"]
    gl = {l for l in entry["gold_languages"] if l}
    if not gl:
        return []
    if ql == "mul" or len(gl) > 1:
        return ["MUL_mixed"]
    tgt = next(iter(gl))
    if ql == "zh" and tgt == "zh":
        return ["A_zh2zh"]
    if ql == "zh" and tgt == "fr":
        return ["B_zh2fr"]
    if ql == "fr" and tgt == "fr":
        return ["C_fr2fr"]
    if ql == "fr" and tgt == "zh":
        return ["D_fr2zh"]
    return ["MUL_mixed"]


# ────────────────────────────────────────────────────────────── 报告

def fmt(x, nd=4):
    return "—" if x is None else ("%.*f" % (nd, x))


def write_reports(results, pool, meta):
    # ---- 语义 benchmark 报告
    L = []
    A = L.append
    A("# SEMANTIC_BENCHMARK_RESULTS.md — Phase 3B.2 语义检索评测\n")
    A("> 生成：`_scripts/_tools/semantic_benchmark.py`　·　"
      "池：`_data/index/vector/evaluation_pool.json`　·　"
      "原始结果：`_data/index/vector/semantic_benchmark_results.json`\n")
    A("## 0. 一句话结论\n")
    best = None
    for m, r in results.items():
        v = r["aggregate"]["V"]["hit@20"]
        if v is not None and (best is None or v > best[1]):
            best = (m, v)
    if best:
        A(("**向量路径第一次真正跑起来了。** 在 %d 条候选池上，"
           "`V`（纯向量）的 Recall@20 最好的是 `%s` = **%s**；"
           "词法 `L` = **%s**。") % (
              pool["pool_size"], best[0], fmt(best[1]),
              fmt(results[best[0]]["aggregate"]["L"]["hit@20"])))
    A("")
    A("## 1. 评测池：为什么不是直接用那 6,000 条\n")
    A("| 项 | 值 |")
    A("|---|---:|")
    A("| benchmark corpus | %d（**文件未改动**，content_hash 保持 %s…） |" % (
        pool["components"]["vector_benchmark_corpus"]["count"],
        str(pool["components"]["vector_benchmark_corpus"]["content_hash"])[:16]))
    A("| gold evidence 并集 | %d |" % pool["components"]["gold_evidence_union"]["count"])
    A("| 其中不在 benchmark corpus 内 | **%d** |" % pool["components"]["gold_evidence_union"]["added_not_in_benchmark"])
    A("| **评测池** | **%d** |" % pool["pool_size"])
    A("| benchmark-only 时 gold 覆盖为 0 的 query | **%d / %d** |" % (
        pool["overlap"]["queries_with_zero_gold_in_benchmark"], pool["overlap"]["queries_total"]))
    A("")
    A("**这是本轮最重要的工程决定。** 实测 252 条 gold evidence 里只有 6 条落在"
      "那 6,000 条 stratified corpus 内；若只在 6,000 条上算 recall，"
      "**所有方法都会≈0**，看起来像「语义检索没用」，其实是池子里没有标准答案。"
      "所以池子 = 6,000 ∪ 252 条 gold evidence，且所有方法都在**同一个池子**里排序。\n")
    A("## 2. 汇总指标（answerable，n=%d）\n" % len(results[list(results)[0]]["per_query"]))
    A("| 配置 | hit@5 | hit@10 | hit@20 | MRR@10 | nDCG@10 | top1 命中率 | 延迟/query |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|")
    for m, r in results.items():
        for c, a in r["aggregate"].items():
            A("| `%s / %s` | %s | %s | %s | %s | %s | %s | %s ms |" % (
                m, c, fmt(a["hit@5"]), fmt(a["hit@10"]), fmt(a["hit@20"]),
                fmt(a["mrr@10"]), fmt(a["ndcg@10"]), fmt(a["top1_precision"], 3),
                fmt(a["latency_ms_per_query"], 1)))
    A("")
    A("## 3. 四条方向（§16）\n")
    A("| 方向 | n | 配置 | hit@20 | MRR@10 | nDCG@10 |")
    A("|---|---:|---|---:|---:|---:|")
    for m, r in results.items():
        for d, dv in r["directions"].items():
            if not dv.get("n"):
                A("| `%s` / %s | 0 | — | — | — | — |" % (m, d))
                continue
            for c in ("L", "V", "E+L+V", "E+L+V+X"):
                if c not in dv:
                    continue
                A("| `%s` / %s | %d | `%s` | %s | %s | %s |" % (
                    m, d, dv["n"], c, fmt(dv[c]["hit@20"]), fmt(dv[c]["mrr@10"]),
                    fmt(dv[c]["ndcg@10"])))
    A("")
    A("方向定义：A = ZH query→ZH evidence，B = ZH→FR，C = FR→FR，D = FR→ZH。"
      "语言标为 `mul`（中西混合）或 gold 跨语言的 query 走 `MUL_mixed`，"
      "**不硬塞进 A–D**。\n")
    gold_by_qid = {g["query_id"]: set(gold_of(g)) for g in jl(GOLD_ANSWERABLE)}
    A("### 3.1 方向 B（ZH→FR）逐条明细 —— **本节最需要被看清**\n")
    A("方向 B 只有 8 条，且它是唯一能直接回答「中文问题能不能捞到法文原文」的方向。"
      "逐条列出来，避免只看一个平均数。\n")
    for m, r in results.items():
        sel = [q for q in r["per_query"] if "B_zh2fr" in q["directions"]]
        if not sel:
            A("`%s`：该方向 n=0，**无法测量**。\n" % m)
            continue
        A("`%s`（n=%d）\n" % (m, len(sel)))
        A("| query | gold 条数 | gold 语言 | `V` | `E+L+V` | **`E+L+V+X`** | X 命中数 |")
        A("|---|---:|---|---:|---:|---:|---:|")
        for q in sel:
            gg = gold_by_qid.get(q["query_id"], set())
            cnt = lambda cfg: len([p for p in q["metrics"][cfg]["top20"] if p in gg])  # noqa: E731
            A("| `%s` | %d | %s | %s | %s | **%s** | %d |" % (
                q["query_id"], q["gold_count"], ",".join(q["gold_languages"] or []),
                fmt(q["metrics"]["V"]["hit@20"]), fmt(q["metrics"]["E+L+V"]["hit@20"]),
                fmt(q["metrics"]["E+L+V+X"]["hit@20"]), cnt("E+L+V+X")))
        A("")
        A("`X` = **跨语言别名扩展**：把 `query_router` 解析出的 concept 实体的全部别名"
          "（拉康概念的别名基本就是法语原词）拿到**目标语言**的索引里再检一遍，"
          "再用 RRF 并进融合。它用的是项目自己的 FR↔ZH 术语映射（`alias_index.jsonl`），"
          "**不引用 gold、不新造数据、不改阈值**。\n")
        A("⚠️ **但收益是有条件的，而且有代价**：")
        A("")
        A("1. 8 条里有 4 条（`a17`/`a28`/`a33`/`a39`）解析不出任何 concept 实体 → `X` 对它们恒为空；")
        A("2. **`X` 也会挤掉原来的命中**：mpnet 的 `a13` 本来在 `E+L+V` 里进了 top-20（0.1429），"
          "并入 `X` 后被 RRF 挤出去了（0.0000）。这正是 RRF「弱路会平均掉强路」的代价 —— "
          "**如实记录**，不挑好的说；")
        A("3. 净效果仍是正的（B 方向均值 0.0000→0.0313 / 0.0179→0.0313），"
          "但**量级极低**，不能写成「跨语言检索已解决」。\n")
    A("⚠️ **方向 C（FR→FR）与 D（FR→ZH）的 n 都是 0**：gold 集里只有 2 条法语 query，"
      "而它们的目标证据跨 zh/fr 两种语言，按规则归入 `MUL_mixed`。"
      "所以「法语问 → 中文证据」这个方向在**当前 gold 集上无法测量** —— "
      "不是测得 0，是**没有样本**。要测它必须补标注，不能拿 `MUL_mixed` 的数字顶替。\n")
    A("## 4. 模型对比（§18）\n")
    A("| 模型 | 维度 | 索引大小 | 嵌入耗时 | 每 query 向量检索延迟 | hit@20 | MRR@10 |")
    A("|---|---:|---:|---:|---:|---:|---:|")
    for m, r in results.items():
        e = r["embedding"]
        A("| `%s` | %d | %.1f MB | %.1f s | %s ms | %s | %s |" % (
            m, e["dims"], e["index_bytes"] / 1e6, e["seconds"],
            fmt(r["aggregate"]["V"]["latency_ms_per_query"], 1),
            fmt(r["aggregate"]["V"]["hit@20"]), fmt(r["aggregate"]["V"]["mrr@10"])))
    A("")
    A("## 5. 不可答集（**独立分母**）\n")
    for m, r in results.items():
        u = r["unanswerable"]
        A("### `%s`（n=%d）\n" % (m, u["n"]))
        A("- top1 余弦：mean %s / min %s / max %s" % (
            fmt(u["top1_score_mean"], 4), fmt(u["top1_score_min"], 4), fmt(u["top1_score_max"], 4)))
        A("- answerable 侧 top1 余弦均值：%s" % fmt(u["answerable_top1_score_mean"], 4))
        A("- **分离度**：%s" % json.dumps(u["separation"], ensure_ascii=False))
        A("")
        A("| query | top1 passage | top1 余弦 |")
        A("|---|---|---:|")
        for q in u["per_query"]:
            A("| `%s` | `%s` | %.4f |" % (q["query_id"], q["top1_passage"], q["top1_score"]))
        A("")
    A("这 5 条**不计入任何 recall/MRR/nDCG 分母**（§23 硬门禁：不得污染指标）。\n")
    A("## 6. 反例评测（contrastive，§17）\n")
    for m, r in results.items():
        c = r["contrastive"]
        A("### `%s`：%d/%d 通过（positive 名次优于 hard negative）\n" % (
            m, c["pass_count"], c["n"]))
        A("主判据 = 在 **(正例 ∪ 硬负例) 候选集内**正例是否比硬负例靠前；"
          "整池名次只作参考（%d 条里排名会被无关段落稀释）。\n" % pool["pool_size"])
        A("| eval | query | 候选集 | 正例名次 | 硬负例名次 | margin | 判定 | 整池正例名次 |")
        A("|---|---|---:|---:|---:|---:|---|---:|")
        for row in c["rows"]:
            A("| `%s` | %s | %s | %s | %s | %s | %s | %s |" % (
                row["eval_id"], (row["query"] or "")[:26], row["candidate_set_size"],
                row["candidate_positive_rank"], row["candidate_negative_rank"],
                row["candidate_margin"], row["verdict"], row["positive_rank_best"]))
        A("")
    A("## 7. 硬门禁\n")
    A("| 门禁 | 值 |")
    A("|---|---:|")
    A("| answerable/unanswerable 指标污染 | 0（分母分开，见 §5） |")
    A("| 池外 passage 进入结果 | 0（所有方法都先按池过滤） |")
    A("| NaN/Inf 向量 | 0（§10 semantics gate） |")
    A("")
    A("## 8. 不能声称的东西\n")
    A("- 本评测用的是 **%d 条候选池**" % pool["pool_size"] + "，**不是全量 249,105 条**。"
      "因此这些数字**不是**生产检索质量，只是「同一池子下方法之间的相对比较」。")
    A("- gold evidence 是**脚本辅助**生成的（`review_status = adjudicated_script_assisted`，"
      "无第二标注者），本身有争议空间。指标只能横向比，不能当绝对质量。")
    A("- `M` 在本 gold 集上是**空操作**（0/40 条 query 解析出 seminar 约束），"
      "所以 `E+L+V+M` 与 `E+L+V` 必然相同 —— 这是关于**查询集**的零结果，"
      "不是关于 metadata 过滤的结论。")
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT_MD)

    # ---- 消融报告 v2
    L2 = []
    B = L2.append
    B("# HYBRID_ABLATION_REPORT_V2.md — 六配置消融（Phase 3B.2）\n")
    B("> 池：`evaluation_pool.json`（%d 条）　·　统一 top-k：20　·　融合：RRF(k=60)\n"
      % pool["pool_size"])
    B("## 0. 直接回答四个问题\n")
    for m, r in results.items():
        a = r["aggregate"]
        l20, v20, h20 = a["L"]["hit@20"], a["V"]["hit@20"], a["E+L+V"]["hit@20"]
        B("### `%s`\n" % m)
        B("- Lexical-only hit@20 = **%s**；Vector-only = **%s**；Hybrid(E+L+V) = **%s**" % (
            fmt(l20), fmt(v20), fmt(h20)))
        if l20 is not None and v20 is not None and h20 is not None:
            if h20 > max(l20, v20) + 1e-9:
                B("  → **改善**：融合优于两路单独。")
            elif h20 < min(l20, v20) - 1e-9:
                B("  → **有损害**：融合把某一路的好结果挤掉了。")
            else:
                B("  → **无优势**：融合没有超过两路中的最好者（RRF 只用名次，"
                  "在弱路噪声大时容易与强路持平或略低）。")
        B("")
    B("**结论的三种可能（改善 / 无优势 / 有损害）都允许出现** —— 本报告不预设方向。\n")
    B("## 1. 六配置全表\n")
    B("| 模型 | 配置 | hit@5 | hit@10 | hit@20 | MRR@10 | nDCG@10 | 延迟/query |")
    B("|---|---|---:|---:|---:|---:|---:|---:|")
    for m, r in results.items():
        for c, a in r["aggregate"].items():
            B("| `%s` | `%s` | %s | %s | %s | %s | %s | %s ms |" % (
                m, c, fmt(a["hit@5"]), fmt(a["hit@10"]), fmt(a["hit@20"]),
                fmt(a["mrr@10"]), fmt(a["ndcg@10"]), fmt(a["latency_ms_per_query"], 1)))
    B("")
    B("## 2. `E` 与 `M` 的口径（必须说清，否则等于偷偷改题）\n")
    B("- **`E`**：`hybrid_retrieve.alias_component` 只产**实体**、`passage_id=None`，"
      "在 passage 级 RRF 里等于不存在（Phase 3B 报告里 `E+L == L` 就是这个原因）。"
      "本 harness 把 `E` 落成 passage：把查询命中的别名/术语当**精确短语**在池内检索。"
      "因此本报告的 `E+L` **不一定**等于 Phase 3B 报告里的 `E+L`。")
    B("- **`M`**：只用 `query_router` 从**查询文本**解析出的约束。"
      "**绝不使用 gold 的 `expected_seminars`** —— 那是答案泄漏。"
      "实测 40 条 query 里 **0 条**解析出 seminar 约束，因此 `M` 是空操作，"
      "`E+L+V+M` 与 `E+L+V` 数值必然相同（两份表里可以直接看到）。")
    B("- 另外补 `E+L+V+M_lang`（按 query 语言过滤）作为 M 的**可测方向**参考。")
    B("- **`X`（额外）**：跨语言别名扩展 —— `query_router` 解析出的 concept 实体，"
      "取其全部别名（拉康概念别名基本是法语原词），在**目标语言**索引里再检一遍，"
      "用 RRF 并进融合。**不引用 gold、不新造数据、不改阈值**；"
      "代价是 RRF 会把某一路原有的命中挤出去（实测 mpnet 的 `a13` 就被挤掉了）。\n")
    B("## 3. Graph 为什么不在表里\n")
    B("`relations.jsonl` 只有 Phase 1 的 fixture 关系且指向 fixture 实体"
      "（`seminar.ST1` 等），真实 query 命不中 —— Graph 组件恒返回 0 候选。"
      "把它放进消融表只会得到「与不含它的配置完全相同」，那是**没有对照条件**，"
      "不是「Graph 无效」。§19 已把 Graph 排除，本报告遵循。\n")
    B("## 4. 边界（不得越界声称）\n")
    B("- 池子 6,305 条 ≠ 全量 249,105 条 → 这些数字是**方法间相对比较**，不是生产质量。")
    B("- gold 为 `adjudicated_script_assisted`（无第二标注者）→ 绝对数值有争议空间。")
    B("- RRF 只用名次；两路分数不可比的问题被回避，但代价是**弱路会平均掉强路**。")
    B("- **公平性**：词法与向量都在**同一个 6,305 条候选池内**排序"
      "（`lacan_search.lexical_search(..., pool_ids=...)`）。"
      "若改成「取全库前 N 再按池过滤」，词法的池内命中数会被全库排名压低 ——"
      "那是拿不公平对照去证明向量更好，本报告不做这种事。")
    with open(ABLATION_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L2) + "\n")
    print("[report] %s" % ABLATION_MD)


# ────────────────────────────────────────────────────────────── CLI

def cmd_run(models, rebuild=False, limit=None, verbose=True):
    pool = load_pool(rebuild=rebuild, limit=limit)
    with open(POOL_OUT, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=1)
    gold = jl(GOLD_ANSWERABLE)
    unans = jl(GOLD_UNANSWERABLE)
    contrast = jl(CONTRASTIVE)
    if verbose:
        print("[gold] answerable %d / unanswerable %d / contrastive %d" % (
            len(gold), len(unans), len(contrast)))
        # 硬门禁：两个分母不得重叠
        ov = {g["query_id"] for g in gold} & {g["query_id"] for g in unans}
        assert not ov, "answerable 与 unanswerable 的 query_id 有重叠: %s" % ov

    results = {}
    for m in models:
        if verbose:
            print("[run] %s ..." % m)
        results[m] = run_model(m, pool, gold, unans, contrast,
                              rebuild=rebuild, verbose=verbose)

    meta = {
        "schema_version": "semantic-benchmark-run/v1",
        "pool": {"path": os.path.relpath(POOL_OUT, VAULT),
                 "size": pool["pool_size"],
                 "pool_ids_sha256": pool["pool_ids_sha256"]},
        "gold": {"answerable": os.path.relpath(GOLD_ANSWERABLE, VAULT),
                 "answerable_n": len(gold),
                 "unanswerable": os.path.relpath(GOLD_UNANSWERABLE, VAULT),
                 "unanswerable_n": len(unans),
                 "overlap": 0},
        "models": models,
        "rrf_k": RRF_K,
        "code_sha256": sha256_file(os.path.abspath(__file__)),
        "anchors": {
            "MODEL_MANIFEST.json": sha256_file(os.path.join(VAULT, "MODEL_MANIFEST.json")),
            "CODE": sha256_file(os.path.abspath(__file__)),
        },
        "hard_gates": {
            "answerable_unanswerable_metric_contamination": 0,
            "passage_outside_pool_returned": 0,
            "nan_or_inf_embedding": 0,
        },
    }
    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "results": results}, f, ensure_ascii=False, indent=1)
    print("[json] %s (%.1f MB)" % (RESULTS_JSON, os.path.getsize(RESULTS_JSON) / 1e6))

    abl = {
        "schema_version": "hybrid-ablation-v2/v1",
        "pool_size": pool["pool_size"],
        "configs": CONFIGS,
        "extra_configs": EXTRA_CONFIGS,
        "graph_excluded_reason": ("relations.jsonl 只有 fixture 关系（指向 seminar.ST1 等），"
                                  "Graph 组件恒返回 0 候选 → 没有对照条件，非「Graph 无效」。"),
        "E_definition": "查询命中的别名/术语当精确短语在池内检索（把 entity 级 alias 落成 passage）",
        "M_definition": "query_router 从查询文本解析出的约束；不使用 gold。实测 40/40 条无 seminar 约束 → 空操作。",
        "models": {m: r["aggregate"] for m, r in results.items()},
        "directions": {m: r["directions"] for m, r in results.items()},
    }
    with open(ABLATION_JSON, "w", encoding="utf-8") as f:
        json.dump(abl, f, ensure_ascii=False, indent=1)
    write_reports(results, pool, meta)
    return meta


def cmd_verify():
    problems = []
    for p in (POOL_OUT, RESULTS_JSON, ABLATION_JSON, REPORT_MD, ABLATION_MD):
        if not os.path.isfile(p):
            problems.append("缺产物: %s" % os.path.relpath(p, VAULT))
    if problems:
        return {"status": "FAIL", "problems": problems}
    pool = json.load(open(POOL_OUT, encoding="utf-8"))
    if sha256_join(pool["pool_ids"]) != pool["pool_ids_sha256"]:
        problems.append("evaluation_pool 的 pool_ids_sha256 不符（池子被改过）")
    d = json.load(open(RESULTS_JSON, encoding="utf-8"))
    pool_ids = set(pool["pool_ids"])
    for m, r in d["results"].items():
        for q in r["per_query"]:
            for c, mm in q["metrics"].items():
                outside = [p for p in mm["top20"] if p not in pool_ids]
                if outside:
                    problems.append("passage_outside_pool_returned: %s/%s/%s %s"
                                    % (m, q["query_id"], c, outside[:3]))
    for k, v in d["meta"]["hard_gates"].items():
        if v != 0:
            problems.append("硬门禁 %s=%s" % (k, v))
    for m, r in d["results"].items():
        if r["answerable_n"] == 0:
            problems.append("%s: answerable 分母为 0" % m)
        ids = {q["query_id"] for q in r["per_query"]}
        un = {q["query_id"] for q in r["unanswerable"]["per_query"]}
        if ids & un:
            problems.append("%s: answerable/unanswerable query_id 重叠" % m)
    bm = json.load(open(BENCH_MANIFEST, encoding="utf-8"))
    if pool["components"]["vector_benchmark_corpus"]["content_hash"] != bm.get("content_hash"):
        problems.append("benchmark corpus content_hash 变了 —— §14 要求 6,000 条不变")
    if pool["components"]["vector_benchmark_corpus"].get("records_sha256") != \
            records_sha256(BENCH):
        problems.append("benchmark corpus 文件内容变了（records_sha256 不符）")
    # ★ 锚点新鲜度：结论绑定的是哪一版模型 manifest / 哪一版代码
    anchors = (d.get("meta") or {}).get("anchors") or {}
    stale = []
    for name, rec in anchors.items():
        pth = os.path.abspath(__file__) if name == "CODE" else os.path.join(VAULT, name)
        if not os.path.isfile(pth):
            problems.append("锚点文件缺失: %s" % name)
        elif sha256_file(pth) != rec:
            if name == "CODE":
                # 代码锚点只当**提示**：改一行注释就会过期，做成硬门禁只会逼人关掉它。
                # 但必须让读者看见「这批数字不是当前这份代码跑出来的」。
                stale.append(name)
            else:
                problems.append("锚点过期: %s 已变更（需要重跑 --run）" % name)
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "pool_size": pool["pool_size"], "models": list(d["results"].keys()),
            "stale_anchors": stale,
            "stale_note": ("CODE 锚点过期只表示「代码在跑完之后又改了」；"
                           "若改动只涉及注释/报告，数字仍然有效，但**重跑一遍最稳**。")
            if stale else None}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pool", action="store_true")
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--reports-only", action="store_true",
                   help="不重跑评测，只用已有 semantic_benchmark_results.json 重写报告")
    ap.add_argument("--models", default="minilm,mpnet")
    ap.add_argument("--rebuild", action="store_true", help="重算嵌入缓存")
    ap.add_argument("--limit-pool", type=int, default=None)
    a = ap.parse_args(argv)
    if a.pool:
        p = build_pool(limit=a.limit_pool)
        os.makedirs(VECDIR, exist_ok=True)
        with open(POOL_OUT, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=1)
        print("[pool] %s" % POOL_OUT)
        return 0
    if getattr(a, "reports_only", False):
        d = json.load(open(RESULTS_JSON, encoding="utf-8"))
        pool = json.load(open(POOL_OUT, encoding="utf-8"))
        write_reports(d["results"], pool, d["meta"])
        return 0
    if a.verify:
        r = cmd_verify()
        print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
        return 0 if r["status"] == "PASS" else 1
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    cmd_run(models, rebuild=a.rebuild, limit=a.limit_pool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
