#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browse_api.concepts — Concept Explorer 的只读视图（Phase 4D.4 §5–§8/§45/§46）

纪律（§7/§33/§34/§66）：
    * Canonical Reference 只展示 canonical ontology 里**已经记着**的东西；
      ontology 没写定义就显示 `No canonical definition recorded.` ——
      绝不让 LLM 临时生造一个「定义」冒充 canonical。
    * Relations 分 reviewed / candidate 两组；candidate **不混入** canonical graph。
    * Corpus attestation（语料里出现多少次）与 ontology（本体里记了什么）分别标注。
    * 0 结果只表示「当前 browse 条件下没有匹配段落」，不是「拉康没有这个概念」。
"""
from __future__ import annotations

from . import cursors as CU
from . import store as S

MAX_LIMIT = 50
DEFAULT_LIMIT = 25


def _form_count(item, limit=3):
    """给列表页用的 attestation 摘要（只算前几个形式，避免全表扫描太多）。"""
    out = []
    for f in (item.get("forms") or [])[:limit]:
        a = S.attestation(f["form"])
        out.append({"form": f["form"], "source": f["source"], "hits": a["hits"]})
    return out


def list_concepts(query=None, status=None, layer=None, cursor=None, limit=DEFAULT_LIMIT,
                  with_counts=False):
    """§6：概念列表（search / preferred label / aliases / status / 计数），分页。

    `with_counts=False` 时不逐行做语料 attestation —— 那是对全表做子串计数，
    放在列表页会让 25 行变成几十次全表扫描。列表只给**记录层面**的计数
    （seminars_n / relations_n / ontology_evidence_n），语料计数在详情页给。
    """
    idx = S.concept_index()
    rels = S.relations_by_concept()
    q = S.fold(query) if query else None
    items = []
    for cid, item in sorted(idx.items()):
        if layer and layer not in item["layers"]:
            continue
        if status and str(item.get("review_status") or "") != status:
            continue
        if q:
            hay = " ".join([cid, str(item.get("preferred_label") or "")]
                           + [f["form"] for f in item.get("forms") or []])
            if q not in S.fold(hay):
                continue
        seminars = _seminar_ids_for(item)
        row = {
            "concept_id": cid,
            "preferred_label": item.get("preferred_label"),
            "aliases": [f["form"] for f in (item.get("forms") or [])][:8],
            "alias_n": len(item.get("forms") or []),
            "layers": list(item["layers"]),
            "review_status": item.get("review_status"),
            "canonical": item.get("canonical"),
            "ontology_status": item.get("ontology_status"),
            "entity_role": item.get("entity_role"),
            "relations_n": len(rels.get(cid) or []),
            "reviewed_relations_n": len([r for r in (rels.get(cid) or [])
                                         if S._rel_status_bucket(r) == "reviewed"]),
            "seminars_n": len(seminars),
            "ontology_evidence_n": item.get("evidence_n") or 0,
        }
        items.append(row)
    items.sort(key=lambda r: (str(r["preferred_label"]).casefold(), r["concept_id"]))
    total = len(items)
    keys = CU.decode(cursor, "concepts", {"q": query, "status": status, "layer": layer}) \
        if cursor else None
    if keys:
        items = [r for r in items if r["concept_id"] > keys]
    page_items = items[:limit]
    has_more = len(items) > limit
    next_key = page_items[-1]["concept_id"] if (has_more and page_items) else None
    # 计数：列表页只做**小规模** attestation 摘要（上限 3 个形式）
    if with_counts:
        for row in page_items:
            row["attestation_sample"] = _form_count(idx[row["concept_id"]])
    return {
        "kind": "concepts", "query": query, "items": page_items, "total": total,
        "page": CU.page_meta("concepts", {"q": query, "status": status, "layer": layer},
                             limit, len(page_items), has_more, next_key=next_key,
                             total=total),
        "counts_note": ("seminars_n / relations_n 来自 ontology 与 catalog 的记录；"
                        "attestation_sample 是语料里**字面形式**的出现次数，"
                        "两者不是一回事（§33）。"),
    }


def _seminar_ids_for(item):
    out = set()
    for pid in item.get("evidence_passages") or []:
        sid = S.seminar_of_passage(pid)
        if sid:
            out.add(sid)
    return sorted(out)


def get_concept_view(concept_id, evidence_limit=20):
    """§7：Concept Detail（Header / Canonical Reference / Relations / Evidence /
    Seminar Distribution / Diachronic View）。"""
    idx = S.concept_index()
    item = idx.get(str(concept_id))
    if not item:
        return None
    ont = item["records"].get("ontology") or {}
    cat = item["records"].get("catalog") or {}
    rel = S.relations_view(item["concept_id"])
    forms = item.get("forms") or []
    attestation = [dict(S.attestation(f["form"]), source=f["source"],
                        language=f.get("language")) for f in forms[:12]]
    for a in attestation:
        a["zero"] = a["hits"] == 0
    definition = ont.get("definition") or cat.get("definition")
    return {
        "kind": "concept",
        "header": {
            "concept_id": item["concept_id"],
            "preferred_label": item.get("preferred_label"),
            "aliases": [f["form"] for f in forms],
            "forms": forms,
            "ontology_status": item.get("ontology_status"),
            "ontology_version": item.get("ontology_version"),
            "review_status": item.get("review_status"),
            "canonical": item.get("canonical"),
            "layers": list(item["layers"]),
            "entity_role": item.get("entity_role"),
            "authority_level": item.get("authority_level"),
            "fr": item.get("fr"), "zh": item.get("zh"), "en": item.get("en"),
        },
        "canonical_reference": {
            "canonical_definition": definition,
            "definition_status": item.get("definition_status"),
            "empty_note": (None if definition else "No canonical definition recorded."),
            "source_layer": ("ontology.v4a1.definition" if ont.get("definition")
                             else ("catalog.definition" if cat.get("definition") else None)),
            "usage_note": ont.get("usage_note") or cat.get("usage_note"),
            "misreadings": ont.get("misreadings") or cat.get("misreadings"),
            "note": ("Only what the canonical ontology already records is shown here. "
                     "No definition is generated on the fly."),
        },
        "relations": {**rel, "note": ("reviewed relations come from the canonical "
                                      "ontology layer; candidates are shown separately "
                                      "and are never drawn into the canonical graph.")},
        "evidence": _evidence(item, evidence_limit),
        "attestation": {
            "items": attestation,
            "source": "corpus.form-attestation",
            "mode": "substring count over the full corpus (deterministic)",
            "label": "corpus attestation — NOT ontology evidence",
        },
        "seminar_distribution": _distribution(item),
        "diachronic": _diachronic(item),
        "states": _states(item["concept_id"]),
        "research_actions": [
            {"id": "research", "label": "Research this concept",
             "tool": "lacan.research", "mode": "concept_definition",
             "request": {"question": "请给出 %s 的工作定义、关键区分与语料证据。"
                         % item.get("preferred_label")}},
            {"id": "compare", "label": "Compare",
             "tool": "lacan.compare_terms", "mode": "concept_relation",
             "request": {"term_a": item.get("preferred_label")}},
            {"id": "diachronic", "label": "Research diachronically",
             "tool": "lacan.research_diachronic", "mode": "diachronic",
             "request": {"concept": item.get("preferred_label")}},
            {"id": "translation", "label": "Translation research",
             "tool": "lacan.research_translation", "mode": "translation_terminology",
             "request": {"term": item.get("preferred_label")}},
        ],
        "note": ("0 browse results mean 'no matching passages under the current browse "
                 "filters', not 'Lacan does not have this concept'."),
    }


def _evidence(item, limit):
    ids = list(item.get("evidence_passages") or [])
    return {
        "mode": "ontology.evidence" if ids else "none",
        "ontology_evidence_n": item.get("evidence_n") or 0,
        "sample": ids[:limit],
        "sample_truncated": len(ids) > limit,
        "label": ("passages recorded in the canonical ontology for this concept"
                  if ids else "the ontology records no passage evidence for this concept"),
    }


def _distribution(item):
    from . import passages as P                                    # noqa: PLC0415
    return P.seminar_distribution(item["concept_id"])


def _diachronic(item):
    from . import passages as P                                    # noqa: PLC0415
    return P.diachronic_view(item["concept_id"])


def _states(concept_id):
    out = []
    for rec in S.catalog_states():
        if rec.get("concept_id") == concept_id or rec.get("id", "").find(
                concept_id.split(".", 1)[-1]) >= 0:
            out.append({"state_id": rec.get("id"), "period": rec.get("period"),
                        "period_label": rec.get("period_label"),
                        "definition": rec.get("definition"),
                        "review_status": rec.get("review_status")})
    out.sort(key=lambda r: str(r.get("period") or ""))
    return out


def concept_graph(concept_id, max_nodes=25):
    """§45/§46：1-hop 小型图，**只用 reviewed relations**；每条 edge 可解释。"""
    view = get_concept_view(concept_id, evidence_limit=0)
    if view is None:
        return None
    nodes = {concept_id: {"id": concept_id,
                          "label": view["header"]["preferred_label"],
                          "role": "selected"}}
    edges = []
    idx = S.concept_index()
    candidate_edges = []
    for rel in view["relations"]["candidate"]:
        candidate_edges.append({"from": (concept_id if rel["direction"] == "out"
                                         else rel["other_id"]),
                                "to": (rel["other_id"] if rel["direction"] == "out"
                                       else concept_id),
                                "predicate": rel["predicate"],
                                "review_status": rel["review_status"],
                                "ontology_source": rel["ontology_source"],
                                "evidence": rel.get("evidence"),
                                "relation_id": rel["relation_id"],
                                "drawn": False})
    for rel in view["relations"]["reviewed"][:max_nodes]:
        other = rel["other_id"]
        nodes.setdefault(other, {"id": other,
                                 "label": (idx.get(other) or {}).get("preferred_label")
                                 or other, "role": "related"})
        edges.append({"from": rel["subject"] if rel.get("direction") == "out" else other,
                      "to": other if rel.get("direction") == "out" else rel["subject"],
                      "predicate": rel["predicate"],
                      "review_status": rel["review_status"],
                      "ontology_source": rel["ontology_source"],
                      "evidence": rel.get("evidence"),
                      "relation_id": rel["relation_id"]})
    return {"concept_id": concept_id, "nodes": list(nodes.values())[:max_nodes],
            "edges": edges,
            "candidate_edges": candidate_edges,
            "candidate_edges_n": len(candidate_edges),
            "note": ("Only reviewed relations are drawn. Candidate relations are "
                     "counted but not drawn, so the graph never mixes candidate "
                     "material into the canonical view."),
            "empty_note": (None if edges else
                           "No reviewed canonical relation recorded for this concept.")}
