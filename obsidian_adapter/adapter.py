#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
obsidian_adapter.adapter — Phase 4D.3 Obsidian 导出（唯一入口）

三种 artifact（§6）：Research Note / Saved Passage Note / Concept Reference Note
（Seminar Note 为第四类）。语义边界：

* Research Note 里 **Final scholarly answer 原样保存**（不重新让 LLM 总结）；
* 研究回答**只进 Related Research**，绝不写成 concept 定义（§16）；
* Passage 只在**被实际引用**时 materialize（§10 Strategy A / §60 硬上限）；
* 用户区（`## My Notes`）与 managed 区块外的文本**逐字节保留**（§13/§14/§47）；
* 已存在的非本系统管理文件**绝不重写**（§31/§48）；
* 一切写入走 `scholarly_api.policy` 闸门 → 只可能落在 USER_WORKSPACE。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone

from . import vault as V
from .frontmatter import (MARK_END, MARK_START, dump_frontmatter, has_managed_block,
                          parse_frontmatter, upsert_managed)
from .links import duplicate_safe, passage_note_name, slug, wikilink

ADAPTER_VERSION = "obsidian-adapter/v1"

CONCEPTS_SOURCE = os.path.join(V.PROJECT_VAULT, "_data", "passage_store",
                              "concepts.jsonl")
MAX_CONCEPT_LINKS = 8
CONTEXT_SNAPSHOT = 2                     # §35：只存 ±2 上下文快照
TRACE_INCOMPLETE_TEXT = ("**Source trace incomplete** — 当前 recovered 文本可验证，"
                         "但来源链未闭合到原始物理文件。")
SOURCE_LAYER_TEXT = {"L1_TRANSCRIPTION": "L1 · original/primary transcription",
                     "L1_EDITION": "L1 · original/primary edition",
                     "L2_RECOVERED": "L2 · recovered/translated material"}


# ─────────────────────────────────────────────────────────── 工具
def _now():
    return datetime.now(timezone.utc)


def _safe_text(value):
    """把不可信文本规范化为可安全写入 UTF-8 的字符串（§49 无效 UTF-8 处理）。

    孤立代理项（surrogate）无法编码为 UTF-8 —— 直接写会抛 UnicodeEncodeError。
    这里用 `errors="replace"` 变成 `?`，绝不因此让保存失败。
    """
    if value is None:
        return None
    return str(value).encode("utf-8", "replace").decode("utf-8")


_ASSET_EMBED = re.compile(r"!\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]")


def _plain_assets(text):
    """corpus 里的嵌入语法 `![[…/image21.jpeg|200]]` → 纯文本 `` `[asset: …]` ``。

    §12/§49：**不把 corpus 资产拷进 vault**（corpus 只读、工作区不复制原始材料）。
    因此 corpus 相对路径的 embed 在 Obsidian 里必然是**破图**（悬空嵌入），
    而且会让工作区笔记看起来指向一个不存在的文件。
    这里保留路径本身（可回查），只去掉 embed 语法 —— 信息不丢，链接不悬空。
    """
    def rep(m):
        target = m.group(1).strip().replace("`", "").replace("\n", " ")
        return "`[asset: %s]`" % target if target else ""
    return _ASSET_EMBED.sub(rep, str(text if text is not None else ""))


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def answer_hash(payload):
    """scholarly payload 的规范化哈希（§8/§20 的 source_answer_hash）。"""
    return hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()


def body_hash(text):
    """正文（去掉用户区与 frontmatter）的哈希 → 用于 detect MODIFIED_BY_USER。"""
    body = text or ""
    if body.startswith("---"):
        _, body = parse_frontmatter(body)
    body = _strip_user_zone(body)
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


_USER_ZONE = re.compile(r"\n##\s+My Notes\b.*$", re.S)


def _strip_user_zone(text):
    return _USER_ZONE.sub("", text or "")


def research_id(view):
    """稳定 id：同一问题 + 同一答案 → 同一 id（不依赖时间）。"""
    q = _safe_text((view or {}).get("question") or "")
    h = answer_hash((view or {}).get("raw", {}).get("scholarly_payload")
                    or (view or {}).get("raw") or {})
    return "res-%s" % hashlib.sha1(("%s|%s" % (q, h)).encode("utf-8")).hexdigest()[:12]


def _seminar_from_passage(pid):
    m = re.match(r"^passage\.(S\d+[A-Z]?)\.", str(pid or ""))
    return "seminar.%s" % m.group(1) if m else None


def _seminar_from_note_rel(rel):
    """从 passage note 路径取所属研讨班：`Passages/S10.P8448.md` → `seminar.S10`。

    实测踩过：原实现把 `os.path.basename(p).split(".")[0]`（即 `S10`，**没有**
    `passage.` 前缀）喂给 `_seminar_from_passage()`，正则永不匹配 → 返回 None，
    而过滤条件是 `in (None, sid)` → **恒真**。结果每个 Seminar hub 都把别的
    研讨班的 passage 列进自己的 Saved Passages（S10 页里出现 S11 的段落）。
    """
    stem = os.path.basename(str(rel or ""))
    stem = stem[:-3] if stem.endswith(".md") else stem
    m = re.match(r"^(S\d+[A-Z]?)\.", stem)
    return "seminar.%s" % m.group(1) if m else None


def _append_managed_line(inner, heading, line):
    """在 managed 区块内某个小节的末尾插入一行（找不到该小节 → 追加到区块末尾）。

    实测踩过：直接把新行 `rstrip + "\\n- link"` 追加到区块末尾，会落到
    `## Concepts` 下面 —— 第二次保存引用同一研讨班的研究时，Saved Research
    里的链接会显示在 Concepts 小节里。
    """
    inner = inner or ""
    line = str(line or "").strip("\n")
    i = inner.find(heading)
    if i < 0:
        return inner.rstrip("\n") + (("\n" + line) if line else "") + "\n"
    j = inner.find("\n##", i + len(heading))
    j = len(inner) if j < 0 else j
    head = inner[:j].rstrip("\n")
    if line and line in head.split("\n"):
        return inner
    tail = inner[j:]                       # 以 `\n## ` 开头（或为空）
    # ⚠️ 插行后必须补空行：`- x\n## 下一节` 会把下一节标题挤到列表项上（实测踩过）
    return head + (("\n" + line) if line else "") + ("\n" if tail else "") + tail


def _section_bullets(src, heading):
    """取出 managed 区块内某小节的项目符号条目（忽略「（暂无）」占位行）。"""
    src = src or ""
    i = src.find(heading)
    if i < 0:
        return []
    j = src.find("\n##", i + len(heading))
    j = len(src) if j < 0 else j
    return [l.strip() for l in src[i + len(heading):j].split("\n")
            if l.strip().startswith("- ") and "（暂无）" not in l]


def _drop_section_placeholder(src, heading):
    """小节里已有真实条目时，去掉「（暂无）」占位行（否则占位与真链接并存，读起来自相矛盾）。"""
    i = src.find(heading)
    if i < 0:
        return src
    j = src.find("\n##", i + len(heading))
    j = len(src) if j < 0 else j
    kept = [l for l in src[i:j].split("\n") if "（暂无）" not in l]
    return src[:i] + "\n".join(kept) + src[j:]


