#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
query_routing_policy.py — Phase 3C §8–§10 Query-Class-Aware Retrieval Routing

为什么要它
──────────
Phase 3B.2 实测：**向量不是普适增益**。

| query class | 最佳配置 | 说明 |
|---|---|---|
| FR 单语 | `L` 0.3125 > `E+L+V` 0.2500 | 向量**负贡献** |
| ZH→FR | 必须带 `X` | 纯向量 0.0000 |

所以「所有 query 都跑 E+L+V+X」是错的。§9 要求一张正式 routing table，
§10 要求 `vector_enabled = false` 是一等能力，并且要有
`vector_weight` / `vector_candidate_limit`。

设计原则
────────
* **规则可读、可审计**：每条 route 都带 `why`（哪条规则命中），不是黑箱打分。
* **不静默解析歧义**：`ambiguous_entities` 非空且无消歧线索 → `AMBIGUOUS_ENTITY`，
  返回歧义候选，**不替用户选一个**（§9 明确要求）。
* **向量可关**：`vector_enabled=False` 时下游**不得**偷偷算向量。
* **分道优先于合并**：`CONTRASTIVE_TERMINOLOGY` 与 `CONCEPT_COMPARISON`
  走多 lane，且 lane 之间不允许在 Evidence Assembly 之前混合。

用法
────
    python3 _scripts/_tools/query_routing_policy.py --route "Réel 和 réalité 有什么区别？"
    python3 _scripts/_tools/query_routing_policy.py --table      # 打印 routing table
    python3 _scripts/_tools/query_routing_policy.py --doc        # 生成 QUERY_ROUTING_POLICY.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

DOC = os.path.join(VAULT, "QUERY_ROUTING_POLICY.md")
CJK = re.compile(r"[\u4e00-\u9fff]")
ID_RE = re.compile(r"\b(?:passage|session|seminar|concept|claim|trans|witness)\.[A-Za-z0-9.\-]+")
QUOTED_RE = re.compile(r"[\"“”『』「」]([^\"“”『』「」]{3,})[\"“”『』「」]")

# ─────────────────────────────────────────────────────────────────────
# 正式 routing table（§9 的 9 类 + 歧义类）
#
# components 取值：exact / entity / lexical / vector / x / metadata / period / diversity
# vector_enabled=False 时下游不得计算向量（不是「算了但权重 0」）
# ─────────────────────────────────────────────────────────────────────
ROUTING_TABLE = {
    "EXACT_QUOTATION": {
        "components": ["exact", "lexical", "metadata"],
        "vector_enabled": False,
        "vector_weight": 0.0,
        "vector_candidate_limit": 0,
        "lanes": 1,
        "guard": False,
        "why": "查询里带引号短语 —— 用户要的是**字面出处**，语义近邻只会引入噪声",
    },
    "EXACT_SOURCE_LOOKUP": {
        "components": ["exact", "lexical", "metadata"],
        "vector_enabled": False,
        "vector_weight": 0.0,
        "vector_candidate_limit": 0,
        "lanes": 1,
        "guard": False,
        "why": "查询里出现 passage/session/seminar 等 ID —— 精确定位，向量无意义",
    },
    "FR_MONOLINGUAL": {
        "components": ["entity", "lexical", "metadata"],
        "vector_enabled": False,
        "vector_weight": 0.0,
        "vector_candidate_limit": 0,
        "lanes": 1,
        "guard": False,
        # 这一条是**实测**结论，不是先验：FR 单语 L 0.3125 > E+L+V 0.2500
        "why": "法语单语查询：Phase 3C 实测 `L` 优于含向量的配置（0.3125 vs 0.2500）→ 默认关向量",
    },
    "ZH_TO_FR": {
        "components": ["entity", "x", "lexical", "vector", "metadata"],
        "vector_enabled": True,
        "vector_weight": 0.5,
        "vector_candidate_limit": 200,
        "lanes": 1,
        "guard": False,
        "why": "中文问 → 需要法文证据：主要机制是 Terminology Bridge `X`，向量作补充",
    },
    "CONCEPTUAL_PARAPHRASE": {
        "components": ["entity", "lexical", "vector", "x"],
        "vector_enabled": True,
        "vector_weight": 0.5,
        "vector_candidate_limit": 200,
        "lanes": 1,
        "guard": False,
        "why": "概念性改写（不是问句也不是引文）：实体 + 词法 + 向量 + 跨语言桥",
    },
    "CONCEPT_COMPARISON": {
        "components": ["entity", "lexical", "vector"],
        "vector_enabled": True,
        "vector_weight": 0.4,
        "vector_candidate_limit": 100,
        "lanes": "per_concept",
        "guard": False,
        "why": "涉及 ≥2 个概念 —— **每个概念独立 lane**（§9），最后才在证据层比较",
    },
    "DIACHRONIC": {
        "components": ["entity", "lexical", "period", "diversity", "vector"],
        "vector_enabled": True,
        "vector_weight": 0.3,
        "vector_candidate_limit": 120,
        "lanes": 1,
        "guard": False,
        "why": "历时性概念问题：期号感知 + 证据多样性为主，向量只作低权重补充",
    },
    "CONTRASTIVE_TERMINOLOGY": {
        "components": ["guard", "entity", "lexical", "vector", "x"],
        "vector_enabled": True,
        "vector_weight": 0.4,
        "vector_candidate_limit": 100,
        "lanes": "per_contrastive_side",
        "guard": True,
        "why": "Semantic Guard 命中 contrastive 配对 → **禁止合并**，每侧独立 lane（§8）",
    },
    "SEMINAR_SPECIFIC": {
        "components": ["entity", "lexical", "metadata", "vector"],
        "vector_enabled": True,
        "vector_weight": 0.3,
        "vector_candidate_limit": 120,
        "lanes": 1,
        "guard": False,
        "why": "查询显式限定研讨班：精确 subset 为主，向量低权重",
    },
    "AMBIGUOUS_ENTITY": {
        "components": ["entity", "lexical"],
        "vector_enabled": False,
        "vector_weight": 0.0,
        "vector_candidate_limit": 0,
        "lanes": 1,
        "guard": False,
        "why": "实体歧义且无线索 —— **不静默解析**，返回歧义候选让用户选（§9）",
    },
    "GENERAL": {
        "components": ["entity", "lexical", "vector", "x"],
        "vector_enabled": True,
        "vector_weight": 0.4,
        "vector_candidate_limit": 150,
        "lanes": 1,
        "guard": False,
        "why": "没有命中任何专门规则的兜底路径",
    },
}


