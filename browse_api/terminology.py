#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browse_api.terminology — Terminology Explorer（Phase 4D.4 §27–§32）

本视图存在的**唯一理由**：把三件长期被混在一起的事拆开显示 ——

    Mapping         本体层面：某形式被映射到某个 entity（可能仍是 candidate）
    Attestation     语料层面：这个字面形式在 249,105 段里真的出现了几次（0 就写 0）
    Interpretation  解释层面：**默认不生成**；只有用户主动发起研究才由冻结核心产出

铁律：
    * 「有 mapping」**不等于**「语料里出现过」（§29/§33）；
    * 同义词不做 alias collapse（§32：`le Réel` 与 `réalité` 是两个 entity）。
"""
from __future__ import annotations

from . import cursors as CU
from . import store as S

DEFAULT_LIMIT = 25
MAX_LIMIT = 50


def _mappings_by_entity():
    out: dict = {}
    for rec in S.ontology_term_mappings():
        out.setdefault(rec.get("entity_id"), []).append(rec)
    return out


def _catalog_aliases_by_entity():
    out: dict = {}
    for rec in S.catalog_concepts():
        cid = rec.get("id")
        if not cid:
            continue
        forms = []
        for k in ("canonical_name", "fr", "zh", "en"):
            if rec.get(k):
                forms.append({"form": rec[k], "origin": "catalog." + k})
        for a in rec.get("aliases") or []:
            forms.append({"form": a, "origin": "catalog.aliases"})
        out[cid] = forms
    return out


def term_index():
    """→ [{term, entity_id, label, mapping_status, source, attestation}]（每个形式一条）。"""
    idx = S.concept_index()
    maps = _mappings_by_entity()
    cat = _catalog_aliases_by_entity()
    rows = []
    for cid, item in sorted(idx.items()):
        ont_maps = maps.get(cid, [])
        seen = set()
        for form in item.get("forms") or []:
            key = S.fold(form["form"])
            if not key or key in seen:
                continue
            seen.add(key)
            rel = [m for m in ont_maps if S.fold(m.get("source_form")) == key]
            rows.append({
                "term": form["form"],
                "term_folded": key,
                "entity_id": cid,
                "label": item.get("preferred_label"),
                "layer": "ontology" if form["source"].startswith("ontology") else "catalog",
                "form_source": form["source"],
                "mapping": ([{"target_form": m.get("target_form"),
                              "source_language": m.get("source_language"),
                              "review_status": m.get("review_status"),
                              "status": m.get("status"),
                              "relation_type": m.get("relation_type"),
                              "mapping_id": m.get("mapping_id"),
                              "note": m.get("note"),
                              "source": "ontology.v4a1.term_mappings"}
                             for m in rel] or
                            ([{"target_form": None, "review_status": None,
                               "source": "catalog.alias (no reviewed mapping record)",
                               "note": "该形式只是 catalog 里的别名，**没有**受控映射记录。",
                               "mapping_id": None, "status": None,
                               "relation_type": None, "source_language": None}]
                             if cat.get(cid) else [])),
                "has_reviewed_mapping": any(
                    str(m.get("review_status") or "").lower() in ("reviewed", "approved")
                    for m in rel),
                "entity": {
                    "concept_id": cid,
                    "preferred_label": item.get("preferred_label"),
                    "review_status": item.get("review_status"),
                    "layers": list(item["layers"]),
                },
            })
    rows.sort(key=lambda r: (r["term_folded"], r["entity_id"]))
    return rows


def list_terminology(query=None, cursor=None, limit=DEFAULT_LIMIT):
    rows = term_index()
    q = S.fold(query) if query else None
    if q:
        rows = [r for r in rows if q in r["term_folded"] or q in S.fold(r["label"])]
    total = len(rows)
    keys = CU.decode(cursor, "terminology", {"q": query}) if cursor else None
    if keys:
        rows = [r for r in rows if (r["term_folded"], r["entity_id"]) > tuple(keys)]
    page = rows[:limit]
    has_more = len(rows) > limit
    next_key = ([page[-1]["term_folded"], page[-1]["entity_id"]]
                if has_more and page else None)
    return {"kind": "terminology", "query": query, "items": page, "total": total,
            "page": CU.page_meta("terminology", {"q": query}, limit, len(page),
                                 has_more, next_key=next_key, total=total),
            "zones": ["Mapping", "Attestation", "Interpretation"],
            "zones_note": ("Mapping = ontology; Attestation = corpus; Interpretation = "
                           "only produced by an explicit research call.")}


def get_term_view(term, attestation_forms=None):
    """§28–§32：术语详情（Mapping / Attestation / Interpretation 三块）。"""
    q = S.fold(term)
    if not q:
        return None
    rows = term_index()
    exact = [r for r in rows if r["term_folded"] == q or S.fold(r["label"]) == q]
    partial = [r for r in rows if r not in exact and q in r["term_folded"]]
    matches = exact + partial
    if not matches:
        return None
    entities = []
    for r in matches:
        if r["entity_id"] not in [e["concept_id"] for e in entities]:
            entities.append({**r["entity"], "matched_form": r["term"],
                             "match_kind": "exact" if r in exact else "partial"})
    forms = {}
    for r in matches:
        forms.setdefault(r["term"], {"form": r["term"], "entity_id": r["entity_id"],
                                     "mapping": r["mapping"],
                                     "has_reviewed_mapping": r["has_reviewed_mapping"]})
    for extra in (attestation_forms or []):
        forms.setdefault(str(extra), {"form": str(extra), "entity_id": None,
                                      "mapping": [], "has_reviewed_mapping": False})
    attestation = []
    for form, meta in sorted(forms.items()):
        a = S.attestation(form)
        # 同一 entity 的其它写法：这是**别名共指**（catalog 层），
        # 不是受控映射记录，因此单独给字段、单独标注来源。
        co = []
        if meta.get("entity_id"):
            for r in rows:
                if r["entity_id"] == meta["entity_id"] and r["term"] != form:
                    co.append(r["term"])
        attestation.append({**meta, "hits": a["hits"], "zero": a["hits"] == 0,
                            "attestation_mode": a["mode"], "co_forms": co[:12]})
    attestation.sort(key=lambda x: (x["hits"] == 0, -x["hits"], x["form"]))
    idx = S.concept_index()
    rels = S.relations_view(entities[0]["concept_id"]) if len(entities) == 1 else None
    distinct = []
    for e in entities:
        other = [r for r in (S.relations_by_concept().get(e["concept_id"]) or [])
                 if r.get("predicate") in ("distinct_from", "distinguished_from")]
        for r in other:
            oid = r["object"] if r["subject"] == e["concept_id"] else r["subject"]
            distinct.append({"predicate": r.get("predicate"), "subject": r.get("subject"),
                             "object": r.get("object"),
                             "other_label": (idx.get(oid) or {}).get("preferred_label"),
                             "review_status": r.get("review_status"),
                             "note": (r.get("evidence") or {}).get("note")})
    return {
        "kind": "term",
        "query": term,
        "ambiguous": len(entities) > 1,
        "entities": entities,
        "mapping": {
            "rows": [{"form": f["form"], "entity_id": f["entity_id"],
                      "mapping": f["mapping"],
                      "has_reviewed_mapping": f["has_reviewed_mapping"]}
                     for f in attestation],
            "source": "ontology.v4a1.term_mappings + catalog aliases",
            "warning": ("A mapping record means the ontology maps this form to an entity. "
                        "It does NOT mean the corpus attests the form."),
        },
        "attestation": {
            "rows": attestation,
            "source": "corpus.form-attestation",
            "label": "corpus attestation — NOT ontology evidence",
            "mode": "deterministic substring count over the full corpus",
            "warning": ("Exact-form attestation only. Zero stays zero — nothing falls "
                        "back to another form or layer."),
            "zero_forms": [r["form"] for r in attestation if r["zero"]],
        },
        "interpretation": {
            "generated": False,
            "answer": None,
            "note": ("Interpretation is never generated by the Explorer. It is produced "
                     "only by an explicit research call to the frozen scholarly core."),
            "action": {"id": "translation_research",
                       "label": "Research translation differences",
                       "tool": "lacan.research_translation", "mode": "translation_terminology",
                       "request": {"term": entities[0]["preferred_label"]}},
        },
        "distinct_from": distinct,
        "relations": rels,
        "no_alias_collapse_note": (
            "Multiple entities may match one written form; they are listed separately "
            "and are never merged into a single term."),
    }


def reel_realite_control():
    """§32 验收例：`le Réel` 与 `réalité` 必须是**两个** entity，且不得 alias collapse。"""
    reel = get_term_view("Réel", attestation_forms=["实在界", "现实"])
    realite = get_term_view("réalité")
    out = {
        "case": "Réel / réalité control",
        "reel": _slim(reel),
        "realite": _slim(realite),
    }
    ids_reel = {e["concept_id"] for e in (reel or {}).get("entities", [])}
    ids_realite = {e["concept_id"] for e in (realite or {}).get("entities", [])}
    out["distinct_entities"] = bool(ids_reel and ids_realite and not (ids_reel & ids_realite))
    out["reel_entities"] = sorted(ids_reel)
    out["realite_entities"] = sorted(ids_realite)
    out["collapsed"] = bool(ids_reel & ids_realite)
    out["note"] = ("le Réel / réalité are separate entities; writing them as one alias "
                   "would be an alias collapse and is refused.")
    return out


def _slim(view):
    if not view:
        return None
    return {"query": view["query"], "entities": view["entities"],
            "attestation": [{"form": r["form"], "hits": r["hits"], "zero": r["zero"]}
                            for r in view["attestation"]["rows"]],
            "zero_forms": view["attestation"]["zero_forms"],
            "ambiguous": view["ambiguous"]}
