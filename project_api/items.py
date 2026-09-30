#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_api.items — Open Questions / User Hypotheses / Notes / Bibliography（4D.5 §22–§26/§32）

三种用户对象的边界：
    **Open Question**  研究问题；可来自 run 的 limitation，但必须标来源（§22），
                        写进项目**不会**变成知识关系（§23）。
    **Hypothesis**     `USER_HYPOTHESIS`；必须 `not_validated: true`，
                        视觉上永远与 ValidatedClaim 分开（§24）；
                        「Test with corpus」只是生成 ResearchRequest（§25）。
    **Note**           自由文本；**不进入** scholarly evidence pipeline（§26）。

Bibliography（§32）：只存用户给出的可靠元数据；**禁止模型补齐缺失书目信息**。
`CorpusSource`（系统 provenance）与 `BibliographyRef`（用户引用管理对象）不可互换（§33）。
"""
from __future__ import annotations

import os

from . import store as S

NOTE_MAX_BYTES = 200_000
BIB_SOURCE_TYPES = ("book", "article", "chapter", "thesis", "web", "manuscript",
                    "lecture", "other")


# ─────────────────────────────────────────────────────────── Open Questions（§22/§23）
def add_open_question(project_id, expected_revision, text, origin="user_created",
                      run_id=None, limitation=None):
    if origin not in ("user_created", "created_from_run", "created_from_limitation"):
        raise S.Invalid("invalid origin: %s" % origin)
    if origin != "user_created" and not run_id:
        raise S.Invalid("origin %s requires run_id" % origin)

    def fn(p):
        p["open_questions"].append({
            "question_id": S.new_item_id("oq"),
            "text": S.clean_text(text, 4000, "open question"),
            "origin": origin,
            "run_id": run_id,
            "limitation": (str(limitation)[:1000] if limitation else None),
            "status": "OPEN",
            "created_at": S.now_iso(),
            "is_evidence": False,
            "note": ("An open question is a research question. It does not assert a "
                     "relation and is not knowledge."),
        })
        return True
    project, _ = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "add_open_question", {"origin": origin, "run_id": run_id})
    return project


def open_questions_from_run(project_id, expected_revision, run_id, indices=None):
    """把某 run 的 limitation / missing information 转成 open question（**用户点击才发生**）。"""
    from . import runs as R                                                # noqa: PLC0415
    rec = R.get_run(project_id, run_id)
    if not rec:
        raise S.NotFound("run not found: %s" % run_id)
    view = rec.get("snapshot") or {}
    texts = []
    for i, lim in enumerate(rec.get("limitations") or []):
        if indices is None or i in indices:
            texts.append((str(lim), "created_from_limitation", str(lim)))
    ab = view.get("abstention") or {}
    for item in (ab.get("missing_information") or []):
        texts.append((str(item), "created_from_run", str(item)))
    if not texts:
        raise S.Invalid("this run has no limitation / missing information to convert")
    project = None
    revision = expected_revision
    for text, origin, lim in texts:
        project = add_open_question(project_id, revision, text, origin=origin,
                                    run_id=run_id, limitation=lim)
        revision = project["revision"]
    return project


# ─────────────────────────────────────────────────────────── Hypotheses（§24/§25）
def add_hypothesis(project_id, expected_revision, text, rationale=None):
    def fn(p):
        p["hypotheses"].append({
            "hypothesis_id": S.new_item_id("hyp"),
            "text": S.clean_text(text, 4000, "hypothesis"),
            "rationale": (S.clean_text(rationale, 4000, "rationale")
                          if rationale else None),
            "created_at": S.now_iso(),
            "object_class": "USER_HYPOTHESIS",
            "not_validated": True,
            "label": "User hypothesis · not validated by the Scholarly Core",
            "test_runs": [],
        })
        return True
    project, _ = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "add_hypothesis", {"revision": project["revision"]})
    return project


def record_hypothesis_test(project_id, expected_revision, hypothesis_id, run_id,
                           answer_state):
    """§25：Core 决定 SUPPORTED/QUALIFIED/ABSTAINED；hypothesis 本身仍是用户对象。"""
    def fn(p):
        for h in p["hypotheses"]:
            if h["hypothesis_id"] == hypothesis_id:
                h["test_runs"].append({"run_id": run_id, "answer_state": answer_state,
                                       "at": S.now_iso(),
                                       "note": "Core answer state; hypothesis stays a user object."})
                return True
        return False
    project, _ = S.mutate(project_id, expected_revision, fn)
    return project


def hypothesis_research_request(hypothesis_text):
    """§25：生成 ResearchRequest 的预填（只预填，不执行）。"""
    q = ("请检验以下假设是否有语料支持，并给出可核证的反例或限制：%s"
         % str(hypothesis_text or "").strip())
    return {"tool": "lacan.research", "mode": "scholarly",
            "request": {"question": q},
            "note": ("The hypothesis is a user object. The Core decides the verdict; "
                     "the Project never labels a hypothesis as validated.")}


# ─────────────────────────────────────────────────────────── Notes（§26）
def add_note(project_id, expected_revision, text, title=None):
    text = S.clean_text(text, NOTE_MAX_BYTES, "note")
    note_id = S.new_item_id("note")

    def fn(p):
        p["notes"].append({"note_id": note_id, "title": (title or "")[:200] or None,
                           "text": text, "created_at": S.now_iso(),
                           "is_evidence": False})
        return True
    project, _ = S.mutate(project_id, expected_revision, fn)
    # 同时落一份 Markdown（用户可读；**不**进入 evidence pipeline）
    path = os.path.join(S.project_dir(project_id), "notes", "%s.md" % note_id)
    S.POL.assert_writable(path)                                           # noqa: SLF001
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\nnote_id: %s\nproject_id: %s\nis_evidence: false\n---\n\n# %s\n\n%s\n"
                % (note_id, project_id, (title or "Note"), text))
    S.append_audit(project_id, "add_note", {"note_id": note_id})
    return project


def update_note(project_id, expected_revision, note_id, text=None, title=None):
    def fn(p):
        for n in p["notes"]:
            if n["note_id"] == note_id:
                if text is not None:
                    n["text"] = S.clean_text(text, NOTE_MAX_BYTES, "note")
                if title is not None:
                    n["title"] = str(title)[:200] or None
                n["updated_at"] = S.now_iso()
                return True
        return False
    project, _ = S.mutate(project_id, expected_revision, fn)
    return project


def remove_note(project_id, expected_revision, note_id):
    def fn(p):
        before = len(p["notes"])
        p["notes"] = [n for n in p["notes"] if n["note_id"] != note_id]
        return len(p["notes"]) != before
    project, _ = S.mutate(project_id, expected_revision, fn)
    path = os.path.join(S.project_dir(project_id), "notes", "%s.md" % note_id)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    return project


# ─────────────────────────────────────────────────────────── Bibliography（§32/§33）
def add_bibliography_ref(project_id, expected_revision, title, author=None, year=None,
                         source_type=None, identifier=None, url_or_reference=None,
                         user_note=None):
    """只存**用户提供**的字段；缺失就是缺失（不补齐、不猜）。"""
    if not str(title or "").strip():
        raise S.Invalid("bibliography title is required")
    st = (str(source_type).lower() if source_type else None)
    if st and st not in BIB_SOURCE_TYPES:
        raise S.Invalid("invalid source_type: %s" % source_type)
    if year not in (None, ""):
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise S.Invalid("invalid year")

    def fn(p):
        p["bibliography_refs"].append({
            "ref_id": S.new_item_id("bib"),
            "title": S.clean_text(title, 500, "bibliography title"),
            "author": (str(author)[:300] if author else None),
            "year": year,
            "source_type": st,
            "identifier": (str(identifier)[:200] if identifier else None),
            "url_or_reference": (str(url_or_reference)[:1000] if url_or_reference else None),
            "user_note": (S.clean_text(user_note, 4000, "note") if user_note else None),
            "created_at": S.now_iso(),
            "object_class": "BibliographyRef",
            "missing_fields": [k for k, v in (("author", author), ("year", year),
                                              ("source_type", st),
                                              ("identifier", identifier))
                               if not v],
            "note": ("A BibliographyRef is a user reference-management object. It is "
                     "NOT a CorpusSource and never substitutes for system provenance."),
        })
        return True
    project, _ = S.mutate(project_id, expected_revision, fn)
    S.append_audit(project_id, "add_bibliography_ref",
                   {"revision": project["revision"]})
    return project


def remove_bibliography_ref(project_id, expected_revision, ref_id):
    def fn(p):
        before = len(p["bibliography_refs"])
        p["bibliography_refs"] = [x for x in p["bibliography_refs"]
                                  if x["ref_id"] != ref_id]
        return len(p["bibliography_refs"]) != before
    project, _ = S.mutate(project_id, expected_revision, fn)
    return project


# ─────────────────────────────────────────────────────────── 项目内搜索（§34）
def search_project(project_id, query, limit=50):
    """只搜项目自身内容（questions / notes / refs / run 标题），**不搜 corpus**。"""
    p = S.read_project(project_id)
    q = str(query or "").casefold().strip()
    if not q:
        return {"items": [], "total": 0, "note": "empty query"}
    hits = []

    def hit(kind, ident, text, extra=None):
        hits.append({"kind": kind, "id": ident, "text": text, **(extra or {})})

    for x in p.get("research_questions") or []:
        if q in str(x.get("text") or "").casefold():
            hit("question", x["question_id"], x["text"], {"status": x.get("status")})
    for x in p.get("research_runs") or []:
        if q in str(x.get("question") or "").casefold():
            hit("run", x["run_id"], x["question"],
                {"answer_state": x.get("answer_state")})
    for x in p.get("notes") or []:
        if q in str(x.get("text") or "").casefold() or q in str(x.get("title") or "").casefold():
            hit("note", x["note_id"], (x.get("title") or x["text"])[:200])
    for field, kind in (("saved_passages", "passage"), ("saved_concepts", "concept"),
                        ("saved_seminars", "seminar"), ("saved_terms", "term")):
        for x in p.get(field) or []:
            if q in str(x.get("id") or "").casefold() or q in str(
                    x.get("referent_label") or "").casefold():
                hit(kind, x["id"], x.get("referent_label") or x["id"])
    for x in p.get("open_questions") or []:
        if q in str(x.get("text") or "").casefold():
            hit("open_question", x["question_id"], x["text"])
    for x in p.get("hypotheses") or []:
        if q in str(x.get("text") or "").casefold():
            hit("hypothesis", x["hypothesis_id"], x["text"])
    for x in p.get("bibliography_refs") or []:
        if q in str(x.get("title") or "").casefold():
            hit("bibliography", x["ref_id"], x["title"])
    return {"items": hits[:limit], "total": len(hits),
            "scope": "project content only (corpus search lives in the Explorer)"}


# ─────────────────────────────────────────────────────────── 时间线（§51）
def timeline(project_id, limit=200):
    """workspace activity（不是理论 timeline）。"""
    p = S.read_project(project_id)
    ev = [{"at": p.get("created_at"), "kind": "project_created", "label": p.get("title")}]
    if p.get("status") == "ARCHIVED":
        ev.append({"at": p.get("updated_at"), "kind": "archived", "label": p.get("title")})
    for x in p.get("research_questions") or []:
        ev.append({"at": x.get("created_at"), "kind": "question", "label": x.get("text")})
    for x in p.get("research_runs") or []:
        ev.append({"at": x.get("created_at"), "kind": "run",
                   "label": "%s · %s" % (x.get("answer_state"), x.get("question")),
                   "run_id": x.get("run_id")})
    for field, kind in (("saved_passages", "passage_saved"), ("saved_concepts", "concept_saved"),
                        ("saved_seminars", "seminar_saved"), ("saved_terms", "term_saved")):
        for x in p.get(field) or []:
            ev.append({"at": x.get("added_at"), "kind": kind, "label": x.get("id")})
    for x in p.get("open_questions") or []:
        ev.append({"at": x.get("created_at"), "kind": "open_question", "label": x.get("text")})
    for x in p.get("hypotheses") or []:
        ev.append({"at": x.get("created_at"), "kind": "hypothesis", "label": x.get("text")})
    for x in p.get("notes") or []:
        ev.append({"at": x.get("created_at"), "kind": "note",
                   "label": x.get("title") or "(note)"})
    for x in p.get("bibliography_refs") or []:
        ev.append({"at": x.get("created_at"), "kind": "bibliography", "label": x.get("title")})
    ev = [e for e in ev if e.get("at")]
    ev.sort(key=lambda e: str(e["at"]))
    return {"items": ev[-limit:], "total": len(ev),
            "label": "workspace activity (not a theoretical timeline)"}