def classify(query, plan=None, guard=None, resolution=None):
    """规则式判定，**按优先级**依次尝试。返回 (route, why_fired)。

    实体判定用 `entity_resolution.resolve()`（router ∪ 中文子串扫描），
    而不是只用 `query_router` 的实体 —— 实测后者在中文句子上的解析率明显偏低
    （40 条 gold 里 14 条会漏），而漏掉实体就等于 `X` 为空。
    """
    import lacanian_semantic_guard as guard_mod
    import entity_resolution as er
    if plan is None:
        import query_router
        plan = query_router.route(query)
    if guard is None:
        guard = guard_mod.analyze(query, plan)
    if resolution is None:
        resolution = er.resolve(query, plan)

    q = query or ""
    intent = (plan or {}).get("intent")
    ents = resolution["entities"]
    amb = resolution["ambiguous"] or (plan or {}).get("ambiguous_entities") or []
    sems = (plan or {}).get("seminars") or []
    lang = (plan or {}).get("language")

    if guard["lanes_required"] >= 2:
        return "CONTRASTIVE_TERMINOLOGY", "Semantic Guard 命中 %d 组 contrastive 配对，建了 %d 条 lane" % (
            len(guard["contrastive_pairs_detected"]), guard["lanes_required"])
    if QUOTED_RE.search(q):
        return "EXACT_QUOTATION", "查询含引号短语"
    if ID_RE.search(q):
        return "EXACT_SOURCE_LOOKUP", "查询含 passage/session/seminar ID"
    if amb and not ents:
        return "AMBIGUOUS_ENTITY", "有 %d 个歧义实体且无可用线索 —— 不静默解析" % len(amb)
    if intent == "diachronic_concept":
        return "DIACHRONIC", "router intent = diachronic_concept"
    if len(ents) >= 2:
        return "CONCEPT_COMPARISON", "router 解析出 %d 个概念实体" % len(ents)
    if sems:
        return "SEMINAR_SPECIFIC", "查询显式限定研讨班 %s" % sems[:2]
    if lang == "fr":
        return "FR_MONOLINGUAL", "查询语言为法语（单语路径，实测向量负贡献）"
    # 中文（或中西混合）查询且解析出概念 → 需要法文证据。
    # 这里**不要求** router 给出具体 intent：实测中文句子的 intent 常为 `unknown`，
    # 若按 intent 白名单判定，最需要跨语言桥的那些 query 反而会掉到 GENERAL。
    if lang in ("zh", "mul") and ents:
        return "ZH_TO_FR", ("%s 查询 + 解析出 %d 个概念实体 → 需要法文原文证据"
                            "（router intent=%s）" % (lang, len(ents), intent))
    if lang in ("zh", "mul"):
        return "ZH_TO_FR", ("%s 查询（未解析出实体）—— 仍走跨语言路径，"
                            "靠词法与向量补偿" % lang)
    if intent in ("concept_definition", "conceptual_relation", "textual_reading"):
        return "CONCEPTUAL_PARAPHRASE", "概念性/改写类意图（intent=%s）" % intent
    return "GENERAL", "未命中专门规则"


