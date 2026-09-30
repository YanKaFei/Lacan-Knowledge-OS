#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hybrid_retrieve.py — §7 Hybrid / §8 Graph / §9 Evidence Bundle / §10 Diversity

一个模块装下 Phase 3 的检索主链，因为这几部分互相咬合、分开写反而更乱：

    QueryPlan
      → ① Exact/Alias   （alias_index）
      → ② Lexical       （lacan_search，FTS5）
      → ③ Graph         （SQLite typed relations，深度/候选受控）
      → ④ 可选 Vector   （adapter；未实现则如实标注 component 缺失）
      → union → dedup → **RRF 融合** → rerank → diversity
      → Evidence Bundle

为什么不用 0.5*BM25 + 0.5*cosine（用户 §7 明确禁止）
────────────────────────────────────────────────────
BM25 与 cosine 属于**不可比的 score space**：BM25 无上界、随语料规模漂移，
cosine 固定在 [-1,1]。线性加权等于给两个量表硬扣一个汇率，权重无法解释。
RRF 只用**名次**，天然可跨组件比较：

    RRF(d) = Σ_c  1 / (k + rank_c(d))        k 默认 60

所有组件的名次都保留在 evidence 的 `*_rank` 字段里，`--explain` 会全部打印。

Graph（§8）
──────────
用现有 SQLite typed relations，**不引入 Neo4j**。扩展受 max_depth 与
candidate_limit 双重限制，每条 graph 派生结果都带 `graph_reason`
（例如 `gaze --formalized_as--> objet-a`）。

Diversity（§10）
────────────────
* near-duplicate collapse（文本前缀指纹）
* session concentration limit（同一 session 最多取 N 条）
* witness-aware dedup
* 历时查询优先 period coverage 而非某期相邻段堆积
输出 coverage.seminars / periods / languages / authority_levels。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
LEX = os.path.join(IDX, "lexical.sqlite")
REL_DIR = os.path.join(VAULT, "_data", "relations")

RRF_K = 60
DEFAULT_MAX_DEPTH = 2
DEFAULT_GRAPH_CANDIDATES = 40
SESSION_LIMIT = 3          # 同一 session 最多贡献几条
NEAR_DUP_PREFIX = 120      # 前缀指纹长度


# ------------------------------------------------------------ 工具
def _lex_con():
    con = sqlite3.connect(LEX)
    con.row_factory = sqlite3.Row
    return con


def _norm_dup(text):
    """近重复指纹：抹平空白与标点后的前缀。"""
    t = re.sub(r"[\s\u3000]+", "", str(text or ""))
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    return t[:NEAR_DUP_PREFIX]


def load_relations():
    """加载 typed relations（canonical 主库 + 候选库分开）。"""
    out = {"main": [], "candidate": []}
    for key, fn in (("main", "relations.jsonl"),
                    ("candidate", "relations.candidate.jsonl")):
        p = os.path.join(REL_DIR, fn)
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out[key].append(json.loads(line))
    return out


# ------------------------------------------------------------ ① Alias
def alias_component(plan):
    hits = []
    for i, e in enumerate(plan.get("entities") or [], 1):
        hits.append({
            "component": "alias",
            "entity_id": e["entity_id"],
            "matched_alias": e["matched_alias"],
            "match_type": e.get("match_type", "exact"),
            "rank": i,
            "why_retrieved": "alias:%s" % e["matched_alias"],
            # alias 只给**实体**，不给 passage；passage 由 lexical/graph 落下来
            "passage_id": None,
        })
    return hits


# ------------------------------------------------------------ ② Lexical
def lexical_component(plan, limit=50):
    import lacan_search
    hits = []
    queries = list(plan.get("quoted_phrases") or []) or [plan["query"]]
    # 实体别名也作为词法查询线索（提高召回）。
    # 但**过短的别名必须排除**：实测 `concept.l-autre` 的别名 `A`（数学型 S(Ⱥ) 的简写）
    # 会让词法召回被单字母噪声淹没（rank 1-3 全是含字母 A 的无关段）。
    for e in (plan.get("entities") or [])[:4]:
        al = e["matched_alias"]
        if len(re.sub(r"\W", "", al)) >= 2:
            queries.append(al)
    seen = set()
    rank = 0
    for q in queries:
        for h in lacan_search.lexical_search(
                q, language=plan.get("language") if plan.get("language") in ("fr", "zh") else None,
                limit=limit,
                seminar=(plan.get("seminars") or [None])[0],
                trace_status=None):
            if h["passage_id"] in seen:
                continue
            seen.add(h["passage_id"])
            rank += 1
            hits.append({
                "component": "lexical",
                "passage_id": h["passage_id"],
                "seminar_id": h["seminar_id"],
                "session_id": h["session_id"],
                "language": h["language"],
                "text": h["text"],
                "text_role": h["text_role"],
                "authority_level": h["authority_level"],
                "trace_status": h["trace_status"],
                "witness_id": h.get("witness_id"),
                "corpus_source_id": h.get("corpus_source_id"),
                "canonical": h.get("canonical"),
                "matched_query": q,
                "rank": rank,
                "score": h.get("score"),
                "why_retrieved": "lexical:%s" % q[:40],
            })
    return hits


