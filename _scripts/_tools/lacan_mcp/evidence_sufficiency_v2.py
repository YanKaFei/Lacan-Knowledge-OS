#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evidence_sufficiency_v2.py — Phase 4C：**分层的证据充分性判定**

为什么必须分层（Phase 4B 的实证）
─────────────────────────────────
`rt-J02`（拉康如何看待 fMRI / 当代神经科学）取到 10 条证据并判 `SUPPORTED`，
而实测：`fMRI` 全库 0（词法索引）/ 3 段旁及提及，`neuroscience(s)` 0 段，
没有任何实体、关系或专门论述。

问题在于 v1 把两件事混成一个判断：

* **找到了相关文本**（availability）
* **这些文本是否真的以该问题为主题**（topicality）

v2 把它们拆开，并加上 coverage / source / ontology 三层，最后才给
`final_state`。**不引入任何 0–1 的神秘 confidence，也不使用 cosine 阈值。**

六层输出（§12）
───────────────
    availability_state : NONE / SPARSE / AVAILABLE
    topicality_state   : ABSENT / INCIDENTAL / CONTEXTUAL / SUBSTANTIAL / DIRECT
    coverage_state     : NONE / LOW / MEDIUM / HIGH
    source_state       : NO_EVIDENCE / RECOVERED_ONLY / SECONDARY_ONLY /
                         PRIMARY_PRESENT_BUT_NON_TOPICAL / PRIMARY_PRESENT
    ontology_state     : ENTITY_PRESENT / CANDIDATE_ONLY / MISSING_ENTITY /
                         ENTITY_COLLISION / AMBIGUOUS_ENTITY
    final_state        : SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE /
                         CONFLICTING_EVIDENCE
    + reasons[] / signals / absence_profile / structural_unanswerability

每条证据的 `topic_support_level`（§5）
─────────────────────────────────────
    DIRECT      明确讨论目标概念（实体已连接 + 段内重复/邻域持续/与核心概念共现）
    SUBSTANTIAL 未给定义但明显参与论证（实体已连接，但缺少上述加强信号）
    CONTEXTUAL  提供必要上下文，不能单独支持核心 claim（含相关实体但不含主题词）
    INCIDENTAL  只提到名词/人名/技术词（无实体连接、无加强信号）

**directness > raw count**（§14）：1–2 条 DIRECT 的 L1 原文可以 SUPPORTED；
10 条 INCIDENTAL 不可以。规则见 `_decide`。

方法学纪律
──────────
* 全部信号都是**可复核的结构事实**（词法计数、实体连接、研讨班/时期分布、
  检索分量、溯源状态），没有模型打分、没有概率层；
* `corpus_prevalence` 用词法索引的**精确计数**（不是 limit=50 的截断），
  因为「辨别性术语」和「泛用词」必须分开：实测 fMRI 的问题里
  `拉康`/`看待` 命中都很多，而 `fMRI` 才是主题词。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

import evidence_sufficiency as es1      # noqa: E402  （v1：保留其 signals 与历史语义）
import knowledge_api as _api            # noqa: E402  （只用 KB_.concepts()/meta()）

METHOD = "structural_only_no_cosine_threshold"
ENGINE = "evidence_sufficiency/v2"

LEX = os.path.join(VAULT, "_data", "index", "lexical.sqlite")
LAYER = os.path.join(VAULT, "_data", "ontology", "v4a1")

# ── 预登记阈值（写在代码里，不是事后凑的）
GENERIC_PREVALENCE = 300      # 超过这个命中数的词视为「泛用词」，不承担主题
SPARSE_PREVALENCE = 5         # 辨别性术语命中 < 5 → 语料对该主题稀疏
DENSE_EVIDENCE_MIN = 6        # 「dense」的参考下限
DIRECT_MIN = 1                # 至少 1 条 DIRECT 才可能 SUPPORTED
SUBSTANTIAL_MIN = 2           # SUBSTANTIAL 路线至少要 2 条
MULTI_SEMINAR_MIN = 2

