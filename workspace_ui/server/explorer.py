#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui.server.explorer — Explorer 的产品适配层（Phase 4D.4 §3/§35/§36/§41）

    Explorer UI  →  explorer（本模块，产品适配）
                     ├── browse_api     只读语料/本体浏览（deterministic，无 LLM）
                     └── MCP            **仅** 在用户点 Research* 时进入冻结学术核心

本模块的职责只有三件：
    1. 把 browse_api 的结果转成 UI 视图，并**把来源标注带上**
       （ontology 事实 / corpus attestation 必须一眼可分，§33）；
    2. Research 按钮只**预填 ResearchRequest**，不自己写研究逻辑（§8/§54）；
    3. Saved Research / Open in Obsidian 复用 4D.3 的 manifest 与 adapter（§35/§36）。
"""
from __future__ import annotations

import json
import os

import browse_api as B

from . import config as C
from . import viewmodel as VM

EXPLORER_VERSION = "explorer/v1"


def _cfg(path_attr, default):
    return getattr(C, path_attr, default)


# ─────────────────────────────────────────────────────────── 可用性 / 概览
def availability():
    a = B.availability()
    return {
        "kind": "explorer_availability",
        "explorer_version": EXPLORER_VERSION,
        **a,
        "retrieval_banner": (
            "Dense semantic retrieval unavailable — lexical retrieval active."
            if not a.get("dense_available") else None),
        "corpus_total": B.corpus_total(),
        "browse_vs_research": {
            "browse": "Corpus Browse — server-side SQL over the full corpus (exhaustive)",
            "research": ("Research Retrieval — frozen scholarly core; the optional "
                         "session / source_layer / concept / formalism filters there are "
                         "applied AFTER top-k retrieval (post-filtered)"),
        },
    }


# ─────────────────────────────────────────────────────────── Concept
def concept_list(query=None, status=None, layer=None, cursor=None, limit=None):
    limit = max(1, min(int(limit or C.EXPLORER_PAGE_DEFAULT), C.EXPLORER_PAGE_MAX))
    out = B.list_concepts(query=query, status=status, layer=layer, cursor=cursor,
                          limit=limit)
    out["view"] = "concept_list"
    out["title"] = "Concepts"
    out["sources"] = {
        "ontology": "canonical ontology layer (review_status shown per row)",
        "catalog": "term catalog layer",
        "corpus": "not queried on the list page (attestation belongs to the detail page)",
    }
    return out


def concept_detail(concept_id):
    v = B.get_concept_view(concept_id, evidence_limit=C.EXPLORER_EVIDENCE_LIMIT)
    if v is None:
        return None
    v["view"] = "concept_detail"
    v["saved_research"] = saved_research_for("concept", concept_id)
    v["obsidian"] = obsidian_action("concept", concept_id)
    v["graph"] = B.concept_graph(concept_id)
    v["filters"] = _passage_filter_spec()
    return v


# ─────────────────────────────────────────────────────────── Passage
def _passage_filter_spec():
    return {
        "seminars": [{"id": s["seminar_id"], "label": s.get("title") or s["seminar_id"]}
                     for s in B.list_seminars(limit=50)["items"]],
        "languages": [{"id": "fr", "label": "Français"},
                      {"id": "zh", "label": "中文"}],
        "source_layers": [{"id": "L1", "label": "L1 primary transcription"},
                          {"id": "L2", "label": "L2 recovered"},
                          {"id": "L3", "label": "L3 editorial"},
                          {"id": "METADATA", "label": "Metadata"}],
        "provenance": [{"id": "COMPLETE", "label": "COMPLETE"},
                       {"id": "SOURCE_TRACE_INCOMPLETE", "label": "SOURCE_TRACE_INCOMPLETE"}],
        "formalism_patterns": [p[0] for p in B.store.FORMALISM_PATTERNS],
    }


def passage_search(filters=None, cursor=None, limit=None):
    limit = max(1, min(int(limit or C.EXPLORER_PAGE_DEFAULT), C.EXPLORER_PAGE_MAX))
    f = dict(filters or {})
    f["limit"] = limit
    out = B.browse_passages(f, cursor=cursor)
    out["view"] = "passage_search"
    out["filters_spec"] = _passage_filter_spec()
    out["dense_banner"] = availability()["retrieval_banner"]
    out["zero_note"] = ("No matching passages under current browse filters." if
                        not out["items"] else None)
    out["label"] = ("Corpus Browse (exhaustive SQL over %d passages) — NOT research "
                    "retrieval" % B.corpus_total())
    return out


def passage_detail(passage_id, before=None, after=None):
    p = B.get_passage_view(passage_id)
    if p is None:
        return None
    before = C.EXPLORER_CONTEXT_DEFAULT if before in (None, "") else int(before)
    after = C.EXPLORER_CONTEXT_DEFAULT if after in (None, "") else int(after)
    before = max(0, min(before, C.MAX_CONTEXT_BEFORE))
    after = max(0, min(after, C.MAX_CONTEXT_AFTER))
    ctx = B.context(passage_id, before, after) or {"items": [], "target_index": None}
    sess = B.list_sessions(p.get("seminar") or "")["items"]
    lesson = p.get("lesson")
    session_row = next((s for s in sess if s.get("lesson") == lesson), None)
    return {
        "view": "passage_detail",
        "passage": p,
        "context": ctx,
        "witnesses": B.witnesses(passage_id),
        "trace": B.source_trace(passage_id),
        "languages": B.realization_languages(passage_id),
        "session_row": session_row,
        "siblings": [{"session_id": s["session_id"], "lesson": s["lesson"],
                      "passage_count": s["passage_count"]} for s in sess],
        "saved_research": saved_research_for("passage", passage_id),
        "obsidian": obsidian_action("passage", passage_id),
        "citation": citation_block(p),
        "trace_incomplete_note": (VM.TRACE_INCOMPLETE_NOTE
                                  if p.get("provenance_status") == "SOURCE_TRACE_INCOMPLETE"
                                  else None),
        "research_actions": [
            {"id": "passage_research", "label": "Research this passage",
             "tool": "lacan.research", "mode": "scholarly",
             "request": {"question": "请就这一段给出可核证的研究结论：%s"
                         % (p.get("text") or "")[:C.EXPLORER_SEED_CHARS]},
             "note": ("The passage is used as a scope hint / seed only. It is never "
                      "treated as an already-proven conclusion.")},
        ],
    }


def citation_block(p):
    """§51：Copy Citation —— 只给**存在**的出版学字段，绝不生造。"""
    pid = p.get("passage_id")
    short = "%s · %s" % ((pid or "").split(".")[1] if pid else "", 
                         (pid or "").rsplit(".", 1)[-1])
    return {
        "short": short,
        "passage_id": pid,
        "seminar": p.get("seminar"),
        "session": p.get("session"),
        "language": p.get("language"),
        "source_layer": p.get("source_layer"),
        "witness": p.get("witness"),
        "provenance_status": p.get("provenance_status"),
        "full": ("%s — %s, %s, source layer %s, witness %s, provenance %s"
                 % (pid, p.get("seminar"), p.get("session"), p.get("source_layer"),
                    p.get("witness"), p.get("provenance_status"))),
        "note": ("No bibliographic citation is invented: fields that the store does not "
                 "record (page numbers, print edition) are simply absent."),
    }


def context_window(passage_id, before, after):
    before = max(0, min(int(before or 0), C.MAX_CONTEXT_BEFORE))
    after = max(0, min(int(after or 0), C.MAX_CONTEXT_AFTER))
    ctx = B.context(passage_id, before, after)
    if ctx is None:
        return {"kind": "error", "code": "NOT_FOUND",
                "title": "Passage not found.",
                "body": "That passage id does not exist in the corpus store."}
    ctx["view"] = "context"
    return ctx


def session_reading(session_id, cursor=None, limit=None):
    limit = max(1, min(int(limit or C.EXPLORER_READING_PAGE), C.EXPLORER_PAGE_MAX))
    out = B.session_stream(session_id, cursor=cursor, limit=limit)
    out["view"] = "session_reading"
    out["reading_mode"] = True
    return out


# ─────────────────────────────────────────────────────────── Seminar
def seminar_list(cursor=None, limit=None, query=None, year_from=None, year_to=None):
    out = B.list_seminars(cursor=cursor, limit=50, query=query, year_from=year_from,
                          year_to=year_to)
    out["view"] = "seminar_list"
    return out


def seminar_detail(seminar_id):
    v = B.get_seminar_view(seminar_id,
                           passage_limit=C.EXPLORER_PAGE_DEFAULT)
    if v is None:
        return None
    v["view"] = "seminar_detail"
    v["saved_research"] = saved_research_for("seminar", seminar_id)
    v["obsidian"] = obsidian_action("seminar", seminar_id)
    return v


def sessions(seminar_id):
    out = B.list_sessions(seminar_id, limit=50)
    out["view"] = "sessions"
    return out


# ─────────────────────────────────────────────────────────── Terminology
def terminology_list(query=None, cursor=None, limit=None):
    limit = max(1, min(int(limit or C.EXPLORER_PAGE_DEFAULT), C.EXPLORER_PAGE_MAX))
    out = B.list_terminology(query=query, cursor=cursor, limit=limit)
    out["view"] = "terminology_list"
    return out


def terminology_detail(term, extra_forms=None):
    v = B.get_term_view(term, attestation_forms=extra_forms)
    if v is None:
        return None
    v["view"] = "terminology_detail"
    v["zones"] = [
        {"id": "mapping", "title": "Mapping",
         "subtitle": "ontology layer — a mapping record is not corpus attestation"},
        {"id": "attestation", "title": "Attestation",
         "subtitle": "corpus layer — exact-form occurrence count over 249,105 passages"},
        {"id": "interpretation", "title": "Interpretation",
         "subtitle": "only produced by an explicit research call — never auto-generated"},
    ]
    return v


def concept_graph_detail(concept_id):
    g = B.concept_graph(concept_id)
    if g is None:
        return None
    g["view"] = "concept_graph"
    return g


def terminology_control():
    """§32 验收例：Réel / réalité。"""
    out = B.reel_realite_control()
    out["view"] = "terminology_control"
    return out


# ─────────────────────────────────────────────────────────── Saved / Obsidian
def _manifests():
    try:
        from obsidian_adapter import adapter as OA                        # noqa: PLC0415
        return OA.list_saved_research()["items"]
    except Exception:                                                     # noqa: BLE001
        return []


def _mapping():
    try:
        from obsidian_adapter import adapter as OA                        # noqa: PLC0415
        from obsidian_adapter import vault as OV                          # noqa: PLC0415
        v = OV.Vault()
        return OA._load_mapping(v)                                        # noqa: SLF001
    except Exception:                                                     # noqa: BLE001
        return {}


def saved_research_for(entity_type, entity_id):
    """§35：Saved Research **来自 manifest / mapping**，不靠重新扫 Markdown 猜链接。"""
    key = {"concept": entity_id, "seminar": entity_id,
           "passage": entity_id}.get(entity_type, entity_id)
    items = []
    for m in _manifests():
        note = m.get("research_note")
        hit = False
        if entity_type == "concept":
            hit = key in (list((m.get("concept_note_paths") or {}).keys()))
        elif entity_type == "seminar":
            hit = key in (list((m.get("seminar_note_paths") or {}).keys()))
        elif entity_type == "passage":
            hit = key in (list((m.get("passage_note_paths") or {}).keys()))
        if not hit:
            continue
        items.append({
            "research_id": m.get("research_id"), "research_note": note,
            "saved_at": m.get("saved_at"), "answer_state": m.get("answer_state"),
            "manifest": m.get("manifest"),
        })
    items.sort(key=lambda r: str(r.get("saved_at") or ""), reverse=True)
    return {"items": items, "total": len(items),
            "source": "Workspace / Obsidian manifests (not a Markdown scan)"}


def obsidian_action(entity_type, entity_id):
    """§36：有对应 note → Open in Obsidian；否则 → Create Reference Note（复用 4D.3）。"""
    try:
        from obsidian_adapter import adapter as OA                        # noqa: PLC0415
        from obsidian_adapter import vault as OV                          # noqa: PLC0415
        v = OV.Vault()
        mapping = OA._load_mapping(v)                                     # noqa: SLF001
    except Exception as exc:                                              # noqa: BLE001
        return {"available": False, "reason": str(exc)[:160]}
    rel = (mapping.get(entity_id) or {}).get("note")
    exists = bool(rel) and v.exists(rel)
    uri = OA.open_in_obsidian(rel, vault=v) if exists else None
    return {
        "available": True,
        "note": rel,
        "exists": exists,
        "action": "open" if exists else "create",
        "label": "Open in Obsidian" if exists else "Create Reference Note",
        "obsidian_uri": uri,
        "managed": bool((mapping.get(entity_id) or {}).get("managed")),
        "entity_type": entity_type,
        "note_policy": ("Only the 4D.3 adapter writes notes; the Explorer never writes "
                        "files directly."),
    }


def obsidian_create(entity_type, entity_id):
    """§36/§64：Create Reference Note —— 复用 4D.3 adapter（不另写第二套保存逻辑）。"""
    try:
        from obsidian_adapter import adapter as OA                        # noqa: PLC0415
        if entity_type == "concept":
            res = OA.ensure_concept_note(entity_id)
        elif entity_type == "seminar":
            res = OA.ensure_seminar_note(entity_id)
        elif entity_type == "passage":
            res = OA.save_passage(entity_id)
        else:
            return {"ok": False, "error": "UNSUPPORTED_ENTITY"}
    except Exception as exc:                                              # noqa: BLE001
        return {"ok": False, "error": "SAVE_FAILED", "detail": str(exc)[:200]}
    out = {"kind": "obsidian_create", "entity_type": entity_type,
           "entity_id": entity_id, **res}
    if res.get("note"):
        try:
            from obsidian_adapter import adapter as OA                    # noqa: PLC0415
            from obsidian_adapter import vault as OV                      # noqa: PLC0415
            out["obsidian_uri"] = OA.open_in_obsidian(res["note"], vault=OV.Vault())
        except Exception:                                                 # noqa: BLE001
            out["obsidian_uri"] = None
    return out


# ─────────────────────────────────────────────────────────── Research 桥
def research_requests():
    """§8/§54/§65：Explorer 只**预填** ResearchRequest；真正执行仍走 Research Contract。

    Explorer 自己**不做**研究、不产生 abstention ——
    `ABSTAINED` 只会出现在用户点 Research 之后的学术回答里。
    """
    return {
        "requests": [
            {"id": "concept", "label": "Research this concept",
             "tool": "lacan.research", "mode": "concept_definition",
             "prefill": "请给出 {label} 的工作定义、关键区分与语料证据。"},
            {"id": "compare", "label": "Compare", "tool": "lacan.compare_terms",
             "mode": "concept_relation",
             "prefill": "{term_a} 与 {term_b} 有什么区别？请分别给出各自的语料证据。"},
            {"id": "diachronic", "label": "Diachronic research",
             "tool": "lacan.research_diachronic", "mode": "diachronic",
             "prefill": "{concept} 在 {span} 之间发生了什么变化？请给出各阶段的语料依据。"},
            {"id": "translation", "label": "Translation research",
             "tool": "lacan.research_translation", "mode": "translation_terminology",
             "prefill": "中文语料里 {term} 有哪些译法？这些译名差异意味着什么？"},
            {"id": "seminar", "label": "Ask about this Seminar",
             "tool": "lacan.research", "mode": "seminar_specific",
             "prefill": "在 {seminar} 中，{topic} 是如何被论述的？请给出来源层可核的段落。"},
        ],
        "note": ("Explorer never executes research itself and never labels an empty "
                 "browse result as a scholarly abstention."),
    }
