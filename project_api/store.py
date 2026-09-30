#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_api.store — Research Project 的**工作区**存储层（Phase 4D.5 §6/§55/§56/§57/§58）

定位（§2/§3）：
    Research Project = **USER_WORKSPACE**。它可以 organize / reference / annotate /
    group / bookmark / plan，但**不能** promote 用户笔记为 canonical claim、
    不能改 ontology / passage / evidence、不能覆盖 abstention。

存储（§6）：
    _workspace/projects/<project_id>/
        project.json          schema_version=1，revision 单调 +1
        notes/<note_id>.md    自由文本（不进入 scholarly evidence pipeline）
        snapshots/<run_id>.json  **不可变**的 FinalScholarlyAnswer 快照
        manifests/*.json      导出/QA 清单
        audit.jsonl           轻量审计（create/rename/archive/add_*/…）

写入纪律：
    * 一切写入经 `scholarly_api.policy`（`_workspace/**` = USER_WORKSPACE），
      写到核心会抛 `CoreMutationError`；
    * **原子写**：temp → fsync → `os.replace`（§55）；
    * **revision 并发控制**（§56/§57）：mutation 必须带 `expected_revision`，
      不匹配 → `WORKSPACE_CONFLICT`；
    * 进程内再加一把锁，避免同进程两个请求交错读改写。
"""
from __future__ import annotations

import errno
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

from scholarly_api import policy as POL

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)

PROJECT_API_VERSION = "project-api/v1"
PROJECT_SCHEMA_VERSION = 1
PROJECTS_REL = os.path.join("_workspace", "projects")
PROJECTS_DIR = os.path.join(VAULT, PROJECTS_REL)

PROJECT_ID_RE = re.compile(r"^proj_[0-9A-HJKMNP-TV-Z]{26}$")
_MAX_TITLE = 200
_MAX_DESCRIPTION = 4000
_MAX_TAG = 60
_MAX_TAGS = 30
_MAX_NOTE = 200_000
_MAX_REFS = 500

_LOCK = threading.RLock()

# Crockford base32（ULID 兼容：48 位毫秒时间 + 80 位随机 → 可按时间排序的稳定 id）
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class ProjectError(RuntimeError):
    """基类。"""


class NotFound(ProjectError):
    pass


class Invalid(ProjectError):
    pass


class Conflict(ProjectError):
    """revision 不匹配（§57 WORKSPACE_CONFLICT）。"""

    def __init__(self, message, expected=None, actual=None):
        super().__init__(message)
        self.expected = expected
        self.actual = actual


def _encode(value, length):
    out = []
    for _ in range(length):
        out.append(_B32[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_project_id():
    """→ `proj_` + ULID（48 位毫秒时间戳 + 80 位随机），可按时间排序且稳定。"""
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = secrets.randbits(80)
    return "proj_" + _encode(ts, 10) + _encode(rand, 16)


def new_item_id(prefix):
    return "%s_%s" % (prefix, _encode(int(time.time() * 1000) & ((1 << 48) - 1), 10)
                      + _encode(secrets.randbits(40), 8))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_dir(project_id):
    if not PROJECT_ID_RE.match(str(project_id or "")):
        raise Invalid("invalid project id: %r" % project_id)
    return os.path.join(PROJECTS_DIR, project_id)


def project_json_path(project_id):
    return os.path.join(project_dir(project_id), "project.json")


# ─────────────────────────────────────────────────────────── 原子写
def _atomic_write_json(path, obj):
    """temp → fsync → os.replace（§55）；路径经 policy 闸门。"""
    POL.assert_writable(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp-%d-%s" % (path, os.getpid(), secrets.token_hex(4))
    blob = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(blob)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError as exc:                       # 某些文件系统不支持
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EBADF):
                raise
    os.replace(tmp, path)
    return path


def write_project(project):
    project["updated_at"] = now_iso()
    return _atomic_write_json(project_json_path(project["project_id"]), project)


def read_project(project_id):
    p = project_json_path(project_id)
    if not os.path.isfile(p):
        raise NotFound("project not found: %s" % project_id)
    try:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
    except json.JSONDecodeError as exc:
        raise Invalid("malformed project.json: %s" % exc)
    if not isinstance(doc, dict) or doc.get("project_id") != project_id:
        raise Invalid("project.json 与目录不一致：%s" % project_id)
    if doc.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise Invalid("unsupported project schema_version: %r" % doc.get("schema_version"))
    return doc


def append_audit(project_id, action, detail=None):
    """轻量审计（§39）：jsonl 追加，不做 event sourcing。"""
    path = os.path.join(project_dir(project_id), "audit.jsonl")
    POL.assert_writable(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rec = {"at": now_iso(), "action": action, "detail": detail or {}}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


def read_audit(project_id, limit=200):
    path = os.path.join(project_dir(project_id), "audit.jsonl")
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
            except Exception:                                    # noqa: BLE001
                continue
    return out[-limit:]


# ─────────────────────────────────────────────────────────── mutation
def mutate(project_id, expected_revision, fn):
    """带 revision 检查的 read-modify-write（进程内串行 + 原子落盘）。

    `fn(project)` 直接改 dict（或返回 False 表示无变化）。返回 (project, changed)。
    """
    with _LOCK:
        project = read_project(project_id)
        actual = int(project.get("revision") or 0)
        if expected_revision is not None and int(expected_revision) != actual:
            raise Conflict("WORKSPACE_CONFLICT: expected revision %s, actual %s"
                           % (expected_revision, actual), expected=expected_revision,
                           actual=actual)
        changed = fn(project)
        if changed is False:
            return project, False
        project["revision"] = actual + 1
        write_project(project)
        return project, True


# ─────────────────────────────────────────────────────────── 校验
def clean_title(title):
    t = str(title or "").strip()
    if not t:
        raise Invalid("title is required")
    if len(t) > _MAX_TITLE:
        raise Invalid("title too long (max %d)" % _MAX_TITLE)
    # 路径注入：标题只作为数据，不进路径；仍然拒绝控制字符与路径分隔
    if any(ch in t for ch in "/\\\x00") or "\n" in t or ".." in t:
        raise Invalid("title contains path characters")
    return t


def clean_tags(tags):
    out = []
    for t in (tags or []):
        s = str(t).strip()
        if not s:
            continue
        if len(s) > _MAX_TAG:
            raise Invalid("tag too long (max %d)" % _MAX_TAG)
        if any(ch in s for ch in "/\\\x00\n\r"):
            raise Invalid("tag contains path characters")
        if s not in out:
            out.append(s)
    if len(out) > _MAX_TAGS:
        raise Invalid("too many tags (max %d)" % _MAX_TAGS)
    return out


def clean_text(text, limit, field="text"):
    s = str(text or "")
    if len(s.encode("utf-8")) > limit:
        raise Invalid("%s too large (max %d bytes)" % (field, limit))
    return s


def clean_status(status):
    s = str(status or "ACTIVE").upper()
    if s not in ("ACTIVE", "ARCHIVED"):
        raise Invalid("invalid status: %s" % status)
    return s