# ------------------------------------------------------------ ③ Graph
def graph_component(plan, max_depth=DEFAULT_MAX_DEPTH,
                    candidate_limit=DEFAULT_GRAPH_CANDIDATES):
    """从查询实体出发做**受控**的关系扩展，再落到这些实体相关的 passage。

    每条结果都带 `graph_reason`（走的是哪条 typed relation）。
    """
    rels = load_relations()
    start = {e["entity_id"] for e in (plan.get("entities") or [])}
    # 拓扑/个案/话语 也作为起点
    for k in ("topology", "discourses", "mathemes", "cases"):
        start.update(plan.get(k) or [])
    if not start:
        return []

    # 邻接表（只走主库；候选库的关系是未审核建议，不作为检索依据）
    adj = defaultdict(list)
    for r in rels["main"]:
        s, o, p = r.get("subject"), r.get("object"), r.get("predicate")
        if not (s and o and p):
            continue
        adj[s].append((p, o, r.get("evidence", {}).get("passage_id") or []))
        adj[o].append((p, s, r.get("evidence", {}).get("passage_id") or []))

    found = []          # [{entity_id, depth, reason, evidence_passages}]
    visited = set(start)
    frontier = [(e, 0, None) for e in start]
    while frontier:
        node, depth, _ = frontier.pop(0)
        if depth >= max_depth:
            continue
        for pred, nxt, evp in adj.get(node, []):
            reason = "%s --%s--> %s" % (node, pred, nxt)
            if nxt in visited:
                continue
            visited.add(nxt)
            found.append({"entity_id": nxt, "depth": depth + 1,
                          "graph_reason": reason, "evidence_passages": evp,
                          "predicate": pred})
            frontier.append((nxt, depth + 1, reason))
            if len(found) >= candidate_limit:
                break
        if len(found) >= candidate_limit:
            break

    # graph 派生 passage：① 关系自带 evidence passage ② 该实体名下已连的 passage
    out = []
    rank = 0
    if not found:
        return out
    ent_ids = [f["entity_id"] for f in found]
    concepts = {}
    cp = os.path.join(STORE, "concepts.jsonl")
    if os.path.isfile(cp):
        with open(cp, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    c = json.loads(line)
                    concepts[c["id"]] = c
    con = _lex_con()
    try:
        for f in found:
            pids = list(f["evidence_passages"])
            c = concepts.get(f["entity_id"])
            if c:
                pids.extend(c.get("passages") or [])
            for pid in pids:
                r = con.execute("SELECT * FROM passage_meta WHERE id=?",
                                (pid,)).fetchone()
                if r is None:
                    continue
                rank += 1
                out.append({
                    "component": "graph",
                    "passage_id": r["id"], "seminar_id": r["seminar_id"],
                    "session_id": r["session_id"], "language": r["language"],
                    "text": r["raw_text"], "text_role": r["text_role"],
                    "authority_level": r["authority_level"],
                    "trace_status": r["trace_status"],
                    "witness_id": r["witness_id"],
                    "corpus_source_id": r["corpus_source_id"],
                    "rank": rank,
                    "graph_reason": f["graph_reason"],
                    "graph_depth": f["depth"],
                    "why_retrieved": "graph:%s" % f["graph_reason"],
                })
                if rank >= candidate_limit:
                    break
            if rank >= candidate_limit:
                break
    finally:
        con.close()
    return out


# ------------------------------------------------------------ ④ Vector（占位）
def vector_component(plan, adapter=None, limit=50):
    """向量召回。**未实现时如实返回空并说明**，不得静默当作 0 分。"""
    if adapter is None:
        return [], {"implemented": False,
                    "reason": "vector backend 尚未实现（见 VECTOR_INDEX.md 状态标注）"}
    try:
        hits = adapter.search(plan["query"], limit=limit)
    except Exception as e:
        return [], {"implemented": True, "error": "%s: %s" % (type(e).__name__, e)}
    out = []
    for i, h in enumerate(hits, 1):
        out.append({
            "component": "vector", "passage_id": h.get("passage_id"),
            "rank": i, "score": h.get("score"),
            "seminar_id": h.get("seminar_id"), "session_id": h.get("session_id"),
            "language": h.get("language"), "text": h.get("text"),
            "why_retrieved": "vector",
        })
    return out, {"implemented": True}


# ------------------------------------------------------------ RRF 融合
def rrf_fuse(components, k=RRF_K):
    """Reciprocal Rank Fusion。

    RRF(d) = Σ_c 1 / (k + rank_c(d))

    只用名次，不用原始分数 —— 这正是为了避开「不可比 score space」问题。
    """
    scores = defaultdict(float)
    ranks = defaultdict(dict)
    for comp, hits in components.items():
        for h in hits:
            pid = h.get("passage_id")
            if not pid:
                continue
            ranks[pid][comp] = h.get("rank")
            scores[pid] += 1.0 / (k + int(h.get("rank") or 1))
    return scores, ranks


# ------------------------------------------------------------ diversity
def diversify(ordered, session_limit=SESSION_LIMIT, top_k=10,
              diachronic=False):
    """去重 + 集中度限制 + 历时优先。返回 (kept, dropped_reasons)。"""
    kept, dropped = [], []
    sess_count = Counter()
    seen_dup = {}
    seen_witness_text = set()

    for h in ordered:
        pid = h.get("passage_id")
        if not pid:
            continue
        # ① 近重复折叠
        fp = (_norm_dup(h.get("text")), h.get("witness_id"))
        if fp in seen_witness_text:
            dropped.append({"passage_id": pid, "reason": "near_duplicate"})
            continue
        # ② witness-aware：同一 witness 下同一指纹只留一条（上面已覆盖）
        # ③ session 集中度
        sess = h.get("session_id")
        if sess and sess_count[sess] >= session_limit:
            dropped.append({"passage_id": pid, "reason": "session_concentration"})
            continue
        # ④ 历时查询：连续同一 seminar 超过 2 条时优先让位
        if diachronic and kept:
            same_sem_streak = 0
            for k in reversed(kept):
                if k.get("seminar_id") == h.get("seminar_id"):
                    same_sem_streak += 1
                else:
                    break
            if same_sem_streak >= 2:
                dropped.append({"passage_id": pid, "reason": "seminar_streak_diachronic"})
                continue

        seen_witness_text.add(fp)
        if sess:
            sess_count[sess] += 1
        kept.append(h)
        if len(kept) >= top_k:
            break
    return kept, dropped


def coverage_of(items):
    sems = sorted({i.get("seminar_id") for i in items if i.get("seminar_id")})
    langs = sorted({i.get("language") for i in items if i.get("language")})
    auths = sorted({i.get("authority_level") for i in items if i.get("authority_level")})
    periods = sorted({_period_of_sem(i.get("seminar_id")) for i in items
                      if i.get("seminar_id")})
    return {"seminars": sems, "periods": [p for p in periods if p],
            "languages": langs, "authority_levels": auths,
            "sessions": sorted({i.get("session_id") for i in items if i.get("session_id")})}


_SEM_PERIOD = {1: "1953-1955", 2: "1953-1955", 3: "1955-1958", 4: "1955-1958",
               5: "1955-1958", 6: "1955-1958", 7: "1959-1963", 8: "1959-1963",
               9: "1959-1963", 10: "1959-1963", 11: "1964-1966", 12: "1964-1966",
               13: "1964-1966", 14: "1967-1971", 15: "1967-1971", 16: "1967-1971",
               17: "1967-1971", 18: "1967-1971", 19: "1967-1971", 20: "1972-1973",
               21: "1972-1973", 22: "1974-1976", 23: "1974-1976", 24: "1974-1976",
               25: "1974-1976", 26: "1976-1981", 27: "1976-1981"}


def _period_of_sem(seminar_id):
    if not seminar_id:
        return None
    m = re.search(r"S(\d{1,2})", str(seminar_id))
    return _SEM_PERIOD.get(int(m.group(1))) if m else None


# ------------------------------------------------------------ Evidence Bundle
def _evidence_entry(h, ranks):
    return {
        "passage_id": h.get("passage_id"),
        "seminar_id": h.get("seminar_id"),
        "session_id": h.get("session_id"),
        "witness_id": h.get("witness_id"),
        "textual_realization": h.get("witness_id") or h.get("passage_id"),
        "language": h.get("language"),
        "text": h.get("text"),
        # §1：四个维度**各自独立**，绝不压成一个 authority/confidence
        "source_authority": h.get("authority_level"),
        "text_role": h.get("text_role"),
        "canonical_status": bool(h.get("canonical", False)),
        "provenance_status": h.get("trace_status"),
        # 各组件名次全部保留（§7 要求）
        "lexical_rank": ranks.get("lexical"),
        "vector_rank": ranks.get("vector"),
        "graph_rank": ranks.get("graph"),
        "alias_rank": ranks.get("alias"),
        "fusion_rank": h.get("fusion_rank"),
        "rerank_score": h.get("rerank_score"),
        "graph_reason": h.get("graph_reason"),
        "why_retrieved": h.get("why_retrieved"),
    }


def retrieve(query, top_k=10, adapter=None, explain=False,
             max_depth=DEFAULT_MAX_DEPTH, diachronic=None):
    """主入口：返回 Evidence Bundle（§9）。"""
    import query_router
    plan = query_router.route(query)
    if diachronic is None:
        diachronic = plan["intent"] == "diachronic_concept"

    a_hits = alias_component(plan)
    l_hits = lexical_component(plan)
    g_hits = graph_component(plan, max_depth=max_depth)
    v_hits, v_status = vector_component(plan, adapter=adapter)

    scores, ranks = rrf_fuse({"alias": a_hits, "lexical": l_hits,
                              "graph": g_hits, "vector": v_hits})
    # passage 级候选（alias 只给实体，没有 passage_id，故不进入 passage 排序）
    pool = {}
    for hits in (l_hits, g_hits, v_hits):
        for h in hits:
            pid = h.get("passage_id")
            if pid and pid not in pool:
                pool[pid] = dict(h)
    for pid, h in pool.items():
        h["rrf_score"] = scores.get(pid, 0.0)
    ordered = sorted(pool.values(),
                     key=lambda h: (-h.get("rrf_score", 0.0), h["passage_id"]))
    for i, h in enumerate(ordered, 1):
        h["fusion_rank"] = i

    kept, dropped = diversify(ordered, top_k=top_k, diachronic=diachronic)
    for i, h in enumerate(kept, 1):
        h["rerank_score"] = round(h.get("rrf_score", 0.0), 6)
        h["fusion_rank"] = i

    evidence = [_evidence_entry(h, ranks.get(h["passage_id"], {})) for h in kept]

    warnings = []
    # §5：seminar/concept 这类显式约束若解析不出，必须**显式告警**。
    # 原先会静默失效（例如「研讨班 11」解析失败 → 过滤没生效，用户却不知道）。
    import re as _re
    if _re.search(r"研讨班|seminar|S\d{1,2}\b", query, _re.I) and not plan["seminars"]:
        warnings.append("QUERY_CONSTRAINT_UNPARSED: 查询里出现了期号线索，"
                        "但未解析出 seminar —— 过滤未生效，结果可能跨全部研讨班")
    if not v_status.get("implemented"):
        warnings.append("VECTOR_COMPONENT_ABSENT: %s" % v_status.get("reason"))
    if plan["ambiguous_entities"]:
        warnings.append("AMBIGUOUS_ENTITIES: %d（大小写/同写法碰撞，未自动合并）"
                        % len(plan["ambiguous_entities"]))
    no_gold_note = None

    bundle = {
        "schema": "evidence-bundle/v1",
        "query": query,
        "intent": plan["intent"],
        "entities": plan["entities"],
        "ambiguous_entities": plan["ambiguous_entities"],
        "filters": plan["filters"],
        "periods": plan["periods"],
        "language": plan["language"],
        # 审计字段：本次 query 解析是否用了 LLM fallback（默认永不启用）
        "from_llm_fallback": plan.get("from_llm_fallback", False),
        "router": plan.get("router", "deterministic"),
        "evidence": evidence,
        "coverage": coverage_of(kept),
        "warnings": warnings,
        "diversity": {
            "kept": len(kept),
            "dropped": dropped,
            "session_limit": SESSION_LIMIT,
        },
        "components": {
            "alias": len(a_hits), "lexical": len(l_hits),
            "graph": len(g_hits), "vector": len(v_hits),
            "vector_status": v_status,
        },
        "fusion": {"method": "rrf", "k": RRF_K,
                   "note": "只用名次，不用原始分数（避开不可比 score space）"},
    }
    if explain:
        bundle["explain"] = explain_trace(plan, a_hits, l_hits, g_hits, v_hits,
                                          ordered, kept, dropped, v_status, ranks)
    return bundle


def explain_trace(plan, a, l, g, v, ordered, kept, dropped, v_status, ranks=None):
    import query_router
    return {
        "query_plan": query_router.explain(plan).splitlines(),
        "alias_hits": [{"entity": h["entity_id"], "alias": h["matched_alias"],
                        "rank": h["rank"]} for h in a],
        "lexical_hits": [{"passage_id": h["passage_id"], "rank": h["rank"],
                          "why": h["why_retrieved"]} for h in l[:20]],
        "graph_expansion": [{"passage_id": h["passage_id"],
                             "reason": h.get("graph_reason"),
                             "depth": h.get("graph_depth")} for h in g[:20]],
        "vector_hits": [h["passage_id"] for h in v[:20]],
        "vector_status": v_status,
        # ⚠️ 修过的缺陷：原先读的是 h["lexical_rank"] 之类，
        # 但那些字段只加在**最终 evidence 条目**上；此处 h 是融合前的候选，
        # 其名次存在 `ranks` 映射里（rrf_fuse 的产物）。于是调试视图全是 null,
        # 而 evidence[] 里却是对的 —— 证据对、调试错，最难发现的一类不一致。
        "fusion_order_before_diversity": [
            {"passage_id": h["passage_id"], "rrf": round(h.get("rrf_score", 0), 6),
             # 键名与 evidence[] 统一（原先 explain 用 `lexical`、evidence 用
             # `lexical_rank`，同一事实两套键名，消费方要写两套逻辑）
             "ranks": {"%s_rank" % k: v
                       for k, v in (ranks or {}).get(h["passage_id"], {}).items()}}
            for h in ordered[:20]],
        "after_diversity": [h["passage_id"] for h in kept],
        "dropped_by_diversity": dropped,
    }


# ------------------------------------------------------------ 校验
def validate_bundle(*args, **kw):
    """兼容 `validate_bundle(bundle)` 与 `validate_bundle(bundle, store_ids)`。

    ⚠️ 实测踩过的坑：函数签名是 `(bundle, store_ids=None)`，
    而调用方写的是 `validate_bundle(self.bundle)` —— 位置参数没错；
    但另一处误写成 `validate_bundle(None, bundle)` 之类会把 bundle 顶掉。
    为避免这类静默错位，这里显式做一次参数归一化：
    若第一个参数是 None 或不像 bundle（没有 evidence key），则视为 store_ids 前缀。
    """
    bundle = None
    store_ids = None
    for a in args:
        if isinstance(a, dict) and ("evidence" in a or "query" in a):
            bundle = a
        elif isinstance(a, (set, frozenset, list, tuple)) or a is None:
            store_ids = a
    bundle = kw.get("bundle", bundle)
    store_ids = kw.get("store_ids", store_ids)
    if bundle is None:
        return ["BUNDLE_MISSING"]
    return _validate_bundle_impl(bundle, store_ids)


def _validate_bundle_impl(bundle, store_ids=None):
    """Evidence Bundle 硬校验（§15 门禁在 bundle 侧的落点）。"""
    problems = []
    if store_ids is None:
        con = _lex_con()
        try:
            store_ids = {r[0] for r in con.execute("SELECT id FROM passage_meta")}
        finally:
            con.close()
    seen = set()
    for e in bundle.get("evidence") or []:
        pid = e.get("passage_id")
        if not pid:
            problems.append("evidence 缺 passage_id")
            continue
        if pid not in store_ids:
            problems.append("FABRICATED_PASSAGE_ID: %s" % pid)
        if pid in seen:
            problems.append("DUPLICATE_EVIDENCE: %s" % pid)
        seen.add(pid)
        # provenance 不得被检索层篡改
        if e.get("provenance_status") not in ("COMPLETE", "SOURCE_TRACE_INCOMPLETE"):
            problems.append("PROVENANCE_STATUS_INVALID: %s" % pid)
        if e.get("source_authority") not in ("L0", "L1", "L2", "L3", "L4"):
            problems.append("AUTHORITY_INVALID: %s" % pid)
    return problems
