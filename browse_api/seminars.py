#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browse_api.seminars — Seminar / Session Explorer（Phase 4D.4 §19–§26）

要点：
    * Seminar list 的标题缺失时**如实留空**（不伪造标题，§20）；
    * Session Browser 是**按原顺序连续阅读**的入口（§22），不是搜索过滤器；
    * Seminar 的 concept 分布标注为 **corpus occurrence**（§24），
      形式（formalism）只来自**真实文本上的确定性模式识别**（§25）；
    * Person / Case 只有本体层真的有时才显示，否则明说没有（§26）。
"""
from __future__ import annotations

from . import cursors as CU
from . import store as S

MAX_LIMIT = 50
DEFAULT_LIMIT = 20


def list_seminars(cursor=None, limit=50, year_from=None, year_to=None, query=None):
    """§20：Seminar list。"""
    sems = S.seminars_index()
    sess = S.sessions_index()
    con = S.lexical()
    try:
        counts = {r[0]: int(r[1]) for r in con.execute(
            "select seminar_id, count(*) from passage_meta group by seminar_id")}
        langs = {}
        for r in con.execute("select seminar_id, language, count(*) from passage_meta "
                             "group by seminar_id, language"):
            langs.setdefault(r[0], {})[r[1]] = int(r[2])
        traces = {}
        for r in con.execute("select seminar_id, trace_status, count(*) from passage_meta "
                             "group by seminar_id, trace_status"):
            traces.setdefault(r[0], {})[r[1]] = int(r[2])
    finally:
        con.close()
    wcount = len(S.witnesses_index())
    items = []
    for sid, row in sorted(sems.items()):
        if year_from and (row.get("year_to") or row.get("year_from") or 0) < year_from:
            continue
        if year_to and (row.get("year_from") or 0) > year_to:
            continue
        title = row.get("zh_title") or row.get("fr_title")
        if query and S.fold(query) not in S.fold(" ".join([
                sid, row.get("roman") or "", title or "", row.get("fr_title") or ""])):
            continue
        n_sessions = len([x for x in sess.values() if x.get("seminar_id") == sid])
        items.append({
            "seminar_id": sid,
            "roman": row.get("roman"),
            "title": title,
            "title_fr": row.get("fr_title"),
            "title_missing": title is None,
            "year_from": row.get("year_from"), "year_to": row.get("year_to"),
            "lessons": row.get("lessons"),
            "sessions_n": n_sessions,
            "passages_n": counts.get(sid, 0),
            "languages": sorted((langs.get(sid) or {}).items()),
            "provenance": sorted((traces.get(sid) or {}).items()),
            "witnesses_n": wcount,
            "note": (None if title else "No canonical title recorded."),
        })
    total = len(items)
    keys = CU.decode(cursor, "seminars", {"yf": year_from, "yt": year_to, "q": query}) \
        if cursor else None
    if keys:
        items = [r for r in items if r["seminar_id"] > keys]
    page_items = items[:limit]
    has_more = len(items) > limit
    return {"kind": "seminars", "items": page_items, "total": total,
            "page": CU.page_meta("seminars",
                                 {"yf": year_from, "yt": year_to, "q": query},
                                 limit, len(page_items), has_more,
                                 next_key=(page_items[-1]["seminar_id"]
                                           if has_more and page_items else None),
                                 total=total),
            "title_policy": "titles come from the canonical store; missing titles stay empty"}


def list_sessions(seminar_id, cursor=None, limit=MAX_LIMIT):
    """§21/§22：某研讨班的 sessions（按 lesson 稳定排序；lesson 缺失排在最后并标注）。"""
    seminar_id = _norm_seminar(seminar_id)
    if seminar_id is None:
        raise ValueError("invalid seminar id")
    sess = [x for x in S.sessions_index().values() if x.get("seminar_id") == seminar_id]
    sess.sort(key=lambda x: (x.get("lesson") is None, x.get("lesson") or 0, x.get("id") or ""))
    items = []
    for x in sess:
        items.append({
            "session_id": x.get("id"), "lesson": x.get("lesson"),
            "lesson_missing": x.get("lesson") is None,
            "passage_count": x.get("passage_count"),
            "trace_status": x.get("trace_status"),
            "session_date": x.get("session_date"),
            "date_precision": x.get("session_date_precision"),
            "note": ("This session has no lesson number in the store; it is listed last "
                     "and is not re-numbered." if x.get("lesson") is None else None),
        })
    keys = CU.decode(cursor, "sessions", {"s": seminar_id}) if cursor else None
    if keys:
        items = [r for r in items if str(r["session_id"]) > keys]
    page_items = items[:limit]
    has_more = len(items) > limit
    return {"kind": "sessions", "seminar": seminar_id, "items": page_items,
            "total": len(items),
            "page": CU.page_meta("sessions", {"s": seminar_id}, limit, len(page_items),
                                 has_more,
                                 next_key=(page_items[-1]["session_id"]
                                           if has_more and page_items else None),
                                 total=len(items))}


def _norm_seminar(seminar_id):
    import re                                                     # noqa: PLC0415
    s = str(seminar_id or "").strip()
    if not re.match(r"^(seminar\.)?S\d+[A-Z]?$", s):
        return None
    return s if s.startswith("seminar.") else "seminar." + s


def get_seminar_view(seminar_id, concept_limit=12, passage_limit=10):
    """§21：Seminar Detail（Metadata / Sessions / Concepts / Passages / Formalisms /
    Cases-Persons / Saved Research）。"""
    from . import passages as P                                    # noqa: PLC0415
    sid = _norm_seminar(seminar_id)
    if sid is None:
        return None
    sems = S.seminars_index()
    row = sems.get(sid)
    if row is None:
        return None
    title = row.get("zh_title") or row.get("fr_title")
    langs = {}
    traces = {}
    lesson_counts = {}
    con = S.lexical()
    try:
        for r in con.execute("select language, count(*) from passage_meta where "
                             "seminar_id = ? group by language", (sid,)):
            langs[r[0]] = int(r[1])
        for r in con.execute("select trace_status, count(*) from passage_meta where "
                             "seminar_id = ? group by trace_status", (sid,)):
            traces[r[0]] = int(r[1])
        for r in con.execute("select lesson, count(*) from passage_meta where "
                             "seminar_id = ? group by lesson", (sid,)):
            lesson_counts[r[0]] = int(r[1])
    finally:
        con.close()
    sessions = list_sessions(sid)["items"]
    for s in sessions:
        s["passage_count_meta"] = s.get("passage_count")
        s["passage_count"] = lesson_counts.get(s.get("lesson"), s.get("passage_count"))
    passages = P.browse({"seminar": sid, "limit": passage_limit})
    return {
        "kind": "seminar",
        "metadata": {
            "seminar_id": sid, "roman": row.get("roman"), "title": title,
            "title_fr": row.get("fr_title"), "title_missing": title is None,
            "year_from": row.get("year_from"), "year_to": row.get("year_to"),
            "lessons": row.get("lessons"), "segments": row.get("segments"),
            "languages": sorted(langs.items()),
            "provenance": sorted(traces.items()),
            "note": (None if title else "No canonical title recorded."),
        },
        "sessions": sessions,
        "concepts": _concepts(sid, concept_limit),
        "passages": passages["items"],
        "passages_page": passages["page"],
        "formalisms": P.formalism_counts(sid),
        "cases_persons": _cases_persons(),
        "saved_research": None,          # 由产品层（manifest / Obsidian）填入
    }


def _concepts(seminar_id, limit):
    """§24：研讨班里的概念 **corpus occurrence** 计数（标注为语料出现，不是重要性）。"""
    idx = S.concept_index()
    out = []
    for cid, item in idx.items():
        n = 0
        for pid in item.get("evidence_passages") or []:
            if S.seminar_of_passage(pid) == seminar_id:
                n += 1
        if n:
            out.append({"concept_id": cid, "preferred_label": item.get("preferred_label"),
                        "ontology_evidence_in_seminar_n": n})
    out.sort(key=lambda r: (-r["ontology_evidence_in_seminar_n"], str(r["concept_id"])))
    return {"items": out[:limit], "total": len(out), "mode": "ontology.evidence",
            "attestation": _attestation_in_seminar(seminar_id, limit),
            "label": ("ontology-recorded evidence in this seminar; the second list is "
                      "corpus occurrence count, not theoretical importance")}


def _attestation_in_seminar(seminar_id, limit):
    """在**该研讨班内**做字面形式计数（确定性子串匹配）。"""
    idx = S.concept_index()
    con = S.lexical()
    rows = []
    try:
        for cid, item in idx.items():
            forms = [f["form"] for f in (item.get("forms") or [])][:2]
            hits = 0
            for form in forms:
                hits += int(con.execute(
                    "select count(*) from passage_meta where seminar_id = ? and "
                    "raw_text like ? escape '\\'",
                    (seminar_id, "%" + S._like_escape(form) + "%")).fetchone()[0])  # noqa: SLF001
            if hits:
                rows.append({"concept_id": cid, "preferred_label": item.get("preferred_label"),
                             "passages": hits, "forms_used": forms})
    finally:
        con.close()
    rows.sort(key=lambda r: (-r["passages"], str(r["concept_id"])))
    return {"items": rows[:limit], "total": len(rows),
            "mode": "corpus.form-attestation",
            "label": "corpus occurrence (exact-form substring count within this seminar)"}


def _cases_persons():
    """§26：只有本体层真的有 person / case 实体时才显示，否则如实说明没有。"""
    ents = S.ontology_entities()
    persons = [e for e in ents if str(e.get("entity_role") or "") in
               ("person", "case", "clinical_case")]
    return {"items": [{"id": e.get("id"), "label": e.get("canonical_name"),
                       "role": e.get("entity_role")} for e in persons],
            "available": bool(persons),
            "note": (None if persons else
                     "No person/case entity layer is available in the current "
                     "ontology; nothing is inferred from names in the text.")}
