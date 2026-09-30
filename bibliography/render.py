#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bibliography.render — Phase 5C：**唯一**的 CitationRenderer（§31/§32）。

    CitationRecord → CitationRenderer → 各出口（UI / Export / Obsidian / Project）

禁止 UI / Export / Obsidian 各自拼 citation；同一个
`BibliographicItem + style` 在四个出口必须**逐字相同**（§32，由 citation_identity_hash 保证）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
for _p in (VAULT, os.path.join(VAULT, "_scripts", "_tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from . import model as M                                                   # noqa: E402
from . import registry as R                                                # noqa: E402

STYLES = ("internal", "provenance", "chicago", "apa", "mla", "bibtex")


def _bib_dict(item):
    """registry item → export_system.citations 认得的 bibliographic 字典。"""
    return {
        "author": (item.get("authors") or [None])[0],
        "authors": item.get("authors") or [],
        "title": item.get("title"),
        "publication_title": item.get("short_title") or item.get("title"),
        "publisher": item.get("publisher"),
        "publication_place": item.get("publication_place"),
        "year": item.get("publication_year"),
        "edition": item.get("edition"),
        "volume": item.get("volume"),
        "issue": item.get("issue"),
        "pages": item.get("pages"),
        "doi": item.get("doi"), "isbn": item.get("isbn"), "url": item.get("url"),
        "language": item.get("language"),
    }


def _names_join(names):
    return ", ".join(names) if names else None


def render_bibliographic(item, style):
    """出版型样式：**只用真实字段**；不足时 fail closed（§30/§48）。"""
    caps = M.capability_flags(item)
    if style in ("chicago", "mla", "apa") and not caps.get(style):
        raise ValueError("BIBLIOGRAPHIC_METADATA_INCOMPLETE: %s 需要 %s（缺失：%s）"
                         % (style, ",".join(M.STYLE_REQUIREMENTS[style]),
                            ",".join(caps["missing_fields"])))
    a = _names_join(item.get("authors"))
    t = item.get("title")
    pub = item.get("publisher")
    y = item.get("publication_year")
    place = item.get("publication_place")
    if style == "chicago":
        return "%s. *%s*. %s%s: %s, %s." % (
            a, t, (place + ": ") if place else "", pub, pub and "" or "", y
        ).replace(": ,", ",") if False else \
            "%s. *%s*. %s%s, %s." % (a, t, (place + ": ") if place else "", pub, y)
    if style == "mla":
        return "%s. *%s*. %s, %s." % (a, t, pub, y)
    if style == "apa":
        return "%s (%s). *%s*. %s." % (a, y, t, pub)
    if style == "bibtex":
        from . import zotero as Z                                          # noqa: PLC0415
        return Z.export_bibtex(item)[0]
    raise ValueError("UNSUPPORTED_STYLE: %s" % style)


def render(style, *, item=None, passage_id=None, passage_meta=None,
           quoted_span=None, claim_id=None):
    """统一入口。`internal` 家族需要 passage 信息；出版型需要 item。"""
    if style in ("internal", "provenance"):
        if not passage_id:
            raise ValueError("PASSAGE_REQUIRED_FOR_INTERNAL_STYLE")
        import export_system as EX                                         # noqa: PLC0415
        meta = dict(passage_meta or {})
        rec = EX.citations.citation_record(
            passage_id, meta=meta, quoted_span=quoted_span, claim_id=claim_id,
            bibliographic=(_bib_dict(item) if item else None),
            style=("internal-full" if style == "internal"
                   else "provenance"))
        key = "internal_full" if style == "internal" else "provenance"
        return rec[key]
    if item is None:
        raise ValueError("ITEM_REQUIRED_FOR_BIBLIOGRAPHIC_STYLE")
    return render_bibliographic(item, style)


def capability_matrix(item, *, passage_id=None):
    """§14 输出形状（contract 明确）。"""
    caps = M.capability_flags(item)
    return {
        "passage_id": bool(passage_id) or caps["passage_id"],
        "internal_short": caps["internal_short"],
        "internal_full": caps["internal_full"],
        "provenance": caps["provenance"],
        "chicago": caps["chicago"], "mla": caps["mla"], "apa": caps["apa"],
        "bibtex": caps["bibtex"],
        "missing_fields": caps["missing_fields"],
        "style_missing": caps.get("style_missing") or {},
        "style_reasons": caps.get("style_reasons") or {},
        "soft_missing": caps.get("soft_missing") or [],
        "soft_missing_note": ("Not required for the style, but no verified value exists: "
                              + ", ".join(caps.get("soft_missing") or []))
        if caps.get("soft_missing") else None,
        "metadata_completeness": caps["metadata_completeness"],
        "internal_citation_ready": caps["internal_citation_ready"],
        "bibliographic_citation_ready": caps["bibliographic_citation_ready"],
        "bibtex_ready": caps["bibtex_ready"],
    }


def citation_identity_hash(item, style):
    """§32：同一 item+style 在**任何出口**必须同值。"""
    try:
        text = render(style, item=item) if style in ("chicago", "apa", "mla",
                                                     "bibtex") else None
        err = None
    except ValueError as exc:
        text, err = None, str(exc)
    return hashlib.sha256(json.dumps(
        {"id": item["bibliographic_id"], "style": style, "text": text,
         "unavailable": err}, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