def _merge_managed_section(old_inner, new_inner, heading):
    """把旧 note 某小节的链接**并入**新生成的 managed 区块（累计，不丢历史链接）。

    实测踩过：`_stage_concept` / `_stage_seminar` 用「只含本次研究」的新区块
    整体替换 managed 区块 → 同一概念/研讨班的**上一次研究链接被静默抹掉**。
    参考页是累积性的：新研究进来只能追加，不能删除既有 workspace 链接。
    """
    old = _section_bullets(old_inner, heading)
    if not old:
        return new_inner
    new = _section_bullets(new_inner, heading)
    for line in old:
        if line not in new:
            new_inner = _append_managed_line(new_inner, heading, line)
            new.append(line)
    return _drop_section_placeholder(new_inner, heading)


def _seminar_short(seminar_id):
    return str(seminar_id or "").replace("seminar.", "")


def _load_concepts():
    """读 canonical concepts（**只读**），用于把答案里真正出现的概念变成 workspace 链接。"""
    out = []
    if not os.path.isfile(CONCEPTS_SOURCE):
        return out
    with open(CONCEPTS_SOURCE, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:                              # noqa: BLE001
                continue
            names = [r.get("canonical_name"), r.get("title"), r.get("zh"),
                     r.get("fr"), r.get("en")] + list(r.get("aliases") or [])
            out.append({"concept_id": r.get("id"),
                        "canonical_name": r.get("canonical_name") or r.get("title"),
                        "aliases": [n for n in names if isinstance(n, str) and n],
                        "status": r.get("review_status") or r.get("status"),
                        "ontology_version": r.get("schema_version")})
    return out


def derive_concepts(view, limit=MAX_CONCEPT_LINKS):
    """从答案文本里**匹配已存在的 canonical 概念** → workspace 链接（不发明本体论）。"""
    text = " ".join([(view or {}).get("question") or ""]
                    + [str(s.get("text") or "") for s in (view or {}).get("sections") or []]
                    + [str(c.get("claim_text") or "")
                       for c in (view or {}).get("claims") or []])
    hits = []
    for c in _load_concepts():
        for nm in c["aliases"]:
            if len(nm) >= 3 and nm.lower() in text.lower():
                hits.append(c)
                break
        if len(hits) >= limit:
            break
    return hits


def _default_panel_fetcher(passage_id, before=CONTEXT_SNAPSHOT, after=CONTEXT_SNAPSHOT):
    """默认从 Workspace 产品 API 取证据面板（UI → MCP → core）；测试可注入替身。"""
    from workspace_ui.server import api as UIA                          # noqa: PLC0415
    return UIA.passage_panel(passage_id, before=before, after=after)


# ─────────────────────────────────────────────────────────── 映射表 / manifest
def _load_mapping(v):
    return (V.read_json(v.resolve(V.LAYOUT["system"], "mappings",
                                  "entity_note_map.json")) or {})


def _mapping_stage(tx, v, mapping):
    tx.stage(os.path.join(V.LAYOUT["system"], "mappings", "entity_note_map.json"),
             json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))


def _manifest_rel(research_id_):
    return os.path.join(V.LAYOUT["system"], "manifests", "%s.json" % research_id_)


# ─────────────────────────────────────────────────────────── Research Note
def _inner_block(body):
    """→ managed 区块内部文本（生成区）；用于 generated_body_hash。"""
    if MARK_START in (body or "") and MARK_END in (body or ""):
        return body.split(MARK_START)[1].split(MARK_END)[0].strip()
    return (body or "").strip()


def _research_frontmatter(view, rid, ahash, concepts, seminars, note_body):
    a = view.get("advanced") or {}
    fm = {
        "type": "lacan-research",
        "status": "research",
        "created": _now().strftime("%Y-%m-%d"),
        "research_id": rid,
        "request_id": a.get("request_id"),
        "task_type": view.get("task_type"),
        "answer_state": view.get("state"),
        "answer_permission": view.get("answer_permission"),
        "provider": a.get("provider"),
        "core_freeze_version": a.get("core_freeze_version"),
        "source_answer_hash": ahash,
        # ⚠️ 定义：生成区（managed 区块内部）的哈希 —— verify_snapshot 用同一算法比对
        "generated_body_hash": hashlib.sha256(
            _inner_block(note_body).encode("utf-8")).hexdigest(),
        "generated_snapshot_status": "VERIFIED",
        "citation_count": len(view.get("citations") or []),
        "concepts": [c["concept_id"] for c in concepts],
        "concept_link_derivation": "canonical-name-match" if concepts else None,
        "seminars": seminars,
        "workspace_adapter": ADAPTER_VERSION,
    }
    return {k: val for k, val in fm.items() if val is not None}


def _research_body(view, rid, concept_notes, seminar_notes, passage_notes):
    L = []
    L.append("# %s" % (_safe_text(view.get("question")) or "Research"))
    gen = []

    def g(line=""):
        gen.append(line)

    g("## Research Question")
    g()
    g(_safe_text(view.get("question")) or "")
    g()
    if view.get("is_abstention"):
        ab = view.get("abstention") or {}
        g("## %s" % (ab.get("title") or "Current corpus cannot support a reliable answer"))
        g()
        for title, items in (("Why this cannot be answered", ab.get("categories")),
                             ("Missing information", ab.get("missing_information")),
                             ("Available partial information",
                              ab.get("available_partial_information")),
                             ("Sources needed", ab.get("required_sources"))):
            if not items:
                continue
            g("### %s" % title)
            g()
            for it in items:
                g("- %s" % it)
            g()
    else:
        g("## Scholarly Answer")
        g()
        for s in view.get("sections") or []:
            if s.get("internal"):
                continue
            g("### %s" % s.get("label"))
            g()
            g(str(s.get("text") or "").strip())
            g()
    if view.get("claims"):
        g("## Key Claims")
        g()
        for c in view.get("claims") or []:
            g("- **[%s · %s]** %s" % (c.get("epistemic_label") or "",
                                      c.get("claim_type") or "", c.get("claim_text")))
        g()
    if view.get("citations"):
        g("## Citations")
        g()
        for c in view.get("citations") or []:
            note = passage_notes.get(c.get("passage_id"))
            link = wikilink(note, c.get("label")) if note else (c.get("label") or "")
            extra = []
            if c.get("source_layer_tag"):
                extra.append(c["source_layer_tag"])
            if c.get("provenance_status") == "SOURCE_TRACE_INCOMPLETE":
                extra.append("source trace incomplete")
            g("- %s%s" % (link, (" — " + " · ".join(extra)) if extra else ""))
        g()
    if view.get("limitations"):
        g("## Source Limitations")
        g()
        for it in view.get("limitations") or []:
            g("- %s" % it)
        g()
    g("## Research Context")
    g()
    a = view.get("advanced") or {}
    for k, val in (("Research mode", a.get("mode") or view.get("task_type")),
                   ("Task type", view.get("task_type")),
                   ("Answer state", a.get("answer_state") or view.get("state")),
                   ("Answer permission", view.get("answer_permission")),
                   ("Provider", a.get("provider")),
                   ("Core freeze", a.get("core_freeze_version")),
                   ("Request id", a.get("request_id")),
                   ("Generated", _now().strftime("%Y-%m-%dT%H:%M:%SZ")),
                   ("Research id", rid)):
        g("- %s: `%s`" % (k, val))
    if concept_notes:
        g()
        g("## Concepts")
        g()
        for cid, rel in sorted(concept_notes.items()):
            g("- %s" % wikilink(rel, cid))
    if seminar_notes:
        g()
        g("## Seminars")
        g()
        for sid, rel in sorted(seminar_notes.items()):
            g("- %s" % wikilink(rel, sid))
    gen_txt = "\n".join(gen).strip("\n")
    L.append("%s\n%s\n%s" % (MARK_START, gen_txt, MARK_END))
    L.append("")
    L.append("## My Notes")
    L.append("")
    L.append("<!-- 你自己的研究笔记写在这里；系统刷新时不会覆盖此区域。 -->")
    L.append("")
    return "\n".join(L)


