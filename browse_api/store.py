#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browse_api.store — Explorer 的**只读**数据源句柄（Phase 4D.4 §42/§43）

定位（§41/§43）：
    这是 **Corpus Browse** 层，不是 **Research Retrieval**。
    * 不调用 LLM、不 import 冻结核心内部、不做任何写入；
    * 只读**已存在的派生索引**与**canonical 元数据**；
    * 结果全部是「语料里有什么」，不是「学术上意味着什么」。

只读数据源
──────────
    _data/index/lexical.sqlite       passage_meta（249,105 行）+ fr_fts / zh_fts
    _index/passage_store.sqlite      seminars / sessions / witnesses / translations /
                                     corpus_sources / passage_realizations /
                                     passage_witnesses
    _data/ontology/v4a1/*.jsonl      entities / relations / term_mappings（canonical ontology）
    _data/passage_store/*.jsonl      concepts / concept_states（术语目录层）

两类事实必须始终分开（§33）：
    ontology_* → 「本体里记了这条关系/映射」（可能还是 candidate）
    corpus_*   → 「语料里实际出现这个字面形式」（deterministic 计数）

连接策略：SQLite 以 `mode=ro` 打开；Web 服务是多线程的，因此**每次调用新建连接**
（开销约 1ms），不共享 connection 对象。小体积的 ontology/catalog 直接解析为内存结构。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)

LEXICAL_DB = os.path.join(VAULT, "_data", "index", "lexical.sqlite")
STORE_DB = os.path.join(VAULT, "_index", "passage_store.sqlite")
ONTOLOGY_DIR = os.path.join(VAULT, "_data", "ontology", "v4a1")
CATALOG_CONCEPTS = os.path.join(VAULT, "_data", "passage_store", "concepts.jsonl")
CATALOG_STATES = os.path.join(VAULT, "_data", "passage_store", "concept_states.jsonl")

BROWSE_API_VERSION = "browse-api/v1"
CORPUS_TOTAL = 249105          # 实测常量；由 store.count() 现算为准

# 语料里可能出现的 matheme 形式（§25：只做**确定性模式识别**，不做 LLM 生成）
#
# ⚠️ 单独一个 `J` 在法语正文里几乎全是省音/缩写：实测宽松的 `\bJ\b` 在 S11 命中的
#    64 条**全部**是 `J’ai / J’in / J’en / J’es…`。因此 `J` 只在「前面不是字母、
#    后面不是字母/点/撇号」时才算 matheme —— 宁可少报，也不伪造一个公式索引。
FORMALISM_PATTERNS = (
    ("$ ◊ a", r"\$\s*[◊◇]\s*a"),
    ("S ◊ a", r"S\s*[◊◇]\s*a"),
    ("a ◊ $", r"a\s*[◊◇]\s*\$"),
    ("S(Ⱥ)", r"S\s*\(\s*[ȺA]\s*\)"),
    ("S(A)", r"S\s*\(\s*A\s*\)"),
    ("Φ", r"Φ"),
    ("J", "(?<![A-Za-z])J(?![A-Za-z.\u2019\u02bc'])"),
    ("Σ", r"Σ"),
    ("I(A)", r"I\s*\(\s*A\s*\)"),
    ("i(a)", r"i\s*\(\s*a\s*\)"),
)
# 这些模式**故意不收录**（会在正文里大量误报），记录在此以便复核：
FORMALISM_EXCLUDED = (
    {"pattern": r"\bJ\b", "reason": "matches French elision (J’ai) — false positives"},
    {"pattern": r"(?i)\ba\b", "reason": "ordinary French preposition/article 'a'"},
    {"pattern": r"(?i)\bS\b", "reason": "ordinary initial S. and abbreviation"},
)

_LOCK = threading.Lock()
_CACHE: dict = {}


class BrowseUnavailable(RuntimeError):
    """派生索引缺失（可重建）。调用方应把它变成 INDEX_UNAVAILABLE 文案。"""


# ─────────────────────────────────────────────────────────── 连接
def lexical():
    if not os.path.isfile(LEXICAL_DB):
        raise BrowseUnavailable("lexical index 缺失：%s（可重建）" % LEXICAL_DB)
    con = sqlite3.connect("file:%s?mode=ro" % LEXICAL_DB, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def store():
    if not os.path.isfile(STORE_DB):
        raise BrowseUnavailable("passage store sqlite 缺失：%s（可重建）" % STORE_DB)
    con = sqlite3.connect("file:%s?mode=ro" % STORE_DB, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def availability():
    """→ 数据源可用性（UI 必须如实展示，不得假装 dense 可用，§10）。"""
    import importlib.util                                        # noqa: PLC0415
    numpy_ok = importlib.util.find_spec("numpy") is not None
    vec = os.path.join(VAULT, "_data", "index", "vector")
    vec_files = []
    if os.path.isdir(vec):
        vec_files = [f for f in os.listdir(vec) if f.endswith((".npy", ".faiss", ".hnsw"))]
    return {
        "browse_api_version": BROWSE_API_VERSION,
        "lexical_index": os.path.isfile(LEXICAL_DB),
        "passage_store_sqlite": os.path.isfile(STORE_DB),
        "ontology": os.path.isdir(ONTOLOGY_DIR),
        "dense_available": bool(numpy_ok and vec_files),
        "dense_reason": (None if (numpy_ok and vec_files)
                         else ("no local embedding runtime (numpy/vector index unavailable)")),
        "retrieval_mode": "lexical",
    }


# ─────────────────────────────────────────────────────────── 小工具
def fold(text):
    """术语折叠：NFKC + casefold（**只做形式归一，不做近义合并**）。"""
    return unicodedata.normalize("NFKC", str(text or "")).casefold().strip()


_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _like_escape(s):
    return (str(s).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"))


def count_passages(where="", args=()):
    with lexical() as con:
        row = con.execute("select count(*) from passage_meta " + where, args).fetchone()
    return int(row[0])


def corpus_total():
    key = "corpus_total"
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    n = count_passages()
    with _LOCK:
        _CACHE[key] = n
    return n


def attestation(form, language=None):
    """语料里**字面形式**的出现次数（deterministic 子串匹配，不推理、不妨假）。

    §30/§33：这是 corpus attestation，与「ontology 里有没有这条映射」是两件事。
    0 就是 0：`Zero corpus attestation` 必须显示，不得回退到别层。
    """
    form = str(form or "").strip()
    if not form:
        return {"form": form, "hits": 0, "language": language, "mode": "substring"}
    key = "att:%s|%s" % (form, language)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    where = "where raw_text like ? escape '\\'"
    args = ["%" + _like_escape(form) + "%"]
    if language:
        where += " and language = ?"
        args.append(language)
    # 拉丁形式大小写不敏感：加一个 lower() 兜底（CJK 不受影响）
    if not _CJK.search(form):
        where = "where lower(raw_text) like ? escape '\\'"
        args[0] = "%" + _like_escape(form.casefold()) + "%"
        if language:
            where += " and language = ?"
    hits = count_passages(where, tuple(args))
    out = {"form": form, "hits": hits, "language": language, "mode": "substring",
           "zero": hits == 0}
    with _LOCK:
        _CACHE[key] = out
    return out


# ─────────────────────────────────────────────────────────── ontology / catalog
def _read_jsonl(path):
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:                                    # noqa: BLE001
                continue
    return out


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _cached(name, path, loader):
    sig = _mtime(path)
    with _LOCK:
        hit = _CACHE.get(name)
        if hit and hit[0] == sig:
            return hit[1]
    data = loader(path)
    with _LOCK:
        _CACHE[name] = (sig, data)
    return data


def ontology_entities():
    return _cached("ont_entities", os.path.join(ONTOLOGY_DIR, "entities.jsonl"),
                   _read_jsonl)


def ontology_relations():
    return _cached("ont_relations", os.path.join(ONTOLOGY_DIR, "relations.jsonl"),
                   _read_jsonl)


def ontology_term_mappings():
    return _cached("ont_mappings", os.path.join(ONTOLOGY_DIR, "term_mappings.jsonl"),
                   _read_jsonl)


def catalog_concepts():
    return _cached("cat_concepts", CATALOG_CONCEPTS, _read_jsonl)


def catalog_states():
    return _cached("cat_states", CATALOG_STATES, _read_jsonl)


# ─────────────────────────────────────────────────────────── 统一 concept 视图
def _concept_forms(rec, layers):
    """→ 该概念的**字面形式**集合（每个都标明它来自哪一层）。"""
    forms = []
    seen = set()

    def add(form, source, language=None):
        f = str(form or "").strip()
        if not f or f in seen:
            return
        seen.add(f)
        forms.append({"form": f, "source": source, "language": language})

    for src in layers:
        add(rec.get("canonical_name"), src)
        for f in (rec.get("aliases") or []):
            add(f, src + ".aliases")
        for lang in ("fr", "zh", "en"):
            add(rec.get(lang), src + "." + lang)
    return forms


def concept_index():
    """→ {concept_id: 合并视图}（catalog 层 + ontology 层，**两层来源分别标注**）。

    §33：合并的是**身份**（同一个 id），不是把两层的权威性混为一谈 ——
    视图里保留 `layers`，任何字段都能回溯它来自哪一层。
    """
    key = "concept_index"
    sig = tuple(_mtime(p) for p in (CATALOG_CONCEPTS,
                                    os.path.join(ONTOLOGY_DIR, "entities.jsonl")))
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    idx: dict = {}
    for rec in catalog_concepts():
        cid = rec.get("id")
        if not cid:
            continue
        idx.setdefault(cid, {"concept_id": cid, "layers": [], "records": {}})
        idx[cid]["layers"].append("catalog")
        idx[cid]["records"]["catalog"] = rec
        idx[cid].setdefault("entity_role", rec.get("entity_role") or "concept")
    for rec in ontology_entities():
        cid = rec.get("id")
        if not cid:
            continue
        idx.setdefault(cid, {"concept_id": cid, "layers": [], "records": {}})
        idx[cid]["layers"].append("ontology")
        idx[cid]["records"]["ontology"] = rec
        idx[cid]["entity_role"] = rec.get("entity_role") or idx[cid].get("entity_role")

    for cid, item in idx.items():
        ont = item["records"].get("ontology") or {}
        cat = item["records"].get("catalog") or {}
        item["preferred_label"] = (ont.get("canonical_name") or cat.get("canonical_name")
                                   or cat.get("title") or cid)
        item["fr"] = ont.get("fr") or cat.get("fr")
        item["zh"] = ont.get("zh") or cat.get("zh")
        item["en"] = ont.get("en") or cat.get("en")
        item["forms"] = _concept_forms(ont, ["ontology"]) + \
            [f for f in _concept_forms(cat, ["catalog"])
             if f["form"] not in {x["form"] for x in _concept_forms(ont, ["ontology"])}]
        item["review_status"] = ont.get("review_status") or cat.get("review_status")
        item["canonical"] = bool(ont.get("canonical") or cat.get("canonical"))
        item["ontology_status"] = ont.get("status")
        item["authority_level"] = ont.get("authority_level") or cat.get("authority_level")
        item["definition_status"] = ont.get("definition_status") or (
            "recorded" if cat.get("definition") else "not_written_backlog")
        item["evidence_passages"] = list(ont.get("passages") or [])
        item["evidence_n"] = int(ont.get("passage_evidence_n") or 0)
        item["distinction_from"] = list(ont.get("distinction_from") or [])
        item["ontology_version"] = ont.get("schema_version") or cat.get("schema_version")
    with _LOCK:
        _CACHE[key] = (sig, idx)
    return idx


def relations_by_concept():
    """→ {concept_id: [relation...]}（relation 保留 review_status，绝不升级为 reviewed）。"""
    out: dict = {}
    for rel in ontology_relations():
        for side in ("subject", "object"):
            cid = rel.get(side)
            if not cid:
                continue
            out.setdefault(cid, []).append(rel)
    return out


def _rel_status_bucket(rel):
    st = str(rel.get("review_status") or "").lower()
    return "reviewed" if st in ("reviewed", "approved", "canonical") else "candidate"


def relations_view(concept_id):
    """§7B/§34：reviewed 与 candidate **分开**列出，candidate 绝不混入 canonical graph。"""
    rels = relations_by_concept().get(concept_id, [])
    idx = concept_index()
    reviewed, candidate = [], []
    for rel in rels:
        other = rel["object"] if rel["subject"] == concept_id else rel["subject"]
        row = {
            "relation_id": rel.get("relation_id"),
            "predicate": rel.get("predicate"),
            "direction": "out" if rel.get("subject") == concept_id else "in",
            "other_id": other,
            "other_label": (idx.get(other) or {}).get("preferred_label") or other,
            "review_status": rel.get("review_status"),
            "status_bucket": _rel_status_bucket(rel),
            "authority_level": rel.get("authority_level"),
            "confidence": rel.get("confidence"),
            "ontology_source": rel.get("layer") or "ontology.v4a1",
            "created_by": rel.get("created_by"),
            "evidence": (rel.get("evidence") or {}),
        }
        (reviewed if row["status_bucket"] == "reviewed" else candidate).append(row)
    for group in (reviewed, candidate):
        group.sort(key=lambda r: (str(r.get("predicate")), str(r.get("other_id"))))
    return {"reviewed": reviewed, "candidate": candidate,
            "reviewed_n": len(reviewed), "candidate_n": len(candidate)}


def seminar_of_passage(passage_id):
    m = re.match(r"^passage\.(S\d+[A-Z]?)\.", str(passage_id or ""))
    return "seminar.%s" % m.group(1) if m else None


def seminars_index():
    """→ {seminar_id: row}（来自派生 sqlite 的 seminars 表）。"""
    with store() as con:
        rows = [dict(r) for r in con.execute("select * from seminars order by id")]
    return {r["id"]: r for r in rows}


def sessions_index():
    with store() as con:
        rows = [dict(r) for r in con.execute("select * from sessions order by id")]
    return {r["id"]: r for r in rows}


def witnesses_index():
    with store() as con:
        rows = [dict(r) for r in con.execute("select * from witnesses order by id")]
    return {r["id"]: r for r in rows}


def translations_index():
    with store() as con:
        rows = [dict(r) for r in con.execute("select * from translations order by id")]
    return {r["id"]: r for r in rows}


TRANSLATIONS_JSONL = os.path.join(VAULT, "_data", "passage_store", "translations.jsonl")


def translation_notes():
    """→ {translation_id: {provenance_note, source_state, edition}}。

    ⚠️ 实测：派生 sqlite 的 `translations` 表**没有** provenance_note 列，
    而 canonical JSONL 有（L2 中译的「上游源目录已消失，未经审核不得升级为 canonical」
    就写在里面）。这条 provenance 说明不能丢，所以读这个小文件（979 B，只读、可重建映射）。
    """
    key = "translation_notes"
    sig = _mtime(TRANSLATIONS_JSONL)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    out = {}
    for rec in _read_jsonl(TRANSLATIONS_JSONL):
        tid = rec.get("id")
        if tid:
            out[tid] = {"provenance_note": rec.get("provenance_note"),
                        "source_state": rec.get("source_state"),
                        "edition": rec.get("edition"),
                        "authority_level": rec.get("authority_level")}
    with _LOCK:
        _CACHE[key] = (sig, out)
    return out


def translations_by_witness():
    """→ {witness_id: translation row}。

    实测：`passage_meta` **没有** translation_id 列，但 translation 记录里有
    witness_id —— 这正是可用的连接键（L2 中译的 provenance_note 就挂在 translation
    上，而不是 witness 上）。
    """
    out = {}
    for row in translations_index().values():
        wid = row.get("witness_id")
        if wid and wid not in out:
            out[wid] = row
    return out


def corpus_sources_index():
    with store() as con:
        rows = [dict(r) for r in con.execute("select * from corpus_sources order by id")]
    return {r["id"]: r for r in rows}


def clear_cache():
    with _LOCK:
        _CACHE.clear()
