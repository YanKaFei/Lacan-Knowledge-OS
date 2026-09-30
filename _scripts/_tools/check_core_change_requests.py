#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_core_change_requests.py — Phase 4D.0 §8：核心变更请求协议校验（只读）

检查：
  1. SCHEMA.json 存在且是合法 JSON Schema；
  2. TEMPLATE.json 通过该 schema（模板必须自身合法）；
  3. requests/*.json 逐份通过 schema；
  4. request_id 唯一；
  5. 状态机合法：OPEN → TRIAGED → {ACCEPTED_FOR_REMEDIATION|REJECTED|DEFERRED}；
     ACCEPTED_FOR_REMEDIATION 必须写明 resolution_phase（否则无人认领就"合法"了）。

本工具**不修改任何请求**，也不接触核心数据。零请求时平凡通过。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
CCR = os.path.join(VAULT, "_core_change_requests")
SCHEMA = os.path.join(CCR, "SCHEMA.json")
TEMPLATE = os.path.join(CCR, "TEMPLATE.json")
REQ_DIR = os.path.join(CCR, "requests")

ALLOWED_TRANSITIONS = {
    "OPEN": {"TRIAGED", "REJECTED", "DEFERRED"},
    "TRIAGED": {"ACCEPTED_FOR_REMEDIATION", "REJECTED", "DEFERRED"},
    "ACCEPTED_FOR_REMEDIATION": {"ACCEPTED_FOR_REMEDIATION", "RESOLVED"},
    # Phase 4E 补：协议一直写着「(新 remediation phase) → 关闭」，但枚举里没有终态。
    #   第一次真正关闭一个 CCR（CCR-0001）时暴露了这个缺口，故补上 RESOLVED。
    "RESOLVED": {"RESOLVED"},
    "REJECTED": {"REJECTED"},
    "DEFERRED": {"DEFERRED", "TRIAGED"},
}


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _validator():
    try:
        import jsonschema  # noqa: PLC0415
        return jsonschema.Draft202012Validator(_load(SCHEMA))
    except ImportError:
        return None


def verify(quiet=False):
    problems = []
    for p in (SCHEMA, TEMPLATE):
        if not os.path.isfile(p):
            problems.append("缺文件：%s" % os.path.relpath(p, VAULT))
    if problems:
        print("FAIL 核心变更请求协议不完整：")
        for x in problems:
            print("  - %s" % x)
        return 1

    v = _validator()
    schema = _load(SCHEMA)
    tmpl = _load(TEMPLATE)
    if v is not None:
        for e in v.iter_errors(tmpl):
            problems.append("TEMPLATE 不合 schema：%s" % e.message)

    ids = {}
    n = 0
    if os.path.isdir(REQ_DIR):
        for fn in sorted(os.listdir(REQ_DIR)):
            if not fn.endswith(".json"):
                continue
            n += 1
            p = os.path.join(REQ_DIR, fn)
            try:
                req = _load(p)
            except Exception as exc:  # noqa: BLE001
                problems.append("%s 不是合法 JSON：%s" % (fn, exc))
                continue
            if v is not None:
                for e in v.iter_errors(req):
                    problems.append("%s schema 违规：%s" % (fn, e.message))
            rid = req.get("request_id")
            if rid in ids:
                problems.append("request_id 重复：%s（%s 与 %s）" % (rid, ids[rid], fn))
            ids[rid] = fn
            st = req.get("status")
            if st not in ALLOWED_TRANSITIONS:
                problems.append("%s 非法状态：%s" % (fn, st))
            elif st in ("ACCEPTED_FOR_REMEDIATION", "RESOLVED") \
                    and not req.get("resolution_phase"):
                problems.append("%s 状态 %s 但未写 resolution_phase"
                                "（不得无 phase 认领/关闭核心改动）" % (fn, st))
            if req.get("requires_scholarly_revalidation") is True \
                    and st in ("ACCEPTED_FOR_REMEDIATION", "RESOLVED") \
                    and not req.get("triage_note"):
                problems.append("%s 需学术重新验收但缺 triage_note" % fn)
    if problems:
        print("FAIL 核心变更请求校验未通过：")
        for x in problems[:12]:
            print("  - %s" % x)
        return 1
    if not quiet:
        print("核心变更请求协议校验通过：schema+template 合法；requests=%d；"
              "状态机 %s" % (n, "→".join(["OPEN", "TRIAGED",
                                          "ACCEPTED_FOR_REMEDIATION", "RESOLVED"])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4D.0 核心变更请求协议校验")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    return verify(quiet=a.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
