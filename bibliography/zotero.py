#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bibliography.zotero — Phase 5C：Zotero 的**文件式** import / export（§22–§29）。

定位（§22/§53）：
    Zotero = external bibliography manager（外部工具）
    Bibliographic Registry = 产品读取模型 / 书目身份真源
    → **Zotero 不是 canonical source**。

流程（§25，禁止直接 canonicalize）：
    Zotero Item → Import Candidate → Normalize → Deduplicate → Review → Registry

安全（§43）：大小上限、UTF-8 容错、`javascript:`/`data:` URL 拒绝、key 路径穿越拒绝、
重复 id、冲突 zotero key、HTML 注入净化、XML 明确拒绝（本层只解析 JSON）。
**默认离线**（§45）：不发起任何网络请求；不自动补 metadata（§44）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from . import model as M                                                   # noqa: E402


def _clean(v, limit=500):
    """外部导入字段统一净化（含去标签，§43）。"""
    return M.safe_text(v, limit, strip_html=True)

MAX_IMPORT_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 5000
_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")

CSL_TYPE_TO_ITEM = {
    "book": "book", "chapter": "chapter", "article-journal": "article",
    "thesis": "thesis", "report": "report", "manuscript": "manuscript",
    "webpage": "web", "translation": "translation", "document": "other",
}


class ImportError_(ValueError):
    pass


def _check_key(k, what):
    if not k or not _KEY_RE.match(str(k)):
        raise ImportError_("UNSAFE_OR_INVALID_KEY(%s): %r" % (what, str(k)[:60]))
    if "/" in str(k) or "\\" in str(k) or ".." in str(k):
        raise ImportError_("PATH_TRAVERSAL_IN_KEY(%s)" % what)
    return str(k)


