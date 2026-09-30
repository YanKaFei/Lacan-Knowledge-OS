#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""obsidian_adapter.entities — Phase 5B：受审实体的**参考笔记**（只读引用）。

纪律：
  * 只写**受管区**（`LACAN-OS:GENERATED` 标记内）；用户区逐字节保留。
  * 只渲染**提及证据**；不写影响/关系/分析结论（§31）。
  * Person 与 Case 分属不同目录；Schreber 类同名的两者**不合并**。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from . import vault as V                                                  # noqa: E402
from .frontmatter import MARK_END, MARK_START, dump_frontmatter           # noqa: E402

# ⚠️ 关键约束（实测踩过，vault 是唯一真源）：
#   仓库的 Obsidian vault 已经声明了 person / case 命名空间，而且**已经有**人工编写的
#   canonical 实体笔记（例如 07_Cases/case.schreber.md，generated_by="human:coffee"）。
#   因此 Phase 5B **不得**把自己的派生笔记写成 canonical 实体：
#     * 不写 `id` / `type` frontmatter（test_vault 只把带 `id` 的笔记当实体）；
#     * 不写进 canonical 分区（07_Cases / 11_Thinkers …），避免覆盖或抢注；
#     * 放在 `_System/entities/`，并在有 canonical 实体时**指向**它。
ENTITY_DIR = "_System/entities"
CANONICAL_DIRS = ("06_Clinical", "07_Cases", "10_Freud", "11_Thinkers",
                  "12_Schools_Debates", "13_Reading_Notes")


def _api():
    import entity_browse_api as E                                         # noqa: PLC0415
    return E


def entity_note_rel(entity_id, kind):
    k = str(kind or "").lower()
    if k not in ("person", "case"):
        raise V.VaultError("invalid entity kind: %s" % k)
    return "%s/%s.md" % (ENTITY_DIR, entity_id)


def _canonical_note(entity_id):
    """→ 已存在的 canonical 实体笔记的相对路径（若有）。绝不改动它。"""
    for d in CANONICAL_DIRS:
        rel = "%s/%s.md" % (d, entity_id)
        try:
            if V.Vault().exists(rel):
                return rel
        except Exception:                                                  # noqa: BLE001
            continue
    return None


def render_entity_note(rec, kind):
    """→ 受管区正文（只含提及证据）。"""
    api = _api()
    lines = ["# %s" % (rec.get("label_zh") or rec.get("label") or rec["id"]), "",
             "> 这是 Phase 5B 的**派生参考笔记**（提及证据），不是 canonical 实体笔记。",
             "> 若同名 canonical 实体已存在，本笔记只指向它，不改动它。", ""]
    lines += ["* `%s`" % rec["id"], "* kind: `%s`" % kind,
              "* labels: %s" % ", ".join(
                  x for x in [rec.get("label"), rec.get("label_zh")] if x),
              "* aliases: %s" % ", ".join(rec.get("aliases") or []),
              "* mentions (corpus): **%d**" % (rec.get("mention_count") or 0),
              "* review_status: `%s`" % rec.get("review_status"),
              "* evidence_kind: `MENTION_ONLY`", ""]
    if kind == "case" and rec.get("subject_person"):
        lines += ["## Subject person", "",
                  "* `%s`（**不同实体**：case ≠ person，不得折叠）" % rec["subject_person"]]
        link = rec.get("subject_person_link") or {}
        if link.get("evidence_passage_ids"):
            lines += ["* 连线证据段：%s" % ", ".join(
                "`%s`" % p for p in link["evidence_passage_ids"][:6])]
        lines += [""]
    lines += ["## Mention evidence (sample)", ""]
    for pid in (rec.get("mention_sample_passage_ids") or [])[:12]:
        lines.append("* `%s`" % pid)
    if not rec.get("mention_sample_passage_ids"):
        lines.append("* （无）")
    lines += ["", "> 本笔记只记录该实体在语料中的**出现**。",
              "> 它**不**主张影响、理论关系或个案分析（Phase 5B §31 no-inference gate）。", ""]
    return "\n".join(lines)


def save_entity_note(entity_id, kind, vault=None, include_mentions=True):
    """写/刷新受审实体的**派生**参考笔记（`_System/entities/`）；用户区逐字节保留。

    绝不写入 canonical 分区、绝不携带 `id`/`type` frontmatter。
    """
    api = _api()
    rec = api.get_person(entity_id) if kind == "person" else api.get_case(entity_id)
    if rec.get("review_status") != "reviewed":
        raise V.VaultError("CANDIDATE_ENTITY_NOT_PUBLISHABLE: %s" % entity_id)
    v = vault or V.Vault()
    rel = entity_note_rel(entity_id, kind)
    canon = _canonical_note(entity_id)
    # 派生参考笔记：**不含** id / type（不是 canonical 实体，只是引用记录）
    fm = dump_frontmatter({
        "entity_ref": rec["id"], "entity_kind": kind,
        "review_status": "reviewed", "evidence_kind": "MENTION_ONLY",
        "mention_count": rec.get("mention_count"),
        "canonical_note": canon,
        "canonical_note_unchanged": True,
        "managed_by": "lacan-knowledge-os/phase5b",
    })
    body = render_entity_note(rec, kind)
    inner = "%s\n%s\n%s" % (MARK_START, body.rstrip("\n"), MARK_END)
    existing = v.read(rel) if v.exists(rel) else None
    if existing is None:
        text = "%s\n\n%s\n\n## My Notes\n\n" % (fm, inner)
        v.write(rel, text)
        return {"entity_id": entity_id, "kind": kind, "note": rel, "created": True}
    # 只替换受管区，用户区原样保留
    import re
    m = re.search(r"(?s)%s.*?%s" % (re.escape(MARK_START), re.escape(MARK_END)),
                  existing)
    if m:
        text = existing[:m.start()] + inner + existing[m.end():]
    else:
        text = existing.rstrip("\n") + "\n\n" + inner + "\n"
    v.write(rel, text)
    return {"entity_id": entity_id, "kind": kind, "note": rel, "created": False,
            "managed_region_refreshed": True}