def plan_for(query, plan=None):
    """→ RoutingPlan（可直接被检索器消费的可执行决策）。"""
    import lacanian_semantic_guard as guard_mod
    import entity_resolution as er
    if plan is None:
        import query_router
        plan = query_router.route(query)
    guard = guard_mod.analyze(query, plan)
    resolution = er.resolve(query, plan)
    route, why = classify(query, plan, guard, resolution)
    pol = dict(ROUTING_TABLE[route])
    lanes = []
    if pol["lanes"] == "per_contrastive_side":
        lanes = guard["lanes"]
    elif pol["lanes"] == "per_concept":
        for i, e in enumerate(resolution["entities"], 1):
            lanes.append({"lane_id": "concept.%d" % i,
                          "surface_form": e.get("matched_alias"),
                          "entity_ids": [e["entity_id"]],
                          "entity_bound": True,
                          "query_forms": [e.get("matched_alias")] or [],
                          "excluded_forms": [],
                          "exclusion_reason": "概念比较：每个概念一条 lane"})
    return {
        "policy_version": "query-routing-policy/v1",
        "query": query,
        "route": route,
        "why": why,
        "components": pol["components"],
        "vector_enabled": pol["vector_enabled"],
        "vector_weight": pol["vector_weight"],
        "vector_candidate_limit": pol["vector_candidate_limit"],
        "lanes_mode": pol["lanes"],
        "lanes": lanes,
        "lanes_count": len(lanes) or 1,
        "guard_enabled": pol["guard"],
        "guard": guard if pol["guard"] else {
            "flattening_risk": guard["flattening_risk"],
            "contrastive_pairs_detected": guard["contrastive_pairs_detected"],
            "warnings": guard["warnings"],
        },
        "merge_policy": "FORBID_MERGE" if lanes else "normal",
        "ambiguous_entities": resolution["ambiguous"],
        "router_intent": (plan or {}).get("intent"),
        "router_language": (plan or {}).get("language"),
        "router_entities": [(e["entity_id"], e.get("matched_alias"))
                            for e in resolution["router_entities"]],
        "entity_resolution": {
            "counts": resolution["counts"],
            "entities": [(e["entity_id"], e.get("matched_alias"), e["origin"])
                         for e in resolution["entities"]],
            "extra_from_scan": resolution["counts"]["extra"],
        },
        "vector_disabled_reason": None if pol["vector_enabled"] else pol["why"],
    }