def save_research(view, *, vault=None, create_snapshot=False, fetcher=None,
                  concept_ids=None, include_audit=False):
    """把一次已验证研究保存为 Obsidian Research Note（+ 实际引用的 passage/concept/seminar notes）。

    事务性：预检全部路径 → 全部写 temp → 原子 rename；失败回滚（§28）。
    幂等：同一 research_id 已保存 → `already_saved`（不 silent overwrite，§41）。
    """
    v = vault or V.Vault()
    if not isinstance(view, dict) or view.get("kind") not in (None, "answer"):
        return {"ok": False, "error": "NOT_AN_ANSWER_VIEW"}
    # ★ Phase 5A §12：标准 Research Note 只写用户可见面（学术内容 + 学术限制）；
    #   校验器诊断需**显式**选择 `include_audit=True` 才另存审计工件（不改标准笔记）。
    _audit_artifact = None
    rid = research_id(view)
    payload = (view.get("raw") or {}).get("scholarly_payload") or {}
    ahash = answer_hash(payload)

    manifest_rel = _manifest_rel(rid)
    if v.exists(manifest_rel) and not create_snapshot:
        man = V.read_json(v.resolve(manifest_rel)) or {}
        return {"ok": True, "status": "already_saved", "research_id": rid,
                "research_note": man.get("research_note_path"),
                "manifest": manifest_rel, "obsidian_uri": open_in_obsidian(
                    man.get("research_note_path") or "", vault=v)}

    # 概念（只做 workspace 链接；可由调用方显式给出）
    concepts = ([{"concept_id": c, "canonical_name": c} for c in concept_ids]
                if concept_ids else derive_concepts(view))
    seminars = sorted({_seminar_from_passage(c.get("passage_id"))
                       for c in view.get("citations") or []
                       if _seminar_from_passage(c.get("passage_id"))})

    # 文件名（重复安全）—— 先于 passage note 计算：passage 的「Used in Research」
    # 要写进生成区，因此必须在算 generated_body_hash 之前就知道研究 note 的路径。
    base = "%s - %s" % (_now().strftime("%Y-%m-%d"),
                        slug(_safe_text(view.get("question")) or "research"))
    fname = duplicate_safe(lambda n: v.exists(V.LAYOUT["research"], n), base)
    note_rel = os.path.join(V.LAYOUT["research"], fname)

    # 只为**实际引用**的 passage 建 note（§10 Strategy A / §60）
    cited = [c for c in (view.get("citations") or []) if c.get("passage_id")]
    fetch = fetcher or _default_panel_fetcher
    passage_note_rel = {}
    passage_stage = []
    for c in cited:
        try:
            panel = fetch(c["passage_id"])
        except Exception:                                    # noqa: BLE001
            panel = None
        rel = os.path.join(V.LAYOUT["passages"],
                           "%s.md" % passage_note_name(c["passage_id"]))
        passage_note_rel[c["passage_id"]] = rel
        text, fm = _passage_note(panel, c, used_in=[note_rel])
        passage_stage.append((rel, text, fm))

    concept_note_rel = {}
    for c in concepts:
        rel = os.path.join(V.LAYOUT["concepts"], "%s.md" % slug(
            str(c["concept_id"]).split(".", 1)[-1]))
        concept_note_rel[c["concept_id"]] = rel
    seminar_note_rel = {s: os.path.join(V.LAYOUT["seminars"],
                                        "%s.md" % _seminar_short(s)) for s in seminars}

    body = _research_body(view, rid, concept_note_rel, seminar_note_rel,
                          passage_note_rel)
    fm = _research_frontmatter(view, rid, ahash, concepts, seminars, body)
    note_text = dump_frontmatter(fm) + "\n" + body

    tx = v.transaction()
    try:
        tx.stage(note_rel, note_text)
        for rel, text, _fm in passage_stage:
            if v.exists(rel):
                continue                       # 已存在 → 不覆盖用户可能加过的笔记
            tx.stage(rel, text)
        # concept / seminar reference hub：只更新 managed 区块
        hub_status = {}
        for c in concepts:
            rel = concept_note_rel[c["concept_id"]]
            hub_status[rel] = _stage_concept(tx, v, rel, c, rid, note_rel)
        for s in seminars:
            rel = seminar_note_rel[s]
            hub_status[rel] = _stage_seminar(tx, v, rel, s, rid, note_rel,
                                             [p for p in passage_note_rel.values()])
        mapping = _load_mapping(v)
        # ⚠️ 映射必须如实：系统**没有**碰过用户自己的文件（§31/§48），
        #    就不能在 provenance 记录里写成 managed=true（实测踩过）。
        def _hub_entry(rel):
            if hub_status.get(rel) == "existing_unmanaged":
                return {"note": rel, "managed": False,
                        "reason": "existing_unmanaged",
                        "updated_at": _now().isoformat(timespec="seconds")}
            return {"note": rel, "managed": True,
                    "updated_at": _now().isoformat(timespec="seconds")}

        for cid, rel in concept_note_rel.items():
            mapping[cid] = _hub_entry(rel)
        for sid, rel in seminar_note_rel.items():
            mapping[sid] = _hub_entry(rel)
        for pid, rel in passage_note_rel.items():
            mapping[pid] = _hub_entry(rel)
        _mapping_stage(tx, v, mapping)
        manifest = {
            "schema_version": "obsidian-save-manifest/v1",
            "research_id": rid,
            "saved_at": _now().isoformat(timespec="seconds"),
            "source_answer_hash": ahash,
            "answer_state": view.get("state"),
            "research_note_path": note_rel,
            "passage_note_paths": {k: p for k, p in sorted(passage_note_rel.items())},
            "concept_note_paths": {k: p for k, p in sorted(concept_note_rel.items())},
            "seminar_note_paths": {k: p for k, p in sorted(seminar_note_rel.items())},
            "core_freeze_version": (view.get("advanced") or {}).get("core_freeze_version"),
            "mcp_version": (view.get("advanced") or {}).get("mcp_version"),
            "adapter_version": ADAPTER_VERSION,
            "vault_root_kind": ("project-workspace" if v.is_project_default else "external"),
            "note": "workspace provenance（§30）；**不是** scholarly evidence。",
        }
        tx.stage(manifest_rel, json.dumps(manifest, ensure_ascii=False, indent=1,
                                          sort_keys=True))
        # ★ Phase 5A §12：审计工件**显式 opt-in**，写在 _System/audit/ 下；
        #   标准 Research Note 与 Section 正文都不含这些内容（presentation taxonomy）。
        if include_audit:
            _audit_artifact = "_System/audit/research-%s.json" % rid
            audit_doc = dict(view.get("audit") or {})
            audit_doc["presentation_taxonomy_version"] = "presentation-taxonomy/v1"
            audit_doc["research_id"] = rid
            audit_doc["source_answer_hash"] = ahash
            audit_doc["note"] = ("校验器诊断（AUDIT_DIAGNOSTIC）：**不是**学术内容，"
                                 "也不进标准 Research Note。/ Validator diagnostics, "
                                 "not scholarly content.")
            tx.stage(_audit_artifact, json.dumps(audit_doc, ensure_ascii=False, indent=1,
                                                 sort_keys=True))
        tx.commit()
    except Exception as exc:                                 # noqa: BLE001
        return {"ok": False, "error": "SAVE_FAILED", "detail": str(exc)[:300],
                "research_id": rid}

    return {"ok": True, "status": "saved", "research_id": rid,
            "research_note": note_rel, "manifest": manifest_rel,
            "audit_artifact": _audit_artifact,
            "passage_notes": sorted(set(passage_note_rel.values())),
            "concept_notes": sorted(set(concept_note_rel.values())),
            "seminar_notes": sorted(set(seminar_note_rel.values())),
            "obsidian_uri": open_in_obsidian(note_rel, vault=v),
            "answer_state": view.get("state")}


