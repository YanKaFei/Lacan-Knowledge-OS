#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browse_api.passages — Passage Explorer 的只读查询（Phase 4D.4 §9–§18）

**Corpus Browse ≠ Research Retrieval**（§41）：
    * 这里的筛选是对全部 249,105 行的 **SQL 级 exhaustive 过滤**（真·全库），
      并在响应里给出 `exhaustive: true` 与命中总数；
    * 4D.1 的 `lacan.search_passages` 是研究检索，session/source_layer/date_range/
      concept/formalism 属于 **top_k 之后的后置过滤**（`post_filtered: true`）。
      两条路径分开命名、分开实现，绝不混用（§39/§40/§41）。
"""
from __future__ import annotations

import os
import re

from . import cursors as CU
from . import store as S

MAX_LIMIT = 50
DEFAULT_LIMIT = 20
SNIPPET_CHARS = 280

_LANG = ("fr", "zh", "en")
_LAYERS = ("L1", "L2", "L3", "EDITORIAL", "METADATA")
_PROV = ("COMPLETE", "SOURCE_TRACE_INCOMPLETE")


class FilterError(ValueError):
    pass


def normalise_filters(raw):
    """把 UI 传来的筛选值规范化；非法值**报错**而不是静默忽略（§62）。"""
    f = dict(raw or {})
    out = {}
    seminar = f.get("seminar")
    if seminar:
        s = str(seminar).strip()
        if not re.match(r"^(seminar\.)?S\d+[A-Z]?$", s):
            raise FilterError("invalid seminar filter")
        out["seminar"] = s if s.startswith("seminar.") else "seminar." + s
    session = f.get("session")
    if session:
        s = str(session).strip()
        if not re.match(r"^session\.[A-Za-z0-9._-]+$", s):
            raise FilterError("invalid session filter")
        out["session"] = s
    lesson = f.get("lesson")
    if lesson not in (None, ""):
        try:
            n = int(lesson)
        except (TypeError, ValueError):
            raise FilterError("invalid lesson filter")
        if n < 0 or n > 999:
            raise FilterError("lesson out of range")
        out["lesson"] = n
    lang = f.get("language")
    if lang and lang != "any":
        if lang not in _LANG:
            raise FilterError("invalid language filter")
        out["language"] = lang
    layer = f.get("source_layer")
    if layer and layer != "any":
        if str(layer).upper() not in _LAYERS:
            raise FilterError("invalid source_layer filter")
        out["source_layer"] = str(layer).upper()
    prov = f.get("provenance")
    if prov and prov != "any":
        if str(prov).upper() not in _PROV:
            raise FilterError("invalid provenance filter")
        out["provenance"] = str(prov).upper()
    role = f.get("text_role")
    if role and role != "any":
        if role not in ("transcription", "translation"):
            raise FilterError("invalid text_role filter")
        out["text_role"] = role
    for k in ("year_from", "year_to"):
        v = f.get(k)
        if v not in (None, ""):
            try:
                n = int(v)
            except (TypeError, ValueError):
                raise FilterError("invalid %s" % k)
            if n < 1900 or n > 2100:
                raise FilterError("%s out of range" % k)
            out[k] = n
    concept = f.get("concept")
    if concept:
        c = str(concept).strip()
        if not re.match(r"^[A-Za-z0-9._-]{3,80}$", c):
            raise FilterError("invalid concept filter")
        out["concept"] = c
    formalism = f.get("formalism")
    if formalism:
        names = [p[0] for p in S.FORMALISM_PATTERNS]
        if str(formalism) not in names:
            raise FilterError("invalid formalism filter")
        out["formalism"] = str(formalism)
    try:
        lim = int(f.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        raise FilterError("invalid limit")
    out["limit"] = max(1, min(lim, MAX_LIMIT))          # §62：硬上限
    return out


def _where(f):
    clauses, args = [], []

    def add(sql, *vals):
        clauses.append(sql)
        args.extend(vals)

    if f.get("seminar"):
        add("seminar_id = ?", f["seminar"])
    if f.get("session"):
        add("session_id = ?", f["session"])
    if f.get("lesson") is not None:
        add("lesson = ?", f["lesson"])
    if f.get("language"):
        add("language = ?", f["language"])
    if f.get("source_layer"):
        add("authority_level = ?", f["source_layer"])
    if f.get("provenance"):
        add("trace_status = ?", f["provenance"])
    if f.get("text_role"):
        add("text_role = ?", f["text_role"])
    if f.get("year_from") or f.get("year_to"):
        sems = [sid for sid, row in S.seminars_index().items()
                if _year_overlap(row, f.get("year_from"), f.get("year_to"))]
        if not sems:
            add("0 = 1")
        else:
            clauses.append("seminar_id in (%s)" % ",".join("?" * len(sems)))
            args.extend(sorted(sems))
    return (" where " + " and ".join(clauses)) if clauses else "", tuple(args)


def _year_overlap(row, y_from, y_to):
    a = row.get("year_from")
    b = row.get("year_to") or a
    if a is None:
        return False
    if y_from and b is not None and b < y_from:
        return False
    if y_to and a > y_to:
        return False
    return True


def _row_out(row, snippet_chars=SNIPPET_CHARS):
    text = row["raw_text"] or ""
    out = {
        "passage_id": row["id"],
        "seminar": row["seminar_id"],
        "session": row["session_id"],
        "lesson": row["lesson"],
        "language": row["language"],
        "source_layer": row["authority_level"],
        "text_role": row["text_role"],
        "status": row["status"],
        "provenance_status": row["trace_status"],
        "witness": row["witness_id"],
        "canonical": bool(row["canonical"]),
        "review_status": row["review_status"],
        "snippet": text[:snippet_chars],
        "text_length": len(text),
        "truncated": len(text) > snippet_chars,
    }
    return out


def _order_clause(kind):
    """顺序 = `id` 字典序。

    实测：全部 249,105 条 id 的段号都是定宽 `P%04d`（S.unknown.Pxxxx 166,527 条 /
    S.unknown.Lxx.Pxxxx 82,578 条），课次也是定宽 `L%02d`；所以**字典序 == 语料顺序**。
    这也让游标退化为单一键（稳定、无重复、无缺行），不需要 offset（§44）。
    """
    return " order by id asc"


def browse(filters=None, cursor=None, kind="passages"):
    """→ {kind, filters, items[], page{}}。全库 exhaustive 过滤（count 现算）。"""
    f = normalise_filters(filters)
    limit = f.pop("limit")
    concept_mode = None
    extra_ids = None
    if f.get("concept"):
        extra_ids, concept_mode = _concept_passage_ids(f["concept"])
        if not extra_ids:
            return {"kind": kind, "filters": f, "items": [],
                    "page": dict(CU.page_meta(kind, f, limit, 0, False, total=0),
                                 exhaustive=True),
                    "concept_filter_mode": concept_mode,
                    "notice": "No matching passages under current browse filters."}
    formalism = f.pop("formalism", None)
    cur_keys = CU.decode(cursor, kind, f) if cursor else None
    where, args = _where(f)
    if extra_ids is not None:
        where = (where + " and " if where else " where ") + \
            "id in (%s)" % ",".join("?" * len(extra_ids))
        args = tuple(args) + tuple(extra_ids)
    if formalism:
        pat = dict(S.FORMALISM_PATTERNS)[formalism]
        where = (where + " and " if where else " where ") + "raw_text regexp ?"
        args = tuple(args) + (pat,)
    # ⚠️ `total` 必须是**当前 filters** 的命中总数，与翻到第几页无关；
    #    `remaining` 才是从本页游标之后还剩多少（实测踩过：把带游标的 count 当 total，
    #    第 2 页的 total 会莫名少掉第 1 页的行数）。
    base_where, base_args = where, tuple(args)
    if cur_keys:
        pid = cur_keys[-1] if isinstance(cur_keys, list) else cur_keys
        where = (where + " and " if where else " where ") + "id > ?"
        args = tuple(args) + (pid,)
    order = _order_clause(kind)
    fetch = limit + 1
    con = S.lexical()
    try:
        con.create_function("regexp", 2,
                            lambda p_, v: 1 if re.search(p_, v or "") else 0)
        total = int(con.execute("select count(*) from passage_meta " + base_where,
                                base_args).fetchone()[0])
        remaining = int(con.execute("select count(*) from passage_meta " + where,
                                    args).fetchone()[0])
        rows = con.execute(
            "select id, seminar_id, session_id, lesson, language, authority_level, "
            "text_role, status, trace_status, witness_id, canonical, review_status, "
            "raw_text from passage_meta " + where + order +
            " limit ?", tuple(args) + (fetch,)).fetchall()
    finally:
        con.close()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [_row_out(r) for r in rows]
    next_key = rows[-1]["id"] if (has_more and rows) else None
    page = CU.page_meta(kind, f, limit, len(items), has_more, next_key=next_key,
                        cursor_in=cur_keys, total=total)
    page["remaining"] = remaining
    page["exhaustive"] = True
    page["filter_mode"] = "server-side SQL over the full corpus (browse layer)"
    return {"kind": kind, "filters": f, "items": items, "page": page,
            "concept_filter_mode": concept_mode}


def _concept_passage_ids(concept_id):
    """概念 → passage ids 的**两种语义**必须分开标注（§33）。

    1. `ontology.evidence`：ontology 实体里记录的 passage evidence（可能只是样本）；
    2. `corpus.form-attestation`：按该概念的字面形式在语料里做 deterministic 匹配。
       仅当 ontology 没有记录证据时使用，并在响应里明确标注。
    """
    idx = S.concept_index()
    item = idx.get(concept_id)
    if not item:
        return [], "unknown-concept"
    ids = [p for p in item.get("evidence_passages") or []]
    if ids:
        return ids, "ontology.evidence"
    forms = [x["form"] for x in item.get("forms") or []][:4]
    if not forms:
        return [], "no-forms"
    con = S.lexical()
    try:
        found = []
        for form in forms:
            pat = "%" + S._like_escape(form) + "%"          # noqa: SLF001
            for r in con.execute("select id from passage_meta where raw_text like ? "
                                 "escape '\\' order by id limit 400", (pat,)):
                found.append(r[0])
        return sorted(set(found)), "corpus.form-attestation"
    finally:
        con.close()


# ─────────────────────────────────────────────────────────── 单段视图
def get_passage(passage_id):
    con = S.lexical()
    try:
        row = con.execute("select * from passage_meta where id = ?",
                          (str(passage_id),)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    d = dict(row)
    out = _row_out(row, snippet_chars=10 ** 9)
    out["text"] = d.get("raw_text")
    out["session_date"] = d.get("session_date")
    out["session_date_precision"] = d.get("session_date_precision")
    out["corpus_source_id"] = d.get("corpus_source_id")
    out["document_id"] = d.get("document_id")
    return out


def context(passage_id, before=2, after=2):
    """±N 上下文（§14）。只取该 session 内的相邻段，按 sequence 稳定排序。"""
    before = max(0, min(int(before or 0), 10))
    after = max(0, min(int(after or 0), 10))
    con = S.lexical()
    try:
        head = con.execute("select * from passage_meta where id = ?",
                           (str(passage_id),)).fetchone()
        if head is None:
            return None
        # 语料顺序 = id 字典序（P%04d 定宽）。先定位目标 id 在 session 内的序号，
        # 再取 ±N 行；不使用 OFFSET 翻页，也不会一次载入整个 session（§14）。
        ids = [r[0] for r in con.execute(
            "select id from passage_meta where session_id = ? order by id",
            (head["session_id"],))]
        try:
            pos = ids.index(str(passage_id))
        except ValueError:
            return None
        window = ids[max(0, pos - before): pos + after + 1]
        rows = con.execute(
            "select id, session_id, seminar_id, language, lesson, authority_level, "
            "trace_status, raw_text from passage_meta where id in (%s) order by id"
            % ",".join("?" * len(window)), tuple(window)).fetchall()
    finally:
        con.close()
    items = []
    for r in rows:
        items.append({"passage_id": r["id"], "session": r["session_id"],
                      "seminar": r["seminar_id"], "language": r["language"],
                      "source_layer": r["authority_level"],
                      "provenance_status": r["trace_status"],
                      "lesson": r["lesson"],
                      "text": r["raw_text"],
                      "is_target": r["id"] == passage_id})
    target_index = next((i for i, x in enumerate(items) if x["is_target"]), None)
    return {"passage_id": passage_id, "before": before, "after": after,
            "session": head["session_id"], "seminar": head["seminar_id"],
            "items": items, "target_index": target_index,
            "session_total": _session_total(head["session_id"])}


def _session_total(session_id):
    con = S.lexical()
    try:
        return int(con.execute("select count(*) from passage_meta where session_id = ?",
                               (session_id,)).fetchone()[0])
    finally:
        con.close()


def session_stream(session_id, cursor=None, limit=DEFAULT_LIMIT):
    """Session 顺序阅读流（§22/§23）。顺序 = passage id 字典序 = 语料顺序。"""
    f = {"session": str(session_id), "limit": limit}
    return browse(f, cursor=cursor, kind="session")


def witnesses(passage_id):
    """§16：该段的 witness / realization。**witness ≠ translation ≠ canonical identity**。"""
    out = {"passage_id": passage_id, "linked": [], "unlinked_witnesses": [],
           "note": ("A witness is a carrier of text (transcription / edition extract / "
                    "translation). It is not the canonical passage identity, and a "
                    "translation is not a witness of the same kind.")}
    widx = S.witnesses_index()
    con = S.store()
    try:
        for r in con.execute("select * from passage_witnesses where passage_id = ?",
                             (str(passage_id),)):
            w = widx.get(r["witness_id"]) or {}
            out["linked"].append({
                "witness_id": r["witness_id"], "link_role": r["link_role"],
                "authority_level": r["authority_level"],
                "method": r["method"], "review_status": r["review_status"],
                "language": w.get("language"), "witness_kind": w.get("witness_kind"),
                "edition": w.get("edition"), "status": w.get("status"),
                "corpus_source_id": w.get("corpus_source_id"),
                "provenance_note": w.get("provenance_note"),
            })
        linked = {x["witness_id"] for x in out["linked"]}
        for wid, w in sorted(widx.items()):
            if wid in linked:
                continue
            out["unlinked_witnesses"].append({
                "witness_id": wid, "language": w.get("language"),
                "witness_kind": w.get("witness_kind"), "edition": w.get("edition"),
                "passage_link_state": w.get("passage_link_state") or "not_linked",
                "note": ("存在这份 witness，但当前 passage store **没有**把它与这一段"
                         "建立 realization 链接 —— 不隐藏，也不假装已对齐。"),
            })
    finally:
        con.close()
    sid = S.seminar_of_passage(passage_id)
    out["seminar"] = sid
    return out


def realization_languages(passage_id):
    """§15：语言/对译。语料**没有**可靠的 fr↔zh 对齐 → 如实说明，禁止猜对齐。"""
    p = get_passage(passage_id)
    if p is None:
        return None
    con = S.lexical()
    try:
        langs = [r[0] for r in con.execute(
            "select distinct language from passage_meta where session_id = ? "
            "order by language", (p["session"],))]
    finally:
        con.close()
    aligned = _aligned_targets(passage_id)
    return {
        "passage_id": passage_id,
        "language": p["language"],
        "available_languages": langs,
        "aligned": aligned,
        "aligned_available": bool(aligned),
        "note": ("No aligned realization available." if not aligned else
                 "Aligned realization(s) come from the passage store's alignment "
                 "records only (never from text similarity)."),
        "policy": ("Alignment is never inferred from similar text. The corpus's "
                   "alignment records are seeds/placeholders, so side-by-side is "
                   "shown only when a stored alignment exists."),
    }


def _aligned_targets(passage_id):
    path = os.path.join(S.VAULT, "_data", "passage_store", "alignments.jsonl")
    if not os.path.isfile(path):
        return []
    out = []
    for rec in S._read_jsonl(path):                              # noqa: SLF001
        if passage_id in (rec.get("source_passage_id"), rec.get("target_passage_id")):
            out.append(rec)
    return out


def source_trace(passage_id):
    """§17：CorpusSource → Witness → PassageRealization → Session → Seminar。

    断点必须显式列出（`broken_at`），不补空、不猜。
    """
    p = get_passage(passage_id)
    if p is None:
        return None
    widx = S.witnesses_index()
    cidx = S.corpus_sources_index()
    tidx = S.translations_index()
    sid = S.seminar_of_passage(passage_id)
    sem = S.seminars_index().get(sid) or {}
    ses = S.sessions_index().get(p["session"]) or {}
    realizations = []
    con = S.store()
    try:
        for r in con.execute("select * from passage_realizations where passage_id = ?",
                             (str(passage_id),)):
            realizations.append(dict(r))
    finally:
        con.close()
    w = widx.get(p.get("witness")) or {}
    translation = S.translations_by_witness().get(p.get("witness"))
    chain = [
        {"step": "CorpusSource", "id": p.get("corpus_source_id")
            or w.get("corpus_source_id"), "label": (cidx.get(
                p.get("corpus_source_id") or w.get("corpus_source_id")) or {}).get("name"),
         "present": bool(p.get("corpus_source_id") or w.get("corpus_source_id"))},
        {"step": "Witness", "id": p.get("witness"), "label": w.get("edition"),
         "present": bool(p.get("witness"))},
        {"step": "PassageRealization", "id": (realizations[0].get("witness_id")
                                              if realizations else None),
         "label": (realizations[0].get("method") if realizations else None),
         "present": bool(realizations)},
        {"step": "Session", "id": p.get("session"),
         "label": ("lesson %s" % ses.get("lesson")) if ses.get("lesson") else
                  ("session (%d passages)" % (ses.get("passage_count") or 0)),
         "present": bool(p.get("session"))},
        {"step": "Seminar", "id": sid,
         "label": sem.get("zh_title") or sem.get("fr_title"),
         "present": bool(sid and sem)},
    ]
    for step in chain:
        if step["step"] == "CorpusSource" and not (cidx.get(step["id"]) or {}).get("name"):
            step["label"] = step["label"] or "(source id not recorded)"
    broken = [s["step"] for s in chain if not s["present"]]
    missing = list(p.get("trace_missing") or []) if isinstance(p.get("trace_missing"),
                                                              list) else []
    tnote = S.translation_notes().get((translation or {}).get("id")) or {}
    note = w.get("provenance_note") or tnote.get("provenance_note")
    note_source = ("witness.provenance_note" if w.get("provenance_note")
                   else ("translation.provenance_note" if tnote.get("provenance_note")
                         else None))
    return {
        "passage_id": passage_id,
        "chain": chain,
        "broken_at": broken,
        "trace_status": p.get("provenance_status"),
        "trace_missing": missing or _trace_missing(p),
        "complete": not broken and p.get("provenance_status") == "COMPLETE",
        "translation": ({"translation_id": translation.get("id"),
                         "edition": translation.get("edition"),
                         "provenance_note": tnote.get("provenance_note"),
                         "source_state": tnote.get("source_state")}
                        if translation else None),
        "witness_note": note,
        "witness_note_source": note_source,
        "witness_edition": w.get("edition"),
        "witness_kind": w.get("witness_kind"),
        "source_state": w.get("source_state") or tnote.get("source_state"),
    }


def _trace_missing(p):
    out = []
    if not p.get("witness"):
        out.append("witness")
    if p.get("provenance_status") == "SOURCE_TRACE_INCOMPLETE":
        out.append("upstream_original_file")
    return out


def formalism_counts(seminar=None, limit=12):
    """§25：**确定性模式识别**（正则）在真实语料文本上计数。

    这是「语料里出现过这个写法」，**不是** canonical formalism metadata，
    更不是 LLM 生成的公式索引。每条都带可分页的 passage 证据。
    """
    where, args = _where({"seminar": seminar} if seminar else {})
    out = []
    con = S.lexical()
    try:
        for name, pat in S.FORMALISM_PATTERNS:
            con.create_function("regexp", 2, lambda p_, v: 1 if re.search(p_, v or "") else 0)
            n = int(con.execute("select count(*) from passage_meta " + where +
                                (" and " if where else " where ") + "raw_text regexp ?",
                                tuple(args) + (pat,)).fetchone()[0])
            if not n:
                continue
            sample = [r[0] for r in con.execute(
                "select id from passage_meta " + where +
                (" and " if where else " where ") + "raw_text regexp ? order by id limit 5",
                tuple(args) + (pat,))]
            out.append({"formalism": name, "pattern": pat, "passages": n,
                        "sample_passages": sample, "detected_by": "regex over corpus text"})
    finally:
        con.close()
    out.sort(key=lambda r: (-r["passages"], r["formalism"]))
    return {"seminar": seminar, "items": out[:limit], "method": "deterministic regex count",
            "is_canonical_metadata": False}


def seminar_distribution(concept_id, limit=None):
    """§7D：concept 的 corpus distribution（passage count by seminar）。

    明确是 **corpus occurrence**，不是理论重要性评分（§7D/§24）。
    """
    ids, mode = _concept_passage_ids(concept_id)
    if not ids:
        return {"concept_id": concept_id, "mode": mode, "seminars": [], "total": 0}
    con = S.lexical()
    try:
        rows = []
        chunk = 500
        counts: dict = {}
        for i in range(0, len(ids), chunk):
            part = ids[i:i + chunk]
            for r in con.execute(
                    "select seminar_id, count(*) from passage_meta where id in (%s) "
                    "group by seminar_id" % ",".join("?" * len(part)), tuple(part)):
                counts[r[0]] = counts.get(r[0], 0) + int(r[1])
    finally:
        con.close()
    rows = [{"seminar": k, "passages": v} for k, v in sorted(counts.items())]
    if limit:
        rows = rows[:limit]
    return {"concept_id": concept_id, "mode": mode, "seminars": rows,
            "total": sum(x["passages"] for x in rows),
            "label": "corpus occurrence (passage count), not theoretical importance"}


def diachronic_view(concept_id):
    """§7E：时间轴 = 语料出现（year / seminar / passages）。

    **不**自动推导「概念从 A 演化到 B」—— 那必须走 Research Engine（diachronic）。
    """
    dist = seminar_distribution(concept_id)
    sems = S.seminars_index()
    points = []
    for row in dist["seminars"]:
        s = sems.get(row["seminar"]) or {}
        year = s.get("year_from")
        points.append({"year": year, "year_to": s.get("year_to"),
                       "seminar": row["seminar"], "passages": row["passages"],
                       "title": s.get("zh_title") or s.get("fr_title")})
    points.sort(key=lambda p: (p["year"] is None, p["year"] or 0, p["seminar"]))
    return {"concept_id": concept_id, "points": points, "mode": dist["mode"],
            "derived_conclusion": None,
            "note": ("Timeline reports where the concept appears in the corpus. "
                     "It does not infer theoretical evolution; run diachronic "
                     "research for that.")}
