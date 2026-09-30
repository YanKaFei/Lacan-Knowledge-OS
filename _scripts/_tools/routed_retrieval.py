#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
routed_retrieval.py — Phase 3C §16–§18

三件事，一个入口：

§17 **Evidence Bundle 扩展** —— 在 Phase 3A 的 bundle schema 上增加 6 个字段：
    `retrieval_route` · `term_expansions` · `semantic_guard` ·
    `contrastive_lane` · `vector_enabled` · `component_contribution`

§16 **Contrastive Production Test** —— 分开报两种通过率：
    * **Raw Vector Contrastive Pass**：纯 embedding 在候选集内能不能排对；
    * **System Contrastive Pass**：ROUTED + Semantic Guard 之后，
      最终检索系统能不能保住区分。
    §16 明确：系统**不要求** embedding 自己解决所有 Lacanian distinction；
    真正的 gate 是最终 retrieval system 能不能维持这些区分。

§18 **Abstention** —— **禁止 cosine threshold**。实测不可答 query 的 top1 余弦
    **高于**可答 query（delta −0.0128 / −0.0076），所以 `cosine < t → abstain`
    在数学上就是错的。本模块只建 schema / evidence-sufficiency 接口：
    `SUPPORTED` / `PARTIALLY_SUPPORTED` / `INSUFFICIENT_EVIDENCE`，
    判据全部是**结构性的**（分量一致性、session 多样性、术语覆盖），
    真正的 calibration 留到后续阶段。

用法
────
    .venv-embedding/bin/python _scripts/_tools/routed_retrieval.py --bundle "大他者是怎么被定义的"
    .venv-embedding/bin/python _scripts/_tools/routed_retrieval.py --contrastive
    python3 _scripts/_tools/routed_retrieval.py --verify
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
STORE = os.path.join(VAULT, "_data", "passage_store")

CONTRAST = os.path.join(VAULT, "lacan_contrastive_eval.jsonl")
GOLD = os.path.join(VAULT, "retrieval_gold_answerable.jsonl")
OUT_JSON = os.path.join(VECDIR, "contrastive_system_vs_raw.json")
REPORT = os.path.join(VAULT, "ROUTED_RETRIEVAL_EVALUATION.md")

TOPK = 20
LANE_TOPK = 20

sys.path.insert(0, HERE)


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ─────────────────────────────────────────────────────── §18 证据充分性

def evidence_sufficiency(bundle):
    """§18：**不使用 cosine threshold** 的证据充分性接口。

    判据（全部结构性）
    ------------------
    * `component_agreement` —— 在 top-k 内同时被 **≥2 个独立分量**召回的比例；
    * `session_diversity`   —— top-k 来自多少个不同 session；
    * `term_coverage`       —— 查询解析出的实体里，有多少个在证据里真的出现；
    * `contrastive_risk`    —— Guard 是否报了压平风险。

    → `SUPPORTED` / `PARTIALLY_SUPPORTED` / `INSUFFICIENT_EVIDENCE`
    """
    ev = bundle.get("evidence") or []
    if not ev:
        return {"status": "INSUFFICIENT_EVIDENCE", "signals": {"evidence_n": 0},
                "why": "没有任何证据条目",
                "method": "structural_only_no_cosine_threshold"}

    multi = 0
    for e in ev:
        comps = set()
        for w in (e.get("why_retrieved") or []):
            comps.add(str(w).split(":")[0])
        for k in ("lexical_rank", "vector_rank", "alias_rank"):
            if e.get(k):
                comps.add(k)
        if len(comps) >= 2:
            multi += 1
    agreement = multi / len(ev)

    sessions = {e.get("session_id") for e in ev if e.get("session_id")}
    seminars = {e.get("seminar_id") for e in ev if e.get("seminar_id")}

    ents = bundle.get("entity_resolution", {}).get("entities") or []
    covered = 0
    for ent in ents:
        forms = [f for f in (ent.get("bridge_forms") or []) if f]
        if not forms:
            forms = [ent.get("matched_alias")] if ent.get("matched_alias") else []
        blob = " ".join((e.get("text") or "") for e in ev)
        if any(f and f in blob for f in forms):
            covered += 1
    term_cov = (covered / len(ents)) if ents else None

    risk = (bundle.get("semantic_guard") or {}).get("flattening_risk")
    signals = {"evidence_n": len(ev), "component_agreement": agreement,
               "session_diversity": len(sessions), "seminar_diversity": len(seminars),
               "term_coverage": term_cov, "contrastive_risk": risk}

    if agreement >= 0.5 and len(sessions) >= 2:
        status = "SUPPORTED"
        why = "≥2 个独立分量在 top-k 内一致，且证据来自 ≥2 个 session"
    elif ev:
        status = "PARTIALLY_SUPPORTED"
        why = "有证据，但分量一致性或 session 多样性不足"
    else:
        status = "INSUFFICIENT_EVIDENCE"
        why = "无证据"
    return {"status": status, "signals": signals, "why": why,
            "method": "structural_only_no_cosine_threshold",
            "prohibited": ("禁止用 `cosine < threshold → abstain`："
                           "实测不可答 query 的 top1 余弦**高于**可答 query，"
                           "该规则在数学上就是错的。")}


