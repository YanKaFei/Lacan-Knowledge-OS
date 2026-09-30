#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace_ui.server.entities — Phase 5B：Person / Case Explorer 的服务端适配层。

**只**转发 `entity_browse_api` 的只读、分页、确定性结果；不新增任何推断。
禁止的操作（影响/理论关系/个案分析/折叠/同义）在此显式拒绝并翻译为 400。
"""
from __future__ import annotations

import sys

import os

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

import entity_browse_api as E                                              # noqa: E402


def availability():
    return {"kind": "entities_availability", "persons": E.list_persons(limit=1)["page"]["total"],
            "cases": E.list_cases(limit=1)["page"]["total"],
            "evidence_kind": "MENTION_ONLY", "read_only": True}


def persons(cursor=None, limit=None):
    return E.list_persons(cursor, limit or 20)


def person(entity_id):
    return E.get_person(entity_id)


def cases(cursor=None, limit=None):
    return E.list_cases(cursor, limit or 20)


def case(entity_id):
    return E.get_case(entity_id)


def mentions(entity_id, cursor=None, limit=None):
    return E.mentions(entity_id, cursor, limit or 20)


def search(q, kind=None, cursor=None, limit=None):
    return E.search(q, kind, cursor, limit or 20)