# ─────────────────────────────────────────────────────────── Passage Note
def _passage_frontmatter(panel, citation, generated_inner=None):
    p = (panel or {}).get("passage") or {}
    sl = (panel or {}).get("source_layer") or {}
    return {
        "type": "lacan-passage",
        "passage_id": p.get("passage_id") or (citation or {}).get("passage_id"),
        "seminar": _seminar_short(p.get("seminar")),
        "language": p.get("language"),
        "source_layer": sl.get("code") or (citation or {}).get("source_layer"),
        "provenance_status": p.get("trace_status")
                             or (citation or {}).get("provenance_status"),
        "witness": p.get("witness"),
        "context_snapshot": CONTEXT_SNAPSHOT,
        "read_only_source": True,
        "source_snapshot": True,
        "generated_body_hash": (hashlib.sha256(
            (generated_inner or "").strip().encode("utf-8")).hexdigest()
            if generated_inner is not None else None),
        "generated_snapshot_status": "VERIFIED",
    }


def _used_in_entries(used_in):
    """把『Used in Research』渲染成条目：note 路径 → `[[…]]`，纯文本原样保留。

    实测踩过：`"- %s\\n" % (wikilink(e) if cond else "- %s\\n" % e)` 在纯文本分支
    会产出 `- - e`（双项目符号 + 多余空行）。
    """
    items = used_in if isinstance(used_in, (list, tuple, set)) else [used_in]
    out = []
    for e in items:
        s = str(e or "").strip()
        if not s:
            continue
        out.append(wikilink(s) if (s.endswith(".md") or "/" in s) else s)
    return out


def _passage_note(panel, citation, used_in=None):
    p = (panel or {}).get("passage") or {}
    pid = p.get("passage_id") or (citation or {}).get("passage_id")
    short = passage_note_name(pid)
    fm = _passage_frontmatter(panel, citation)      # 临时（哈希稍后补）
    L = ["# %s · %s" % (short.split(".")[0], short.split(".")[-1]), ""]
    # corpus 文本投影进工作区：embed 语法不会解析（资产不在 vault 内）→ 去语法留路径
    gen = ["## Passage", "", _plain_assets((p.get("text") or "").strip()), ""]
    span = (citation or {}).get("quoted_span")
    if span:
        gen += ["### Quoted span", "", _plain_assets(span), ""]
    ctx = (panel or {}).get("context") or []
    if ctx:
        gen += ["## Context (±%d)" % CONTEXT_SNAPSHOT, ""]
        for c in ctx:
            mark = " **←**" if c.get("passage_id") == pid else ""
            gen.append("- `%s`%s %s" % (c.get("passage_id"), mark,
                                        _plain_assets((c.get("text") or "").strip())[:400]))
        gen.append("")
    if fm["provenance_status"] == "SOURCE_TRACE_INCOMPLETE":
        gen += ["> %s" % TRACE_INCOMPLETE_TEXT, ""]
    gen += ["## Source", "",
            "- Seminar: %s" % wikilink(os.path.join(V.LAYOUT["seminars"],
                                                    "%s.md" % fm["seminar"]),
                                       fm["seminar"]),
            "- Language: %s" % (fm.get("language") or "—"),
            "- Source layer: %s" % SOURCE_LAYER_TEXT.get(fm.get("source_layer") or "",
                                                         fm.get("source_layer") or "—"),
            "- Witness: `%s`" % (fm.get("witness") or "—"),
            "- Provenance: `%s`" % (fm.get("provenance_status") or "—"),
            "- Canonical source: `%s`（**只读快照**；本 note 不写回 corpus）" % pid,
            ""]
    gen += ["## Used in Research", ""]
    # ⚠️ used_in 必须在**算哈希之前**进正文：生成区哈希覆盖整个 managed 区块，
    #    先算哈希再补字 → verify_snapshot() 对新保存的 note 报 MODIFIED_BY_USER。
    entries = _used_in_entries(used_in)
    gen += (["- %s" % e for e in entries] if entries
            else ["- （暂无：尚未被任何研究引用）"])
    gen += [""]
    L.append("%s\n%s\n%s" % (MARK_START, "\n".join(gen).strip("\n"), MARK_END))
    L += ["", "## My Notes", "",
          "<!-- 你对这一段的笔记；系统不会覆盖此区域。 -->", ""]
    # ⚠️ frontmatter 必须一起产出（实测踩过：只写正文 → read_only_source 等标记丢失）
    body_text = "\n".join(L)
    fm = _passage_frontmatter(panel, citation, _inner_block(body_text))
    return dump_frontmatter({k: v for k, v in fm.items() if v is not None}) + "\n" \
        + body_text, fm


