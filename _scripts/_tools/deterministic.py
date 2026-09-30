#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deterministic.py — 确定性构建的公共实现（Phase 2 P0.1）

问题
────
产物里带 `generated_at: <当前时间>` 会让**每次运行都产生一次无意义的 git diff**。
Phase 1 交付时实测：重跑一次测试就脏了 4 个文件，而内容其实完全没变。
对一个把 Markdown 当 Source of Truth 的系统，这会淹没真正的变更。

方案：默认确定性，显式才打真实时间
──────────────────────────────────
* 默认模式：`generated_at` 由**内容哈希**推导。
  内容不变 → 时间戳逐字不变 → `git diff` 为空。
  内容变了 → 时间戳跟着变（所以它仍然是一条有用的「这一版是什么时候定的」信号）。
* `--stamp`：写入真实的当前 UTC 时间，用于发布快照。

关键点：**确定性 ≠ 冻结**。时间戳仍然是内容的函数，只是函数里不含墙上时钟。
产物里同时记录 `stamp_mode`（deterministic / stamped）与 `content_hash`，
让「这个时间戳是怎么来的」可审计。

为什么不能简单 .gitignore 掉
───────────────────────────
这些是核心 evidence artifacts（inventory 基线、校验报告）。
把它们 ignore 掉等于放弃「可 diff 的审计线索」——那正是本库存在的理由之一。
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

# 占位符必须是一个**固定常量**：算内容哈希时要把它替换成常量，
# 否则「哈希里含哈希」会自指、无法收敛。
_PLACEHOLDER = "1970-01-01T00:00:00+00:00"

# 这些键不参与内容哈希（它们本身就是时间戳/构建元数据）
_VOLATILE_KEYS = ("generated_at", "stamp_mode", "content_hash")


def content_hash(payload) -> str:
    """对 payload 做规范化内容哈希（剔除时间戳类字段，键排序）。

    序列化必须是**规范形式**：sort_keys + 固定分隔符，
    否则 dict 顺序变化会改变哈希 —— 那正是要禁止的非确定性来源。
    """
    p = copy.deepcopy(payload)
    if isinstance(p, dict):
        for k in _VOLATILE_KEYS:
            p.pop(k, None)
    blob = json.dumps(p, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def content_timestamp(payload, epoch: int = 0) -> str:
    """由内容哈希推导一个**确定性**的 ISO-8601 时间戳。

    epoch 让同一份内容也能有多个合法的时间戳来源（保留扩展余地）。
    """
    h = content_hash(payload)
    seconds = int(h[:12], 16) % (2 ** 31)   # 稳定落在 datetime 可表示范围内
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.isoformat(timespec="seconds")


def apply_stamp(payload: dict, stamp: bool = False) -> dict:
    """就地写入 generated_at / stamp_mode / content_hash，并返回 payload。

    * stamp=False（默认）：generated_at 由内容推导 → 重跑不变
    * stamp=True：generated_at = 真实当前 UTC 时间
    """
    payload.pop("generated_at", None)
    payload.pop("stamp_mode", None)
    payload.pop("content_hash", None)

    if stamp:
        payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload["stamp_mode"] = "stamped"
    else:
        payload["generated_at"] = content_timestamp(payload)
        payload["stamp_mode"] = "deterministic"
    payload["content_hash"] = content_hash(payload)
    return payload


def stable_json_dumps(payload, stamp: bool = False) -> str:
    """产出稳定序的 JSON 文本（含确定性时间戳）。"""
    apply_stamp(payload, stamp=stamp)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)


def add_stamp_flag(parser):
    """给 argparse parser 加上统一的 --stamp 开关。"""
    parser.add_argument(
        "--stamp", action="store_true",
        help="写入真实当前时间作为 generated_at（默认：由内容哈希推导，保证重跑无 diff）")
    return parser
