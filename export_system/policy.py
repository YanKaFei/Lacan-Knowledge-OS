#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.policy — 导出落盘策略（Phase 4D.6 §45/§46/§47/§49）

* 所有导出只落 **export root**：默认 `_workspace/exports/`（USER_WORKSPACE）；
* 不接受用户给的任意绝对路径：只接受**已登记**的 export root 名（§46）；
* 原子导出（§47）：build temp → validate → hash → manifest → verify → atomic finalize；
  失败不留「看起来成功」的半 bundle；
* 导出审计（§49）：只记元数据，**不记 scholarly 全文**。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone

from scholarly_api import policy as POL

from .model import ExportError

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)

EXPORT_ROOT_REL = os.path.join("_workspace", "exports")
DEFAULT_EXPORT_ROOT = os.path.join(VAULT, EXPORT_ROOT_REL)
AUDIT_REL = os.path.join(EXPORT_ROOT_REL, "audit.jsonl")

# 已登记的导出根（§46）：名字 → 相对路径；用户不能传路径，只能传名字
EXPORT_ROOTS = {
    "default": EXPORT_ROOT_REL,
}

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._\-\u4e00-\u9fff]{1,120}$")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def export_root(name="default"):
    rel = EXPORT_ROOTS.get(str(name or "default"))
    if not rel:
        raise ExportError("EXPORT_POLICY_DENIED",
                          "unknown export root: %r" % name,
                          {"registered": sorted(EXPORT_ROOTS)})
    p = os.path.join(VAULT, rel)
    POL.assert_writable(os.path.join(p, "x.json"))          # 闸门：必须可写（USER_WORKSPACE）
    os.makedirs(p, exist_ok=True)
    return p


def safe_name(name, fallback="export"):
    """磁盘名安全化：拒绝路径分隔、`..`、控制字符；限长（§44）。"""
    s = str(name or "").strip()
    s = s.replace("\\", "-").replace("/", "-")
    s = re.sub(r"[\x00-\x1f]", "", s)
    s = s.replace("..", "-")
    if not s or not _SAFE_NAME.match(s):
        s = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", s)[:100].strip("-.")
    if not s or s in (".", ".."):
        s = fallback
    return s[:120]


def export_dir_name(export_id, title=None):
    """目录名 = `<export_id>`（**确定性、不依赖 title**，§44）。"""
    return safe_name(export_id, fallback="export")


def temp_dir_for(final_dir):
    parent = os.path.dirname(final_dir)
    os.makedirs(parent, exist_ok=True)
    return os.path.join(parent, ".tmp-%s-%s" % (os.path.basename(final_dir),
                                                secrets.token_hex(4)))


def atomic_finalize(temp_dir, final_dir):
    """temp → final 的**原子**替换；目标已存在则先移到 .bak 再删。"""
    if os.path.exists(final_dir):
        backup = final_dir + ".bak-%s" % secrets.token_hex(3)
        os.replace(final_dir, backup)
        try:
            os.replace(temp_dir, final_dir)
        finally:
            shutil.rmtree(backup, ignore_errors=True)
        return final_dir
    os.replace(temp_dir, final_dir)
    return final_dir


def write_file(path, data, *, binary=False):
    """经闸门 + 原子写的单文件写入。"""
    POL.assert_writable(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp-%s" % (path, secrets.token_hex(4))
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8"}
    with open(tmp, mode, **kwargs) as f:
        f.write(data)
    os.replace(tmp, path)
    return path


def audit(record):
    """§49：只记元数据（export_id/source/format/success/file_count/hash/error_code）。"""
    path = os.path.join(VAULT, AUDIT_REL)
    POL.assert_writable(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    allow = ("export_id", "source_type", "source_id", "format", "timestamp", "success",
             "file_count", "bundle_hash", "error_code", "bytes", "export_root")
    rec = {k: record.get(k) for k in allow}
    rec["timestamp"] = rec.get("timestamp") or now_iso()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


def read_audit(limit=200):
    path = os.path.join(VAULT, AUDIT_REL)
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:                                          # noqa: BLE001
                continue
    return out[-limit:]


def list_exports(root="default"):
    d = export_root(root)
    items = []
    for name in sorted(os.listdir(d), reverse=True):
        if name.startswith(".") or name == "audit.jsonl":
            continue
        p = os.path.join(d, name)
        entry = {"name": name, "path": os.path.relpath(p, VAULT),
                 "is_dir": os.path.isdir(p),
                 "size": (sum(os.path.getsize(os.path.join(dp, fn))
                              for dp, _dn, fns in os.walk(p) for fn in fns)
                          if os.path.isdir(p) else os.path.getsize(p))}
        man = os.path.join(p, "manifest.json")
        if os.path.isfile(man):
            try:
                with open(man, encoding="utf-8") as f:
                    entry["manifest"] = json.load(f)
            except Exception:                                          # noqa: BLE001
                entry["manifest"] = None
        items.append(entry)
    return {"root": root, "path": os.path.relpath(d, VAULT), "items": items,
            "total": len(items)}


def resolve_export_path(rel_path, root="default"):
    """把 `_workspace/exports/...` 下的相对路径解析成绝对路径（拒绝越界）。"""
    d = export_root(root)
    p = os.path.abspath(os.path.join(d, str(rel_path or "")))
    if not p.startswith(os.path.abspath(d) + os.sep) and p != os.path.abspath(d):
        raise ExportError("EXPORT_POLICY_DENIED", "path escapes the export root",
                          {"root": os.path.relpath(d, VAULT)})
    return p