def save_passage(passage_id, *, panel=None, vault=None, used_in=None,
                 fetcher=None, citation=None):
    """显式保存单个 Passage Note（§26）。已存在 → `already_saved`（不覆盖）。"""
    v = vault or V.Vault()
    if panel is None:
        try:
            panel = (fetcher or _default_panel_fetcher)(passage_id)
        except Exception:                                     # noqa: BLE001
            panel = None
    rel = os.path.join(V.LAYOUT["passages"], "%s.md" % passage_note_name(passage_id))
    if v.exists(rel):
        return {"ok": True, "status": "already_saved", "note": rel,
                "obsidian_uri": open_in_obsidian(rel, vault=v)}
    text, _fm = _passage_note(panel, citation or {"passage_id": passage_id,
                                                  "quoted_span": None},
                              used_in=used_in)
    # §17/§18：passage note 里的 [[Seminars/Sxx]] 必须有对应文件，否则是悬空链接
    sid = _seminar_from_passage(passage_id)
    seminar_rel = (os.path.join(V.LAYOUT["seminars"], "%s.md" % _seminar_short(sid))
                   if sid else None)
    tx = v.transaction()
    try:
        tx.stage(rel, text)
        mapping = _load_mapping(v)
        mapping[passage_id] = {"note": rel, "managed": True,
                               "updated_at": _now().isoformat(timespec="seconds")}
        hub_status = None
        if seminar_rel:
            hub_status = _stage_seminar_hub(tx, v, seminar_rel, sid, rel)
            if hub_status == "existing_unmanaged":
                mapping[sid] = {"note": seminar_rel, "managed": False,
                                "reason": "existing_unmanaged",
                                "updated_at": _now().isoformat(timespec="seconds")}
            else:
                mapping[sid] = {"note": seminar_rel, "managed": True,
                                "updated_at": _now().isoformat(timespec="seconds")}
        _mapping_stage(tx, v, mapping)
        tx.commit()
    except Exception as exc:                                  # noqa: BLE001
        return {"ok": False, "error": "SAVE_FAILED", "detail": str(exc)[:200]}
    return {"ok": True, "status": "saved", "note": rel,
            "seminar_note": (seminar_rel if hub_status == "saved" else None),
            "obsidian_uri": open_in_obsidian(rel, vault=v)}


# ─────────────────────────────────────────────────────────── Concept / Seminar
def _concept_frontmatter(c, related_notes, passage_notes):
    fm = {
        "type": "lacan-concept",
        "concept_id": c.get("concept_id"),
        "preferred_label": c.get("canonical_name") or c.get("concept_id"),
        "ontology_status": c.get("status"),
        "ontology_version": c.get("ontology_version"),
        "canonical_source": "scholarly-core",
        "managed_by": ADAPTER_VERSION,
    }
    aliases = [a for a in (c.get("aliases") or []) if a and a != c.get("canonical_name")]
    if aliases:
        fm["aliases"] = sorted(set(aliases))[:12]     # §33：只来自 canonical data
    return fm


def _concept_body(c, related, passages):
    gen = ["## Canonical Reference", "",
           "Concept ID: `%s`" % c.get("concept_id"), ""]
    if c.get("canonical_name"):
        gen += ["Canonical name: **%s**" % c["canonical_name"], ""]
    # §33：aliases 只来自 canonical data；去重 + 去掉与 canonical name 重复者
    #（实测踩过：`_load_concepts` 把 canonical_name/title/zh/fr/en 与 aliases 合并，
    #  正文里同一个别名会重复出现 2–3 次）
    alias_list = sorted({a for a in (c.get("aliases") or [])
                         if a and a != c.get("canonical_name")})
    if alias_list:
        gen += ["Aliases (from canonical data): %s"
                % ", ".join("`%s`" % a for a in alias_list[:12]), ""]
    gen += ["## Related Research", ""]
    gen += ["- %s" % wikilink(r) for r in sorted(set(related or []))] or ["- （暂无）"]
    gen += ["", "## Saved Passages", ""]
    gen += ["- %s" % wikilink(p) for p in sorted(set(passages or []))] or ["- （暂无）"]
    gen += ["", "> 本页是 **workspace reference hub**，不是 canonical 定义；"
                "研究回答不会被自动提升为概念定义（§16）。", ""]
    body = ["# %s" % (c.get("canonical_name") or c.get("concept_id")), ""]
    body.append("%s\n%s\n%s" % (MARK_START, "\n".join(gen).strip("\n"), MARK_END))
    body += ["", "## My Notes", "",
             "<!-- 你自己的概念笔记；系统不会覆盖此区域。 -->", ""]
    return "\n".join(body)


def ensure_concept_note(concept_id, *, vault=None, canonical=None,
                        related_research=None, passage_notes=None,
                        existing_note=None):
    """创建/更新 Concept **Reference Hub**（managed 区块内更新，用户区逐字节保留）。"""
    v = vault or V.Vault()
    canon = canonical
    if canon is None:
        canon = next((c for c in _load_concepts() if c["concept_id"] == concept_id), None)
    if canon is None:
        canon = {"concept_id": concept_id, "canonical_name": concept_id,
                 "aliases": [], "status": None, "ontology_version": None}
    rel = os.path.join(V.LAYOUT["concepts"], "%s.md" % slug(
        str(concept_id).split(".", 1)[-1]))
    # §31/§48：用户已有自己的 note → **只登记映射，绝不重写**（需显式指定）
    if existing_note:
        target = v.read(existing_note)
        if target is not None:
            mapping = _load_mapping(v)
            mapping[concept_id] = {"note": existing_note, "managed": False,
                                   "reason": "existing_unmanaged",
                                   "updated_at": _now().isoformat(timespec="seconds")}
            v.write(os.path.join(V.LAYOUT["system"], "mappings",
                                 "entity_note_map.json"),
                    json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))
            return {"ok": True, "status": "existing_unmanaged_preserved",
                    "note": existing_note}
    existing = v.read(rel)
    stub = _concept_body(canon, related_research or [], passage_notes or [])
    if existing is not None:
        meta, _ = parse_frontmatter(existing)
        if not meta or meta.get("type") != "lacan-concept" \
                or meta.get("concept_id") != concept_id:
            # §31/§48：非本系统管理的文件 → **绝不重写**，只登记映射
            mapping = _load_mapping(v)
            mapping[concept_id] = {"note": rel, "managed": False,
                                   "reason": "existing_unmanaged",
                                   "updated_at": _now().isoformat(timespec="seconds")}
            v.write(os.path.join(V.LAYOUT["system"], "mappings",
                                 "entity_note_map.json"),
                    json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))
            return {"ok": True, "status": "existing_unmanaged_preserved", "note": rel}
        new_inner = stub.split(MARK_START)[1].split(MARK_END)[0]
        prev = existing.split(MARK_START)
        if len(prev) > 1:
            old_inner = prev[1].split(MARK_END)[0]
            for heading in ("## Related Research", "## Saved Passages"):
                new_inner = _merge_managed_section(old_inner, new_inner, heading)
        text = upsert_managed(existing, new_inner)
        if text == existing:
            return {"ok": True, "status": "already_saved", "note": rel}
    else:
        text = dump_frontmatter(_concept_frontmatter(canon, related_research or [],
                                                     passage_notes or [])) + "\n" + stub
    v.write(rel, text)
    mapping = _load_mapping(v)
    mapping[concept_id] = {"note": rel, "managed": True,
                           "updated_at": _now().isoformat(timespec="seconds")}
    v.write(os.path.join(V.LAYOUT["system"], "mappings", "entity_note_map.json"),
            json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))
    return {"ok": True, "status": "saved", "note": rel}


