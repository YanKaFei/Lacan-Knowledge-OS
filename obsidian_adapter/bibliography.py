#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""obsidian_adapter.bibliography — Phase 5C §35/§36：书目的**派生**参考笔记。

沿用 5B 的纪律（实测踩过）：**不**写 canonical 分区、**不**带 `id`/`type` frontmatter，
放在 `_System/bibliography/`，并指向（若有）canonical 实体；用户区逐字节保留。
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from . import vault as V                                                  # noqa: E402
from .frontmatter import MARK_END, MARK_START, dump_frontmatter           # noqa: E402

NOTE_DIR = "_System/bibliography"


def note_rel(bibliographic_id):
    return "%s/%s.md" % (NOTE_DIR, bibliographic_id)


def render_note(item, capability=None):
    B = _B()
    caps = capability or B.render.capability_matrix(item)
    L = ["# %s" % (item.get("title") or item["bibliographic_id"]), "",
         "> Phase 5C **派生**书目参考笔记（不是 canonical 实体笔记，不含理论相关性判断）。",
         "",
         "## Bibliographic metadata", ""]
    rows = [("id", item["bibliographic_id"]), ("item_type", item.get("item_type")),
            ("authors", ", ".join(item.get("authors") or []) or "—"),
            ("publisher", item.get("publisher") or "—"),
            ("publication_year", item.get("publication_year") or "—"),
            ("edition", item.get("edition") or "—"),
            ("language", item.get("language") or "—"),
            ("review_status", item.get("review_status")),
            ("metadata_completeness", item.get("metadata_completeness"))]
    for k, v in rows:
        L.append("* %s: %s" % (k, v))
    L += ["", "## Citation capabilities", "",
          "* internal: READY" if caps["internal_citation_ready"] else "* internal: —",
          "* chicago: %s" % ("READY" if caps["chicago"] else "unavailable"),
          "* apa: %s" % ("READY" if caps["apa"] else "unavailable"),
          "* mla: %s" % ("READY" if caps["mla"] else "unavailable"),
          "* bibtex: %s" % ("READY" if caps["bibtex"] else "unavailable"),
          "* missing_fields: %s" % (", ".join(caps["missing_fields"]) or "—"), ""]
    prov = item.get("provenance") or {}
    if prov:
        L += ["## Provenance", "", "```json",
              __import__("json").dumps(prov, ensure_ascii=False, indent=1)[:800],
              "```", ""]
    return "\n".join(L)


def _B():
    import bibliography as B                                              # noqa: PLC0415
    return B


def save_bibliography_note(bibliographic_id, vault=None):
    B = _B()
    it = B.registry.get(bibliographic_id)
    if it.get("review_status") != "reviewed":
        raise V.VaultError("CANDIDATE_ITEM_NOT_PUBLISHABLE: %s" % bibliographic_id)
    v = vault or V.Vault()
    rel = note_rel(bibliographic_id)
    fm = dump_frontmatter({
        "bibliographic_ref": bibliographic_id,
        "note_kind": "lacan-bibliography-reference",
        "review_status": "reviewed",
        "metadata_completeness": it.get("metadata_completeness"),
        "managed_by": "lacan-knowledge-os/phase5c",
        "canonical_note": None,
        "canonical_note_unchanged": True,
    })
    inner = "%s\n%s\n%s" % (MARK_START, render_note(it).rstrip("\n"), MARK_END)
    existing = v.read(rel) if v.exists(rel) else None
    if existing is None:
        v.write(rel, "%s\n\n%s\n\n## My Notes\n\n" % (fm, inner))
        return {"bibliographic_id": bibliographic_id, "note": rel, "created": True}
    m = re.search(r"(?s)%s.*?%s" % (re.escape(MARK_START), re.escape(MARK_END)),
                  existing)
    text = (existing[:m.start()] + inner + existing[m.end():]) if m else \
        existing.rstrip("\n") + "\n\n" + inner + "\n"
    v.write(rel, text)
    return {"bibliographic_id": bibliographic_id, "note": rel, "created": False,
            "managed_region_refreshed": True}