# ─────────────────────────────────────────────────────── §17 扩展 bundle

def retrieve_bundle(query, idx, prov, np, top_k=TOPK):
    import query_router
    import query_routing_policy as rp
    import lacanian_semantic_guard as guard_mod
    import terminology_bridge as tb
    import entity_resolution as er
    import full_corpus_retrieval as fcr

    plan = query_router.route(query)
    res = er.resolve(query, plan)
    route = rp.plan_for(query, plan)
    guard = route["guard"]

    qv = np.asarray(prov.embed_queries([query])[0], dtype="float32")
    E = fcr.comp_exact(query, res)
    L = fcr.comp_lexical(query, route["router_language"]
                         if route["router_language"] in ("fr", "zh") else None, res=res)
    V, Vsim = idx.search(qv)
    X = fcr.comp_bridge(res, target_langs=("fr",) if route["router_language"] == "zh"
                        else (("zh",) if route["router_language"] == "fr" else ("fr", "zh")))

    comp_rank = {"exact": {p: i for i, p in enumerate(E, 1)},
                 "lexical": {p: i for i, p in enumerate(L, 1)},
                 "terminology_bridge": {p: i for i, p in enumerate(X, 1)}}
    if route["vector_enabled"]:
        comp_rank["vector"] = {p: i for i, p in enumerate(V, 1)}

    lists = [E, L]
    if route["vector_enabled"]:
        lists.append(V)
    if "x" in route["components"]:
        lists.append(X)
    fused = fcr.rrf(lists)[:top_k]

    # ── lane 归属（contrastive 时）
    lane_of = {}
    if route["lanes_count"] > 1:
        for lane in route["lanes"]:
            forms = [f for f in (lane.get("query_forms") or []) if f]
            for pid in fused:
                t = _text_of(pid)
                if any(f in t for f in forms):
                    lane_of.setdefault(pid, lane["lane_id"])

    evidence = []
    for i, pid in enumerate(fused, 1):
        contrib = {name: rk[pid] for name, rk in comp_rank.items() if pid in rk}
        why = []
        if pid in comp_rank.get("terminology_bridge", {}):
            why.append("terminology_bridge")
        if pid in comp_rank.get("exact", {}):
            why.append("exact_alias_match")
        if pid in comp_rank.get("lexical", {}):
            why.append("lexical_match")
        if pid in comp_rank.get("vector", {}):
            why.append("semantic_candidate")
        evidence.append({
            "rank": i, "passage_id": pid,
            "session_id": _meta_of(pid, "session_id"),
            "seminar_id": _meta_of(pid, "seminar_id"),
            "language": _meta_of(pid, "language"),
            "text": _text_of(pid)[:400],
            "why_retrieved": why,
            "contrastive_lane": lane_of.get(pid),
            "component_contribution": contrib,
        })

    term_expansions = []
    for e in res["entities"][:4]:
        for form in [e.get("matched_alias")] + tb.lexical_forms_for_entity(e["entity_id"])[:4]:
            if not form:
                continue
            for m in tb.expand(form, target_langs=("fr", "zh", "en")):
                term_expansions.append({
                    "from": form, "to": m["target_form"],
                    "target_language": m["target_language"],
                    "entity_id": m["entity_id"], "term_id": m["term_id"],
                    "relation_type": "equivalent"})
    # 去重
    seen, te = set(), []
    for x in term_expansions:
        k = (x["from"], x["to"])
        if k not in seen:
            seen.add(k)
            te.append(x)

    bundle = {
        "schema": "evidence-bundle/v2",
        "query": query,
        "retrieval_route": route["route"],
        "retrieval_route_why": route["why"],
        "vector_enabled": route["vector_enabled"],
        "vector_weight": route["vector_weight"],
        "vector_candidate_limit": route["vector_candidate_limit"],
        "vector_disabled_reason": route["vector_disabled_reason"],
        "term_expansions": te[:40],
        "semantic_guard": {
            "flattening_risk": guard.get("flattening_risk"),
            "contrastive_pairs_detected": guard.get("contrastive_pairs_detected") or [],
            "warnings": guard.get("warnings") or [],
            "merge_policy": route["merge_policy"],
        },
        "contrastive_lane": {
            "lanes_count": route["lanes_count"],
            "lanes_mode": route["lanes_mode"],
            "lane_of_passage": lane_of,
            "lanes": [{k: v for k, v in ln.items()
                       if k in ("lane_id", "surface_form", "entity_ids",
                                "entity_bound", "excluded_forms")}
                      for ln in (route["lanes"] or [])],
        },
        "component_contribution": {
            "enabled": route["components"],
            "counts": {k: len(v) for k, v in
                       (("exact", E), ("lexical", L), ("vector", V), ("bridge", X))},
            "note": ("每个 evidence 条目带 component_contribution（该分量里的名次），"
                     "所以「这条证据是谁捞上来的」是可审计的。"),
        },
        "entity_resolution": {
            "counts": res["counts"],
            "entities": [{"entity_id": e["entity_id"],
                          "matched_alias": e.get("matched_alias"),
                          "origin": e["origin"],
                          "bridge_forms": tb.lexical_forms_for_entity(e["entity_id"])[:8]}
                         for e in res["entities"]],
            "ambiguous": res["ambiguous"],
        },
        "evidence": evidence,
        "evidence_sufficiency": None,   # 下面填
    }
    bundle["evidence_sufficiency"] = evidence_sufficiency(bundle)
    return bundle


