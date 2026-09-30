#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace_ui.server.jobs — 长研究请求的**进度可见**作业登记（产品层，进程内）。

为什么需要它：冻结核心的 MCP `lacan.research` 是一次**阻塞往返**，
没有任何中途进度可读（`audit` 只在返回后才有）。因此产品层唯一诚实的做法是：
把请求放进一个后台线程，对外只报告**真实可观测**的东西——已耗时、阶段名、是否仍在跑；
不再假装有百分比进度，也不猜"模型正在思考"。

作业表有上限（`MAX_JOBS`），只保留最近若干条，避免无界增长。
"""
from __future__ import annotations

import hashlib
import threading
import time

MAX_JOBS = 24
PHASES = (
    (0, "检索语料"),
    (1, "构建证据契约"),
)

_LOCK = threading.Lock()
_JOBS = {}          # jid -> dict
_ORDER = []         # 由旧到新的 jid


def _now():
    return time.time()


def _sweep_locked():
    while len(_ORDER) > MAX_JOBS:
        old = _ORDER.pop(0)
        _JOBS.pop(old, None)


def start(question, runner):
    """`runner()` 返回产品层 research 结果视图。立即返回 jid，不阻塞 HTTP。"""
    jid = "job_" + hashlib.sha1(
        ("%s|%.6f" % (question or "", _now())).encode("utf-8")).hexdigest()[:14]
    rec = {"job_id": jid, "status": "RUNNING", "question": question,
           "started_at": _now(), "finished_at": None, "result": None, "error": None}
    with _LOCK:
        _JOBS[jid] = rec
        _ORDER.append(jid)
        _sweep_locked()

    def _run():
        try:
            out = runner()
            rec["result"] = out
            rec["status"] = "DONE"
        except BaseException as exc:                                      # noqa: BLE001
            rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
            rec["status"] = "FAILED"
        finally:
            rec["finished_at"] = _now()

    threading.Thread(target=_run, name="lacan-research-%s" % jid[-6:], daemon=True).start()
    return jid


def get(jid):
    with _LOCK:
        rec = _JOBS.get(jid)
        if rec is None:
            return None
        snap = dict(rec)
    snap["elapsed_ms"] = int(((snap["finished_at"] or _now()) - snap["started_at"]) * 1000)
    return snap


def progress(jid, include_result=False):
    """轮询用的**轻量**视图：默认不含 result（结果只在 DONE 时按需取一次）。"""
    snap = get(jid)
    if snap is None:
        return {"kind": "error", "code": "JOB_NOT_FOUND", "job_id": jid, "view": "error",
                "title": "Job not found", "body": "作业已过期或不存在（作业表只保留最近 24 条）。"}
    out = {"kind": "job", "view": "job", "job_id": snap["job_id"], "status": snap["status"],
           "elapsed_ms": snap["elapsed_ms"]}
    if snap["status"] == "FAILED":
        out["error"] = snap["error"]
    if include_result and snap["status"] == "DONE":
        out["result"] = snap["result"]        # ★ 只在此刻、只按需，交一次给前端
    return out


def discard(jid):
    with _LOCK:
        rec = _JOBS.pop(jid, None)
        if jid in _ORDER:
            _ORDER.remove(jid)
    return rec is not None
