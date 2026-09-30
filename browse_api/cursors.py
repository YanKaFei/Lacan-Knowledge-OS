#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browse_api.cursors — 稳定 cursor 分页（Phase 4D.4 §44/§60/§61）

要求：
    * 不靠 `offset=200000`（深翻页在 249k 行上不可接受，也容易被并发写坏）；
    * **稳定顺序**：同一 filters+cursor 重复调用 → 结果顺序一致；
    * page1 ∩ page2 = ∅，且合起来与「一次性 filtered sample」逐行一致；
    * cursor 与 filters 绑定：换了 filters 还拿旧 cursor 必须**显式报错**，
      而不是悄悄返回错位的页（那会静默丢行）。
"""
from __future__ import annotations

import base64
import hashlib
import json

CURSOR_VERSION = "browse-cursor/v1"


class CursorError(ValueError):
    """cursor 非法 / 与 filters 不匹配。"""


def filter_fingerprint(filters) -> str:
    blob = json.dumps(filters or {}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def encode(kind: str, filters, key) -> str:
    payload = {"v": CURSOR_VERSION, "k": kind, "f": filter_fingerprint(filters),
               "key": list(key) if isinstance(key, (list, tuple)) else key}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode(cursor: str, kind: str, filters):
    """→ sort key（list 或标量）。非法或不匹配 → CursorError（fail closed）。"""
    if cursor in (None, ""):
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + pad).decode("utf-8"))
    except Exception as exc:                                     # noqa: BLE001
        raise CursorError("cursor 无法解析") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise CursorError("cursor 版本不支持")
    if payload.get("k") != kind:
        raise CursorError("cursor 与查询类型不匹配")
    if payload.get("f") != filter_fingerprint(filters):
        raise CursorError("cursor 与当前 filters 不匹配（换了筛选条件就必须从第一页开始）")
    return payload.get("key")


def page_meta(kind, filters, limit, n, has_more, next_key=None, cursor_in=None,
              total=None):
    """分页元信息。`next_key` = 下一页游标所指的**最后一行排序键**（无下一页则 None）。"""
    out = {"cursor_in": (encode(kind, filters, cursor_in) if cursor_in is not None
                         else None),
           "next_cursor": (encode(kind, filters, next_key) if next_key is not None
                           else None),
           "limit": limit, "returned": n, "has_more": bool(has_more),
           "order": _ORDER.get(kind, kind),
           "filter_fingerprint": filter_fingerprint(filters)}
    if total is not None:
        out["total"] = total
    return out


_ORDER = {
    "passages": "passage_id ASC (lexicographic, unique)",
    "session": "(sequence_in_session, passage_id) ASC (unique)",
    "concepts": "concept_id ASC (lexicographic, unique)",
    "seminars": "seminar_id ASC (lexicographic, unique)",
    "terminology": "term ASC (lexicographic, unique)",
}
