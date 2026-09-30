#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_api.projects — Research Project 的生命周期与引用管理（4D.5 §4/§5/§17–§22/§54）

对象（§4）：ResearchProject（schema_version=1）
    project_id / title / description / created_at / updated_at / status / tags
    research_questions[] / research_runs[] / saved_passages[] / saved_concepts[]
    saved_seminars[] / saved_terms[] / notes[] / open_questions[] / hypotheses[]
    bibliography_refs[] / obsidian_note / revision

三种「用户对象」与 scholarly 概念严格分开：
    validated claim  → 只可能来自 Scholarly Core
    hypothesis       → **USER_HYPOTHESIS**（必须标 not_validated）
    open question    → 研究问题（不是结论、不产生关系）
"""
from __future__ import annotations

import os

from . import store as S

VALID_REF_KINDS = ("passage", "concept", "seminar", "term")


# ─────────────────────────────────────────────────────────── 创建 / 读取
def create_project(title, description="", tags=None, questions=None):
    title = S.clean_title(title)
    description = S.clean_text(description, S._MAX_DESCRIPTION, "description")   # noqa: SLF001
    tags = S.clean_tags(tags)
    pid = S.new_project_id()
    with S._LOCK:                                                                 # noqa: SLF001
        if os.path.isdir(S.project_dir(pid)):                                     # 极低概率
            raise S.Conflict("project id collision")
        project = {
            "schema_version": S.PROJECT_SCHEMA_VERSION,
            "project_id": pid,
            "title": title,
            "description": description,
            "created_at": S.now_iso(),
            "updated_at": S.now_iso(),
            "status": "ACTIVE",
            "tags": tags,
            "revision": 1,
            "research_questions": [],
            "research_runs": [],
            "saved_passages": [],
            "saved_concepts": [],
            "saved_seminars": [],
            "saved_terms": [],
            "notes": [],
            "open_questions": [],
            "hypotheses": [],
            "bibliography_refs": [],
            "obsidian_note": None,
        }
        for q in (questions or []):
            project["research_questions"].append(_question_record(q))
        S._atomic_write_json(S.project_json_path(pid), project)                   # noqa: SLF001
        S.append_audit(pid, "create", {"title": title, "revision": 1})
    return project


def _question_record(text, status="OPEN", source="user_created", run_id=None):
    return {"question_id": S.new_item_id("q"),
            "text": S.clean_text(text, 4000, "question"),
            "status": str(status).upper(),
            "created_at": S.now_iso(),
            "source": source,
            "run_id": run_id}


def get_project(project_id, with_referents=True):
    p = S.read_project(project_id)
    return enrich(p) if with_referents else p


def list_projects(status=None, tag=None, updated_after=None, query=None, limit=200):
    """§35：status / tag / updated_at 过滤即可（不做复杂化）。"""
    out = []
    if not os.path.isdir(S.PROJECTS_DIR):
        return {"items": [], "total": 0}
    for name in sorted(os.listdir(S.PROJECTS_DIR)):
        if not S.PROJECT_ID_RE.match(name):
            continue
        try:
            p = S.read_project(name)
        except S.ProjectError:
            out.append({"project_id": name, "title": "(malformed project.json)",
                        "status": "MALFORMED", "revision": None,
                        "updated_at": None, "tags": [], "counts": {}})
            continue
        if status and p["status"] != str(status).upper():
            continue
        if tag and tag not in (p.get("tags") or []):
            continue
        if updated_after and str(p.get("updated_at") or "") < str(updated_after):
            continue
        if query:
            hay = " ".join([p.get("title") or "", p.get("description") or "",
                            " ".join(p.get("tags") or [])]).casefold()
            if str(query).casefold() not in hay:
                continue
        out.append(summary(p))
    out.sort(key=lambda r: (str(r.get("updated_at") or ""), r["project_id"]), reverse=True)
    return {"items": out[:limit], "total": len(out)}


def summary(p):
    return {
        "project_id": p["project_id"], "title": p["title"], "status": p["status"],
        "tags": p.get("tags") or [], "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"), "revision": p.get("revision"),
        "description": (p.get("description") or "")[:400],
        "counts": {
            "research_questions": len(p.get("research_questions") or []),
            "research_runs": len(p.get("research_runs") or []),
            "saved_passages": len(p.get("saved_passages") or []),
            "saved_concepts": len(p.get("saved_concepts") or []),
            "saved_seminars": len(p.get("saved_seminars") or []),
            "saved_terms": len(p.get("saved_terms") or []),
            "notes": len(p.get("notes") or []),
            "open_questions": len(p.get("open_questions") or []),
            "hypotheses": len(p.get("hypotheses") or []),
            "bibliography_refs": len(p.get("bibliography_refs") or []),
        },
        "obsidian_note": p.get("obsidian_note"),
    }


# ─────────────────────────────────────────────────────────── 更新 / 归档
def update_project(project_id, expected_revision, title=None, description=None,
                   tags=None, status=None):
    def fn(p):
        changed = False
        if title is not None:
            t = S.clean_title(title)
            if t != p["title"]:
                p["title"] = t
                changed = True
        if description is not None:
            d = S.clean_text(description, S._MAX_DESCRIPTION, "description")
            if d != p.get("description"):
                p["description"] = d
                changed = True
        if tags is not None:
            tg = S.clean_tags(tags)
            if tg != (p.get("tags") or []):
                p["tags"] = tg
                changed = True
        if status is not None:
            st = S.clean_status(status)
            if st != p["status"]:
                p["status"] = st
                changed = True
        return changed
    project, changed = S.mutate(project_id, expected_revision, fn)
    if changed:
        S.append_audit(project_id, "update",
                       {"revision": project["revision"], "title": project.get("title"),
                        "status": project.get("status")})
    return project


def archive_project(project_id, expected_revision):
    """§38：第一版优先 Archive（不真删）。"""
    p = update_project(project_id, expected_revision, status="ARCHIVED")
    S.append_audit(project_id, "archive", {"revision": p["revision"]})
    return p


def restore_project(project_id, expected_revision):
    p = update_project(project_id, expected_revision, status="ACTIVE")
    S.append_audit(project_id, "restore", {"revision": p["revision"]})
    return p


# ─────────────────────────────────────────────────────────── 引用（§17–§21/§40）
def _ref(pid, kind, extra=None):
    rec = {"id": pid, "kind": kind, "added_at": S.now_iso(), "added_by": "user"}
    rec.update(extra or {})
    return rec


def _already(project, field, item_id):
    return any(x.get("id") == item_id for x in (project.get(field) or []))


def add_reference(project_id, expected_revision, kind, item_id, note=None,
                  source_context=None, passage_hash=None):
    """加入 passage / concept / seminar / term 引用（**只存 id，不复制 canonical 内容**）。"""
    kind = str(kind or "").lower()
    if kind not in VALID_REF_KINDS:
        raise S.Invalid("invalid reference kind: %s" % kind)
    item_id = str(item_id or "").strip()
    if not item_id or len(item_id) > 200 or "/" in item_id or "\\" in item_id:
        raise S.Invalid("invalid reference id")
    field = {"passage": "saved_passages", "concept": "saved_concepts",
             "seminar": "saved_seminars", "term": "saved_terms"}[kind]
    referent = check_referent(kind, item_id)

    def fn(p):
        if _already(p, field, item_id):
            # 已存在：只更新用户批注（可重复调用的幂等语义）
            for x in p[field]:
                if x["id"] == item_id and note is not None:
                    x["user_note"] = S.clean_text(note, 4000, "note")
                    return True
            return False
        extra = {"referent_label": referent.get("label"),
                 "referent_status_at_add": referent.get("status")}
        if kind == "passage":
            extra["passage_hash_at_save"] = passage_hash or referent.get("text_hash")
            extra["source_context"] = (source_context or "")[:400]
        p[field].append(_ref(item_id, kind, extra))
        if note is not None:
            p[field][-1]["user_note"] = S.clean_text(note, 4000, "note")
        return True
    project, _ = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "add_%s" % kind,
                   {"id": item_id, "revision": project["revision"]})
    return project


def remove_reference(project_id, expected_revision, kind, item_id):
    """移除引用（只移除 workspace 引用，绝不触碰 canonical 对象，§40/§38）。"""
    kind = str(kind or "").lower()
    field = {"passage": "saved_passages", "concept": "saved_concepts",
             "seminar": "saved_seminars", "term": "saved_terms"}.get(kind)
    if not field:
        raise S.Invalid("invalid reference kind: %s" % kind)

    def fn(p):
        before = len(p.get(field) or [])
        p[field] = [x for x in (p.get(field) or []) if x.get("id") != item_id]
        return len(p[field]) != before
    project, _ = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "remove_%s" % kind, {"id": item_id})
    return project


def add_question(project_id, expected_revision, text, status="OPEN"):
    def fn(p):
        p["research_questions"].append(_question_record(text, status=status))
        return True
    project, _ = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "add_question", {"revision": project["revision"]})
    return project


def set_question_status(project_id, expected_revision, question_id, status):
    """OPEN / RESEARCHED / DEFERRED —— 这是**项目管理状态**，不是 scholarly verdict（§11）。"""
    st = str(status or "").upper()
    if st not in ("OPEN", "RESEARCHED", "DEFERRED"):
        raise S.Invalid("invalid question status: %s" % status)

    def fn(p):
        for q in p["research_questions"]:
            if q["question_id"] == question_id:
                q["status"] = st
                return True
        return False
    project, _ = S.mutate(project_id, expected_revision, fn)
    return project


# ─────────────────────────────────────────────────────────── referent 校验（§54）
def check_referent(kind, item_id):
    """→ {exists, label, status}。不存在 → `Broken reference`（**绝不静默删除**）。"""
    try:
        import browse_api as B                                        # noqa: PLC0415
        if kind == "passage":
            p = B.get_passage_view(item_id)
            if not p:
                return {"exists": False, "status": "BROKEN_REFERENCE", "label": None}
            return {"exists": True, "status": "OK",
                    "label": (p.get("snippet") or "")[:120],
                    "seminar": p.get("seminar"), "language": p.get("language"),
                    "source_layer": p.get("source_layer"),
                    "trace_status": p.get("provenance_status")}
        if kind == "concept":
            idx = B.concept_index()
            item = idx.get(item_id)
            if not item:
                return {"exists": False, "status": "BROKEN_REFERENCE", "label": None}
            return {"exists": True, "status": "OK",
                    "label": item.get("preferred_label"),
                    "layers": list(item.get("layers") or [])}
        if kind == "seminar":
            s = B.store.seminars_index().get(item_id)
            if not s:
                return {"exists": False, "status": "BROKEN_REFERENCE", "label": None}
            return {"exists": True, "status": "OK",
                    "label": s.get("zh_title") or s.get("fr_title"),
                    "year_from": s.get("year_from")}
        if kind == "term":
            t = B.get_term_view(item_id)
            if not t:
                return {"exists": False, "status": "BROKEN_REFERENCE", "label": None}
            return {"exists": True, "status": "OK", "label": t["query"],
                    "entities": [e["concept_id"] for e in t["entities"]]}
    except Exception:                                                 # noqa: BLE001
        return {"exists": False, "status": "UNKNOWN", "label": None}
    return {"exists": False, "status": "UNKNOWN", "label": None}


def enrich(project):
    """给引用补 referent 状态（Broken reference 显式暴露，§54）。"""
    out = dict(project)
    out["referent_status"] = {}
    for kind, field in (("passage", "saved_passages"), ("concept", "saved_concepts"),
                        ("seminar", "saved_seminars"), ("term", "saved_terms")):
        for ref in project.get(field) or []:
            st = check_referent(kind, ref["id"])
            ref = dict(ref)
            ref["referent"] = st
            ref["broken"] = st["status"] == "BROKEN_REFERENCE"
            out["referent_status"][ref["id"]] = ref["broken"]
            idx = [i for i, x in enumerate(out[field]) if x["id"] == ref["id"]]
            if idx:
                out[field][idx[0]] = ref
    out["broken_references"] = sorted(k for k, v in out["referent_status"].items() if v)
    return out