_APOS = re.compile(r"['’`]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)
_CJK = re.compile(r"[\u4e00-\u9fff]")

TOPIC_LEVELS = ("DIRECT", "SUBSTANTIAL", "CONTEXTUAL", "INCIDENTAL")

# 结构性不可答（§11）
STRUCTURAL_CLASSES = ("METADATA_UNAVAILABLE", "TOPIC_NOT_COVERED",
                      "SOURCE_CHAIN_INCOMPLETE", "ONTOLOGY_GAP",
                      "FORMALISM_MISSING")

# ⚠️ 只认**符号/数学型**诉求，不认拓扑对象名。
#    第一版把「莫比乌斯」「拓扑」也算进来，于是 rt-J01 被判 FORMALISM_MISSING ——
#    但语料确实用**散文**解释了莫比乌斯带的单面性（S09 L15），那正是该问题的形式内容。
#    窄化后：只有问题真的要公式/数学型（$ ◊ ◇、mathème、公式、数学型）才谈「缺形式化」。
FORMALISM_MARKERS = ("$", "◊", "◇", "matheme", "mathème", "数学型", "公式",
                     "matrix", "matrice", "formalisation", "形式化")

_PREV_CACHE = {}


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s.lower()).strip()


def squash(s):
    """去标点/空白（用于段内命中判定；与 gold 推导同一套规则）。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _APOS.sub("", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", "", _NONWORD.sub("", s)).lower()


# ─────────────────────────────────────────────── 语料层面的计数

def prevalence(term):
    """该术语在词法索引里的**精确命中数**（fr + zh）。

    与 `lacan_search.lexical_search` 用同一套 FTS 语法（含中文 bigram），
    因此「计数」与「检索」看到的是同一件事。
    """
    t = str(term or "").strip()
    if not t:
        return 0
    if t in _PREV_CACHE:
        return _PREV_CACHE[t]
    import lacan_search
    total = 0
    try:
        con = sqlite3.connect(LEX)
        try:
            for lang, table in (("fr", "fr_fts"), ("zh", "zh_fts")):
                # ⚠️ 只取**最紧**的变体：`syntax_variants` 的第二档是 bigram AND，
                #    在 249k 段语料上会让「莫比乌斯」这种词假性命中 270 段
                #    （实测：原文扫描 = 0 段）。计数必须与「是不是真的出现过」一致。
                variants = lacan_search.syntax_variants(t, lang)[:1]
                for fq in variants:
                    try:
                        n = con.execute(
                            "SELECT count(*) FROM %s WHERE %s MATCH ?"
                            % (table, table), (fq,)).fetchone()[0]
                    except sqlite3.OperationalError:
                        n = 0
                    if n:
                        total += n
                        break          # 该语言取第一个有命中的档，避免重复计数
        finally:
            con.close()
    except Exception:
        total = 0
    _PREV_CACHE[t] = total
    return total


def discriminating_terms(terms):
    """把泛用词与主题词分开（§4「禁止只看 passage 数量」的前提）。

    * 有实体/受控映射的形式 → 一律算主题词（知识库认可它）；
    * 其余按语料命中数：命中 ≥ `GENERIC_PREVALENCE` 的视为泛用词（如「拉康」「看待」）。
    返回 (discriminating, generic)。
    """
    disc, generic = [], []
    for t in terms or []:
        t = str(t)
        if len(t) < 2:
            continue
        # 句子级片段不是术语（中文没有词边界，长片段会被整段当成一个词）
        cjk = len(_CJK.findall(t))
        if cjk > 8 or len(t.split()) > 3:
            continue
        try:
            r = _api.resolve_entity(t)["resolution"]
            if r["resolution_status"] in ("RESOLVED", "ENTITY_COLLISION"):
                disc.append(t)
                continue
        except Exception:
            pass
        if prevalence(t) >= GENERIC_PREVALENCE:
            generic.append(t)
        else:
            disc.append(t)
    return disc, generic


# ─────────────────────────────────────────────── 实体与连接

def _entity_forms(eid):
    forms = []
    try:
        import ontology_v4a1 as onto
        e = onto.entity(eid)
        if e:
            forms += [e.get("fr"), e.get("en"), e.get("zh")] + list(e.get("aliases") or [])
        g = onto.gold_concept(eid)
        if g:
            forms += [g.get("fr"), g.get("en"), g.get("zh")] + list(g.get("aliases") or [])
    except Exception:
        pass
    return [f for f in forms if f and len(str(f)) >= 2]


def _core_concept_forms(limit=53):
    """核心拉康概念的形式池（用于「与核心概念共现」信号）。"""
    out = []
    for c in list(_api.KB_.concepts().values()):
        for k in ("fr", "en", "zh"):
            v = c.get(k)
            if v:
                out.append(str(v))
    return out


_CORE_FORMS = None


def core_forms():
    global _CORE_FORMS
    if _CORE_FORMS is None:
        _CORE_FORMS = _core_concept_forms()
    return _CORE_FORMS


def neighbour_persistence(pid, forms):
    """邻域持续性：同 session 的前后各 2 段里是否也出现主题词（结构事实）。"""
    try:
        order = _api.KB_.order()
        pos = _api.KB_.pos().get(pid)
        if pos is None:
            return False
        sess = (_api.KB_.meta().get(pid) or {}).get("session_id")
        for q in range(max(0, pos - 2), min(len(order), pos + 3)):
            if order[q] == pid:
                continue
            m = _api.KB_.meta().get(order[q]) or {}
            if m.get("session_id") != sess:
                continue
            sq = squash(m.get("raw_text") or "")
            if any(squash(f) and squash(f) in sq for f in forms):
                return True
    except Exception:
        return False
    return False


def classify_evidence(e, ctx):
    """→ (topic_support_level, signals)  **可复核的结构判定**。"""
    pid = e.get("passage_id")
    raw = e.get("text") or ""
    sq = squash(raw)
    forms = ctx["topic_forms"]            # 主题词的写法（实体形式 ∪ 问题辨别性术语）
    related = ctx["related_forms"]        # 其它已解析实体的写法
    hits = sum(1 for f in forms if squash(f) and squash(f) in sq)
    topic_hit = hits > 0
    related_hit = any(squash(f) and squash(f) in sq for f in related)
    core_hit = any(squash(f) and squash(f) in sq for f in core_forms())
    entity_linked = bool(e.get("_entity_linked"))    # 由调用方按证据来源标注
    why = set(e.get("why_retrieved") or [])
    signals = {
        "topic_occurrences": hits,
        "topic_hit": topic_hit,
        "related_concept_hit": related_hit,
        "core_concept_cooccurrence": core_hit,
        "entity_linked": entity_linked,
        "terminology_bridge": "terminology_bridge" in why,
        "authority_level": e.get("authority_level"),
    }
    if topic_hit and entity_linked and (hits >= 2 or core_hit
                                        or neighbour_persistence(pid, forms)):
        return "DIRECT", signals
    if topic_hit and entity_linked:
        return "SUBSTANTIAL", signals
    if topic_hit:
        return "SUBSTANTIAL", signals          # 命中主题词但未连实体：仍算参与论证
    if related_hit or entity_linked:
        return "CONTEXTUAL", signals
    return "INCIDENTAL", signals


# ─────────────────────────────────────────────── 结构性不可答

DATE_DAY_RE = re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{2}-\d{2}|"
                         r"\b\d{1,2}\s+(January|February|March|April|May|June|July|"
                         r"August|September|October|November|December)\b", re.I)
DATE_ASK_RE = re.compile(r"确切|准确|具体|几月几?日|哪一?天|哪日|什么时候|date|quand|exact",
                         re.I)


def kb_has_session_dates():
    for _pid, m in list(_api.KB_.meta().items())[:2000]:
        d = m.get("session_date")
        if d and d != "unknown":
            return True
    return False


def structural_unanswerability(question, ctx):
    """→ [(class, message)]；**只报结构上确实做不到的**。"""
    out = []
    q = question or ""
    if DATE_DAY_RE.search(q) and DATE_ASK_RE.search(q) and not kb_has_session_dates():
        out.append(("METADATA_UNAVAILABLE",
                    "问题要求**日级**日期，而 canonical store 所有 passage 的 "
                    "`session_date` 均为 unknown（语料只给 year_from/year_to）。"))
    if ctx["prevalence"] < SPARSE_PREVALENCE and ctx["evidence_n"]:
        out.append(("TOPIC_NOT_COVERED",
                    "主题词在全库只有 %d 段命中（辨别性术语：%s）—— 语料只旁及该主题。"
                    % (ctx["prevalence"], ctx["discriminating"])))
    if any(mk in q.lower() for mk in FORMALISM_MARKERS) and \
            not ctx["formalism_symbol_present"]:
        out.append(("FORMALISM_MISSING",
                    "问题涉及拓扑/数学型表述，但检索到的段落里**没有**出现相应的"
                    "图式/公式符号（语料多为散文转写）。"))
    if ctx["ontology_state"] in ("MISSING_ENTITY",):
        out.append(("ONTOLOGY_GAP",
                    "主题词在知识库里没有 entity（%s）—— 只能靠词面命中。" % ctx["discriminating"]))
    inc = [e for e in ctx["evidence"]
           if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"]
    if inc and not ctx["has_primary"]:
        out.append(("SOURCE_CHAIN_INCOMPLETE",
                    "%d 条证据全部是 recovered 中译（SOURCE_TRACE_INCOMPLETE），"
                    "没有 L1 法文原文可闭合溯源。" % len(inc)))
    return out


# ─────────────────────────────────────────────── 主判定

def evaluate_v2(payload, question=None, plan=None, entity_linked_pids=None):
    """→ 分层判定结果（§12）。保留 v1 的 signals 以便历史兼容。"""
    v1 = es1.evaluate(payload)
    ev = payload.get("evidence") or []
    res = payload.get("resolution") or {}
    question = question or (payload.get("request") or {}).get("query") or ""
    entity_linked_pids = set(entity_linked_pids or [])

    # ── 主题词 / 关联词
    terms = []
    for e in (res.get("candidates") or []):
        terms += _entity_forms(e.get("entity_id"))
    if plan:
        # ⚠️ 必须也取 plan 里解析出的实体：`pack.resolution.candidates` 在
        #    非实体约束的检索路径上可能是空的（实测 rt-G01：plan 解析出了
        #    concept.desir，但 pack 的 resolution 是空的，于是主题词只剩
        #    三个中文句子片段 → 误报 TOPIC_NOT_COVERED）。
        for e in (plan.get("entities") or []):
            for eid in (e.get("entities") or []):
                terms += _entity_forms(eid)
        terms += [str(t) for t in (plan.get("salient_terms") or [])]
    try:
        import query_terms as qt
        terms += qt.salient_terms(question)
    except Exception:
        pass
    terms = list(dict.fromkeys([t for t in terms if t and len(str(t)) >= 2]))
    disc, generic = discriminating_terms(terms)
    topic_forms = list(dict.fromkeys(disc)) or terms[:6]
    related_forms = []
    for e in (res.get("candidates") or []):
        related_forms += _entity_forms(e.get("entity_id"))
    related_forms = [f for f in dict.fromkeys(related_forms) if f not in topic_forms]

    prevalence_best = max([prevalence(t) for t in disc] or [0])

    # ── 实体状态
    cands = res.get("candidates") or []
    try:
        import ontology_v4a1 as onto
        cand_layer = [c for c in cands
                      if (c.get("ontology_layer") or "") == onto.LAYER_ID]
    except Exception:
        cand_layer = []
    if res.get("collisions"):
        ontology_state = "ENTITY_COLLISION"
    elif res.get("ambiguous") and not cands:
        ontology_state = "AMBIGUOUS_ENTITY"
    elif not cands:
        ontology_state = "MISSING_ENTITY"
    elif cand_layer:
        ontology_state = "CANDIDATE_ONLY"
    else:
        ontology_state = "ENTITY_PRESENT"

    # ── 证据级 topic_support_level
    ctx = {"topic_forms": topic_forms, "related_forms": related_forms,
           "evidence": ev, "evidence_n": len(ev), "discriminating": disc,
           "generic": generic, "prevalence": prevalence_best,
           "ontology_state": ontology_state,
           "has_primary": any(e.get("authority_level") == "L1" for e in ev)}
    ctx["formalism_symbol_present"] = any(
        any(sym in (e.get("text") or "") for sym in ("$", "◊", "◇", "nœud", "noeud"))
        for e in ev)
    levels = []
    for e in ev:
        e2 = dict(e)
        e2["_entity_linked"] = e.get("passage_id") in entity_linked_pids
        lvl, sig = classify_evidence(e2, ctx)
        e["topic_support_level"] = lvl
        e["topic_signals"] = sig
        levels.append(lvl)
    from collections import Counter
    lc = Counter(levels)

    # ── availability
    if not ev:
        availability = "NONE"
    elif prevalence_best < SPARSE_PREVALENCE and lc.get("DIRECT", 0) == 0:
        availability = "SPARSE"
    elif len(ev) < 3 and lc.get("DIRECT", 0) == 0:
        availability = "SPARSE"
    else:
        availability = "AVAILABLE"

    # ── topicality
    seminars = {e.get("seminar_id") for e in ev if e.get("seminar_id")}
    periods = {e.get("period") for e in ev if e.get("period")}
    if not ev:
        topicality = "ABSENT"
    elif lc.get("DIRECT", 0) >= DIRECT_MIN and (
            len(seminars) >= MULTI_SEMINAR_MIN or lc.get("DIRECT", 0) >= 2
            or prevalence_best >= GENERIC_PREVALENCE):
        topicality = "DIRECT"
    elif lc.get("DIRECT", 0) + lc.get("SUBSTANTIAL", 0) >= SUBSTANTIAL_MIN \
            or lc.get("DIRECT", 0) >= DIRECT_MIN:
        topicality = "SUBSTANTIAL"
    elif lc.get("SUBSTANTIAL", 0) == 1 or lc.get("CONTEXTUAL", 0) > 0:
        topicality = "CONTEXTUAL"
    elif lc.get("INCIDENTAL", 0) == len(ev):
        topicality = "INCIDENTAL"
    else:
        topicality = "CONTEXTUAL"

    # ── coverage
    need_periods = bool(plan and ({"period_coverage", "diachronic_grouping"}
                                  & set(plan.get("required_capabilities") or [])))
    if not ev:
        coverage = "NONE"
    elif need_periods:
        coverage = ("HIGH" if len(periods) >= 3 else
                    "MEDIUM" if len(periods) == 2 else "LOW")
    else:
        coverage = ("HIGH" if len(seminars) >= 3 else
                    "MEDIUM" if len(seminars) == 2 else "LOW")

    # ── source
    if not ev:
        source = "NO_EVIDENCE"
    else:
        has_p = ctx["has_primary"]
        rec_only = all(e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE" for e in ev)
        if rec_only:
            source = "RECOVERED_ONLY"
        elif has_p and topicality in ("DIRECT", "SUBSTANTIAL"):
            source = "PRIMARY_PRESENT"
        elif has_p:
            source = "PRIMARY_PRESENT_BUT_NON_TOPICAL"
        else:
            source = "SECONDARY_ONLY"

    structural = structural_unanswerability(question, ctx)

    # ── absence profile（§10）：把「没有找到什么」当作证据
    absence = {
        "topic_prevalence": prevalence_best,
        "discriminating_terms": disc[:6],
        "generic_terms_dropped": generic[:6],
        "no_entity": ontology_state in ("MISSING_ENTITY",),
        "no_relation_evidence": not _has_relation_evidence(cands),
        "no_primary_discussion": not (ctx["has_primary"]
                                      and topicality in ("DIRECT", "SUBSTANTIAL")),
        "levels": dict(lc),
        "method": "词法精确计数 + 实体连接 + 段内/邻域结构事实（无模型打分）",
    }

    # ── final（directness > raw count；§14）
    conflicting = v1.get("state") == "CONFLICTING_EVIDENCE" and not res.get("ontology_repairs")
    if structural and any(c in ("METADATA_UNAVAILABLE", "TOPIC_NOT_COVERED",
                                "FORMALISM_MISSING") for c, _ in structural):
        final = "INSUFFICIENT_EVIDENCE"
    elif conflicting:
        final = "CONFLICTING_EVIDENCE"
    elif topicality in ("DIRECT", "SUBSTANTIAL") and source != "NO_EVIDENCE":
        # direct + sparse 也允许 SUPPORTED（1–2 条 DIRECT 且为 L1）
        final = "SUPPORTED" if (topicality == "DIRECT"
                                or (source == "PRIMARY_PRESENT"
                                    and topicality == "SUBSTANTIAL")) \
            else "PARTIALLY_SUPPORTED"
    elif topicality == "CONTEXTUAL" and availability == "AVAILABLE":
        final = "PARTIALLY_SUPPORTED"
    else:
        final = "INSUFFICIENT_EVIDENCE"

    reasons = []
    if structural:
        reasons += ["[%s] %s" % (c, m) for c, m in structural]
    if lc.get("INCIDENTAL"):
        reasons.append("本次证据中 %d/%d 条属于 INCIDENTAL（只提到名词/人名/技术词，"
                       "不构成对该主题的论述）。" % (lc["INCIDENTAL"], len(ev)))
    if absence["no_entity"]:
        reasons.append("主题词在知识库里没有 entity（absence profile 的一部分）。")
    reasons += list(v1.get("reasons") or [])[:4]

    out = dict(v1)
    out.update({
        "engine": ENGINE,
        "availability_state": availability,
        "topicality_state": topicality,
        "coverage_state": coverage,
        "source_state": source,
        "ontology_state": ontology_state,
        "final_state": final,
        "state": final,
        "topic_support_levels": dict(lc),
        "topic_prevalence": prevalence_best,
        "discriminating_terms": disc[:6],
        "absence_profile": absence,
        "structural_unanswerability": [{"class": c, "message": m}
                                       for c, m in structural],
        "reasons": reasons or list(v1.get("reasons") or []),
        "precedence_note": ("§14：directness > raw count —— 1–2 条 DIRECT（尤其 L1）"
                            "可以 SUPPORTED，10 条 INCIDENTAL 不可以。"),
        "thresholds": {"GENERIC_PREVALENCE": GENERIC_PREVALENCE,
                       "SPARSE_PREVALENCE": SPARSE_PREVALENCE,
                       "DIRECT_MIN": DIRECT_MIN, "SUBSTANTIAL_MIN": SUBSTANTIAL_MIN,
                       "MULTI_SEMINAR_MIN": MULTI_SEMINAR_MIN},
    })
    # v1 的 signals 保留（历史兼容），并补上新信号
    out["signals"] = {**(v1.get("signals") or {}),
                      "topic_prevalence": prevalence_best,
                      "topic_levels": dict(lc),
                      "availability_state": availability,
                      "topicality_state": topicality,
                      "coverage_state": coverage,
                      "source_state": source,
                      "ontology_state": ontology_state,
                      "discriminating_term_n": len(disc)}
    return out


def _has_relation_evidence(cands):
    """已解析实体在 ontology.v4a1 里有没有带证据的 typed 关系（structural fact）。"""
    if not cands:
        return False
    try:
        import ontology_v4a1 as onto
        ids = {c.get("entity_id") for c in cands}
        for r in onto.load().get("relations") or []:
            if r["subject"] in ids or r["object"] in ids:
                if (r.get("evidence") or {}).get("passage_id"):
                    return True
    except Exception:
        return False
    return False


if __name__ == "__main__":
    print(json.dumps({"engine": ENGINE,
                      "thresholds": {"GENERIC_PREVALENCE": GENERIC_PREVALENCE,
                                     "SPARSE_PREVALENCE": SPARSE_PREVALENCE},
                      "levels": TOPIC_LEVELS,
                      "structural": STRUCTURAL_CLASSES}, ensure_ascii=False, indent=1))
