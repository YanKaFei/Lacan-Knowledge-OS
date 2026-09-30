#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bibliography.registry — Phase 5C 书目登记表（唯一书目身份真源，§53）。

来源（**全部机器可验证**，§11/§12）：
  * `01_Sources/Documents/*.md`（vault 内的 document 实体：title / canonical_name /
    edition / language / review_status）
  * passage store 的 `witnesses` 与 `corpus_sources`（含 witness→corpus_source 外键）

链条（§17）：
    Passage → PassageRealization → Witness → Edition → BibliographicItem → CorpusSource

**只显示实际存在的层**；缺层如实写 Not linked / Unknown，不补（§17）。

文件（§10）：
    _data/bibliography/works.jsonl
    _data/bibliography/editions.jsonl
    _data/bibliography/items.jsonl
    _data/bibliography/mappings.jsonl
    _data/bibliography/candidates.jsonl
    _data/bibliography/conflicts.jsonl
    _data/bibliography/manifest.json

冻结分类（§55）：登记表属 **CANONICAL_KNOWLEDGE**（书目身份），
reviewed 条目必须经显式 review state；派生 SQLite 索引可重建。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from . import model as M                                                   # noqa: E402

STORE = os.path.join(VAULT, "_data", "bibliography")
SQLITE = os.path.join(VAULT, "_index", "passage_store.sqlite")
DOCS_DIR = os.path.join(VAULT, "01_Sources", "Documents")
SCHEMA_VERSION = "phase5c-bibliography-registry/v1"
FREEZE_CLASS = "CANONICAL_KNOWLEDGE"

# document.source_type → item_type（**显式确定性映射**，不是猜）
SOURCE_TYPE_TO_ITEM = {
    "seminar_primary": "manuscript",
    "secondary_source": "book",
    "case_meeting": "manuscript",
}
# witness.witness_kind → item_type
WITNESS_KIND_TO_ITEM = {
    "transcription": "working_transcription",
    "translation": "translation",
    "edition_extract": "book",
}


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()


