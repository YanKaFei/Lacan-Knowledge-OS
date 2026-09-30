#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.citations — Citation System（Phase 4D.6 §17–§26/§53/§54）

两类 citation **绝不混淆**：
    A. Internal scholarly citation —— 系统真正可靠的：Passage ID / Seminar / Session /
       Year / Witness / Source layer / Provenance / Quoted span
    B. External bibliographic citation —— 只有当 bibliographic metadata **真的存在且可验证**
       时才允许（Chicago / MLA / APA / BibTeX）；否则返回
       `BIBLIOGRAPHIC_METADATA_INCOMPLETE`，**绝不猜、绝不补**。

三种正式内部样式（§20）：
    internal-short     `S11 · P2253`
    internal-full      `Seminar XI, passage P2253`（+ 年份/语言/source layer）
    provenance         `Seminar XI (1964), passage.S11.unknown.P2253, L1 transcription,
                        witness.fr.staferla, provenance COMPLETE`
"""
from __future__ import annotations

import re

from .model import (ERROR_CODES, SCHEMA_CITATION_RECORD, ExportError, sha256_text)

INTERNAL_STYLES = ("internal-short", "internal-full", "provenance")
BIBLIOGRAPHIC_STYLES = ("chicago", "mla", "apa", "bibtex")

SOURCE_LAYER_LABELS = {
    "L1": "L1 primary transcription",
    "L1_TRANSCRIPTION": "L1 primary transcription",
    "L2": "L2 recovered / translated material",
    "L2_RECOVERED": "L2 recovered / translated material",
    "L3": "L3 editorial",
    "L4": "L4 inferred / derived",
}

# 完整出版型 citation 需要的字段（§22）
BIBLIOGRAPHIC_REQUIREMENTS = {
    "chicago": ("author", "title", "publication_title", "publisher", "year"),
    "mla": ("author", "title", "publication_title", "publisher", "year"),
    "apa": ("author", "title", "year", "publisher"),
    "bibtex": ("author", "title", "year"),
}

_ROMAN = {"01": "I", "02": "II", "03": "III", "04": "IV", "05": "V", "06": "VI",
          "07": "VII", "08": "VIII", "09": "IX", "10": "X", "11": "XI", "12": "XII",
          "13": "XIII", "14": "XIV", "15": "XV", "16": "XVI", "17": "XVII",
          "18": "XVIII", "19": "XIX", "20": "XX", "21": "XXI", "22": "XXII",
          "23": "XXIII", "24": "XXIV", "25": "XXV", "26": "XXVI", "27": "XXVII"}


def passage_parts(passage_id):
    """`passage.S11.unknown.P2253` → {seminar: S11, position: P2253, lesson: None}。"""
    pid = str(passage_id or "")
    m = re.match(r"^passage\.(S\d+[A-Z]?)\.(?:unknown\.)?(?:L(\d+)\.)?(P\d+)$", pid)
    if not m:
        return {"seminar": None, "position": None, "lesson": None}
    return {"seminar": m.group(1), "position": m.group(3),
            "lesson": (int(m.group(2)) if m.group(2) else None)}


def seminar_roman(seminar_key):
    """`S11` → `XI`（仅用于 human-readable 样式；未知就原样返回，不编造）。"""
    if not seminar_key:
        return None
    m = re.match(r"^S(\d+)([A-Z]?)$", str(seminar_key))
    if not m:
        return str(seminar_key)
    num = m.group(1).zfill(2)
    base = _ROMAN.get(num, m.group(1))
    return base + (m.group(2) or "")


def source_layer_label(code):
    if not code:
        return None
    return SOURCE_LAYER_LABELS.get(code, str(code))


def short_citation(passage_id, seminar_key=None, position=None):
    parts = passage_parts(passage_id)
    sem = seminar_key or parts["seminar"] or (str(passage_id).split(".")[1]
                                              if "." in str(passage_id) else "?")
    pos = position or parts["position"] or str(passage_id).rsplit(".", 1)[-1]
    return "%s · %s" % (sem, pos)


def full_citation(passage_id, meta=None):
    meta = dict(meta or {})
    parts = passage_parts(passage_id)
    sem_key = meta.get("seminar_key") or parts["seminar"]
    roman = seminar_roman(sem_key)
    year = meta.get("year")
    head = "Seminar %s" % roman if roman else (meta.get("seminar") or sem_key or "?")
    if year:
        head += " (%s)" % year
    tail = ["passage %s" % (parts["position"] or passage_id)]
    if meta.get("lesson"):
        tail.append("lesson %s" % meta["lesson"])
    if meta.get("language"):
        tail.append(str(meta["language"]))
    if meta.get("source_layer"):
        tail.append(source_layer_label(meta["source_layer"]))
    return "%s, %s" % (head, ", ".join(tail))


def provenance_citation(passage_id, meta=None):
    """§18 Provenance Citation：字段以**实际数据**为准，缺就写 `—`，不编造。"""
    meta = dict(meta or {})
    parts = passage_parts(passage_id)
    sem_key = meta.get("seminar_key") or parts["seminar"]
    roman = seminar_roman(sem_key)
    year = meta.get("year")
    seg = []
    seg.append(("Seminar %s%s" % (roman, (" (%s)" % year) if year else ""))
               if roman else (meta.get("seminar") or sem_key or "—"))
    seg.append(str(passage_id))
    seg.append(source_layer_label(meta.get("source_layer")) or "—")
    seg.append(("witness %s" % meta["witness"]) if meta.get("witness") else "witness —")
    seg.append("provenance %s" % (meta.get("provenance_status") or "—"))
    return ", ".join(seg)


# ─────────────────────────────────────────────────────────── capability（§21）
def citation_capabilities(source, bibliographic=None):
    """→ {internal_short, internal_full, provenance, chicago, mla, apa, bibtex} + missing。"""
    bib = dict(bibliographic or (source or {}).get("bibliographic_metadata") or {})
    caps = {"internal_short": True, "internal_full": True, "provenance": True}
    missing = {}
    for style in BIBLIOGRAPHIC_STYLES:
        need = BIBLIOGRAPHIC_REQUIREMENTS[style]
        gaps = [f for f in need if not bib.get(f)]
        caps[style] = not gaps
        if gaps:
            missing[style] = gaps
    return {"capabilities": caps, "missing_fields": missing,
            "bibliographic_metadata": bib,
            "bibliographic_metadata_complete": all(caps[s] for s in BIBLIOGRAPHIC_STYLES),
            "note": ("Bibliographic styles are only offered when the metadata really "
                     "exists in the system. Nothing is guessed or completed by a model.")}


# ─────────────────────────────────────────────────────────── record（§36）
def citation_record(passage_id, *, meta=None, quoted_span=None, claim_id=None,
                    bibliographic=None, style="internal-full"):
    """→ CitationRecord（schema `citation_record_v1`）。"""
    meta = dict(meta or {})
    caps = citation_capabilities({}, bibliographic=bibliographic)
    rec = {
        "schema_version": SCHEMA_CITATION_RECORD,
        "passage_id": passage_id,
        "internal_short": short_citation(passage_id, meta.get("seminar_key"),
                                         meta.get("position")),
        "internal_full": full_citation(passage_id, meta),
        "provenance": provenance_citation(passage_id, meta),
        "quoted_span": quoted_span,
        "seminar": meta.get("seminar") or meta.get("seminar_key"),
        "session": meta.get("session"),
        "language": meta.get("language"),
        "source_layer": meta.get("source_layer"),
        "source_layer_label": source_layer_label(meta.get("source_layer")),
        "witness": meta.get("witness"),
        "provenance_status": meta.get("provenance_status"),
        "kind": "internal_scholarly",
        "capabilities": caps["capabilities"],
        "missing_fields": sorted({f for gaps in caps["missing_fields"].values()
                                  for f in gaps}),
        "bibliographic": (caps["bibliographic_metadata"] or None),
        "claim_id": claim_id,
    }
    rec["citation_hash"] = sha256_text("%s|%s" % (passage_id, style))
    return rec


def render(record, style):
    """按样式取字符串；出版型样式在 metadata 不足时 fail closed（§20）。"""
    if style == "internal-short":
        return record["internal_short"]
    if style == "internal-full":
        return record["internal_full"]
    if style == "provenance":
        return record["provenance"]
    if style in BIBLIOGRAPHIC_STYLES:
        if not record["capabilities"].get(style):
            raise ExportError(
                "BIBLIOGRAPHIC_METADATA_INCOMPLETE",
                "%s citation is unavailable: missing %s"
                % (style, ", ".join(BIBLIOGRAPHIC_REQUIREMENTS[style])),
                {"style": style, "required": list(BIBLIOGRAPHIC_REQUIREMENTS[style]),
                 "have": sorted((record.get("bibliographic") or {}).keys())})
        return _render_bibliographic(record, style)
    raise ExportError("UNSUPPORTED_FORMAT", "unknown citation style: %r" % style,
                      {"supported": list(INTERNAL_STYLES) + list(BIBLIOGRAPHIC_STYLES)})


def _render_bibliographic(record, style):
    b = record.get("bibliographic") or {}
    if style == "bibtex":
        key = re.sub(r"[^A-Za-z0-9]", "", str(b.get("author") or "ref"))[:12].lower() \
            + str(b.get("year") or "")
        return "@book{%s,\n  author = {%s},\n  title = {%s},\n  year = {%s}\n}" % (
            key, b.get("author"), b.get("title"), b.get("year"))
    if style == "apa":
        return "%s (%s). %s. %s." % (b.get("author"), b.get("year"), b.get("title"),
                                     b.get("publisher") or b.get("publication_title") or "")
    if style == "mla":
        return "%s. %s. %s, %s." % (b.get("author"), b.get("title"),
                                    b.get("publisher"), b.get("year"))
    return "%s. %s. %s: %s, %s." % (b.get("author"), b.get("title"),
                                    b.get("publisher"), b.get("publication_title"),
                                    b.get("year"))


def citation_bindings(claims, citations):
    """§25：维持 Claim ID → CitationBinding → Passage ID，不压平成扁平 bibliography。"""
    by_claim = {}
    for c in citations or []:
        cid = c.get("claim_id") or "unbound"
        by_claim.setdefault(cid, []).append(c.get("passage_id"))
    out = []
    for claim in claims or []:
        cid = claim.get("claim_id")
        out.append({
            "claim_id": cid,
            "claim_text": claim.get("claim_text"),
            "epistemic_label": claim.get("epistemic_label"),
            "claim_type": claim.get("claim_type"),
            "citation_ids": by_claim.get(cid, []),
        })
    orphans = [c.get("passage_id") for c in (citations or [])
               if (c.get("claim_id") or "unbound") not in
               {c2.get("claim_id") for c2 in (claims or [])}]
    return {"bindings": out, "unbound_citations": orphans}
