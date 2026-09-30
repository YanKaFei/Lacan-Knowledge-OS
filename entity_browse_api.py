#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""entity_browse_api — Phase 5B：**只读、分页、确定性**的 Person / Case 浏览 API。

设计铁律（§28/§30/§31）——本模块是"提及证据"的唯一出口，**不提供任何推断**：

    mention      → influence              禁止
    co-occurrence→ theoretical relation   禁止
    case mention → case analysis          禁止
    Person       → Case automatic collapse 禁止
    alias        → conceptual synonym     禁止

因此：
  * 没有任何 `influence` / `relation` / `analysis` / `causal` 端点；
    调用这些名字一律抛 `InferenceNotSupported`（显式拒绝，不是返回空）。
  * 每个响应都带 `evidence_kind = "MENTION_ONLY"` 与三个 `asserts_* = false`。
  * `person.schreber` 与 `case.schreber` 是**不同实体**，任何把二者折叠的请求都被拒绝。
  * 分页是**确定性**的：稳定排序 + 不透明游标（base64(offset)），游标可校验。

数据来源：`_data/entities/`（由 `build_entity_registries.py` 确定性生成）。
本模块**只读**，不写任何工件；且不 import 冻结学术核心。
"""
from __future__ import annotations

import base64
import json
import os

# 本模块位于仓库根 → 仓库根就是 HERE（不是它的父目录）
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = HERE
ENT = os.path.join(VAULT, "_data", "entities")

MAX_LIMIT = 50
DEFAULT_LIMIT = 20

# §31：被显式拒绝的推断性操作名（不是"未实现"，而是**设计上禁止**）
FORBIDDEN_OPERATIONS = (
    "influence", "influences", "influenced_by", "relation", "relations",
    "theoretical_relation", "analysis", "case_analysis", "causal", "causality",
    "synonym", "concept_of", "collapse", "merge", "person_to_case",
)


class InferenceNotSupported(ValueError):
    """请求了一个**设计上禁止**的推断端点（§31 no-inference gate）。"""


def _load(name):
    p = os.path.join(ENT, name)
    if not os.path.isfile(p):
        raise FileNotFoundError("缺登记表 %s（先跑 build_entity_registries.py）"
                                % os.path.relpath(p, VAULT))
    with open(p, encoding="utf-8") as f:
        return json.load(f)


_REG = {}


def _registry(kind):
    if kind not in _REG:
        doc = _load("person_registry.json" if kind == "person" else "case_registry.json")
        _REG[kind] = doc
    return _REG[kind]


def _mentions_path():
    return os.path.join(ENT, "mention_index.jsonl")


def encode_cursor(offset):
    return base64.urlsafe_b64encode(b"off:%d" % int(offset)).decode("ascii")


def decode_cursor(cursor):
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(str(cursor).encode("ascii")).decode("ascii")
        if not raw.startswith("off:"):
            raise ValueError("游标形状非法")
        n = int(raw[4:])
        if n < 0:
            raise ValueError("游标越界")
        return n
    except Exception as exc:                                               # noqa: BLE001
        raise ValueError("INVALID_CURSOR: %s" % exc)


def _envelope(kind, items, cursor, limit, total, extra=None):
    off = decode_cursor(cursor)
    nxt = off + limit
    out = {
        "schema_version": "phase5b-entity-browse/v1",
        "kind": kind,
        # §31：**提及证据**的显式自述
        "evidence_kind": "MENTION_ONLY",
        "asserts_influence": False,
        "asserts_theoretical_relation": False,
        "asserts_case_analysis": False,
        "mention_never_implies_influence": True,
        "cooccurrence_never_implies_relation": True,
        "case_mention_never_implies_analysis": True,
        "person_never_auto_collapses_into_case": True,
        "alias_never_implies_conceptual_synonym": True,
        "items": items,
        "page": {"cursor_in": cursor, "offset": off, "limit": limit,
                 "returned": len(items), "total": total,
                 "next_cursor": encode_cursor(nxt) if nxt < total else None,
                 "deterministic": True},
    }
    if extra:
        out.update(extra)
    return out


def list_persons(cursor=None, limit=DEFAULT_LIMIT):
    doc = _registry("person")
    rows = sorted(doc.get("reviewed") or [], key=lambda r: r["id"])
    off = decode_cursor(cursor)
    lim = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    page = rows[off:off + lim]
    return _envelope("person", [_brief(r) for r in page], cursor, lim, len(rows),
                     {"candidates_not_promoted_n": len(doc.get("candidates_not_promoted") or [])})


def list_cases(cursor=None, limit=DEFAULT_LIMIT):
    doc = _registry("case")
    rows = sorted(doc.get("reviewed") or [], key=lambda r: r["id"])
    off = decode_cursor(cursor)
    lim = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    page = rows[off:off + lim]
    return _envelope("case", [_brief(r) for r in page], cursor, lim, len(rows),
                     {"candidates_not_promoted_n": len(doc.get("candidates_not_promoted") or [])})


def _brief(r):
    return {"id": r["id"], "kind": r["kind"], "label": r.get("label"),
            "label_zh": r.get("label_zh"), "aliases": r.get("aliases"),
            "mention_count": r.get("mention_count"),
            "review_status": r.get("review_status"),
            "evidence_kind": r.get("evidence_kind", "MENTION_ONLY"),
            "subject_person": r.get("subject_person")}


def get_person(entity_id):
    return _get("person", entity_id)


def get_case(entity_id):
    return _get("case", entity_id)


def _get(kind, entity_id):
    eid = str(entity_id or "")
    # §30：拒绝跨 kind 折叠
    if eid.startswith("person.") and kind == "case":
        raise InferenceNotSupported(
            "PERSON_CASE_COLLAPSE_FORBIDDEN：person.* 不是 case（§31）")
    if eid.startswith("case.") and kind == "person":
        raise InferenceNotSupported(
            "CASE_PERSON_COLLAPSE_FORBIDDEN：case.* 不是 person（§31）")
    doc = _registry(kind)
    for r in (doc.get("reviewed") or []) + (doc.get("candidates_not_promoted") or []):
        if r["id"] == eid:
            out = dict(r)
            out["evidence_kind"] = r.get("evidence_kind", "MENTION_ONLY")
            out["asserts_influence"] = False
            out["asserts_theoretical_relation"] = False
            out["asserts_case_analysis"] = False
            out["mention_index_href"] = "entity_browse_api.mentions(%r)" % eid
            if kind == "case":
                out["subject_person_link"] = r.get("subject_person_link")
                out["person_case_are_distinct_entities"] = True
            return out
    raise KeyError("UNKNOWN_ENTITY: %s" % eid)


def mentions(entity_id, cursor=None, limit=DEFAULT_LIMIT):
    """→ 该实体的**提及**页（只读、确定性、可分页）。"""
    eid = str(entity_id or "")
    off = decode_cursor(cursor)
    lim = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    rows, total = [], 0
    with open(_mentions_path(), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("entity_id") != eid:
                continue
            total += 1
            if off <= total - 1 < off + lim:
                rows.append(r)
    return _envelope("mention", rows, cursor, lim, total,
                     {"entity_id": eid,
                      "note": "每条提及只证明**出现**；不含任何影响/关系/分析判断。"})


def search(q, kind=None, cursor=None, limit=DEFAULT_LIMIT):
    """按 label / alias / id 的确定性子串检索（不排序打分、不做语义扩展）。"""
    qq = str(q or "").strip().lower()
    off = decode_cursor(cursor)
    lim = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    kinds = [kind] if kind in ("person", "case") else ["person", "case"]
    hits = []
    for k in kinds:
        doc = _registry(k)
        for r in sorted(doc.get("reviewed") or [], key=lambda x: x["id"]):
            blob = " ".join([r["id"], str(r.get("label") or ""),
                             str(r.get("label_zh") or ""),
                             " ".join(r.get("aliases") or [])]).lower()
            if qq and qq in blob:
                hits.append(_brief(r))
    hits.sort(key=lambda r: r["id"])
    page = hits[off:off + lim]
    return _envelope("search", page, cursor, lim, len(hits), {"query": q})


def guarded(operation, *args, **kwargs):
    """拒绝一切推断性操作（§31 的**显式**入口）。"""
    if str(operation or "").lower() in FORBIDDEN_OPERATIONS:
        raise InferenceNotSupported(
            "FORBIDDEN_OPERATION: %s —— 本 API 只提供提及证据，"
            "不提供影响/理论关系/个案分析/实体折叠/概念同义（Phase 5B §31）"
            % operation)
    raise InferenceNotSupported("UNKNOWN_OPERATION: %s" % (operation,))


def manifest():
    doc = _load("registry_manifest.json")
    return {"schema_version": "phase5b-entity-browse-manifest/v1",
            "registry_manifest": doc,
            "api": {"read_only": True, "paginated": True, "deterministic": True,
                    "forbidden_operations": list(FORBIDDEN_OPERATIONS),
                    "max_limit": MAX_LIMIT,
                    "evidence_kind": "MENTION_ONLY"}}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        print(json.dumps({"persons": list_persons(limit=3)["page"],
                          "cases": list_cases(limit=3)["page"],
                          "manifest": manifest()["api"]}, ensure_ascii=False, indent=1)[:1200])
    else:
        print(json.dumps(manifest(), ensure_ascii=False, indent=1))