def write_doc():
    L = []
    A = L.append
    A("# QUERY_ROUTING_POLICY.md — Phase 3C §9–§10\n")
    A("> 代码：`_scripts/_tools/query_routing_policy.py`　·　"
      "判定是**规则式**的，每条 route 都带 `why`（哪条规则命中），不是黑箱打分。\n")
    A("## 0. 为什么需要按 query class 路由\n")
    A("Phase 3B.2 / 3C 实测：**向量不是普适增益**。\n")
    A("| query class | 实测 | 结论 |")
    A("|---|---|---|")
    A("| FR 单语 | `L` **0.3125** > `E+L+V` 0.2500 | 向量**负贡献** → 默认关闭 |")
    A("| ZH→FR | 纯向量 **0.0000** | 主要机制是 `X`（术语桥），向量只作补充 |")
    A("")
    A("所以「所有 query 都跑 E+L+V+X」是错的。§10 明确要求 `vector_enabled=false` "
      "是一等能力，并且要有 `vector_weight` / `vector_candidate_limit`。\n")
    A("## 1. Routing table\n")
    A("| route | components | vector_enabled | weight | cand_limit | lanes | guard | 规则 |")
    A("|---|---|---:|---:|---:|---|---|---|")
    for name, p in ROUTING_TABLE.items():
        A("| `%s` | %s | %s | %s | %s | %s | %s | %s |" % (
            name, " + ".join(p["components"]),
            "✅" if p["vector_enabled"] else "**❌ 关闭**",
            p["vector_weight"], p["vector_candidate_limit"],
            p["lanes"], "✅" if p["guard"] else "—", p["why"]))
    A("")
    A("## 2. 判定优先级\n")
    A("```")
    for i, n in enumerate(["CONTRASTIVE_TERMINOLOGY（Guard 命中，最高优先）",
                           "EXACT_QUOTATION（引号）",
                           "EXACT_SOURCE_LOOKUP（ID）",
                           "AMBIGUOUS_ENTITY（歧义且无线索 → 不静默解析）",
                           "DIACHRONIC",
                           "CONCEPT_COMPARISON（≥2 概念 → 分 lane）",
                           "SEMINAR_SPECIFIC",
                           "FR_MONOLINGUAL",
                           "ZH_TO_FR",
                           "CONCEPTUAL_PARAPHRASE",
                           "GENERAL（兜底）"], 1):
        A("%2d. %s" % (i, n))
    A("```")
    A("**优先级顺序本身就是设计决定**：Guard 最高，因为一旦涉及必须区分的概念，"
      "任何「先合并再排序」的做法都会把区分弄丢；歧义解析排在精确匹配之后，"
      "因为引号和 ID 是用户显式给出的约束，不该被实体歧义挡住。\n")
    A("## 3. 向量关闭不是「算了但权重 0」\n")
    A("`vector_enabled=False` 时下游**不得计算向量**：`vector_candidate_limit = 0`，"
      "并且 `vector_disabled_reason` 会写进 Evidence Bundle。"
      "理由很实际 —— 全量索引上一次暴力余弦是几十毫秒，"
      "关掉它是真实的延迟收益，也是真实的**质量**收益（FR 单语实测）。\n")
    A("## 4. 歧义不静默解析（§9）\n")
    A("`AMBIGUOUS_ENTITY` 返回的是**歧义候选列表**，不是替用户选好的答案。"
      "实测有 42 条歧义别名（`alias_collisions.jsonl`），"
      "把其中一个静默当真会造成来源不明的结论。\n")
    A("## 5. 复现\n")
    A("```bash")
    A('python3 _scripts/_tools/query_routing_policy.py --route "Réel 和 réalité 有什么区别？"')
    A("python3 _scripts/_tools/query_routing_policy.py --table")
    A("```")
    with open(DOC, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[routing] %s" % DOC)


def coverage(paths=None):
    """§24 第 4 条要有「路由**实际运行**」的证据：把所有评测 query 都路由一遍并统计。"""
    import json as _json
    VECDIR = os.path.join(VAULT, "_data", "index", "vector")
    paths = paths or [os.path.join(VAULT, "retrieval_gold_answerable.jsonl"),
                      os.path.join(VAULT, "retrieval_gold_unanswerable.jsonl"),
                      os.path.join(VAULT, "lacan_contrastive_eval.jsonl"),
                      os.path.join(VAULT, "retrieval_gold_fr_supplement.jsonl")]
    rows, counts, vec_off, multilane = [], {}, 0, 0
    for p in paths:
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                g = _json.loads(line)
                q = g.get("query")
                if not q:
                    continue
                pl = plan_for(q)
                counts[pl["route"]] = counts.get(pl["route"], 0) + 1
                if not pl["vector_enabled"]:
                    vec_off += 1
                if pl["lanes_count"] > 1:
                    multilane += 1
                rows.append({"source": os.path.basename(p),
                             "query_id": g.get("query_id"), "route": pl["route"],
                             "vector_enabled": pl["vector_enabled"],
                             "lanes_count": pl["lanes_count"],
                             "entities": pl["entity_resolution"]["counts"]["total"]})
    doc = {
        "schema_version": "routing-coverage/v1",
        "queries_routed": len(rows),
        "distinct_routes_used": len(counts),
        "route_counts": counts,
        "vector_disabled_queries": vec_off,
        "multi_lane_queries": multilane,
        "sources": [os.path.basename(p) for p in paths if os.path.isfile(p)],
        "rows": rows,
        "note": ("这是「routing policy **实际运行**」的证据：所有评测 query 都被路由过，"
                 "且确实出现了向量关闭与多 lane 的情形。"),
    }
    os.makedirs(VECDIR, exist_ok=True)
    out = os.path.join(VECDIR, "ROUTING_COVERAGE.json")
    _json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[routing] %d 条 query / %d 种 route / 向量关闭 %d / 多 lane %d" % (
        len(rows), len(counts), vec_off, multilane))
    print("[routing] %s" % out)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--route", metavar="QUERY")
    g.add_argument("--table", action="store_true")
    g.add_argument("--doc", action="store_true")
    g.add_argument("--coverage", action="store_true")
    a = ap.parse_args(argv)
    if a.table:
        print(json.dumps({k: v for k, v in ROUTING_TABLE.items()},
                         ensure_ascii=False, indent=1))
        return 0
    if a.doc:
        write_doc()
        return 0
    if a.coverage:
        coverage()
        return 0
    print(json.dumps(plan_for(a.route), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