def _stage_concept(tx, v, rel, c, rid, research_rel):
    existing = v.read(rel)
    stub = _concept_body(c, [research_rel], [])
    if existing is not None:
        meta, _ = parse_frontmatter(existing)
        if not meta or meta.get("type") != "lacan-concept":
            return "existing_unmanaged"             # 非受管文件：不动（§31）
        inner = stub.split(MARK_START)[1].split(MARK_END)[0]
        prev = existing.split(MARK_START)
        if len(prev) > 1:
            # 累计合并：老研究链接必须保留（否则第二次保存会抹掉第一次）
            inner = _merge_managed_section(prev[1].split(MARK_END)[0], inner,
                                           "## Related Research")
        tx.stage(rel, upsert_managed(existing, inner))
        return "saved"
    tx.stage(rel, dump_frontmatter(_concept_frontmatter(c, [research_rel], []))
             + "\n" + stub)
    return "saved"


def _seminar_body(sid, title, years, languages, related, passages):
    gen = ["## Metadata", "",
           "- Seminar: `%s`" % sid,
           "- Title: %s" % (title or "—"),
           "- Years: %s" % (years or "—"),
           "- Languages: %s" % (", ".join(languages or []) or "—"),
           "- Canonical source: `scholarly-core`（bibliographic 缺失时如实留空，不伪造）",
           "", "## Saved Research", ""]
    gen += ["- %s" % wikilink(r) for r in sorted(set(related or []))] or ["- （暂无）"]
    gen += ["", "## Saved Passages", ""]
    gen += ["- %s" % wikilink(p) for p in sorted(set(passages or []))] or ["- （暂无）"]
    gen += ["", "## Concepts", "", "- （由 Research Note 反向链接）", ""]
    body = ["# Seminar %s" % _seminar_short(sid), ""]
    body.append("%s\n%s\n%s" % (MARK_START, "\n".join(gen).strip("\n"), MARK_END))
    body += ["", "## My Notes", "",
             "<!-- 你自己的研讨班笔记；系统不会覆盖此区域。 -->", ""]
    return "\n".join(body)


def ensure_seminar_note(seminar_id, *, vault=None, title=None, years=None,
                        languages=None, related_research=None, passage_notes=None):
    v = vault or V.Vault()
    rel = os.path.join(V.LAYOUT["seminars"], "%s.md" % _seminar_short(seminar_id))
    existing = v.read(rel)
    body = _seminar_body(seminar_id, title, years, languages,
                         related_research or [], passage_notes or [])
    fm = {"type": "lacan-seminar", "seminar_id": seminar_id, "years": years,
          "available_languages": languages or [], "managed_by": ADAPTER_VERSION}
    if existing is not None:
        meta, _ = parse_frontmatter(existing)
        if not meta or meta.get("type") != "lacan-seminar":
            mapping = _load_mapping(v)
            mapping[seminar_id] = {"note": rel, "managed": False,
                                   "reason": "existing_unmanaged",
                                   "updated_at": _now().isoformat(timespec="seconds")}
            v.write(os.path.join(V.LAYOUT["system"], "mappings",
                                 "entity_note_map.json"),
                    json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))
            return {"ok": True, "status": "existing_unmanaged_preserved", "note": rel}
        new_inner = body.split(MARK_START)[1].split(MARK_END)[0]
        prev = existing.split(MARK_START)
        if len(prev) > 1:
            old_inner = prev[1].split(MARK_END)[0]
            for heading in ("## Saved Research", "## Saved Passages"):
                new_inner = _merge_managed_section(old_inner, new_inner, heading)
        text = upsert_managed(existing, new_inner)
        if text == existing:
            return {"ok": True, "status": "already_saved", "note": rel}
    else:
        text = dump_frontmatter({k: val for k, val in fm.items() if val is not None}) \
               + "\n" + body
    v.write(rel, text)
    mapping = _load_mapping(v)
    mapping[seminar_id] = {"note": rel, "managed": True,
                           "updated_at": _now().isoformat(timespec="seconds")}
    v.write(os.path.join(V.LAYOUT["system"], "mappings", "entity_note_map.json"),
            json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))
    return {"ok": True, "status": "saved", "note": rel}


def _stage_seminar(tx, v, rel, sid, rid, research_rel, passage_rels):
    existing = v.read(rel)
    body = _seminar_body(sid, None, None, None, [research_rel],
                         [p for p in passage_rels
                          if _seminar_from_note_rel(p) in (None, sid)])
    fm = {"type": "lacan-seminar", "seminar_id": sid, "managed_by": ADAPTER_VERSION}
    if existing is not None:
        meta, _ = parse_frontmatter(existing)
        if not meta or meta.get("type") != "lacan-seminar":
            return "existing_unmanaged"
        inner = body.split(MARK_START)[1].split(MARK_END)[0]
        prev = existing.split(MARK_START)
        if len(prev) > 1:
            old_inner = prev[1].split(MARK_END)[0]
            # 累计合并：先前研究/段落的链接必须保留（否则第二次保存会抹掉第一次）
            inner = _merge_managed_section(old_inner, inner, "## Saved Research")
            inner = _merge_managed_section(old_inner, inner, "## Saved Passages")
        tx.stage(rel, upsert_managed(existing, inner))
        return "saved"
    tx.stage(rel, dump_frontmatter(fm) + "\n" + body)
    return "saved"


def _stage_seminar_hub(tx, v, rel, sid, passage_rel):
    """独立保存 passage 时确保 Seminar hub 存在（§17/§18）。

    实测踩过：`save_passage()` 原本只写 passage note，`[[Seminars/S05]]`
    在 vault 里**没有对应文件** → Obsidian 图谱里是一个悬空节点，
    Passage → Seminar 链接不可浏览。
    """
    existing = v.read(rel)
    body = _seminar_body(sid, None, None, None, [], [passage_rel])
    fm = {"type": "lacan-seminar", "seminar_id": sid, "managed_by": ADAPTER_VERSION}
    if existing is not None:
        meta, _ = parse_frontmatter(existing)
        if not meta or meta.get("type") != "lacan-seminar":
            return "existing_unmanaged"           # §31/§48：绝不重写非受管文件
        inner = body.split(MARK_START)[1].split(MARK_END)[0]
        prev = existing.split(MARK_START)
        if len(prev) > 1:
            old_inner = prev[1].split(MARK_END)[0]
            # ⚠️ 必须合并：`_seminar_body(sid, …, [], [passage_rel])` 的 Saved Research
            #    小节是空的，整体替换会把已有研究链接一并抹掉。
            inner = _merge_managed_section(old_inner, inner, "## Saved Research")
            inner = _merge_managed_section(old_inner, inner, "## Saved Passages")
        tx.stage(rel, upsert_managed(existing, inner))
        return "saved"
    tx.stage(rel, dump_frontmatter(fm) + "\n" + body)
    return "saved"


# ─────────────────────────────────────────────────────────── 其它入口
def open_in_obsidian(note_rel, *, vault=None, vault_name=None):
    """→ `obsidian://open?vault=…&file=…`（optional；不做任何 shell 调用）。"""
    if not note_rel:
        return None
    v = vault or V.Vault()
    name = vault_name or os.path.basename(v.root)
    file = str(note_rel)[:-3] if str(note_rel).endswith(".md") else str(note_rel)
    from urllib.parse import quote
    return "obsidian://open?vault=%s&file=%s" % (quote(name), quote(file))


