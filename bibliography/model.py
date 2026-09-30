#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bibliography.model — Phase 5C：书目层的数据模型与确定性校验。

实体边界（§2）——**不得**压成一个 `source`：
    Passage ≠ Witness ≠ Edition ≠ BibliographicItem ≠ CorpusSource
            ≠ ProjectBibliographyRef ≠ ZoteroItem

铁律：
  * 未知字段一律 `null`；**禁止**模型补齐（§3/§9/§50）。
  * 页码是高风险字段：`page` 只能来自实际 metadata，绝不用 passage 号冒充（§15/§49）。
"""
from __future__ import annotations

import re
import unicodedata

SCHEMA_ITEM = "bibliography-item/v1"
SCHEMA_EDITION = "bibliography-edition/v1"
SCHEMA_WORK = "bibliography-work/v1"
SCHEMA_MAPPING = "bibliography-mapping/v1"
SCHEMA_CANDIDATE = "bibliography-candidate/v1"
SCHEMA_CONFLICT = "bibliography-conflict/v1"

ITEM_TYPES = ("book", "manuscript", "working_transcription", "translation",
              "article", "chapter", "thesis", "report", "web", "other")

# §13：metadata completeness
COMPLETENESS = ("INTERNAL_ONLY", "PARTIAL", "PUBLISHABLE")

# §15：位置标识的**种类**必须区分开
PAGE_LOCATOR_KINDS = ("page", "section", "session", "passage_id", "folio",
                      "digital_location")

# §3：BibliographicItem 字段（未知 = null）
ITEM_FIELDS = (
    "bibliographic_id", "item_type",
    "title", "short_title",
    "authors", "editors", "translators",
    "publisher", "publication_place", "publication_year", "edition",
    "volume", "issue", "pages",
    "isbn", "issn", "doi", "url",
    "language",
    "zotero_key", "zotero_library_id",
    "review_status", "review_basis", "metadata_completeness", "provenance",
    "metadata_provenance", "source_refs", "is_publication",
)

# reviewed 的**依据**必须显式（避免把"机器可验证"与"人工复核"混为一谈，§12/§51）
REVIEW_BASES = ("HUMAN_VAULT_REVIEW", "MACHINE_VERIFIED_DERIVATION",
                "PENDING_HUMAN_REVIEW", "NONE")

EDITION_FIELDS = (
    "edition_id", "work_id", "title", "language",
    "publisher", "year", "edition_statement",
    "editors", "translators",
    "isbn", "page_locator_available",
    "bibliographic_id", "review_status", "provenance",
)

REVIEW_STATES = ("reviewed", "candidate", "needs_review", "rejected")

# 出版型 citation 需要的字段（与 export_system.citations 对齐）
STYLE_REQUIREMENTS = {
    "chicago": ("authors", "title", "publisher", "publication_year"),
    "mla": ("authors", "title", "publisher", "publication_year"),
    "apa": ("authors", "title", "publication_year", "publisher"),
    "bibtex": ("authors", "title", "publication_year"),
}

_WS = re.compile(r"\s+")


def norm_text(s):
    s = unicodedata.normalize("NFC", str(s or ""))
    return _WS.sub(" ", s).strip()


_TAG_RE = re.compile(r"</?[A-Za-z][^<>]{0,400}>")


def strip_markup(s):
    """去掉**标签样**片段（§43 HTML injection）。只用确定性规则，不做转义偷懒。"""
    return _TAG_RE.sub("", str(s or ""))


def safe_text(s, limit=2000, strip_html=False):
    """入库前的基础净化：去控制字符、截断、**不**执行任何标记（§43 HTML injection）。"""
    t = "".join(ch for ch in str(s or "") if ch == "\n" or ch == "\t"
                or unicodedata.category(ch)[0] != "C")
    t = t.replace("\x00", "")
    if strip_html:
        t = strip_markup(t)
    return t[:limit]


def safe_url(u):
    """只接受 http/https；`javascript:` / `data:` 一律拒绝（§43）。"""
    s = str(u or "").strip()
    if not s:
        return None
    if re.match(r"^(?i)\s*(javascript|data|vbscript|file)\s*:", s):
        raise ValueError("UNSAFE_URL_SCHEME")
    if not re.match(r"^(?i)https?://", s):
        return None
    return s[:500]


def valid_doi(v):
    """基本结构验证（不联网、不补全，§44）。"""
    if not v:
        return None
    s = str(v).strip()
    s = re.sub(r"^(?i)https?://(dx\.)?doi\.org/", "", s)
    if re.match(r"^10\.\d{4,9}/[^\s]+$", s):
        return s
    raise ValueError("INVALID_DOI")


def valid_isbn(v):
    """ISBN-10 / ISBN-13 校验位验证（不联网、不补全，§44）。"""
    if not v:
        return None
    s = re.sub(r"[^0-9Xx]", "", str(v)).upper()
    if len(s) == 10:
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s))
        if total % 11 == 0:
            return s
        raise ValueError("INVALID_ISBN")
    if len(s) == 13:
        total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(s))
        if total % 10 == 0:
            return s
        raise ValueError("INVALID_ISBN")
    raise ValueError("INVALID_ISBN")


def blank_item(bibliographic_id, item_type="other"):
    """→ 全 null 的骨架（调用方只填**确实有**的字段）。"""
    it = {k: None for k in ITEM_FIELDS}
    it.update({
        "schema_version": SCHEMA_ITEM,
        "bibliographic_id": bibliographic_id,
        "item_type": item_type,
        "authors": [], "editors": [], "translators": [],
        "is_publication": None,
        "review_status": "candidate",
        "metadata_completeness": "INTERNAL_ONLY",
        "metadata_provenance": {},
        "provenance": {},
        "source_refs": [],
    })
    return it


def completeness(item):
    """→ INTERNAL_ONLY / PARTIAL / PUBLISHABLE（§13）。只依据**实际存在**的字段。"""
    have = {k for k in ITEM_FIELDS if item.get(k) not in (None, "", [], {})}
    core = {"title"}
    pub = {"publisher", "publication_year"}
    if pub <= have and (item.get("authors") or []):
        return "PUBLISHABLE"
    if core <= have and (have & (pub | {"authors", "edition", "isbn", "doi",
                                        "publication_place", "volume", "pages"})):
        return "PARTIAL"
    return "INTERNAL_ONLY"


def capability_flags(item):
    """§14：citation capability matrix（含 `passage_id` 与缺失字段）。"""
    have = {k: item.get(k) for k in ITEM_FIELDS}
    missing = []
    for f in ("publisher", "publication_year"):
        if have.get(f) in (None, "", [], {}):
            missing.append(f)
    if not have.get("authors"):
        missing.append("authors")
    if not have.get("pages"):
        missing.append("page_locator")
    flags = {
        "passage_id": True,           # Passage 身份始终可用（与书目无关）
        "internal_short": bool(have.get("title")),
        "internal_full": bool(have.get("title")),
        "provenance": True,
        "chicago": False, "mla": False, "apa": False, "bibtex": False,
        "missing_fields": sorted(set(missing)),
        "metadata_completeness": completeness(item),
        "internal_citation_ready": bool(have.get("title")),
        "bibliographic_citation_ready": False,
        "bibtex_ready": False,
        "note": ("Publication-style citations are only offered when the metadata "
                 "actually exists in the registry. Nothing is guessed or completed."),
    }
    style_missing = {}
    for style, need in STYLE_REQUIREMENTS.items():
        gaps = [f for f in need if have.get(f) in (None, "", [], {})]
        style_missing[style] = gaps
        flags[style] = not gaps
    flags["style_missing"] = style_missing
    # 人类可读的"为什么不可用"（UI 直接显示，不再只给 unavailable）
    flags["soft_missing"] = ([] if have.get("pages") else ["page_locator"])
    flags["style_reasons"] = {
        st: ("READY" if not gaps else
             "Missing verified metadata: " + ", ".join(
                 {"authors": "author", "publication_year": "publication year",
                  "publisher": "publisher", "title": "title"}.get(g, g)
                 for g in gaps))
        for st, gaps in style_missing.items()}
    flags["bibliographic_citation_ready"] = any(flags[s] for s in
                                                ("chicago", "mla", "apa"))
    flags["bibtex_ready"] = flags["bibtex"]
    if not flags["bibliographic_citation_ready"]:
        flags["chicago"] = flags["mla"] = flags["apa"] = False
    return flags


def page_locator(kind, value, *, source=None):
    """→ 位置标识记录。**只有** kind == 'page' 才允许被渲染成 page（§15/§49）。"""
    k = str(kind or "")
    if k not in PAGE_LOCATOR_KINDS:
        raise ValueError("INVALID_PAGE_LOCATOR_KIND: %s" % k)
    return {"kind": k, "value": safe_text(value, 120), "source": source}


def validate_item(item):
    """→ 问题列表（空 = 通过）。"""
    probs = []
    if item.get("schema_version") != SCHEMA_ITEM:
        probs.append("schema_version")
    bid = str(item.get("bibliographic_id") or "")
    if not re.match(r"^bib\.[a-z0-9][a-z0-9.-]*$", bid):
        probs.append("bibliographic_id 不符合 ^bib\\.[a-z0-9][a-z0-9.-]*$：%s" % bid)
    if item.get("item_type") not in ITEM_TYPES:
        probs.append("item_type 非法：%r" % item.get("item_type"))
    if item.get("review_status") not in REVIEW_STATES:
        probs.append("review_status 非法：%r" % item.get("review_status"))
    if item.get("metadata_completeness") not in COMPLETENESS:
        probs.append("metadata_completeness 非法")
    if item.get("review_basis") not in REVIEW_BASES:
        probs.append("review_basis 非法：%r" % item.get("review_basis"))
    if item.get("review_status") == "reviewed" and item.get("review_basis") in (
            None, "PENDING_HUMAN_REVIEW", "NONE"):
        probs.append("reviewed 却没有可核的依据（review_basis）")
    for f in ("authors", "editors", "translators"):
        if not isinstance(item.get(f), list):
            probs.append("%s 必须是 list" % f)
    # 不允许出现"填充式占位"
    for f in ("publisher", "publication_year", "publication_place", "isbn", "doi"):
        v = item.get(f)
        if isinstance(v, str) and v.strip().lower() in ("unknown", "n/a", "????",
                                                        "todo", "tbd", "-"):
            probs.append("%s 是占位值（禁止）" % f)
    return probs
