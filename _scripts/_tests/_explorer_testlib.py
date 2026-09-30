#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_explorer_testlib.py — 4D.4 Explorer 测试共享工具（下划线开头 → 不被收集）"""
from __future__ import annotations
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for p in (VAULT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import browse_api as B                                            # noqa: E402
from workspace_ui.server import explorer as X                     # noqa: E402

LEX = os.path.join(VAULT, "_data", "index", "lexical.sqlite")

# 验收案例（§58）
C_OBJET_A = "concept.objet-petit-a"
C_GAZE = "concept.gaze"
C_JOUI = "concept.jouissance"
C_REEL = "concept.le-reel"
C_REALITE = "concept.realite"
P_L1 = "passage.S11.unknown.P2253"          # fr / L1 / COMPLETE
P_L2 = "passage.S05.unknown.L05.P0056"      # zh / L2 / SOURCE_TRACE_INCOMPLETE
S_SEMINAR = "S11"
S_SESSION = "session.S11.unknown.L01"


def raw_ids(where="", args=()):
    """直接用 SQL 取全库真值（作为分页/过滤的**参照实现**，不是被测代码）。"""
    con = sqlite3.connect("file:%s?mode=ro" % LEX, uri=True)
    try:
        return [r[0] for r in con.execute(
            "select id from passage_meta %s order by id" % where, args)]
    finally:
        con.close()


def page_ids(filters, limit=20, max_pages=400):
    """按 cursor 连续翻页 → (ids, pages)。用于验证「不重不漏」。"""
    ids, pages, cursor = [], 0, None
    while pages < max_pages:
        out = B.browse_passages(dict(filters, limit=limit), cursor=cursor)
        ids.extend(x["passage_id"] for x in out["items"])
        pages += 1
        cursor = out["page"].get("next_cursor")
        if not cursor:
            break
    return ids, pages


def save_marker(name, payload):
    """把 QA 证据写到 _workspace（USER_WORKSPACE），供报告引用。"""
    d = os.path.join(VAULT, "_workspace", "explorer_qa")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    return p


def fresh_vault(name):
    import _obsidian_testlib as OL                                # noqa: PLC0415
    return OL.fresh_vault(name)
