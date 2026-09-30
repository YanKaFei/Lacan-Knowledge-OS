#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace_ui.server.bibliography — Phase 5C：Bibliography Explorer 的服务端适配层。

只读；只转发 `bibliography` registry 与**唯一** CitationRenderer 的结果。
不生成任何理论相关性判断（§21）；不做任何 metadata 补全（§11/§50）。
"""
from __future__ import annotations

import os
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

import bibliography as B                                                   # noqa: E402


def _registry():
    return B.registry


def availability():
    man = _registry().manifest()
    return {"kind": "bibliography_availability",
            "counts": man.get("counts"),
            "freeze_class": man.get("freeze_class"),
            "zotero": "external_import_export_only",
            "network": "offline"}


def list_items(q=None, author=None, year=None, language=None, item_type=None,
               review_status=None, cursor=None, limit=None):
    off = int(cursor or 0)
    return _registry().search(q=q, author=author, year=year, language=language,
                              item_type=item_type, review_status=review_status,
                              cursor=off, limit=limit or 20)


def item(bibliographic_id):
    it = _registry().get(bibliographic_id)
    caps = B.render.capability_matrix(it)
    witnesses = [m for m in _registry().mappings()
                 if m.get("bibliographic_id") == bibliographic_id]
    eds = [e for e in _registry().editions()
           if e["edition_id"] in {m.get("edition_id") for m in witnesses}]
    return {
        "schema_version": "phase5c-bibliography-detail/v1",
        "item": it,
        "capabilities": caps,
        "editions": eds,
        "witnesses": [{"witness_id": m.get("witness_id"),
                       "witness_kind": m.get("witness_kind"),
                       "edition_id": m.get("edition_id"),
                       "corpus_source_id": m.get("corpus_source_id"),
                       "passage_count": m.get("passage_count"),
                       "passage_realization_state": ("linked" if m.get("passage_count")
                                                     else "Not linked (0 passages)")}
                      for m in witnesses if m.get("witness_id")],
        "works": [w for w in _registry().works()
                  if bibliographic_id in (w.get("bibliographic_ids") or [])],
        "zotero": {"zotero_key": it.get("zotero_key"),
                   "zotero_library_id": it.get("zotero_library_id"),
                   "role": "external_bibliography_manager（不是 canonical source，§22/§53）"},
        "provenance": it.get("provenance"),
        "metadata_provenance": it.get("metadata_provenance"),
        "no_theoretical_relevance": True,
        "note": "书目层只呈现 metadata relation；理论相关性属 Research（§21）。",
    }


def capabilities(bibliographic_id, passage_id=None):
    it = _registry().get(bibliographic_id)
    return B.render.capability_matrix(it, passage_id=passage_id)


def citation(bibliographic_id, style, passage_id=None):
    """UI 的 Copy Citation 走这里 —— 与 Export/Obsidian/Project **同一个** renderer（§31/§32）。"""
    it = _registry().get(bibliographic_id)
    # §4：candidate 永远不可引用（产品层硬门禁；不是 scholarly semantics）
    if it.get("review_status") != "reviewed":
        return {"style": style, "text": None, "available": False,
                "reason": "CANDIDATE_NOT_CITABLE: review_status=%s（需要 review）"
                          % it.get("review_status"),
                "identity_hash": B.render.citation_identity_hash(it, style)}
    try:
        text = B.render.render(style, item=it, passage_id=passage_id)
        return {"style": style, "text": text, "available": True,
                "identity_hash": B.render.citation_identity_hash(it, style)}
    except ValueError as exc:
        return {"style": style, "text": None, "available": False,
                "reason": str(exc)[:300],
                "identity_hash": B.render.citation_identity_hash(it, style)}


def chain(witness_id):
    return _registry().witness_chain(witness_id)


def _passage_reality(bibliographic_id):
    """§8/§9/§46：internal/provenance 是**段落级**——必须先有真实的 PassageRealization。

    返回 (passage_total, sample_passage_id)。没有真实段落就**不**声称可用。
    """
    total = 0
    sample = None
    for m in _registry().mappings():
        if m.get("bibliographic_id") != bibliographic_id:
            continue
        total += int(m.get("passage_count") or 0)
        if sample is None and (m.get("passage_count") or 0) and m.get("witness_id"):
            try:
                ch = _registry().witness_chain(m["witness_id"])
                ids = ch["passage_realization"]["sample_passage_ids"]
                sample = ids[0] if ids else None
            except Exception:                                              # noqa: BLE001
                sample = None
    return total, sample


def citation_availability(bibliographic_id):
    """§3：逐样式可用性 + **原因**（不显示 disabled 而不解释）。

    §8/§46：`witness.fr.seuil-pdf` 的 PassageRealization = 0 → internal 段落引文不可用，
    但 witness/书目 metadata 记录依然存在（这是事实，不是待补的空位）。
    """
    it = _registry().get(bibliographic_id)
    cand = it.get("review_status") != "reviewed"
    passage_total, sample = _passage_reality(bibliographic_id)
    caps = B.render.capability_matrix(it, passage_id=sample)
    internal_family = ("internal_short", "internal_full", "provenance")
    labels = {"internal_short": "Internal Short", "internal_full": "Internal Full",
              "provenance": "Provenance", "chicago": "Chicago", "apa": "APA",
              "mla": "MLA", "bibtex": "BibTeX"}
    rows = []
    for style in ("internal_short", "internal_full", "provenance",
                  "chicago", "apa", "mla", "bibtex"):
        ok = bool(caps.get(style))
        reason = None
        if cand:
            ok = False
            reason = ("candidate record — not citable (review_status=%s)"
                      % it.get("review_status"))
        elif style in internal_family and passage_total <= 0:
            ok = False
            reason = ("no PassageRealization linked: Passage Realizations = 0 "
                      "(passage-level citation needs a real passage)")
        elif not ok:
            reason = (caps.get("style_reasons") or {}).get(style, None) \
                or ("Missing verified metadata: "
                    + ", ".join(caps.get("missing_fields") or ["unknown"]))
        rows.append({
            "style": style, "label": labels[style],
            "status": ("READY" if ok else "UNAVAILABLE"),
            # §4：candidate 永远不可引用
            "available": bool(ok and not cand),
            "reason": reason,
            "note": ("candidate record — not citable" if cand else None),
        })
    return {
        "schema_version": "phase5c-citation-availability/v1",
        "bibliographic_id": bibliographic_id,
        "review_status": it.get("review_status"),
        "metadata_completeness": it.get("metadata_completeness"),
        "candidate_not_citable": bool(cand),
        "rows": rows,
        # §8/§9/§46：段落现实（客观计数，绝不假装有 passage）
        "passage_realizations": {
            "total": passage_total,
            "sample_passage_id": sample,
            "state": ("linked" if passage_total else "Not linked (0 passages)"),
        },
        "soft_missing": caps.get("soft_missing") or [],
        "soft_missing_note": caps.get("soft_missing_note"),
        "internal_note": (
            "Internal / provenance citations are **passage-level**: they need a linked "
            "PassageRealization."
            + ("" if passage_total else
               " Passage Realizations = 0 for this item: the witness/metadata record "
               "exists, but the canonical passage store has produced no passages from it, "
               "so a passage-level citation cannot be offered.")),
        "no_fake_note": ("Publication metadata is never guessed; unavailable styles state "
                         "the exact missing verified fields."),
    }


def import_preview(text, source="csl-json"):
    """§13–§17：解析 → 预览 → 去重 → 冲突（**不落库、不晋级**）。

    §17：去重**必须**包含已存在的候选（跨次导入），否则「Strong duplicate /
    Possible duplicate / No duplicate found」会失真。
    """
    from bibliography import zotero as Z                                     # noqa: PLC0415
    res = Z.import_file(text, source, existing=Z.stored_candidates(Z.MAX_ITEMS))
    return {
        "schema_version": "phase5c-zotero-import-preview/v1",
        "source": source,
        "counts": {"candidates": len(res["candidates"]),
                   "duplicates": len(res["duplicates"]),
                   "conflicts": len(res["conflicts"]),
                   "rejected": len(res["rejected"])},
        "preview": [{"title": c.get("title"), "authors": c.get("authors"),
                     "year": c.get("publication_year"),
                     "identifier": c.get("doi") or c.get("isbn") or c.get("zotero_key"),
                     "item_type": c.get("item_type"),
                     "candidate_id": c.get("candidate_id")} for c in res["candidates"]],
        "duplicates": res["duplicates"], "conflicts": res["conflicts"],
        "rejected": res["rejected"],
        "will_be": {"review_status": "candidate", "canonicalized": False},
        "note": ("Imported items are **candidates**; they are never automatically "
                 "canonicalized (§16/§25)."),
    }


def import_commit(text, source="csl-json"):
    """把候选**落库为 candidate**（仍然不晋级）。"""
    from bibliography import zotero as Z                                     # noqa: PLC0415
    res = Z.import_file(text, source, existing=Z.stored_candidates(Z.MAX_ITEMS))
    stored = Z.store_import(res, source)
    return {"schema_version": "phase5c-zotero-import-commit/v1",
            "counts": {"candidates": len(res["candidates"]),
                       "duplicates": len(res["duplicates"]),
                       "conflicts": len(res["conflicts"]),
                       "rejected": len(res["rejected"])},
            **stored,
            "message": ("Imported as candidate. Not automatically canonicalized.")}


def imported_candidates(limit=100):
    from bibliography import zotero as Z                                     # noqa: PLC0415
    rows = Z.stored_candidates(limit)
    return {"schema_version": "phase5c-imported-candidates/v1",
            "review_status": "candidate", "canonicalized": False,
            "items": rows, "total": len(rows),
            "note": "candidate 永远不可引用（§4）；它不属于 reviewed registry（§12）。"}


def conflicts(limit=100):
    from bibliography import zotero as Z                                     # noqa: PLC0415
    rows = Z.stored_conflicts(limit)
    return {"schema_version": "phase5c-metadata-conflicts/v1",
            "code": "METADATA_CONFLICT", "resolution": "UNRESOLVED",
            "items": rows, "total": len(rows),
            "note": "冲突只展示，不做 last-write-wins、不做自动裁决（§18/§19）。"}


def registry_health():
    """§31：客观 count，不给"完整度百分比"。

    `items = reviewed + candidates` —— 与 `/api/status.bibliography_registry`
    **同一口径**（两个端点不一致会让体检输出和首页互相打脸）。
    """
    man = _registry().manifest()
    reviewed = len(_registry().items())
    cands = len(_registry().candidates())
    return {"schema_version": "phase5c-registry-health/v1",
            "registry": "READY" if man else "UNAVAILABLE",
            "freeze_class": man.get("freeze_class"),
            "counts": man.get("counts") or {},
            "items": reviewed + cands,
            "reviewed": reviewed,
            "candidates": cands,
            "editions": len(_registry().editions()),
            "works": len(_registry().works()),
            "counts_are_objective": True,
            "note": "items = reviewed + candidates; no completeness score",
            "content_hash": man.get("content_hash")}