def _parse_json(raw, what):
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_IMPORT_BYTES:
            raise ImportError_("OVERSIZED_IMPORT(%s): %d bytes" % (what, len(raw)))
        raw = raw.decode("utf-8", errors="replace")       # malformed UTF-8 → 容错
    if not isinstance(raw, str):
        raise ImportError_("INVALID_INPUT_TYPE")
    if len(raw.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ImportError_("OVERSIZED_IMPORT(%s)" % what)
    s = raw.lstrip()
    if s.startswith("<"):
        # §43：XML（含 Billion Laughs 类实体展开）在本层**不支持** → 显式拒绝
        raise ImportError_("UNSUPPORTED_FORMAT: XML 不受支持（本层只解析 JSON；"
                           "如需 Zotero RDF 请先自行转换）")
    try:
        return json.loads(raw)
    except Exception as exc:                                               # noqa: BLE001
        raise ImportError_("MALFORMED_JSON(%s): %s" % (what, str(exc)[:120]))


def _names(v):
    out = []
    if isinstance(v, list):
        for x in v:
            if isinstance(x, dict):
                n = x.get("literal") or " ".join(
                    y for y in [x.get("family"), x.get("given")] if y)
                if n:
                    out.append(_clean(n, 200))
    elif isinstance(v, str):
        out.append(M.safe_text(v, 200))
    return out


def _first(v):
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = v.get("literal") or v.get("date-parts") or v.get("raw")
    if isinstance(v, list) and v and isinstance(v[0], list):
        v = v[0][0] if v[0] else None
    return v


def _url_or_fail(entry):
    """URL 不安全 → **拒绝该条目**（fail closed，且记录原因），不静默丢弃（§43）。"""
    raw = _first(entry.get("URL"))
    if not raw:
        return None
    try:
        return M.safe_url(raw)
    except ValueError as exc:
        raise ImportError_("UNSAFE_URL_SCHEME: %s" % str(exc))


def normalize_csl(entry, source="csl-json"):
    """CSL JSON / Better BibTeX JSON(CSL 形态) → 规范化 candidate。"""
    if not isinstance(entry, dict):
        raise ImportError_("ENTRY_NOT_OBJECT")
    zk = entry.get("id") or entry.get("citation-key") or entry.get("key")
    if zk:
        _check_key(zk, "zotero_key")
    title = _clean(_first(entry.get("title")), 500)
    year = None
    issued = entry.get("issued")
    if isinstance(issued, dict):
        dp = issued.get("date-parts") or []
        if dp and isinstance(dp[0], list) and dp[0]:
            year = str(dp[0][0])
        elif issued.get("raw"):
            m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", str(issued["raw"]))
            year = m.group(1) if m else None
    elif issued:
        m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", str(issued))
        year = m.group(1) if m else None
    csl_type = str(entry.get("type") or "document")
    item = {
        "candidate_id": "cand.zotero.%s" % hashlib.sha256(
            json.dumps({"zk": zk, "t": title, "y": year}, sort_keys=True)
            .encode()).hexdigest()[:12],
        "source": source,
        "zotero_key": (str(zk) if zk else None),
        "zotero_library_id": (str(entry.get("libraryID"))
                              if entry.get("libraryID") else None),
        "item_type": CSL_TYPE_TO_ITEM.get(csl_type, "other"),
        "csl_type": csl_type,
        "title": (title or None),
        "authors": _names(entry.get("author")),
        "editors": _names(entry.get("editor")),
        "translators": _names(entry.get("translator")),
        "publisher": _clean(_first(entry.get("publisher")), 200) or None,
        "publication_place": _clean(_first(entry.get("publisher-place")),
                                        200) or None,
        "publication_year": year,
        "edition": _clean(_first(entry.get("edition")), 100) or None,
        "volume": _clean(_first(entry.get("volume")), 50) or None,
        "issue": _clean(_first(entry.get("issue")), 50) or None,
        "pages": _clean(_first(entry.get("page")), 100) or None,
        "language": _clean(_first(entry.get("language")), 40) or None,
        "url": _url_or_fail(entry),
        "review_status": "candidate",
        "canonicalized": False,
        "provenance": {"source": source, "zotero_key": str(zk) if zk else None},
        "raw_hash": hashlib.sha256(json.dumps(entry, ensure_ascii=False,
                                             sort_keys=True).encode()
                                   ).hexdigest()[:16],
    }
    for f, key in (("doi", "DOI"), ("isbn", "ISBN"), ("issn", "ISSN")):
        v = _first(entry.get(key))
        if not v:
            item[f] = None
            continue
        try:
            item[f] = (M.valid_doi(v) if f == "doi"
                       else M.valid_isbn(v) if f == "isbn"
                       else M.safe_text(v, 40))
        except ValueError:
            item[f] = None
            item.setdefault("invalid_fields", []).append(f)
    return item


def import_file(raw, source="csl-json", existing=None):
    """→ {candidates, duplicates, conflicts, rejected}（**不**自动 canonicalize）。

    `existing`：已存在的候选记录（产品层传入 stored_candidates）——用于把
    **跨次导入**的重复/冲突也算出来（§17）。缺省 None → 只看本次文件内部（向后兼容）。
    """
    doc = _parse_json(raw, source)
    if isinstance(doc, dict):
        entries = doc.get("items") or doc.get("data") or [doc]
    elif isinstance(doc, list):
        entries = doc
    else:
        raise ImportError_("UNSUPPORTED_TOP_LEVEL")
    if len(entries) > MAX_ITEMS:
        raise ImportError_("TOO_MANY_ITEMS: %d" % len(entries))
    cands, rejected = [], []
    for e in entries:
        try:
            cands.append(normalize_csl(e, source))
        except ImportError_ as exc:
            rejected.append({"reason": str(exc)[:200],
                             "raw_hash": hashlib.sha256(
                                 json.dumps(e, ensure_ascii=False,
                                            sort_keys=True).encode()
                             ).hexdigest()[:16]})
    dups, conflicts = analyze(cands, existing=existing)
    return {"candidates": cands, "duplicates": dups, "conflicts": conflicts,
            "rejected": rejected,
            "note": ("导入结果一律是 **candidate**；必须经 review 才能进入 "
                     "reviewed registry（§25）。")}


def dedup_key(item):
    """§26 优先级：DOI → ISBN → zotero key → normalized title+author+year。"""
    if item.get("doi"):
        return ("doi", str(item["doi"]).lower())
    if item.get("isbn"):
        return ("isbn", str(item["isbn"]))
    if item.get("zotero_key"):
        return ("zotero", str(item["zotero_key"]))
    key = "|".join([M.norm_text(item.get("title")).lower(),
                    M.norm_text((item.get("authors") or [""])[0]).lower(),
                    str(item.get("publication_year") or "")])
    return ("title_author_year", key)


def analyze(cands, existing=None):
    """→ (duplicates, conflicts)。fuzzy 只标 `candidate_duplicate`，**不**自动 merge。"""
    existing = existing or []
    groups, dups = {}, []
    for c in cands + existing:
        k = dedup_key(c)
        groups.setdefault(k, []).append(c)
    for k, rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        ids = sorted(r.get("candidate_id") or r.get("bibliographic_id") for r in rows)
        kind = "EXACT_KEY" if k[0] in ("doi", "isbn", "zotero") else "candidate_duplicate"
        dups.append({"schema_version": "phase5c-bibliography-duplicate/v1",
                     "dedup_key_kind": k[0], "dedup_key": k[1][:120],
                     "kind": kind, "members": ids,
                     "auto_merged": False,
                     "note": ("fuzzy 命中只能标 candidate_duplicate，**不得**自动合并（§26）。"
                              if kind == "candidate_duplicate" else
                              "强键命中：仍须人工确认后才可合并（§26）。")})
    # 冲突：同一强键但字段值不同（§27：不做 last-write-wins）
    conflicts = []
    for k, rows in sorted(groups.items()):
        if k[0] not in ("doi", "isbn", "zotero") or len(rows) < 2:
            continue
        for field in ("publication_year", "publisher", "title", "publication_place",
                      "edition", "pages"):
            vals = {}
            for r in rows:
                v = r.get(field)
                if v not in (None, "", [], {}):
                    vals.setdefault(str(v), []).append(
                        r.get("candidate_id") or r.get("bibliographic_id"))
            if len(vals) > 1:
                conflicts.append({
                    "schema_version": "phase5c-metadata-conflict/v1",
                    "code": "METADATA_CONFLICT", "field": field,
                    "dedup_key": k[1][:120], "values": vals,
                    "resolution": "UNRESOLVED",
                    "auto_overwrite": False,
                    "note": ("冲突必须保留两个来源并显式解决；**禁止** last-write-wins（§27）。")})
    return dups, conflicts


# ─────────────────────────────────────────────────────────── export（§28/§29）
def export_csl_json(item):
    """→ CSL JSON（只填**真实存在**的字段）。"""
    out = {"type": next((k for k, v in CSL_TYPE_TO_ITEM.items()
                         if v == item.get("item_type")), "document"),
           "id": item.get("zotero_key") or item["bibliographic_id"]}
    if item.get("title"):
        out["title"] = item["title"]
    if item.get("authors"):
        out["author"] = [{"literal": a} if " " not in a.strip()
                         # 真实数据里名字是整串（无 family/given 拆分）→ 用 literal 保真
                         else {"literal": a} for a in item["authors"]]
    if item.get("editors"):
        out["editor"] = [{"literal": a} for a in item["editors"]]
    if item.get("translators"):
        out["translator"] = [{"literal": a} for a in item["translators"]]
    for src, dst in (("publisher", "publisher"),
                     ("publication_place", "publisher-place"),
                     ("edition", "edition"), ("volume", "volume"),
                     ("issue", "issue"), ("pages", "page"),
                     ("language", "language"), ("url", "URL"),
                     ("doi", "DOI"), ("isbn", "ISBN"), ("issn", "ISSN")):
        if item.get(src):
            out[dst] = item[src]
    if item.get("publication_year"):
        out["issued"] = {"date-parts": [[int(item["publication_year"])]]}
    return out


def export_bibtex(item):
    """→ (bibtex_text, completeness)。字段不足时**省略**而不是填 `Unknown`/`????`。"""
    flags = M.capability_flags(item)
    if not flags["bibtex"]:            # 需要 authors + title + year
        raise ValueError("BIBLIOGRAPHIC_METADATA_INCOMPLETE: bibtex 需要 "
                         "authors/title/year（缺失：%s）"
                         % ",".join(flags["missing_fields"]))
    first = (item.get("authors") or ["ref"])[0]
    key = re.sub(r"[^A-Za-z0-9]", "", first)[:12].lower() + \
        str(item.get("publication_year") or "")
    kind = {"book": "book", "article": "article", "chapter": "incollection",
            "thesis": "phdthesis", "report": "techreport"}.get(
                item.get("item_type"), "misc")
    fields = [("author", " and ".join(item["authors"])),
              ("title", item["title"]),
              ("year", str(item["publication_year"]))]
    for src, dst in (("publisher", "publisher"), ("publication_place", "address"),
                     ("edition", "edition"), ("volume", "volume"),
                     ("pages", "pages"), ("doi", "doi"), ("isbn", "isbn"),
                     ("url", "url")):
        if item.get(src):
            fields.append((dst, str(item[src])))
    body = ",\n  ".join("%s = {%s}" % (k, v) for k, v in fields)
    text = "@%s{%s,\n  %s\n}\n" % (kind, key, body)
    return text, flags["metadata_completeness"]


# ─────────────────────────────────────────────────────────── 候选持久化（§13–§18）
# ⚠️ 导入候选**不是** reviewed registry（§12/§55）→ 存到 USER_WORKSPACE 侧，
#    与 `_data/bibliography/`（CANONICAL_KNOWLEDGE）严格分开。
CAND_STORE = os.path.join(VAULT, "_workspace", "bibliography",
                          "imported_candidates.jsonl")
CONFLICT_STORE = os.path.join(VAULT, "_workspace", "bibliography",
                              "metadata_conflicts.jsonl")


def store_import(result, source="csl-json"):
    """把一次导入的候选/去重/冲突**持久化**（append-only，不晋级）。"""
    import time as _t
    os.makedirs(os.path.dirname(CAND_STORE), exist_ok=True)
    stamp = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())
    with open(CAND_STORE, "a", encoding="utf-8") as f:
        for c in result["candidates"]:
            row = dict(c)
            row["imported_at"] = stamp
            row["import_source"] = source
            row["review_status"] = "candidate"
            row["canonicalized"] = False
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with open(CONFLICT_STORE, "a", encoding="utf-8") as f:
        for c in result["conflicts"]:
            row = dict(c)
            row["detected_at"] = stamp
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"stored_candidates": len(result["candidates"]),
            "stored_conflicts": len(result["conflicts"]),
            "candidate_store": os.path.relpath(CAND_STORE, VAULT),
            "review_status": "candidate",
            "canonicalized": False}


def stored_candidates(limit=200):
    rows = []
    if os.path.isfile(CAND_STORE):
        with open(CAND_STORE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    return rows[-limit:]


def stored_conflicts(limit=200):
    rows = []
    if os.path.isfile(CONFLICT_STORE):
        with open(CONFLICT_STORE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    return rows[-limit:]
