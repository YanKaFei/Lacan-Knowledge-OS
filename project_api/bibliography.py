#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""project_api.bibliography — Phase 5C §33/§34：项目 ↔ 书目登记表。

    ProjectBibliographyRef → bibliographic_id（stable id）
    用户自由输入但未匹配 registry → bibliographic_id = null, user_supplied = true
    （**不**强行 canonicalize）

§46 向后兼容：4D.5 的 `bibliography_refs`（自由文本）**原样保留**，
由 `legacy_view()` 适配读取；不做 destructive migration。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from . import store as S                                                  # noqa: E402


def _B():
    import bibliography as B                                              # noqa: PLC0415
    return B


def add_bibliographic_item(project_id, expected_revision, bibliographic_id,
                           user_note=None):
    """挂接**已 reviewed** 的 registry 条目（只存 stable id，不复制内容）。"""
    B = _B()
    it = B.registry.get(bibliographic_id)          # 不存在 → KeyError（显式失败）
    if it.get("review_status") != "reviewed":
        raise S.Invalid("candidate item 不得挂到项目（§12/§33）：%s" % bibliographic_id)

    def fn(p):
        refs = p.setdefault("project_bibliography_refs", [])
        if any(r.get("bibliographic_id") == bibliographic_id for r in refs):
            return False
        refs.append({
            "project_bibliographic_ref_id": S.new_item_id("pbib"),
            "bibliographic_id": bibliographic_id,
            "user_supplied": False,
            "title": it.get("title"),
            "metadata_completeness": it.get("metadata_completeness"),
            "capabilities": B.render.capability_matrix(it),
            "user_note": (str(user_note)[:300] if user_note else None),
            "source": "_data/bibliography/manifest.json",
        })
        refs.sort(key=lambda r: r["bibliographic_id"])
        return True

    project, changed = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "add_bibliographic_item",
                   {"bibliographic_id": bibliographic_id, "changed": changed})
    return {"project_id": project_id, "bibliographic_id": bibliographic_id,
            "changed": changed, "revision": project.get("revision")}


def add_user_supplied_ref(project_id, expected_revision, title, **kw):
    """用户自由输入：`bibliographic_id = null` + `user_supplied = true`（§33）。"""
    from .items import add_bibliography_ref                              # noqa: PLC0415
    return add_bibliography_ref(project_id, expected_revision, title, **kw)


def list_bibliography(project_id):
    """→ 新版 refs + **legacy 适配视图**（不迁移、不改写）。"""
    p = S.read_project(project_id)
    legacy = []
    for r in (p.get("bibliography_refs") or []):
        legacy.append({
            "ref_id": r.get("ref_id"), "title": r.get("title"),
            "author": r.get("author"), "year": r.get("year"),
            "source_type": r.get("source_type"),
            "identifier": r.get("identifier"),
            "bibliographic_id": None,          # 未匹配 registry
            "user_supplied": True,
            "legacy": True,
            # §21：显式 Link 的结果必须**可见**（不迁移、不删除原记录）
            "linked_bibliographic_id": r.get("linked_bibliographic_id"),
            "linked_review_status": r.get("linked_review_status"),
        })
    return {
        "project_id": project_id,
        "project_bibliography_refs": p.get("project_bibliography_refs") or [],
        "legacy_user_supplied_refs": legacy,
        "legacy_adapter": ("4D.5 的 bibliography_refs 以只读方式适配呈现；"
                           "**未**做 destructive migration（§46）"),
        "bibliographic_registry_is_source_of_truth": True,     # §53
    }


def link_legacy_ref(project_id, expected_revision, ref_id, bibliographic_id):
    """把一条 legacy 自由文本 ref 显式**关联**到 registry 条目（用户确认的动作）。

    不删除 legacy 记录；只加关联字段（可逆、可审计）。
    """
    B = _B()
    it = B.registry.get(bibliographic_id)

    def fn(p):
        for r in (p.get("bibliography_refs") or []):
            if r.get("ref_id") == ref_id:
                r["linked_bibliographic_id"] = bibliographic_id
                r["linked_review_status"] = it.get("review_status")
                return True
        return False

    project, changed = S.mutate(project_id, expected_revision, fn)
    if not changed:
        raise S.NotFound("legacy ref 不存在：%s" % ref_id)
    return {"project_id": project_id, "ref_id": ref_id,
            "linked_bibliographic_id": bibliographic_id,
            "revision": project.get("revision")}
