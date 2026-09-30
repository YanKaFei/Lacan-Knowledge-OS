#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""project_api.entities — Phase 5B：把**受审实体**接进研究项目。

纪律（§28/§31）：
  * 只能引用 `review_status == "reviewed"` 的实体；candidate 一律拒绝（不静默降级）。
  * 只存 **id + 提及证据摘要**，不复制 canonical 内容，不写入任何推断结论。
  * 引用记录带 `evidence_kind = "MENTION_ONLY"` 与 `asserts_* = false`。
  * Person 与 Case 是**不同 kind**；禁止把 person.X 当作 case.X（§30）。
"""
from __future__ import annotations

import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from . import store as S                                                  # noqa: E402

ENTITY_KINDS = ("person", "case")


def _api():
    import entity_browse_api as E                                         # noqa: PLC0415
    return E


def check_entity(entity_id, kind):
    """→ {exists, reviewed, label, mention_count, status}（不猜测、不晋级）。"""
    k = str(kind or "").lower()
    if k not in ENTITY_KINDS:
        return {"exists": False, "reviewed": False, "status": "INVALID_KIND",
                "label": None, "mention_count": None}
    if not str(entity_id or "").startswith(k + "."):
        return {"exists": False, "reviewed": False, "status": "KIND_ID_MISMATCH",
                "label": None, "mention_count": None}
    api = _api()
    try:
        rec = api.get_person(entity_id) if k == "person" else api.get_case(entity_id)
    except KeyError:
        return {"exists": False, "reviewed": False, "status": "UNKNOWN_ENTITY",
                "label": None, "mention_count": None}
    except api.InferenceNotSupported:
        return {"exists": False, "reviewed": False, "status": "KIND_ID_MISMATCH",
                "label": None, "mention_count": None}
    reviewed = rec.get("review_status") == "reviewed"
    return {"exists": True, "reviewed": reviewed,
            "status": "OK" if reviewed else "CANDIDATE_NOT_PROMOTED",
            "label": rec.get("label_zh") or rec.get("label"),
            "mention_count": rec.get("mention_count")}


def add_entity_reference(project_id, expected_revision, entity_id, kind, note=None):
    """加入 person/case 引用（只存 id + 证据摘要）。candidate 实体拒绝。"""
    k = str(kind or "").lower()
    if k not in ENTITY_KINDS:
        raise S.Invalid("invalid entity kind: %s" % k)
    chk = check_entity(entity_id, k)
    if not chk["exists"]:
        raise S.Invalid("entity not in reviewed registry: %s (%s)"
                        % (entity_id, chk["status"]))
    if not chk["reviewed"]:
        raise S.Invalid("%s 仍是 candidate（未达证据阈值），**不得**晋级引用（§28）"
                        % entity_id)

    def fn(project):
        refs = project.setdefault("entity_references", [])
        if any(r.get("entity_id") == entity_id for r in refs):
            return False
        refs.append({
            "entity_id": entity_id, "kind": k, "label": chk["label"],
            "mention_count": chk["mention_count"],
            "review_status": "reviewed",
            "evidence_kind": "MENTION_ONLY",
            "asserts_influence": False,
            "asserts_theoretical_relation": False,
            "asserts_case_analysis": False,
            "note": (str(note)[:300] if note else None),
            "source": "_data/entities/registry_manifest.json",
        })
        refs.sort(key=lambda r: r["entity_id"])
        return True

    project, changed = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "add_entity_reference",
                   {"entity_id": entity_id, "kind": k, "changed": changed})
    return {"project_id": project_id, "entity_id": entity_id, "kind": k,
            "changed": changed, "revision": project.get("revision"),
            "reference": next((r for r in project.get("entity_references") or []
                               if r["entity_id"] == entity_id), None)}


def list_entity_references(project_id):
    project = S.read_project(project_id)
    return {"project_id": project_id,
            "entity_references": project.get("entity_references") or [],
            "evidence_kind": "MENTION_ONLY",
            "asserts_influence": False,
            "person_case_are_distinct_entities": True}