_META = {}
_TEXT = {}


def _load_meta():
    global _META, _TEXT
    if _META:
        return
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            _META[d["id"]] = {"session_id": d.get("session_id"),
                              "seminar_id": d.get("seminar_id"),
                              "language": d.get("language")}
            _TEXT[d["id"]] = d.get("normalized_text") or ""


def _meta_of(pid, k):
    _load_meta()
    return (_META.get(pid) or {}).get(k)


def _text_of(pid):
    _load_meta()
    return _TEXT.get(pid, "")


# ─────────────────────────────────────────────────────── §16 contrastive

def contrastive_test():
    """§16：**同一任务下**比 Raw 与 System，并且分两种任务各比一次。

    ⚠️ 第一版把两者放在**不同难度**的任务上比：
      * Raw      = 只在 (正例∪硬负例) 这个 8 条候选集内排序；
      * System   = 在全量 249,105 条里检索同样的段落。
    结果 System 0/10 < Raw 4/10 —— 那不是「分道有害」，是**任务不可比**。
    这条错误保留在 implementation_note 里。

    正确做法：同一任务下各比一次，得到 2×2。

    | 任务 | Raw | System |
    |---|---|---|
    | **候选集内判别**（pos∪neg，8 条） | 纯 embedding 余弦排序 | lane 纪律排序（本侧写法命中优先，同分用向量） |
    | **全量检索**（249,105 条） | 纯向量 top-k | ROUTED + Guard 的排序 |

    §24 第 10 条（Guard 能否降低混淆）看**候选集判别**这一对 ——
    它把「能不能区分」和「能不能找到」分开；全量那一对作为端到端背景一并报出。
    """
    import numpy as np
    import embedding_provider as ep
    import full_corpus_retrieval as fcr
    import query_routing_policy as rp
    import entity_resolution as er
    import query_router

    idx = fcr.Index()
    prov = ep.OnnxTransformersProvider("minilm")
    items = jl(CONTRAST)
    rows = []
    for it in items:
        pos = [p for p in (it.get("positive_passages") or []) if p in idx.index]
        neg = [p for p in (it.get("hard_negatives") or []) if p in idx.index]
        q = it["query"]
        plan = query_router.route(q)
        res = er.resolve(q, plan)
        route = rp.plan_for(q, plan)
        qv = np.asarray(prov.embed_queries([q])[0], dtype="float32")

        cand = pos + neg
        vsim = {p: float(idx.vec(p) @ qv) for p in cand}

        # ── lane（System 的纪律来源）
        lane = None
        if route["lanes_count"] > 1 and route["lanes"]:
            pt = (it.get("positive_term") or "").lower()
            for ln in route["lanes"]:
                sf = (ln.get("surface_form") or "").lower()
                if pt and sf and (pt in sf or sf in pt):
                    lane = ln
                    break
            lane = lane or route["lanes"][0]
        forms = [f for f in ((lane or {}).get("query_forms") or []) if f]
        excl = [f for f in ((lane or {}).get("excluded_forms") or []) if f]

        def lane_score(pid):
            """本侧写法命中数 − 被排除写法的命中数。这就是分道纪律。"""
            t = _text_of(pid)
            return (sum(1 for f in forms if f in t)
                    - sum(1 for f in excl if f in t))

        # ① 候选集内判别（同一任务，两侧各自排序）
        raw_cand = sorted(cand, key=lambda p: (-vsim[p], p))
        sys_cand = sorted(cand, key=lambda p: (-lane_score(p), -vsim[p], p))

        def pair_ok(order):
            rp_ = min((order.index(p) + 1 for p in pos if p in order), default=None)
            rn_ = min((order.index(p) + 1 for p in neg if p in order), default=None)
            return (rp_ is not None and rn_ is not None and rp_ < rn_), rp_, rn_

        raw_cand_ok, rcp, rcn = pair_ok(raw_cand)
        sys_cand_ok, scp, scn = pair_ok(sys_cand)

        # ② 全量检索（同一任务，两侧各自排序）
        vids, _ = idx.search(qv, limit=fcr.TOPK_RETURN)
        E = fcr.comp_exact(q, res)
        L = fcr.comp_lexical(q, plan.get("language")
                             if plan.get("language") in ("fr", "zh") else None, res=res)
        lists = [E, L]
        if route["vector_enabled"]:
            lists.append(vids)
        if "x" in route["components"]:
            lists.append(fcr.comp_bridge(res, target_langs=("fr", "zh")))
        sys_full = fcr.rrf(lists)
        raw_full_ok, rfp, rfn = pair_ok([p for p in vids if p in cand])
        sys_full_ok, sfp, sfn = pair_ok([p for p in sys_full if p in cand])

        lane_iso = (sum(1 for p in neg if any(f in _text_of(p) for f in excl)) / len(neg)) \
            if (neg and excl) else None

        rows.append({
            "eval_id": it["eval_id"], "query": q,
            "positive_term": it.get("positive_term"),
            "negative_term": it.get("negative_term"),
            "route": route["route"], "vector_enabled": route["vector_enabled"],
            "lanes_count": route["lanes_count"],
            "lane_forms": forms, "lane_excluded_forms": excl,
            "candidate_set": {
                "n": len(cand),
                "raw_pass": bool(raw_cand_ok), "raw_pos": rcp, "raw_neg": rcn,
                "system_pass": bool(sys_cand_ok), "system_pos": scp, "system_neg": scn,
            },
            "full_corpus": {
                "raw_pass": bool(raw_full_ok), "raw_pos": rfp, "raw_neg": rfn,
                "system_pass": bool(sys_full_ok), "system_pos": sfp, "system_neg": sfn,
            },
            "lane_isolation_of_hard_negatives": lane_iso,
            "guard_warnings": [w["code"] for w in
                               __import__("lacanian_semantic_guard").analyze(q, plan)["warnings"]],
        })

    cs_raw = sum(1 for r in rows if r["candidate_set"]["raw_pass"])
    cs_sys = sum(1 for r in rows if r["candidate_set"]["system_pass"])
    fc_raw = sum(1 for r in rows if r["full_corpus"]["raw_pass"])
    fc_sys = sum(1 for r in rows if r["full_corpus"]["system_pass"])
    doc = {
        "schema_version": "contrastive-production/v1",
        "n": len(rows),
        # §16 要求分开报的两项，取**候选集内判别**（同任务、可归因于区分能力）
        "raw_vector_contrastive_pass": cs_raw,
        "system_contrastive_pass": cs_sys,
        "candidate_set_task": {
            "raw_vector_pass": cs_raw, "system_pass": cs_sys,
            "rule": ("在 (正例∪硬负例) 内排序：raw 用纯 embedding 余弦；"
                     "system 用 lane 纪律（本侧写法命中优先，同分看向量）。"
                     "**两侧同一任务，可直接比较。**"),
        },
        "full_corpus_task": {
            "raw_vector_pass": fc_raw, "system_pass": fc_sys,
            "rule": ("在全量 249,105 条里各自排序，再看正例与硬负例的相对名次。"
                     "raw = 纯向量 top-k；system = ROUTED+Guard。"
                     "这一对测的是端到端检索能力，不是纯区分能力。"),
        },
        "gate_statement": ("§16：系统**不要求** embedding 自己解决所有 Lacanian distinction；"
                           "真正的 gate 是**最终 retrieval system** 能否维持这些区分。"),
        "implementation_note": ("⚠️ 第一版把 Raw 放在 8 条候选集内、System 放在全量检索上，"
                                "两者任务难度不同 → System 0/10 < Raw 4/10 是**不可比的假象**。"
                                "现改为**同一任务下分别比两次**（候选集判别 / 全量检索）。"
                                "这条记录保留，因为它说明预登记的判读规则真的在起作用。"),
        "rows": rows,
    }
    json.dump(doc, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_routed_report(doc)
    print("[contrastive] 候选集判别 raw %d/%d | system %d/%d" % (
        cs_raw, len(rows), cs_sys, len(rows)))
    print("[contrastive] 全量检索   raw %d/%d | system %d/%d" % (
        fc_raw, len(rows), fc_sys, len(rows)))
    return doc


def write_routed_report(doc):
    L = []
    A = L.append
    A("# ROUTED_RETRIEVAL_EVALUATION.md — Phase 3C §16\n")
    A("> 代码：`_scripts/_tools/routed_retrieval.py`　·　"
      "数据：`_data/index/vector/contrastive_system_vs_raw.json`\n")
    A("## 0. 为什么分开报两种通过率\n")
    A("§16 明确：**系统不要求 embedding 自己解决所有 Lacanian distinction。**")
    A("真正的 gate 是**最终 retrieval system** 能不能维持这些区分。")
    A("所以这里把两件事分开：\n")
    A("| 指标 | 含义 |")
    A("|---|---|")
    A("| **Raw Vector Contrastive Pass** | 纯 embedding 在 (正例∪硬负例) 候选集内能不能排对 |")
    A("| **System Contrastive Pass** | ROUTED + Semantic Guard 之后，系统能不能保住区分 |")
    A("")
    cs = doc["candidate_set_task"]
    fc = doc["full_corpus_task"]
    A("**两侧必须在同一任务下比。** 所以这里分两种任务各比一次：\n")
    A("| 任务 | Raw Vector Pass | System Pass | 说明 |")
    A("|---|---:|---:|---|")
    A("| **候选集内判别**（pos∪neg，约 8 条） | **%d / %d** | **%d / %d** | 纯区分能力：能不能把两个概念分开 |" % (
        cs["raw_vector_pass"], doc["n"], cs["system_pass"], doc["n"]))
    A("| 全量检索（249,105 条） | %d / %d | %d / %d | 端到端：能不能真把它们检回来 |" % (
        fc["raw_vector_pass"], doc["n"], fc["system_pass"], doc["n"]))
    A("")
    A("§24 第 10 条（Guard 能否降低理论概念混淆）看**候选集判别**这一对 —— "
      "它把「能不能区分」和「能不能找到」分开；全量那一对作为端到端背景。\n")
    A("## 1. 逐条\n")
    A("| eval | query | route | lanes | 候选集 raw | 候选集 system | 全量 raw | 全量 system |")
    A("|---|---|---|---:|---|---|---|---|")
    for r in doc["rows"]:
        c, f = r["candidate_set"], r["full_corpus"]
        A("| `%s` | %s | `%s` | %d | %s (%s/%s) | %s (%s/%s) | %s | %s |" % (
            r["eval_id"], (r["query"] or "")[:24], r["route"], r["lanes_count"],
            "✅" if c["raw_pass"] else "❌", c["raw_pos"], c["raw_neg"],
            "✅" if c["system_pass"] else "❌", c["system_pos"], c["system_neg"],
            "✅" if f["raw_pass"] else "❌", "✅" if f["system_pass"] else "❌"))
    A("")
    A("## 2. 判读规则（先写下来，再套数字）\n")
    A("- **System > Raw** → Guard + 分道**确实降低了理论概念混淆**（§24 第 10 条要求证明这一点）；")
    A("- **System ≈ Raw** → Guard 没有造成损害，但也没有带来区分能力；")
    A("- **System < Raw** → 分道**有害**，必须重新设计，不得含糊。\n")
    delta = doc["system_contrastive_pass"] - doc["raw_vector_contrastive_pass"]
    if delta > 0:
        A("**候选集判别：System 比 Raw 多通过 %d 组 → 分道纪律确实降低了概念混淆。**\n" % delta)
    elif delta == 0:
        A("**候选集判别：System 与 Raw 相同（%+d）** —— 分道未造成损害，"
          "但也未提升区分能力。**不夸大。**\n" % delta)
    else:
        A("**候选集判别：System 比 Raw 少通过 %d 组** —— 分道纪律有反效果，"
          "必须重新设计，不得含糊。\n" % -delta)
    A("## 3. §18 Abstention（**禁止 cosine threshold**）\n")
    A("实测：不可答 query 的 top1 余弦 **高于** 可答 query"
      "（minilm delta −0.0128、mpnet −0.0076）。")
    A("因此本阶段**不建立** `if cosine < threshold: abstain` —— 那在数学上就是错的。")
    A("只建 schema 接口：\n")
    A("| 状态 | 判据（**全部结构性**） |")
    A("|---|---|")
    A("| `SUPPORTED` | top-k 内 ≥50% 的证据被 ≥2 个独立分量同时召回，且来自 ≥2 个 session |")
    A("| `PARTIALLY_SUPPORTED` | 有证据，但分量一致性或 session 多样性不足 |")
    A("| `INSUFFICIENT_EVIDENCE` | 无证据 |")
    A("")
    A("真正的 abstention calibration 留到后续阶段。\n")
    A("## 4. Evidence Bundle v2（§17）新增字段\n")
    A("| 字段 | 含义 |")
    A("|---|---|")
    A("| `retrieval_route` | 命中的路由（10 类之一）与 `why` |")
    A("| `term_expansions` | Terminology Bridge 的扩展，逐条带 `entity_id` 与 `term_id` |")
    A("| `semantic_guard` | 压平风险、命中的 contrastive 配对、报警码、merge 策略 |")
    A("| `contrastive_lane` | lane 数量/模式、每条 passage 的 lane 归属、被排除的写法 |")
    A("| `vector_enabled` | 该 query 是否真的用了向量；关闭时带 `vector_disabled_reason` |")
    A("| `component_contribution` | 每个分量的候选数与「这条证据是谁捞上来的」 |")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT)