def jl(path):
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in sorted(rows, key=lambda x: json.dumps(x, ensure_ascii=False,
                                                       sort_keys=True)):
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def _fm(path):
    t = open(path, encoding="utf-8").read()
    if not t.startswith("---"):
        return {}
    block = t.split("---", 2)[1]
    out = {}
    for line in block.split("\n"):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def _sq(query, args=()):
    if not os.path.isfile(SQLITE):
        return []
    con = sqlite3.connect("file:%s?mode=ro" % SQLITE, uri=True)
    try:
        cur = con.cursor()
        cur.execute(query, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


# ─────────────────────────────────────────────────────────── 构建（§10–§12）
def build():
    """→ dict(works/editions/items/mappings/candidates/conflicts)。确定性。"""
    src_docs = _sq("select * from corpus_sources")
    witnesses = _sq("select * from witnesses")
    # §62：witness → passage 计数在**构建期**算好（一次聚合），
    # 这样打开书目详情**不会**扫描 249,105 个 passage。
    counts = {}
    for row in _sq("select witness_id, count(*) as n from passage_realizations "
                   "group by witness_id"):
        counts[row["witness_id"]] = row["n"]
    items, editions, works, mappings, candidates = [], [], [], [], []

    # ── 1) corpus_sources → 来源记录（**不是** BibliographicItem）
    for s in src_docs:
        mappings.append({
            "schema_version": M.SCHEMA_MAPPING,
            "mapping_id": "map.corpus-source.%s" % s["id"].split(".")[-1],
            "corpus_source_id": s["id"],
            "corpus_source_kind": s.get("kind"),
            "relation": "corpus_source_record",
            "review_status": "reviewed" if s.get("review_status") == "reviewed"
                             else "needs_review",
            "provenance": {"source": "passage_store.corpus_sources",
                           "fields": ["id", "name", "kind", "language",
                                      "authority_level", "url", "note"],
                           "note": s.get("note")},
        })

    # ── 2) witnesses → Edition（**仅** witness_kind == edition_extract）+ mapping
    for w in witnesses:
        wk = w.get("witness_kind")
        cs = w.get("corpus_source_id")
        mapping = {
            "schema_version": M.SCHEMA_MAPPING,
            "mapping_id": "map.witness.%s" % w["id"].split(".")[-1],
            "witness_id": w["id"],
            "witness_kind": wk,
            "corpus_source_id": cs,
            "relation": "witness_realizes",
            "review_status": "needs_review",
            "passage_count": counts.get(w["id"], 0),
            "passage_realization_layer": "passage_realizations（249,105 行）",
            "provenance": {"source": "passage_store.witnesses",
                           "source_file": w.get("source_file"),
                           "source_file_sha256": w.get("source_file_sha256"),
                           "note": w.get("provenance_note")},
        }
        if wk == "edition_extract":
            eid = "edition.%s" % w["id"].split(".")[-1]
            ed = {k: None for k in M.EDITION_FIELDS}
            ed.update({
                "schema_version": M.SCHEMA_EDITION,
                "edition_id": eid, "work_id": None,
                # §8：只使用**实际可验证**的 metadata；此处仓库未记录出版社/年份/ISBN
                "title": M.safe_text(w.get("edition")),
                "language": w.get("language"),
                "publisher": None, "year": None,
                "edition_statement": M.safe_text(w.get("edition")),
                "editors": [], "translators": [],
                "isbn": None,
                "page_locator_available": True,      # 该 witness 的 note 明确写"带 page 号"
                "bibliographic_id": None,
                "review_status": "needs_review",
                "provenance": {
                    "source": "passage_store.witnesses",
                    "witness_id": w["id"],
                    "why_publisher_null": "仓库未记录出版社字段（§8：不得据模型知识补）",
                    "page_locator_kind": "page",
                },
            })
            editions.append(ed)
            mapping["edition_id"] = eid
        else:
            # §7/§9：转录/中译**不是**出版物 → 不建 Edition，如实留空
            mapping["edition_id"] = None
            mapping["edition_not_linked_reason"] = (
                "working transcription（非瑟伊版定本）" if wk == "transcription"
                else "translation project with SOURCE_TRACE_INCOMPLETE（上游源目录已消失）")
        mappings.append(mapping)

        # ── 3) witness → BibliographicItem（**记录其文本实现身份**，非出版物）
        bid = "bib.witness.%s" % w["id"].split(".")[-1]
        it = M.blank_item(bid, WITNESS_KIND_TO_ITEM.get(wk, "other"))
        it.update({
            "title": M.safe_text(w.get("edition")),
            "language": w.get("language"),
            # §12：witness 身份来自**冻结 store 的机器可验证记录**（含 sha256），
            #   因此可入 reviewed registry，但依据必须显式标注为机器校验派生，
            #   与「人工 vault 复核」严格区分。
            "review_status": "reviewed",
            "review_basis": "MACHINE_VERIFIED_DERIVATION",
            "is_publication": False,
            "source_refs": [{"kind": "witness", "id": w["id"]},
                            {"kind": "corpus_source", "id": cs}],
            "provenance": {"source": "passage_store.witnesses", "witness_id": w["id"],
                           "note": w.get("provenance_note")},
            "metadata_provenance": {
                "title": {"value": w.get("edition"),
                          "source": "passage_store.witnesses.edition",
                          "review_status": "needs_review"},
                "publisher": {"value": None, "source": None,
                              "review_status": "unknown"},
                "publication_year": {"value": None, "source": None,
                                     "review_status": "unknown"},
            },
        })
        it["metadata_completeness"] = M.completeness(it)
        it["page_locator"] = (M.page_locator("page", "S1–S5（该 witness 声明带 page 号）",
                                             source="witness note")
                              if wk == "edition_extract" else None)
        items.append(it)
        mapping["bibliographic_id"] = bid
        mappings[-1] = mapping
        upd = [m for m in mappings if m.get("mapping_id") ==
               "map.witness.%s" % w["id"].split(".")[-1]]
        if upd:
            upd[0]["bibliographic_id"] = bid

    # ── 4) vault documents → BibliographicItem（+ Work/可选 Edition）
    for fn in sorted(os.listdir(DOCS_DIR)) if os.path.isdir(DOCS_DIR) else []:
        if not fn.endswith(".md"):
            continue
        fm = _fm(os.path.join(DOCS_DIR, fn))
        did = fm.get("id")
        if not did:
            continue
        reviewed = fm.get("review_status") == "reviewed"
        item_type = SOURCE_TYPE_TO_ITEM.get(fm.get("source_type"), "other")
        slug = did.replace("doc.", "")
        bid = "bib.doc.%s" % slug
        it = M.blank_item(bid, item_type)
        it.update({
            "title": M.safe_text(fm.get("canonical_name") or fm.get("title")),
            "short_title": M.safe_text(fm.get("title"), 300),
            "language": fm.get("language"),
            "edition": M.safe_text(fm.get("edition")),
            "review_status": "reviewed" if reviewed else "needs_review",
            "review_basis": ("HUMAN_VAULT_REVIEW" if reviewed
                             else "PENDING_HUMAN_REVIEW"),
            "is_publication": False,
            "source_refs": [{"kind": "document", "id": did}],
            "provenance": {"source": "01_Sources/Documents/%s" % fn,
                           "document_id": did,
                           "vault_review_status": fm.get("review_status"),
                           # §11：**不**从文本猜出版社/年份/ISBN
                           "no_metadata_inference": True},
            "metadata_provenance": {
                "title": {"value": fm.get("canonical_name"),
                          "source": "01_Sources/Documents/%s#canonical_name" % fn,
                          "review_status": fm.get("review_status")},
                "edition": {"value": fm.get("edition"),
                            "source": "01_Sources/Documents/%s#edition" % fn,
                            "review_status": fm.get("review_status")},
                "publisher": {"value": None, "source": None, "review_status": "unknown"},
                "publication_year": {"value": None, "source": None,
                                     "review_status": "unknown"},
                "authors": {"value": None, "source": None, "review_status": "unknown"},
            },
        })
        it["metadata_completeness"] = M.completeness(it)
        (items if reviewed else candidates).append(it)
        # Work 层（§5）：**只**由 canonical_name 逐字 + 确定性 id 规则建立
        cn = M.norm_text(fm.get("canonical_name"))
        if cn:
            wid = "work.%s" % slug
            works.append({
                "schema_version": M.SCHEMA_WORK,
                "work_id": wid,
                "title": cn,
                "language": fm.get("language"),
                "derivation_rule": "work.<doc-slug> := id(canonical_name) 的确定性映射；"
                                   "work 标题为 canonical_name 的**逐字**值",
                "bibliographic_ids": [bid],
                "review_status": "reviewed" if reviewed else "needs_review",
                "provenance": {"source": "01_Sources/Documents/%s" % fn,
                               "document_id": did},
            })
        mapping_doc = {
            "schema_version": M.SCHEMA_MAPPING,
            "mapping_id": "map.doc.%s" % slug,
            "document_id": did,
            "bibliographic_id": bid,
            "relation": "document_instantiates_item",
            "review_status": "reviewed" if reviewed else "needs_review",
            "provenance": {"source": "01_Sources/Documents/%s" % fn},
        }
        mappings.append(mapping_doc)

    # 把 work ↔ item 互链（只对已有 work 的 item）
    wmap = {w["work_id"]: w for w in works}
    for it in items + candidates:
        for w in works:
            if it["bibliographic_id"] in (w.get("bibliographic_ids") or []):
                it["work_id"] = w["work_id"]

    bad = [i["bibliographic_id"] for i in items if i.get("review_status") != "reviewed"]
    if bad:
        raise SystemExit("REGISTRY_INVARIANT: items 只能承载 reviewed —— %s" % bad)
    return {"works": works, "editions": editions, "items": items,
            "mappings": mappings, "candidates": candidates,
            "conflicts": []}


def write_all(res, store=STORE):
    write_jsonl(os.path.join(store, "works.jsonl"), res["works"])
    write_jsonl(os.path.join(store, "editions.jsonl"), res["editions"])
    write_jsonl(os.path.join(store, "items.jsonl"), res["items"])
    write_jsonl(os.path.join(store, "mappings.jsonl"), res["mappings"])
    write_jsonl(os.path.join(store, "candidates.jsonl"), res["candidates"])
    write_jsonl(os.path.join(store, "conflicts.jsonl"), res.get("conflicts") or [])
    man = {
        "schema_version": SCHEMA_VERSION,
        "freeze_class": FREEZE_CLASS,
        "source_of_truth": "bibliography registry（§53）；Zotero 是外部导入源，不是真源",
        "rebuildable_index": "_index/bibliography.sqlite（registry → index，不可反向，§54）",
        "counts": {"works": len(res["works"]), "editions": len(res["editions"]),
                   "items": len(res["items"]), "candidates": len(res["candidates"]),
                   "mappings": len(res["mappings"]),
                   "conflicts": len(res.get("conflicts") or [])},
        "reviewed_items": sorted(i["bibliographic_id"] for i in res["items"]),
        "candidate_items": sorted(i["bibliographic_id"] for i in res["candidates"]),
        "no_metadata_inference": True,
        "no_fake_page": True,
        "entities_are_distinct": ["Passage", "Witness", "Edition", "BibliographicItem",
                                  "CorpusSource", "ProjectBibliographyRef", "ZoteroItem"],
        "content_hash": _sha({k: (res[k] if k != "conflicts" else res.get(k) or [])
                              for k in ("works", "editions", "items", "mappings",
                                        "candidates")}),
    }
    os.makedirs(store, exist_ok=True)
    with open(os.path.join(store, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    return man


# ─────────────────────────────────────────────────────────── 读取/查询（只读）
def manifest(store=STORE):
    p = os.path.join(store, "manifest.json")
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


def items(store=STORE):
    return jl(os.path.join(store, "items.jsonl"))


def editions(store=STORE):
    return jl(os.path.join(store, "editions.jsonl"))


def works(store=STORE):
    return jl(os.path.join(store, "works.jsonl"))


def mappings(store=STORE):
    return jl(os.path.join(store, "mappings.jsonl"))


def candidates(store=STORE):
    return jl(os.path.join(store, "candidates.jsonl"))


def get(bibliographic_id, store=STORE):
    for it in items(store) + candidates(store):
        if it["bibliographic_id"] == bibliographic_id:
            return it
    raise KeyError("UNKNOWN_BIBLIOGRAPHIC_ITEM: %s" % bibliographic_id)


def capabilities(bibliographic_id, store=STORE):
    return M.capability_flags(get(bibliographic_id, store))


def witness_chain(witness_id, store=STORE):
    """§17：只显示**实际存在**的层；缺层如实写 not_linked。"""
    w = [m for m in mappings(store) if m.get("witness_id") == witness_id]
    if not w:
        raise KeyError("UNKNOWN_WITNESS: %s" % witness_id)
    m = w[0]
    sample = _sq("select passage_id from passage_realizations where witness_id=? "
                 "order by passage_id limit 5", (witness_id,))
    chain = {
        "passage_realization": {
            "layer": "PassageRealization",
            "witness_id": witness_id,
            "passage_count": (m.get("passage_count") or 0),
            "sample_passage_ids": [r["passage_id"] for r in sample],
            "note": "PassageRealization 是 Passage 在该 witness 下的**文本实现**（§17）。",
        },
        "witness": witness_id,
        "witness_kind": m.get("witness_kind"),
        "edition": m.get("edition_id") or "Not linked",
        "edition_linked": bool(m.get("edition_id")),
        "bibliographic_item": m.get("bibliographic_id") or "Not linked",
        "corpus_source": m.get("corpus_source_id") or "Not linked",
        "relation": m.get("relation"),
        "provenance": m.get("provenance") or {},
        "missing_layers": ([k for k in ("passage_realization", "edition",
                                        "bibliographic_item", "corpus_source")
                            if not (m.get("passage_count") if k == "passage_realization"
                                    else m.get({"edition": "edition_id",
                                                "bibliographic_item": "bibliographic_id",
                                                "corpus_source": "corpus_source_id"}[k]))]
                           if True else []),
        "note": ("缺层如实标注；不补、不猜（§17）。"
                 + (" **PassageRealization = 0**：该 witness 的分段从未进入 canonical "
                    "passage store，因此 Passage→Edition 这一层在证据上无法建立 —— "
                    "这是事实，不是待补的空位。"
                    if not (m.get("passage_count") or 0) else "")),
    }
    if m.get("edition_id"):
        ed = [e for e in editions(store) if e["edition_id"] == m["edition_id"]]
        chain["edition_record"] = ed[0] if ed else None
    return chain


def search(q=None, author=None, year=None, language=None, item_type=None,
           review_status=None, cursor=0, limit=20, store=STORE):
    """服务端过滤 + 分页（§19）。只遍历 registry（**不**扫 passage，§40/§62）。"""
    qq = M.norm_text(q).lower()
    rows = items(store) + candidates(store)
    out = []
    for it in rows:
        if qq and qq not in " ".join([
                str(it.get("title") or ""), str(it.get("short_title") or ""),
                str(it.get("edition") or ""),
                " ".join(it.get("authors") or [])]).lower():
            continue
        if author and not any(M.norm_text(a).lower() == M.norm_text(author).lower()
                              for a in (it.get("authors") or [])):
            continue
        if year is not None and str(it.get("publication_year") or "") != str(year):
            continue
        if language and it.get("language") != language:
            continue
        if item_type and it.get("item_type") != item_type:
            continue
        if review_status and it.get("review_status") != review_status:
            continue
        out.append(it)
    out.sort(key=lambda r: r["bibliographic_id"])
    off = max(0, int(cursor or 0))
    lim = max(1, min(int(limit or 20), 50))
    page = out[off:off + lim]
    return {"schema_version": "phase5c-bibliography-search/v1",
            "items": page,
            "page": {"offset": off, "limit": lim, "returned": len(page),
                     "total": len(out), "next_offset": off + lim
                     if off + lim < len(out) else None},
            "filters": {"q": q, "author": author, "year": year, "language": language,
                        "item_type": item_type, "review_status": review_status},
            "note": ("书目层只呈现 metadata relation；**不**生成理论相关性判断（§21）。")}