def verify_snapshot(note_rel, *, vault=None):
    """§20：比对 note 里已生成正文的哈希 → VERIFIED / MODIFIED_BY_USER / UNKNOWN。"""
    v = vault or V.Vault()
    text = v.read(note_rel)
    if text is None:
        return {"ok": False, "status": "UNKNOWN", "reason": "note_not_found"}
    meta, _ = parse_frontmatter(text)
    if not meta or "generated_body_hash" not in meta:
        return {"ok": True, "status": "UNKNOWN",
                "reason": "no_generated_body_hash", "note": note_rel}
    stored = meta.get("generated_body_hash")
    if has_managed_block(text):
        inner = text.split(MARK_START)[1].split(MARK_END)[0]
        for cand in (inner, inner.lstrip("\n")):
            if hashlib.sha256(cand.strip().encode("utf-8")).hexdigest() == stored:
                return {"ok": True, "status": "VERIFIED", "note": note_rel,
                        "source_answer_hash": meta.get("source_answer_hash")}
    return {"ok": True, "status": "MODIFIED_BY_USER", "note": note_rel,
            "source_answer_hash": meta.get("source_answer_hash")}


def list_saved_research(*, vault=None, limit=200):
    v = vault or V.Vault()
    d = v.resolve(V.LAYOUT["system"], "manifests")
    out = []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d), reverse=True)[:limit]:
            if not fn.endswith(".json"):
                continue
            m = V.read_json(os.path.join(d, fn)) or {}
            out.append({"research_id": m.get("research_id"),
                        "saved_at": m.get("saved_at"),
                        "answer_state": m.get("answer_state"),
                        "research_note": m.get("research_note_path"),
                        "manifest": os.path.join(V.LAYOUT["system"], "manifests", fn)})
    return {"items": out, "total": len(out)}


def vault_status(*, vault=None):
    v = vault or V.Vault()
    return {
        "detection": V.detect(),
        "active_root": v.root,
        "root_kind": "project-workspace" if v.is_project_default else "external",
        "layout": V.LAYOUT,
        "counts": {k: len(v.list_rel(rel)) for k, rel in V.LAYOUT.items()
                   if k != "system"},
        "adapter_version": ADAPTER_VERSION,
    }


# ─────────────────────────────────────────────────────────── Project Hub（4D.5 §27–§31/§61–§63）
def _project_slug(project):
    """文件名只由 **project_id 之外的稳定文本** 生成，且映射表才是权威（§62）。"""
    base = slug(_safe_text(project.get("title")) or project.get("project_id") or "project",
                maxlen=60)
    return base


def _project_frontmatter(project):
    fm = {
        "type": "lacan-research-project",
        "project_id": project.get("project_id"),
        "status": project.get("status"),
        "created": (project.get("created_at") or "")[:10] or None,
        "updated": (project.get("updated_at") or "")[:19] or None,
        "revision": project.get("revision"),
        "tags": list(project.get("tags") or []) or None,
        "authority_level": "L2",
        "managed_by": ADAPTER_VERSION,
        "note": "workspace hub；**不是** scholarly evidence（§2）",
    }
    return {k: v for k, v in fm.items() if v is not None}


def project_note_map(vault=None):
    v = vault or V.Vault()
    return V.read_json(v.resolve(V.LAYOUT["system"], "mappings",
                                 "project_note_map.json")) or {}


def _project_note_rel(project, v):
    """→ note 相对路径：**先查映射表**；没有才生成（绝不按标题猜已有路径，§62）。

    ⚠️ 同名项目的处理：如果目标路径上已有一个**属于别的 project_id** 的受管 note，
    绝不静默接管它（那会把别人的 Hub 改写成我的）——改为 `<title> (2).md`。
    """
    m = project_note_map(v)
    pid = project.get("project_id")
    if m.get(pid):
        return m[pid]
    base = _project_slug(project)
    for i in range(1, 50):
        # ⚠️ 必须带 .md：`duplicate_safe` 会补扩展名，重构时漏掉过一次，
        #    结果写出一个没有扩展名的 note（Obsidian 不识别）。
        name = (base if i == 1 else "%s (%d)" % (base, i)) + ".md"
        rel = os.path.join(V.LAYOUT["projects"], name)
        txt = v.read(rel)
        if txt is None:
            return rel
        meta, _ = parse_frontmatter(txt)
        if (meta or {}).get("project_id") == pid:
            return rel
    raise VaultError("project note naming exhausted for %s" % pid)


def remove_project_note(project_id, *, vault=None):
    """删除**某个 project 自己的**受管 Hub（仅在 frontmatter project_id 完全匹配时）。

    §63 说的是「归档不得删用户笔记」；这里删的是**系统为该项目生成的** hub 文件，
    且必须三个条件同时成立：路径来自映射表、文件是 lacan-research-project、
    frontmatter 的 project_id 就是它。用户自己的文件永远不会被删。
    """
    v = vault or V.Vault()
    rel = unmap_project(project_id, vault=v)
    if not rel:
        return None
    txt = v.read(rel)
    if txt is None:
        return None
    meta, _ = parse_frontmatter(txt)
    if not meta or meta.get("type") != "lacan-research-project" \
            or meta.get("project_id") != project_id:
        return None
    v.remove(rel)
    return rel


def unmap_project(project_id, *, vault=None):
    """从 project_note_map 中移除一个 project（**不删文件**；§63 只归档不删）。"""
    v = vault or V.Vault()
    m = project_note_map(v)
    if project_id in m:
        rel = m.pop(project_id)
        v.write(os.path.join(V.LAYOUT["system"], "mappings", "project_note_map.json"),
                json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True))
        return rel
    return None


def research_links_for_project(project, *, vault=None):
    """§30：把 project 的 research run 与 Obsidian Research Note 对上。

    匹配键 = `source_answer_hash`（4D.3 manifest 里就有），因此**不靠标题/时间猜**。
    未保存到 Obsidian 的 run 明确显示 `(run not saved to Obsidian yet)`。
    """
    v = vault or V.Vault()
    manifests = []
    d = v.resolve(V.LAYOUT["system"], "manifests")
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            rec = V.read_json(os.path.join(d, fn)) or {}
            manifests.append(rec)
    by_hash = {}
    for rec in manifests:
        h = rec.get("source_answer_hash")
        if h:
            by_hash.setdefault(h, rec.get("research_note_path"))
    out = []
    for run in project.get("research_runs") or []:
        rel = by_hash.get(run.get("source_answer_hash"))
        out.append({"run_id": run.get("run_id"), "question": run.get("question"),
                    "answer_state": run.get("answer_state"),
                    "research_note": rel,
                    "linked": bool(rel)})
    return out