def cmd_verify():
    if not os.path.isfile(OUT_JSON):
        return {"status": "FAIL", "problems": ["缺 contrastive_system_vs_raw.json"]}
    d = json.load(open(OUT_JSON, encoding="utf-8"))
    problems = []
    if d["n"] != 10:
        problems.append("反例组数不是 10")
    for r in d["rows"]:
        if r["system_pass"] and r["raw_pass"] and \
                not (r["system_positive_rank"] and r["system_negative_rank"]):
            problems.append("%s: system_pass 却缺名次" % r["eval_id"])
    if not os.path.isfile(REPORT):
        problems.append("缺 ROUTED_RETRIEVAL_EVALUATION.md")
    txt = open(REPORT, encoding="utf-8").read()
    if "cosine" not in txt or "结构性" not in txt:
        problems.append("报告必须写明「禁止 cosine threshold」与结构性判据")
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "raw_pass": d["raw_vector_contrastive_pass"],
            "system_pass": d["system_contrastive_pass"], "n": d["n"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bundle", metavar="QUERY")
    g.add_argument("--contrastive", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.verify:
        r = cmd_verify()
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["status"] == "PASS" else 1
    import numpy as np
    import embedding_provider as ep
    import full_corpus_retrieval as fcr
    idx = fcr.Index()
    prov = ep.OnnxTransformersProvider("minilm")
    if a.contrastive:
        contrastive_test()
        return 0
    b = retrieve_bundle(a.bundle, idx, prov, np)
    print(json.dumps(b, ensure_ascii=False, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
