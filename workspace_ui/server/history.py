#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui.server.history — 4D.2 §24/§42：产品工作区历史（USER_WORKSPACE）

* 只写 `_workspace/history/**`（`scholarly_api.policy` 归为 USER_WORKSPACE）；
* 通过 `policy.write_json` 落盘 —— 试图写到核心会抛 `CoreMutationError`；
* 历史**不是 evidence**（§25）：它只保存请求与答案快照，供回看/继续追问；
  任何学术结论必须重新由 corpus 支撑。
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timezone

from scholarly_api import policy as P

from . import config as C


def _slug(text, n=6):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (text or "").strip())[:40].strip("-")
    words = [w for w in s.split("-") if w][:n]
    return "-".join(words) or "research"


def save(question, view, request_meta=None):
    """保存一次研究（快照）。返回记录（含 path）。"""
    now = datetime.now(timezone.utc)
    rid = (view.get("advanced") or {}).get("request_id") or "no-request-id"
    fname = "%s__%s.json" % (now.strftime("%Y%m%dT%H%M%SZ"), _slug(question))
    path = os.path.join(C.HISTORY_DIR, fname)
    record = {
        "schema_version": "workspace-history/v1",
        "saved_at": now.isoformat(timespec="seconds"),
        "request": {"question": question, **(request_meta or {})},
        "request_id": rid,
        "answer": view,
    }
    P.write_json(path, record)            # ← 闸门：只允许 USER_WORKSPACE
    return {"path": os.path.relpath(path, C.VAULT), "saved_at": record["saved_at"],
            "request_id": rid, "question": question,
            "state": view.get("state"),
            "citations_n": len(view.get("citations") or [])}


def list_items(limit=C.MAX_HISTORY_ITEMS, offset=0, include_answer=False):
    """→ 历史列表（最新在前，lazy：默认不带答案正文）。"""
    files = sorted(glob.glob(os.path.join(C.HISTORY_DIR, "*.json")), reverse=True)
    out = []
    for p in files[offset:offset + limit]:
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:                                  # noqa: BLE001
            continue
        item = {"file": os.path.basename(p), "saved_at": rec.get("saved_at"),
                "request_id": rec.get("request_id"),
                "question": (rec.get("request") or {}).get("question"),
                "mode": (rec.get("request") or {}).get("mode"),
                "provider": (rec.get("request") or {}).get("provider"),
                "state": (rec.get("answer") or {}).get("state"),
                "state_label": (rec.get("answer") or {}).get("state_label"),
                "citations_n": len((rec.get("answer") or {}).get("citations") or [])}
        if include_answer:
            item["answer"] = rec.get("answer")
        out.append(item)
    return {"items": out, "total": len(files), "offset": offset, "limit": limit}


def get(file_name):
    p = os.path.join(C.HISTORY_DIR, os.path.basename(file_name or ""))
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)