def _project_body(project, links):
    gen = ["## Overview", ""]
    if project.get("description"):
        gen += [project["description"], ""]
    gen += ["- Status: `%s`" % project.get("status"),
            "- Project id: `%s`" % project.get("project_id"),
            "- Revision: %s" % project.get("revision"),
            "- Created: %s" % (project.get("created_at") or "—"),
            "- Updated: %s" % (project.get("updated_at") or "—"),
            "- Tags: %s" % (", ".join(project.get("tags") or []) or "—"),
            "",
            "> 本页是 **workspace hub**，不是 scholarly evidence。"
            "研究结论必须回到语料重新取证（§2/§74）。", ""]

    gen += ["## Research Questions", ""]
    qs = project.get("research_questions") or []
    gen += (["- [%s] %s" % (q.get("status"), q.get("text")) for q in qs]
            or ["- （暂无）"])
    gen += ["", "## Research Runs", ""]
    if links:
        for l in links:
            line = ("- `%s` · %s" % (l["answer_state"], l["question"]))
            line += (" → %s" % wikilink(l["research_note"])) if l["linked"] \
                else " → （run not saved to Obsidian yet）"
            gen.append(line)
    else:
        gen.append("- （暂无）")
    gen += ["", "> Run 全文**不**复制进本页：只保留链接，避免 note 膨胀（§29）。", ""]

    gen += ["## Concepts", ""]
    gen += (["- %s" % wikilink(os.path.join(V.LAYOUT["concepts"], "%s.md" % slug(
        str(r["id"]).split(".", 1)[-1]))) for r in (project.get("saved_concepts") or [])]
        or ["- （暂无）"])
    gen += ["", "## Seminars", ""]
    gen += (["- %s" % wikilink(os.path.join(V.LAYOUT["seminars"], "%s.md" %
                                            str(r["id"]).replace("seminar.", "")))
             for r in (project.get("saved_seminars") or [])] or ["- （暂无）"])
    gen += ["", "## Saved Passages", ""]
    gen += (["- %s" % wikilink(os.path.join(V.LAYOUT["passages"], "%s.md" % slug(
        str(r["id"]).replace("passage.", "").replace(".", "-"))))
        for r in (project.get("saved_passages") or [])] or ["- （暂无）"])
    gen += ["", "## Terms", ""]
    gen += (["- `%s`（mapping / attestation / interpretation 三层语义分开，见 Terminology Explorer）"
             % r["id"] for r in (project.get("saved_terms") or [])] or ["- （暂无）"])

    gen += ["", "## Open Questions", ""]
    gen += (["- [%s] %s%s" % (q.get("origin"), q.get("text"),
                              ("（from run `%s`）" % q.get("run_id")) if q.get("run_id") else "")
             for q in (project.get("open_questions") or [])] or ["- （暂无）"])

    gen += ["", "## Hypotheses（user objects, not validated）", ""]
    gen += (["- %s — *not validated by the Scholarly Core*" % h.get("text")
             for h in (project.get("hypotheses") or [])] or ["- （暂无）"])

    gen += ["", "## Bibliography", ""]
    gen += (["- %s%s%s" % (b.get("title"),
                           (" · %s" % b["author"]) if b.get("author") else "",
                           (" · %s" % b["year"]) if b.get("year") else "")
             for b in (project.get("bibliography_refs") or [])] or ["- （暂无）"])
    gen += ["", "> `BibliographyRef` 是用户引用管理对象，**不是** `CorpusSource`（§33）。", ""]

    body = ["# %s" % (project.get("title") or project.get("project_id")), ""]
    body.append("%s\n%s\n%s" % (MARK_START, "\n".join(gen).strip("\n"), MARK_END))
    body += ["", "## My Notes", "",
             "<!-- 你自己的项目笔记；系统刷新时不会覆盖此区域。 -->", ""]
    return "\n".join(body)


def _project_fm_updates(project):
    return {"type": "lacan-research-project",
            "project_id": project.get("project_id"),
            "status": project.get("status"),
            "created": (project.get("created_at") or "")[:10] or None,
            "updated": (project.get("updated_at") or "")[:19] or None,
            "revision": project.get("revision"),
            "tags": list(project.get("tags") or []) or None,
            "managed_by": ADAPTER_VERSION}


def _upsert_frontmatter_keys(existing, updates):
    """只更新**系统拥有**的 frontmatter 键，用户自己加的键原样保留。

    实测踩过：Project Hub 归档后 frontmatter 仍是 `status: ACTIVE` —— 因为
    更新路径只换 managed 区块、从不碰 frontmatter。归档元数据属于系统所有，
    必须随之刷新；但用户手写的自定义键不能丢。
    """
    meta, body = parse_frontmatter(existing or "")
    if meta is None:
        return existing
    merged = dict(meta)
    for k, v in updates.items():
        if v is None:
            merged.pop(k, None)
        else:
            merged[k] = v
    return dump_frontmatter({k: v for k, v in merged.items() if v is not None}) + "\n" + body


def save_project_note(project, *, vault=None):
    """创建/更新 Project Hub（managed 区块内更新，用户区逐字节保留；§28/§61）。

    * 只写 `_workspace/**`（USER_WORKSPACE）；
    * 已有映射 → 就地更新（改名不会另建文件，映射表是权威，§62）；
    * 归档只更新 managed 元数据，**绝不删除**用户 note（§63）。
    """
    v = vault or V.Vault()
    pid = project.get("project_id")
    if not pid:
        return {"ok": False, "error": "PROJECT_ID_REQUIRED"}
    rel = _project_note_rel(project, v)
    links = research_links_for_project(project, vault=v)
    body = _project_body(project, links)
    existing = v.read(rel)
    if existing is not None:
        meta, _ = parse_frontmatter(existing)
        if not meta or meta.get("type") != "lacan-research-project":
            mapping = project_note_map(v)
            mapping[pid] = rel
            v.write(os.path.join(V.LAYOUT["system"], "mappings",
                                 "project_note_map.json"),
                    json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))
            return {"ok": True, "status": "existing_unmanaged_preserved", "note": rel}
        inner = body.split(MARK_START)[1].split(MARK_END)[0]
        prev = existing.split(MARK_START)
        new_inner = inner
        if len(prev) > 1:
            old_inner = prev[1].split(MARK_END)[0]
            for heading in ("## Research Questions", "## Research Runs", "## Concepts",
                            "## Seminars", "## Saved Passages", "## Terms",
                            "## Open Questions", "## Hypotheses（user objects, not validated）",
                            "## Bibliography"):
                new_inner = _merge_managed_section(old_inner, new_inner, heading)
        # 归档/改名的元数据属于系统所有，必须随 managed 区块一起刷新（其余键保留）
        text = _upsert_frontmatter_keys(existing, _project_fm_updates(project))
        text = upsert_managed(text, new_inner)
        if text == existing:
            _write_project_map(v, pid, rel)
            return {"ok": True, "status": "already_saved", "note": rel}
    else:
        text = dump_frontmatter(_project_frontmatter(project)) + "\n" + body
    v.write(rel, text)
    _write_project_map(v, pid, rel)
    return {"ok": True, "status": "saved", "note": rel,
            "obsidian_uri": open_in_obsidian(rel, vault=v),
            "linked_runs": sum(1 for l in links if l["linked"]),
            "runs": len(links)}


def _write_project_map(v, project_id, rel):
    mapping = project_note_map(v)
    mapping[project_id] = rel
    v.write(os.path.join(V.LAYOUT["system"], "mappings", "project_note_map.json"),
            json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True))
