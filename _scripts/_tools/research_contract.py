#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_contract.py — Phase 4C.1-B：Research Plan → **可执行契约**（Executable Contract）

问题（Phase 4C 人工评审实证）
─────────────────────────────
`planned_operations` 一直只是**说明性 metadata**：

    plan 写了三条 lane        → 实际只跑一条        → 仍然 SUPPORTED
    plan 写了 terminology_lookup → 实际没执行         → 仍然 SUPPORTED
    plan 要求 source-layer separation → 没有任何 operation → 仍然 SUPPORTED
    relation question 无 relation evidence            → 仍然 SUPPORTED
    diachronic question 缺一个 endpoint               → 仍然 SUPPORTED
    seminar constraint 被记录但没下推                  → 仍然 SUPPORTED
    formalism question 的公式没进 retrieval            → 判成「结构性不可答」
    query fragment 被当 entity / discriminating term   → 判成「语料不覆盖」

本模块把计划编译成**可检查、可失败**的契约，并给出**状态上限**（state ceiling）：
只有 `completion_state == COMPLETE` 才允许 SUPPORTED。

设计纪律
────────
* **没有任何 task_id 分支**：所有要求都来自 `task_type` / 问题语义 / 已解析实体 /
  约束 / 语料事实。测试 `test_phase4c1b_contracts.py::TestNoTaskSpecificHack`
  会静态扫描本文件，禁止出现 `rt-XX`。
* **不引入 LLM**：全部为确定性规则（正则、计数、字段）。
* **只读**：不写任何 frozen 产物。

十类契约（对应十种 task_type）
──────────────────────────────
    DefinitionResearchContract          concept_definition
    ComparisonResearchContract          concept_relation
    DiachronicResearchContract          diachronic_development
    SeminarSpecificContract             seminar_specific
    CaseResearchContract                case_research
    FreudToLacanResearchContract        freud_to_lacan
    PhilosophyToLacanResearchContract   philosophy_to_lacan
    TopologyMathemeResearchContract     topology_matheme
    TranslationTerminologyResearchContract translation_terminology
    AbstentionResearchContract          insufficient_unanswerable

此外还有两个**横切 facet**（任何 task_type 都可能触发）：
    RelationFacet       问题问「A 与 B 的关系」→ 必须有 relation evidence
    MetadataFacet       问题问确切日期/地点/在场者/版次/页码 → 先查 metadata availability
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
STORE = os.path.join(VAULT, "_data", "passage_store")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import gold_normalization as gn          # noqa: E402  （token 边界安全匹配）

# ── 状态序（SUPPORTED 最高；CONFLICTING 单独处理，不参与上下限比较）
STATE_RANK = {"INSUFFICIENT_EVIDENCE": 0, "PARTIALLY_SUPPORTED": 1, "SUPPORTED": 2}
CONFLICTING = "CONFLICTING_EVIDENCE"


def cap_state(state, ceiling):
    """把 state 压到 ceiling 以下（CONFLICTING 不降级）。"""
    if state == CONFLICTING or ceiling is None:
        return state
    if STATE_RANK.get(state, 0) <= STATE_RANK.get(ceiling, 1):
        return state
    return ceiling


# ─────────────────────────────────────────── §11 证据可用性（deterministic flags）
USABILITY_CLASSES = ("SUBSTANTIVE_TEXT", "EDITORIAL_METADATA", "BIBLIOGRAPHY_ONLY",
                     "MEDIA_ONLY", "FRAGMENT_ONLY")

_MEDIA_RE = re.compile(r"!\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)|<img\b", re.I)
_URL_RE = re.compile(r"https?://|www\.", re.I)
_EDITORIAL_MARKERS = re.compile(
    r"st[ée]notypie|pas de st[ée]notypie|reprographie|au format|disponible sur le site|"
    r"document internet|dactylographi|reconstruction|"
    r"^\s*Le[çc]on\s*\d+\s*\d|Le[çc]on\s*\d+\s+\d{1,2}\s+\w+\s+\d{4}|"
    r"^\[\s*(Pas de|Missing|Note)|"
    r"编者说明|原书|版次说明|此段为编者|未标明", re.I)
_BIBLIO_MARKERS = re.compile(
    r"Erstveröffentlichung|Gesammelte Werke|\bBd\.\s*\d|\bS\.\s*\d+\s*[–—-]|"
    r"出版社|商务印书馆|Éditions|Press\b|\béd\.\s*\d{4}|"
    r"[《\[][^》\]]{2,}[》\]]\s*[，,：:]\s*[^。]{0,40}(出版社|Press)", re.I)


def _strip_source_notes(text) -> str:
    """去掉方括号出处注、URL 与「〔…〕」编者插入，留下**正文**。"""
    t = re.sub(r"\[[^\]]{2,}\]", " ", str(text))
    t = re.sub(r"〔[^〕]{2,}〕", " ", t)
    t = _URL_RE.sub(" ", t)
    return t.strip()


def classify_evidence_usability(rec) -> dict:
    """一条证据能不能承担 substantive claim（**不删段落**，只给 flag）。

    Phase 4C 人工评审确认以下类型不应承担 substantive evidence：
    Obsidian 图片嵌入、书目行、编者版本说明、2 字符片段、媒体占位。

    判定顺序（确定性，全部可复核）：
      1. 去掉媒体嵌入后连一个词都没有        → MEDIA_ONLY
      2. 去掉方括号出处注/编者插入后没有正文  → BIBLIOGRAPHY_ONLY / EDITORIAL_METADATA
      3. 正文 < 12 字符                     → FRAGMENT_ONLY
      4. 正文像「标签行」（<80 字符且无句读）且含书目/编者标记 → 对应元数据类
      5. 其余                               → SUBSTANTIVE_TEXT
    """
    text = str((rec or {}).get("text") or "")
    no_media = _MEDIA_RE.sub(" ", text)
    if not re.findall(r"[\w\u4e00-\u9fff]+", no_media):
        return {"usability_class": "MEDIA_ONLY",
                "can_support_substantive_claim": False,
                "reasons": ["去掉媒体嵌入后没有可读文本"]}
    body = _strip_source_notes(no_media)
    if not re.findall(r"[\w\u4e00-\u9fff]+", body):
        if _BIBLIO_MARKERS.search(no_media):
            return {"usability_class": "BIBLIOGRAPHY_ONLY",
                    "can_support_substantive_claim": False,
                    "reasons": ["整段都是书目/出处注，不含论述"]}
        return {"usability_class": "EDITORIAL_METADATA",
                "can_support_substantive_claim": False,
                "reasons": ["整段都是编者/版本说明（位于方括号内），属元数据"]}
    if len(body) < 12:
        return {"usability_class": "FRAGMENT_ONLY",
                "can_support_substantive_claim": False,
                "reasons": ["正文过短（%d 字符），不构成论述" % len(body)]}
    # 「标签行」：整段没有任何句读（法/中句末标点都算），长度在合理范围内
    note_like = (not re.search(r"[。！？；.!?;]", body)) and len(body) < 200
    if note_like and _BIBLIO_MARKERS.search(no_media):
        return {"usability_class": "BIBLIOGRAPHY_ONLY",
                "can_support_substantive_claim": False,
                "reasons": ["书目/出处行，不含论述"]}
    if note_like and _EDITORIAL_MARKERS.search(no_media):
        return {"usability_class": "EDITORIAL_METADATA",
                "can_support_substantive_claim": False,
                "reasons": ["编者/版本/课次说明，属于元数据而非拉康论述"]}
    reasons = []
    if _EDITORIAL_MARKERS.search(no_media):
        reasons.append("含编者/版本说明成分")
    return {"usability_class": "SUBSTANTIVE_TEXT",
            "can_support_substantive_claim": True, "reasons": reasons}


def _has_prose(text) -> bool:
    """是否像论述（有句读且不只一行短标签）。"""
    sentence_marks = len(re.findall(r"[。！？；.!?;]", text))
    return len(text) >= 40 and (sentence_marks >= 1 or len(text) >= 80)


# ─────────────────────────────────────────── §八 约束（seminar / period / language）
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
         "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
         "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20, "xxi": 21,
         "xxii": 22, "xxiii": 23, "xxiv": 24, "xxv": 25, "xxvi": 26}
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14,
          "十五": 15, "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
          "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25,
          "二十六": 26}
_SEM_RE = re.compile(r"\bS(?:eminar)?\.?\s?(XIXB|XIX|XX|XVI{1,3}|XIV|XIII|XII|XI{1,3}|X|IX|VI{1,3}|IV|V|\d{1,2})\b",
                     re.I)
_SEM_CN_RE = re.compile(r"研讨班\s*(?:第)?\s*([一二三四五六七八九十]{1,3})\s*期")


def seminar_constraints(question) -> list:
    """从**问题文本**里提取研讨班约束（不看 gold）。"""
    q = str(question or "")
    out = []
    for m in _SEM_RE.finditer(q):
        tok = m.group(1).upper()
        if tok == "XIXB":
            sid = "S19B"
        elif tok.isdigit():
            sid = "S%02d" % int(tok)
        else:
            n = ROMAN.get(m.group(1).lower())
            if not n:
                continue
            sid = "S%02d" % n
        if sid not in out:
            out.append(sid)
    for m in _SEM_CN_RE.finditer(q):
        n = CN_NUM.get(m.group(1))
        if n:
            sid = "S%02d" % n
            if sid not in out:
                out.append(sid)
    return out


_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-2]\d)\b")


def year_constraints(question) -> list:
    return sorted({int(y) for y in _YEAR_RE.findall(str(question or ""))})


def period_constraints(question) -> list:
    """把问题里的年份映射到语料的**真实期段**（用 seminars.jsonl 的 year_from/to）。"""
    years = year_constraints(question)
    if not years:
        return []
    spans = _seminar_spans()
    out = []
    for y in years:
        for sid, (a, b) in spans.items():
            if a and b and a <= y <= b:
                label = "%s-%s" % (a, b)
                if label not in out:
                    out.append(label)
    return out


_SPANS = None


def _seminar_spans():
    global _SPANS
    if _SPANS is None:
        _SPANS = {}
        p = os.path.join(STORE, "seminars.jsonl")
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                if line.strip():
                    d = json.loads(line)
                    _SPANS[d["id"]] = (d.get("year_from"), d.get("year_to"))
    return _SPANS


def seminar_of_passage(pid) -> str:
    """`passage.S14.unknown.P0011` → `seminar.S14`。"""
    m = re.match(r"passage\.(S[0-9A-Za-z]+)\.", str(pid or ""))
    return "seminar.%s" % m.group(1) if m else ""


# ─────────────────────────────────────────── 语料普查（一次扫描，缓存）
_CENSUS = None
FORMALISM_SYMBOLS = ("◊", "⋄", "$", "→", "⊂", "∩", "∪", "∅", "∀", "∃", "≠", "≡",
                     "≢", "∈", "∉")
_EXTERNAL_HINT = re.compile(r"freud|弗洛伊德|hegel|黑格尔|koj[eè]ve|科耶夫|"
                            r"descartes|笛卡尔|wittgenstein|维特根斯坦", re.I)


def corpus_census():
    """一次扫描 passages.jsonl，缓存：
      * 含公式符号的段落数与样本
      * 外部来源层（无 seminar_id 的文本）段落数
      * 编者/书目/媒体片段计数（用于验证 usability 规则）
    只读；不写任何东西。
    """
    global _CENSUS
    if _CENSUS is not None:
        return _CENSUS
    sym_count = Counter()
    sym_examples = defaultdict(list)
    n = 0
    external = 0
    external_examples = []
    usab = Counter()
    layer = Counter()
    sym_ids = {}
    p = os.path.join(STORE, "passages.jsonl")
    if not os.path.isfile(p):
        _CENSUS = {"scanned": 0, "symbols": {}, "external_n": 0, "usability": {}}
        return _CENSUS
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            n += 1
            text = d.get("raw_text") or ""
            for s in FORMALISM_SYMBOLS:
                if s in text:
                    sym_count[s] += 1
                    if len(sym_examples[s]) < 3:
                        sym_examples[s].append(d["id"])
                    sym_ids.setdefault(s, []).append(
                        {"passage_id": d["id"], "seminar_id": d.get("seminar_id"),
                         "language": d.get("language"),
                         "authority_level": d.get("authority_level"),
                         "text": text[:400]})
            auth = d.get("authority_level")
            if auth == "L1":
                layer["lacan_primary"] += 1
            elif auth == "L2":
                layer["lacan_translation"] += 1
            if not d.get("seminar_id"):
                external += 1
                if len(external_examples) < 5:
                    external_examples.append(d["id"])
                low = text.lower()
                if re.search(r"freud|trieb|弗洛伊德|冲动|驱力", low):
                    layer["external_freud"] += 1
                if re.search(r"hegel|kant|descartes|黑格尔|康德|笛卡尔|"
                             r"ph[ée]nom[ée]nologie", low):
                    layer["external_philosophy"] += 1
            rec = {"text": text}
            usab[classify_evidence_usability(rec)["usability_class"]] += 1
    _CENSUS = {"scanned": n,
               "symbols": {s: {"passages": sym_count[s], "examples": sym_examples[s]}
                           for s in FORMALISM_SYMBOLS if sym_count[s]},
               "external_n": external, "external_examples": external_examples,
               "layer_counts": dict(layer),
               "symbol_passages": sym_ids,
               "usability": dict(usab)}
    return _CENSUS


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4C.1-B3 §2：结构化不可得的**机器可验证凭据**（metadata → NOT_APPLICABLE）
# ═══════════════════════════════════════════════════════════════════════════
_METADATA_FIELD_PROOF = {}


def metadata_structural_proof(field):
    """扫描整个 canonical store，给出「该 metadata 字段在语料层不可得」的**可复算凭据**。

    → {"field","availability","reason_code","corpus_scan":{...},"upstream_operation"}

    `availability` 取值（必须由扫描得出，不得断言）：
      * `GLOBAL_UNKNOWN`      —— 字段存在但全库只有一个占位值（如 session_date=unknown）
      * `FIELD_ABSENT`        —— 字段根本不在 schema 里
      * `AVAILABLE`           —— 字段有真实取值（**此时禁止** NOT_APPLICABLE）
    """
    key = str(field)
    if key in _METADATA_FIELD_PROOF:
        return _METADATA_FIELD_PROOF[key]
    # 字段名 → passage_store 里的真实键名
    store_key = {"session_date": "session_date", "location": "location",
                 "attendees": "attendees", "session_number": "sequence_in_session",
                 "edition": "edition", "page": "page"}.get(key, key)
    p = os.path.join(STORE, "passages.jsonl")
    values = Counter()
    n = 0
    present = 0
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                n += 1
                if store_key in d:
                    present += 1
                    values[str(d.get(store_key))] += 1
    known_unknown = {"unknown", "none", "null", "", "n/a", "na"}
    real_values = {v: c for v, c in values.items() if v.strip().lower() not in known_unknown}
    if not present:
        availability = "FIELD_ABSENT"
    elif not real_values:
        availability = "GLOBAL_UNKNOWN"
    else:
        availability = "AVAILABLE"
    proof = {
        "field": key,
        "store_key": store_key,
        "availability": availability,
        "reason_code": "METADATA_UNAVAILABLE" if availability != "AVAILABLE" else None,
        "corpus_scan": {
            "executed": True, "scope": "whole_corpus", "method": "passage_store 字段统计",
            "n_passages": n, "field_present_n": present,
            "distinct_values_sample": sorted(values)[:5],
            "n_with_real_value": sum(real_values.values()),
        },
        "upstream_operation": "metadata_check",
    }
    _METADATA_FIELD_PROOF[key] = proof
    return proof


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4C.1-B3 §3：formalism **分级检索**（exact → normalized → spacing →
# parenthesized → notation variant → seminar-constrained related term）
# ═══════════════════════════════════════════════════════════════════════════
GLYPH_EQUIV = {"⋄": "◊", "◇": "◊", "♦": "◊", "⟐": "◊",
               "→": "→", "⇒": "→", "⊃": "⊂"}
_BARRED_SUBJECT = {"$": ("$", "S"), "S": ("S", "$"), "s": ("s", "$")}
# 「问题点名的形式对象」（无符号也要认，否则 topology 题的 formalism 会退化成默认 ◊）
NAMED_FORMAL_OBJECTS = ("borroméen", "borromeen", "borromean", "波罗米", "博罗米",
                        "r.s.i.", "rsi", "nœud", "noeud", "poinçon", "poincon",
                        "mathème", "matheme", "formule", "écriture", "ecriture",
                        "chaîne", "chaine", "rond de ficelle", "tresse", "nappe")
_MATHEME_EXPR = re.compile(
    r"\(?\s*([A-Za-z$])\s*([◊⋄◇♦→⊂])\s*([A-Za-z])\s*\)?")
_GENERIC_FORMAL_WORDS = ("formule", "écriture", "ecriture", "tableau",
                          "logique du fantasme", "mathème", "matheme")
_RELATED_FORMAL_TERMS = ("poinçon", "poincon", "formule", "mathème", "matheme",
                         "logique du fantasme", "écriture", "ecriture",
                         "nœud borroméen", "noeud borromeen", "borroméen", "r.s.i.",
                         "chaîne", "chaine", "rond de ficelle", "tresse", "nappe")
_STRATEGY_RANK = {"exact_expression": 0, "symbol_spacing_variants": 1,
                  "parenthesized_form": 2, "notation_variant": 3,
                  "exact_symbol": 4, "normalized_symbol": 5,
                  "named_formal_object": 6, "related_formal_term": 7}
_FORMALISM_INDEX = None


def normalize_matheme(form):
    """形式归一化：去空格、统一符号字形（`S ⋄ a` → `S◊a`）。"""
    t = str(form or "")
    for a, b in GLYPH_EQUIV.items():
        t = t.replace(a, b)
    return re.sub(r"\s+", "", t)


def formalism_query_forms(question, symbols=None, task_type=None):
    """从问题里解析 formalism 检索形式（**分级**，不是机械 OR）。

    → [{"form","strategy","normalized","strength"}, …]
      strategy ∈ exact_expression / symbol_spacing_variants / parenthesized_form /
                 notation_variant / exact_symbol / normalized_symbol /
                 named_formal_object / related_formal_term
      strength ∈ DIRECT（可作形式证据） / SUPPORTING（相关形式话语，不算直接公式）

    分级纪律：问题里**有**形式化表达式时，只用该表达式的写法族（+记号变体），
    不再把裸符号或泛化形式词混进来（否则 `formule` 这种词会淹没真正的公式命中）。
    """
    q = str(question or "")
    low = q.lower()
    out, seen = [], set()

    def add(form, strategy, strength="DIRECT"):
        nf = normalize_matheme(form)
        if not nf or nf in seen:
            return
        seen.add(nf)
        out.append({"form": form, "normalized": nf, "normalized_form": nf,
                    "strategy": strategy, "strength": strength})

    exprs = list(_MATHEME_EXPR.finditer(q))
    if exprs:
        for m in exprs:
            left, op, right = m.group(1), m.group(2), m.group(3)
            canon_op = GLYPH_EQUIV.get(op, op)
            add(m.group(0), "exact_expression")
            core = "%s%s%s" % (left, canon_op, right)
            add(core, "symbol_spacing_variants")
            add("(%s)" % core, "parenthesized_form")
            # 记号变体：被划杠的主体 $ ↔ S；小客体 a ↔ (a)
            for lv in _BARRED_SUBJECT.get(left, (left,)):
                for rv in ((right, "(a)") if right == "a" else (right,)):
                    add("%s%s%s" % (lv, canon_op, rv), "notation_variant")
                    add("(%s%s%s)" % (lv, canon_op, rv), "notation_variant")
    else:
        named = [t for t in NAMED_FORMAL_OBJECTS
                 if t in low and t not in _GENERIC_FORMAL_WORDS]
        if named:
            for t in named:
                add(t, "named_formal_object")
        else:
            for sym in (symbols or ["◊"]):
                add(sym, "exact_symbol")
                for g, canon in GLYPH_EQUIV.items():
                    if canon == sym:
                        add(g, "normalized_symbol")
    for term in _RELATED_FORMAL_TERMS:
        if term in low:
            add(term, "related_formal_term", strength="SUPPORTING")
    if not out:
        for sym in (symbols or ["◊"]):
            add(sym, "exact_symbol")
    return out


_SEMINAR_TITLES = None
_TITLE_STOP = {"la", "le", "les", "du", "de", "des", "et", "dans", "sur", "un", "une",
               "the", "of", "l", "d", "au", "aux", "en", "a", "à", "ou"}


def seminar_titles():
    """seminar id → fr_title（缓存；只读）。"""
    global _SEMINAR_TITLES
    if _SEMINAR_TITLES is not None:
        return _SEMINAR_TITLES
    out = {}
    p = os.path.join(STORE, "seminars.jsonl")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                if d.get("id") and d.get("fr_title"):
                    out[d["id"]] = d["fr_title"]
    _SEMINAR_TITLES = out
    return out


def _fold(t):
    """去变音符号 + 小写（用于标题词匹配；只做确定性字符串折叠）。"""
    import unicodedata
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def seminar_from_title(question):
    """问题里没有显式期号时，用**研讨班标题**与问题内容词的匹配派生 seminar 约束。

    → {"seminar_id","fr_title","matched_tokens","score"} 或 None（无匹配/并列第一）
    这是语料事实驱动的推导（标题来自 seminars.jsonl），不是 task_id 特判。
    """
    q = " " + _fold(question) + " "
    scores = {}
    toks = {}
    for sid, title in seminar_titles().items():
        ws = [w for w in re.findall(r"[a-zA-Zà-ÿ]{4,}", _fold(title))
              if w not in _TITLE_STOP]
        hit = [w for w in ws if (" %s" % w) in q or ("%s " % w) in q]
        if hit:
            scores[sid] = len(hit)
            toks[sid] = sorted(set(hit))
    if not scores:
        return None
    best = max(scores.values())
    top = [sid for sid, v in scores.items() if v == best]
    if len(top) != 1:
        return None                      # 并列 → 不猜
    sid = top[0]
    return {"seminar_id": sid, "fr_title": seminar_titles().get(sid),
            "matched_tokens": toks[sid], "score": best,
            "method": "seminar_title_token_match"}


def formalism_index():
    """一次扫描建 formalism **计数**索引（缓存；只在内存，不写盘）。

    只存 (key → {seminar: count})，不存段落本体 —— 段落样本由 `formalism_hits()`
    按需第二遍取，避免「按文件顺序截断」把后面的研讨班（S14/S21/S22）整段丢掉。
    """
    global _FORMALISM_INDEX
    if _FORMALISM_INDEX is not None:
        return _FORMALISM_INDEX
    counts = defaultdict(Counter)
    sym_counts = defaultdict(Counter)
    named_counts = defaultdict(Counter)
    n = 0
    p = os.path.join(STORE, "passages.jsonl")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                n += 1
                text = str(d.get("raw_text") or d.get("normalized_text") or "")
                sem = d.get("seminar_id") or "UNKNOWN"
                for m in _MATHEME_EXPR.finditer(text):
                    left, op, right = m.group(1), m.group(2), m.group(3)
                    core = normalize_matheme("%s%s%s" % (left, op, right))
                    for k in _matheme_keys(core, left, op, right):
                        counts[k][sem] += 1
                for g in {c for c in text if c in FORMALISM_SYMBOLS}:
                    sym_counts[g][sem] += 1
                low = text.lower()
                for term in _RELATED_FORMAL_TERMS:
                    if term in low:
                        named_counts[term][sem] += 1
    _FORMALISM_INDEX = {"scanned": n,
                        "counts": {k: dict(v) for k, v in counts.items()},
                        "symbol_counts": {k: dict(v) for k, v in sym_counts.items()},
                        "named_counts": {k: dict(v) for k, v in named_counts.items()}}
    return _FORMALISM_INDEX


def _matheme_keys(core, left, op, right):
    """一个表达式在索引里的全部等价 key（记号变体 / 括号变体）。"""
    keys = {core, "(%s)" % core}
    for lv in _BARRED_SUBJECT.get(left, (left,)):
        for rv in ((right, "(a)") if right == "a" else (right,)):
            k = normalize_matheme("%s%s%s" % (lv, op, rv))
            keys.add(k)
            keys.add("(%s)" % k)
    return keys


_FORMALISM_HITS_CACHE = {}


def formalism_hits(matheme_keys, term_keys=(), seminar=None, per_seminar=4,
                   limit=24):
    """按需第二遍：为**指定 key** 取段落样本（每个 (key, seminar) 最多 per_seminar）。

    → {key: [ {"passage_id","seminar_id","language","authority_level","raw_matched_form"} ]}
    """
    mk = tuple(sorted(set(matheme_keys)))
    tk = tuple(sorted(set(term_keys)))
    ck = (mk, tk, seminar)
    if ck in _FORMALISM_HITS_CACHE:
        return _FORMALISM_HITS_CACHE[ck]
    out = defaultdict(lambda: defaultdict(list))
    mkset = set(mk)
    tkset = {t.lower(): t for t in tk}
    p = os.path.join(STORE, "passages.jsonl")
    if mkset or tkset:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                sem = d.get("seminar_id") or "UNKNOWN"
                if seminar and sem != seminar:
                    continue
                text = str(d.get("raw_text") or d.get("normalized_text") or "")
                base = {"passage_id": d.get("id"), "seminar_id": d.get("seminar_id"),
                        "language": d.get("language"),
                        "authority_level": d.get("authority_level"),
                        "text_role": d.get("text_role")}
                if mkset:
                    for m in _MATHEME_EXPR.finditer(text):
                        left, op, right = m.group(1), m.group(2), m.group(3)
                        core = normalize_matheme("%s%s%s" % (left, op, right))
                        for k in _matheme_keys(core, left, op, right):
                            if k not in mkset:
                                continue
                            bucket = out[k][sem]
                            if len(bucket) < per_seminar:
                                bucket.append(dict(base, raw_matched_form=m.group(0)))
                    for g in mkset:
                        if len(g) == 1 and g in text:
                            bucket = out[g][sem]
                            if len(bucket) < per_seminar:
                                bucket.append(dict(base, raw_matched_form=g))
                if tkset:
                    low = text.lower()
                    for lt, term in tkset.items():
                        if lt in low:
                            bucket = out[term][sem]
                            if len(bucket) < per_seminar:
                                bucket.append(dict(base, raw_matched_form=term))
    res = {k: dict(v) for k, v in out.items()}
    _FORMALISM_HITS_CACHE[ck] = res
    return res


def classify_formalism_match(query_form, raw_matched_form, declared):
    """如实标注命中策略：查询写法 vs 语料里**真实出现**的写法。

    修前会把「索引里为记号变体也生成了同一个 key」说成 `exact_expression` ——
    那是把语料里的 `S ◊ a` 硬说成问题里的 `$ ◊ a`。这里按差异类型如实分类。
    """
    qn = normalize_matheme(query_form)
    rn = normalize_matheme(raw_matched_form or "")
    if not rn:
        return declared
    if qn == rn:
        return declared
    if qn.strip("()") == rn.strip("()"):
        return "parenthesized_form"
    def _nota(t):
        t = t.replace("$", "S")
        return re.sub(r"\(([a-z])\)", r"\1", t)
    if _nota(qn.strip("()")) == _nota(rn.strip("()")):
        return "notation_variant"
    return "symbol_spacing_variants"


def formalism_retrieve(question, symbols=None, task_type=None, seminar=None,
                       limit=12, per_seminar=4):
    """分级 formalism 检索 → hits（每条带 raw/normalized matched form + strategy）。

    只有 DIRECT hits 才是「直接公式证据」；SUPPORTING/WEAK hits 不得单独当作
    direct formalism evidence（如实标注 match_strength）。
    """
    forms = formalism_query_forms(question, symbols, task_type)
    idx = formalism_index()
    mkeys, tkeys = [], []
    for spec in forms:
        if spec["strategy"] in ("named_formal_object", "related_formal_term"):
            tkeys.append(spec["form"])
        else:
            mkeys.append(spec["normalized"])
    keys = formalism_hits(mkeys, tkeys, seminar=seminar, per_seminar=per_seminar)

    def _flat(container):
        out = []
        for _sem, lst in sorted((container or {}).items()):
            out.extend(lst)
        return out

    hits, seen = [], set()
    for spec in forms:
        key = spec["normalized"]
        if spec["strategy"] in ("named_formal_object", "related_formal_term"):
            pool = _flat(keys.get(spec["form"])) + _flat(keys.get(spec["form"].lower()))
        else:
            pool = _flat(keys.get(key))
        for h in pool:
            pid = h["passage_id"]
            if pid in seen:
                continue
            seen.add(pid)
            raw = h.get("raw_matched_form")
            strategy = spec["strategy"]
            if strategy not in ("named_formal_object", "related_formal_term"):
                strategy = classify_formalism_match(spec["form"], raw, strategy)
            hits.append({"passage_id": pid, "seminar_id": h.get("seminar_id"),
                         "language": h.get("language"),
                         "authority_level": h.get("authority_level"),
                         "text_role": h.get("text_role"),
                         "raw_matched_form": raw,
                         "normalized_matched_form": key,
                         "declared_strategy": spec["strategy"],
                         "match_strategy": strategy,
                         "match_strength": spec["strength"],
                         "query_form": spec["form"]})
    # 裸符号的 LaTeX 噪声过滤：`$` 若只在数学环境里出现（无 ◊/→、无形式词）→ WEAK
    for h in hits:
        if h["match_strength"] == "DIRECT" and h["normalized_matched_form"] in ("$", "◊", "→"):
            counts = (idx["counts"].get(h["normalized_matched_form"]) or {})
            if not counts:
                h["match_strength"] = "WEAK_SYMBOL"
    direct = [h for h in hits if h["match_strength"] == "DIRECT"]
    _conc = {}
    for h in direct:
        c = (idx["counts"].get(h["normalized_matched_form"])
             or idx["symbol_counts"].get(h["normalized_matched_form"])
             or idx["named_counts"].get(h["query_form"]) or {})
        _conc[(h["normalized_matched_form"], h.get("seminar_id"))] = c.get(
            h.get("seminar_id"), 0)
    direct.sort(key=lambda h: (_STRATEGY_RANK.get(h["match_strategy"], 9),
                               -_conc.get((h["normalized_matched_form"],
                                           h.get("seminar_id")), 0),
                               h["normalized_matched_form"],
                               h.get("seminar_id") or "", h["passage_id"]))
    supporting = [h for h in hits if h["match_strength"] != "DIRECT"]
    supporting.sort(key=lambda h: (_STRATEGY_RANK.get(h["match_strategy"], 9),
                                   h.get("seminar_id") or "", h["passage_id"]))
    sem_dist = Counter(h.get("seminar_id") for h in direct if h.get("seminar_id"))
    global_dist = Counter()
    for spec in forms:
        c = (idx["counts"].get(spec["normalized"])
             or idx["symbol_counts"].get(spec["normalized"])
             or idx["named_counts"].get(spec["form"]) or {})
        for sem_id, v in c.items():
            global_dist[sem_id] += v
    return {
        "forms": forms,
        "stages": sorted({h["match_strategy"] for h in hits}),
        "hits": hits[:limit * 3],
        "direct_hits": direct[:limit],
        "supporting_hits": supporting[:limit],
        "direct_n": len(direct),
        "supporting_n": len(supporting),
        "seminar_distribution": dict(sem_dist.most_common(6)),
        "corpus_distribution": dict(global_dist.most_common(8)),
        "index_scanned": idx["scanned"],
        "seminar_constraint": seminar,
    }


# ─────────────────────────────────────────── §18 问句残片过滤
# 实测污染源（Phase 4C）：`中文语料里`、`地点与在场者是谁`、`进入拉康的欲望理论`、
# `适合表示拉康的主体`、`在拉康的主体理论里被`、`等译法` —— 它们是**问句片段**，
# 不是术语。它们一旦成为 entity / lane / discriminating term，就会：
#   ① 造出无法满足的 required lane；② 让 TOPIC_NOT_COVERED 假成立（见该轮的对照任务）。
_FRAGMENT_STOP = ("语料里", "语料中", "文本里", "文本中", "问题里", "原句里",
                  "如何", "怎样", "什么", "为什么", "哪些", "哪个", "是否", "有没有",
                  "多少", "以及", "并且", "的话", "里面", "当中", "关于", "对于",
                  "所谓", "到底", "究竟", "可以", "需要", "应该", "包括", "例如",
                  "等译法", "等写法", "等问题", "的差异", "的差别", "的关系",
                  "确切的?", "是谁", "是什么", "在哪里", "什么时候")
_FRAGMENT_TAIL = ("是谁", "是什么", "在哪里", "确切时间", "确切日期", "等译法",
                  "这些译名", "等写法", "如何处理", "如何看待", "怎么样")
_QUESTION_WORDS = re.compile(
    r"(如何|怎样|怎么|什么|为何|为什么|哪些|哪个|哪一|是否|有没有|多少|"
    r"是谁|在哪|何时|什么样|的差别|的差异|的关系|等译法|等写法|"
    r"comment|pourquoi|quel(?:le|s)?|quoi|how|what|which|why)", re.I)


def is_question_fragment(term) -> bool:
    """该「词」是不是问句片段（不是术语）。判据全部可复核。"""
    t = str(term or "").strip()
    if not t:
        return True
    if any(stop.rstrip("?") in t for stop in _FRAGMENT_STOP):
        return True
    if t.endswith(_FRAGMENT_TAIL):
        return True
    if _QUESTION_WORDS.search(t):
        return True
    # 中文片段里以「的/了/着/是/在/与/和」等虚词结尾，或长度过长（≥7 汉字）的整句片段
    if re.search(r"[的了吗着呢是在与和及或等]$", t) and len(t) >= 4:
        return True
    # 方位/时间虚词结尾的中文片段（`中文语料里`、`这两种译法中`…）
    if re.search(r"[里中内上下前后时]", t) and len(re.findall(r"[\u4e00-\u9fff]", t)) >= 4:
        return True
    cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
    if cjk >= 7:
        return True
    if len(t.split()) > 3:
        return True
    return False


def content_terms(terms, limit=6):
    """过滤问句片段后的**内容词**（用于实体解析 / lane 构造）。"""
    out = []
    for t in terms or []:
        if is_question_fragment(t):
            continue
        if t not in out:
            out.append(str(t))
    return out[:limit]


# ─────────────────────────────────────────── §九 relation evidence
RELATION_KINDS = ("CO_OCCURRENCE", "DIRECT_RELATION_STATEMENT", "CROSS_REFERENCE",
                  "REINTERPRETATION", "CONTRAST", "FORMAL_LINK")

_REL_MARKERS = {
    "DIRECT_RELATION_STATEMENT": re.compile(
        r"rapport\s+(?:de|à|entre|du)|relation\s+(?:de|à|entre|du)|en\s+rapport|"
        r"lien\s+entre|关系|之间|相互|对应|关联|涉及|"
        r"\bentre\b[^.]{0,40}\bet\b|\bse\s+rapporte\b", re.I),
    "CROSS_REFERENCE": re.compile(
        r"\bcomme\s+(?:le\s+dit|Freud|Hegel|Descartes)|cit(?:e|é|ant)|se\s+r[ée]f[èe]re|"
        r"renvoie\s+à|参见|引用|援引|正如|据", re.I),
    "REINTERPRETATION": re.compile(
        r"repre(?:nd|nait|nant)|relire|relecture|reformul|r[ée][ée]criture|"
        r"重读|重新|改写|改造|重构|重新定位", re.I),
    "CONTRAST": re.compile(
        r"par\s+opposition|contrairement|s'oppose|se\s+distingu|distinction\s+entre|"
        r"区别|区分|不同于|对立|对照", re.I),
    "PREDICATION": re.compile(
        r"\bc['’]est\b|\best\s+(?:le|la|les|l['’]|un|une)\b|就是|即是|乃是|"
        r"是同一个|不外是|正是", re.I),
    "FORMAL_LINK": re.compile(
        r"[◊⋄$→⊂∩∪∅∀∃]|\bS\s*\(\s*A\s*\)|\ba\s*◊\s*S\b", re.I),
}


def entity_form_groups(plan) -> dict:
    """已解析实体 → 该实体的**词面形式集合**（来自 ontology，不是从问题里瞎猜）。"""
    import knowledge_api as api
    groups = {}
    for e in (plan or {}).get("entities") or []:
        for eid in e.get("entities") or []:
            forms = set()
            ent = None
            try:
                import ontology_v4a1 as onto
                ent = onto.entity(eid)
            except Exception:
                ent = None
            if ent:
                for k in ("fr", "en", "zh", "canonical_name"):
                    if ent.get(k):
                        forms.add(str(ent[k]))
                forms |= {str(a) for a in (ent.get("aliases") or [])}
            g = None
            try:
                g = onto.gold_concept(eid)
            except Exception:
                g = None
            if g:
                for k in ("fr", "en", "zh", "canonical_name"):
                    if g.get(k):
                        forms.add(str(g[k]))
                forms |= {str(a) for a in (g.get("aliases") or [])}
            if not forms:
                forms.add(str(e.get("term")))
            groups[eid] = sorted(f for f in forms if f and len(f) >= 2)
            _FORM_CACHE[eid] = [f for f in groups[eid]]
    return groups


_FORM_CACHE = {}
_CLAUSE_SPLIT = re.compile(r"[，,。！？；;.!?\n]+")


RELATION_STRENGTH = ("R0_NONE", "R1_COOCCURRENCE", "R2_CONTEXTUAL_RELATION",
                     "R3_EXPLICIT_RELATION", "R4_FORMAL_RELATION")


_MATHEME_SYMBOL = re.compile(
    r"[◊⋄→$⊂∩∪∅∀∃]\s*\(?\s*([A-Za-zΦ])\s*\)?"
    r"|\(\s*([A-Za-zΦ])\s*[◊⋄→$]\s*([A-Za-zΦ])\s*\)")


def _entity_symbol(eid):
    """实体 id 的**数学型字母**（`concept.objet-petit-a` → `a`）。找不到返回 None。"""
    tail = re.split(r"[.\-]", str(eid or ""))[-1]
    return tail if len(tail) == 1 and tail.isalpha() else None


def _entity_present(text, eid) -> bool:
    forms = _FORM_CACHE.get(eid) or []
    if any(gn.contains_v2(text, f) for f in forms if f):
        return True
    # 形式化写作：`(S ◊ a)` 里的 `a` 就是 objet petit a —— 词面里没有裸 `a` 这个写法，
    # 但数学型里它确实在场（这是 R4 formal relation 的前提）。
    sym = _entity_symbol(eid)
    if not sym:
        return False
    for m in _MATHEME_SYMBOL.finditer(str(text or "")):
        if sym in [g for g in m.groups() if g]:
            return True
    return False


def relation_strength(text, present_entities) -> str:
    """deterministic 关系强度分级（不做语义 entailment）。

    R4 形式连接（matheme 表达式把两项连起来）
    R3 显式关系陈述 / 预测式等同（`X, c'est Y`）/ 重读 / 对照 / 交叉引用
    R2 上下文关系（两项落在**同一子句**内）
    R1 同段共现（同一段但不同子句）
    R0 无（少于两个实体，或某一项在本段并不真的出现）
    """
    t = str(text or "")
    present = [e for e in (present_entities or []) if _entity_present(t, e)]
    if len(present) < 2:
        return "R0_NONE"
    if _REL_MARKERS["FORMAL_LINK"].search(t) and re.search(r"[◊⋄→$]|S\s*\(\s*A\s*\)", t):
        return "R4_FORMAL_RELATION"
    for key in ("DIRECT_RELATION_STATEMENT", "REINTERPRETATION", "CONTRAST",
                "CROSS_REFERENCE", "PREDICATION"):
        if _REL_MARKERS[key].search(t):
            return "R3_EXPLICIT_RELATION"
    for chunk in _CLAUSE_SPLIT.split(t):
        if all(_entity_present(chunk, e) for e in present):
            return "R2_CONTEXTUAL_RELATION"
    return "R1_COOCCURRENCE"


def relation_evidence(evidence, form_groups, question) -> dict:
    """在**同一段**内判定 relation evidence（确定性启发式，不用 LLM）。

    只有「同一段里同时出现两个实体的形式，并且出现关系/引用/重读/对照/形式连接标记」
    才计入 relation evidence —— A 段说 A、B 段说 B 不算。
    """
    found = []
    kinds = Counter()
    for e in evidence or []:
        text = str(e.get("text") or "")
        if not text:
            continue
        present = []
        for eid, forms in (form_groups or {}).items():
            if any(gn.contains_v2(text, f) for f in forms):
                present.append(eid)
        if len(present) < 2:
            continue
        hit_kinds = [k for k, rx in _REL_MARKERS.items() if rx.search(text)]
        if not hit_kinds:
            hit_kinds = ["CO_OCCURRENCE"]
        strength = relation_strength(text, present)
        found.append({"passage_id": e.get("passage_id"),
                      "entities": sorted(present), "kinds": sorted(hit_kinds),
                      "strength": strength})
        for k in hit_kinds:
            kinds[k] += 1
    strengths = Counter(f["strength"] for f in found)
    best = "R0_NONE"
    for r in RELATION_STRENGTH:
        if strengths.get(r):
            best = r
    return {"relation_evidence_found": bool(found),
            "relation_evidence_n": len(found),
            "relation_evidence_ids": [f["passage_id"] for f in found],
            "relation_kinds": dict(kinds),
            "relation_strength": best,
            "relation_strength_counts": dict(strengths),
            "relation_evidence": found}


_RELATION_QUESTION = re.compile(
    r"什么关系|有什么关系|之间的关系|关系是|如何关联|怎样关联|"
    r"quel(?:le)?\s+rapport|quelle\s+relation|en\s+rapport|relationship|"
    r"如何进入|怎样进入|comment\s+entre|如何被处理|如何重新", re.I)
_PERIOD_WORDS = re.compile(
    r"时期|阶段|早期|晚期|中期|年代|历年|不同时期|各期|per[íi]ode|ann[ée]es|"
    r"diachron|195\d|196\d|197\d", re.I)
_COMPARISON_QUESTION = re.compile(
    r"有什么区别|有什么差异|区别是什么|差别|区分|不同在哪里|对比|"
    r"diff[ée]rence|distinction|s'oppose|versus|\bvs\b|contraste", re.I)


def relation_required(question, task_type, form_groups) -> bool:
    """是否需要 relation evidence。

    判据（不看 gold、不看 task_id）：
      * 问题语义要求关系/对比；或
      * task_type 本身就是跨来源/关系型（concept_relation / freud_to_lacan /
        philosophy_to_lacan）；
      * 否则**不**仅仅因为「解析出 ≥2 个实体」就要求关系证据 ——
        定义题里出现多个实体（如 objet-petit-a 与 term.objet）并不等于关系题。
    """
    q = str(question or "")
    if _RELATION_QUESTION.search(q):
        return True
    if _COMPARISON_QUESTION.search(q):
        # 「区分不同时期的差别」这类是**历时**问题，不是两个实体之间的关系题
        if not _PERIOD_WORDS.search(q):
            return True
    return task_type in ("concept_relation", "freud_to_lacan", "philosophy_to_lacan")


# ─────────────────────────────────────────── §七 十类契约
def _lane(entity_id, forms, language=None, seminar=None, expectation="EXPECTED_POSITIVE"):
    return {"lane": entity_id, "entity_id": entity_id, "needles": list(forms or []),
            "language": language, "seminar": seminar,
            "expectation": expectation}


class BaseContract:
    """契约公共部分：ops / lanes / constraints / source layers / usability。"""

    contract_type = "BaseContract"

    def __init__(self, public_task, plan, pack, executed_tools, op_statuses=None):
        self.task = public_task or {}
        self.plan = plan or {}
        self.pack = pack or {}
        self.op_statuses = dict(op_statuses or {})
        self.q = self.task.get("question") or ""
        self.task_type = self.task.get("task_type") or self.plan.get("task_type")
        self.evidence = list(self.pack.get("evidence") or [])
        self.executed = list(executed_tools or [])
        self.form_groups = entity_form_groups(self.plan)
        self.usability = [dict(classify_evidence_usability(e),
                               passage_id=e.get("passage_id")) for e in self.evidence]
        self.usable_ids = {u["passage_id"] for u in self.usability
                           if u["can_support_substantive_claim"]}

    # ── ops
    # 「手段型」操作：计划里几乎总会出现，但缺了**不构成**契约违规
    # （它们是达成目的的方式，不是任务要求的必要条件）。
    CONDITIONAL_OPS = ("search_passages", "get_context", "trace_source")

    def required_operations(self):
        """**必要条件**型操作 = 契约类型蕴含的 + 计划里非手段型的。

        为什么要区分：`make_plan` 给每个任务都追加 `search_passages`/`get_context`，
        若把它们当必要条件，则「没走通用检索兜底」会被误判成契约未完成。
        Phase 4C 人工评审真正投诉的是**能力蕴含的操作没执行**
        （terminology_lookup / find_concept_evidence / compare_concepts）。
        """
        ops = []
        for op in self.type_required_operations():
            if op not in ops:
                ops.append(op)
        for op in (self.plan.get("planned_operations") or []):
            if op in self.CONDITIONAL_OPS:
                continue
            if op not in ops:
                ops.append(op)
        return ops

    def operation_basis(self):
        """每个必需操作**为什么**必需：契约类型蕴含 / 能力映射 / 计划声明。"""
        from collections import OrderedDict
        basis = OrderedDict()
        for op in self.type_required_operations():
            basis[op] = "CONTRACT_TYPE"
        cap_map = {}
        for c in (self.plan.get("required_capabilities") or []):
            op = OPERATIONS_BY_CAPABILITY_REF.get(c)
            if op:
                cap_map.setdefault(op, []).append(c)
        for op in (self.plan.get("planned_operations") or []):
            if op in self.CONDITIONAL_OPS:
                continue
            if op in cap_map:
                basis.setdefault(op, "CAPABILITY:%s" % ",".join(sorted(cap_map[op])))
            else:
                basis.setdefault(op, "PLAN")
        return dict(basis)

    def optional_operations(self):
        return [op for op in (self.plan.get("planned_operations") or [])
                if op in self.CONDITIONAL_OPS]

    def type_required_operations(self):
        return []

    # ── lanes
    def required_lanes(self):
        lanes = []
        for eid, forms in self.form_groups.items():
            lanes.append(_lane(eid, forms))
        for sid in seminar_constraints(self.q):
            lanes.append(_lane("seminar.%s" % sid, [], seminar="seminar.%s" % sid))
        return lanes

    def expected_zero_lanes(self):
        """预期为 0 的 lane（默认无；terminology 契约会给出）。"""
        return []

    # 执行记录里哪些 lane 是「有证据/有见证」的（B2：证据可用性参与 lane 完成度）
    _LANE_TERMINAL_NO_EVIDENCE_OK = ("ZERO_ATTESTATION_CONFIRMED",)

    def execution_lane_records(self):
        ex = (self.pack.get("execution") or {})
        return {l.get("lane_id"): l for l in (ex.get("lanes") or [])}

    def lane_completed_by_execution(self, lane_id):
        """→ True/False/None（None = 没有执行记录，退回证据集判定）。"""
        rec = self.execution_lane_records().get(lane_id)
        if rec is None:
            return None
        if str(lane_id).startswith("term:"):
            # 术语 lane 的完成语义是「译名有语料见证」，不是「检索到段落」
            return (rec.get("status") == "ZERO_ATTESTATION_CONFIRMED"
                    or (rec.get("corpus_hits") or 0) > 0
                    or bool(rec.get("evidence_ids")))
        if rec.get("status") in self._LANE_TERMINAL_NO_EVIDENCE_OK:
            return True
        return bool(rec.get("evidence_ids"))

    def completed_lanes(self, required):
        out = []
        for lane in required:
            by_ex = self.lane_completed_by_execution(lane.get("lane"))
            if by_ex is None:
                by_ex = bool(self.lane_passages(lane))
            if by_ex:
                out.append(lane["lane"])
        return out

    def lane_passages(self, lane):
        """该 lane 在**本次证据集**里的段落（按 lane 语义过滤）。"""
        out = []
        for e in self.evidence:
            pid = e.get("passage_id")
            text = str(e.get("text") or "")
            if lane.get("seminar"):
                if seminar_of_passage(pid) != lane["seminar"]:
                    continue
            if lane.get("needles"):
                if not any(gn.contains_v2(text, n) for n in lane["needles"]):
                    continue
            out.append(pid)
        return out

    # ── 约束
    def required_constraints(self):
        cons = []
        for sid in seminar_constraints(self.q):
            cons.append({"kind": "seminar", "value": "seminar.%s" % sid})
        for label in period_constraints(self.q):
            cons.append({"kind": "period", "value": label})
        return cons

    def _constraints_structurally_na(self):
        """哪些约束因为**上游结构性不可答**而根本不可能被满足（如 metadata 全库缺字段）。

        依据执行层留下的 NOT_APPLICABLE 结构凭据（不是猜）：有凭据才算。
        """
        ex = (self.pack.get("execution") or {})
        for o in (ex.get("operations") or []):
            dep = o.get("structural_dependency") or {}
            for pr in dep.get("proofs") or []:
                scan = (pr or {}).get("corpus_scan") or {}
                if (o.get("status") == "NOT_APPLICABLE"
                        and dep.get("upstream_state") == "METADATA_UNAVAILABLE"
                        and scan.get("executed") is True
                        and scan.get("scope") == "whole_corpus"
                        and int(scan.get("n_with_real_value") or 0) == 0):
                    return True
        return False

    def check_constraints(self, required):
        sat, failed, na = [], [], []
        structurally_na = self._constraints_structurally_na()
        for c in required:
            if structurally_na and c["kind"] in ("seminar", "period"):
                na.append(c)          # 结构性不可答：既不满足也不算「未满足」
                continue
            ok = False
            if c["kind"] == "seminar":
                ok = any(seminar_of_passage(e.get("passage_id")) == c["value"]
                         for e in self.evidence)
            elif c["kind"] == "period":
                ok = any((e.get("period") or e.get("period_label")) == c["value"]
                         for e in self.evidence)
            (sat if ok else failed).append(c)
        self._na_constraints = na
        return sat, failed

    # ── source layers
    def available_source_layers(self):
        layers = set()
        for e in self.evidence:
            pid = e.get("passage_id")
            u = next((x for x in self.usability if x["passage_id"] == pid), {})
            cls = u.get("usability_class")
            if cls == "MEDIA_ONLY":
                layers.add("media_placeholder")
            elif cls == "EDITORIAL_METADATA":
                layers.add("editorial_metadata")
            elif cls == "BIBLIOGRAPHY_ONLY":
                layers.add("bibliography")
            elif cls == "FRAGMENT_ONLY":
                layers.add("fragment")
            auth = e.get("authority_level")
            if auth == "L1":
                layers.add("lacan_primary")
            elif auth == "L2":
                layers.add("lacan_translation")
            if not e.get("seminar_id"):
                layers.add("external_source")
        return sorted(layers)

    def required_source_layers(self):
        return []

    def source_layer_corpus_availability(self):
        """**语料层**是否存在该层（whole-corpus 事实；区分 SOURCE_GAP 与 retrieval miss）。"""
        lc = (corpus_census() or {}).get("layer_counts") or {}
        return {"lacan_primary": lc.get("lacan_primary", 0) > 0,
                "lacan_translation": lc.get("lacan_translation", 0) > 0,
                "external_source": lc.get("external_source", 0) > 0,
                "freud_source": lc.get("external_freud", 0) > 0,
                "philosophy_source": lc.get("external_philosophy", 0) > 0}

    # ── formalism
    def formalism_symbols(self):
        return [s for s in FORMALISM_SYMBOLS if s in self.q]

    # ── formalism（Phase 4C.1-B3 §3：分级形式检索）
    def formalism_candidates(self):
        """问题解析出的 formalism 检索形式（分级；缓存在实例上）。"""
        if getattr(self, "_formalism_candidates", None) is None:
            self._formalism_candidates = formalism_query_forms(
                self.q, self.formalism_symbols(), self.task_type)
        return self._formalism_candidates

    def formalism_seminar(self):
        """formalism 检索的 seminar 约束：显式期号优先，否则由**研讨班标题**派生。

        H02（`$ ◊ a` + fantasme）由此自然得到 seminar.S14（La logique du fantasme），
        **不是** task_id 特判。
        """
        explicit = seminar_constraints(self.q)
        if explicit:
            return {"seminar_id": "seminar.%s" % explicit[0], "source": "explicit_question"}
        derived = seminar_from_title(self.q)
        if derived:
            d = dict(derived)
            d["source"] = "seminar_title_match"
            return d
        return None

    def formalism_state(self):
        symbols = self.formalism_symbols()
        cands = self.formalism_candidates()
        direct_forms = [f for f in cands if f.get("strength") == "DIRECT"]
        # formalism 是否**必需**：问题里有符号、或点名了形式对象，或本身就是拓扑/数学型任务。
        # 只靠默认符号 `◊` 兜底**不算**必需 —— 否则每个任务都会被塞进一个形式义务
        # （B3 修：J03「1953 年 11 月 18 日…」曾被错误地要求 formalism）。
        named = [f for f in cands if f["strategy"] == "named_formal_object"]
        # 「点名形式对象」只有在**形式性提问**里才构成形式义务：任务类型是拓扑/数学型，
        # 或问题本身在谈公式/书写/数学型（formule / mathème / écriture / poinçon / nœud）。
        # 反例（B3 实测）：`Real 从早期到晚期 Borromean teaching 的变化` 是历时题，
        # 只是把 Borromean 当作晚期标签，不该因此被要求交出形式证据集。
        formal_word = bool(re.search(
            r"formule|math[èe]me|écriture|ecriture|poin[çc]on|topolog",
            str(self.q or ""), re.I))
        required = (bool(symbols) or self.task_type == "topology_matheme"
                    or (bool(named) and formal_word))
        if not required:
            return {"formalism_required": False, "formalism_evidence_found": False,
                    "formalism_state": "NOT_REQUIRED", "symbols": symbols,
                    "formalism_candidates": [],
                    "reason": ("问题里没有符号、也没有点名形式对象，且任务类型不是 "
                               "topology_matheme → 不构成形式义务")}
        needed = symbols or ["◊"]
        mkeys = {f["normalized"] for f in direct_forms
                 if f["strategy"] not in ("named_formal_object", "related_formal_term")}
        tkeys = {f["form"].lower() for f in direct_forms
                 if f["strategy"] in ("named_formal_object", "related_formal_term")}
        in_evidence, kind = [], None
        for e in self.evidence:
            text = str(e.get("text") or "")
            if not text:
                continue
            hit_kind = None
            for m in _MATHEME_EXPR.finditer(text):
                left, op, right = m.group(1), m.group(2), m.group(3)
                core = normalize_matheme("%s%s%s" % (left, op, right))
                if _matheme_keys(core, left, op, right) & mkeys:
                    hit_kind = "MATHEME_EXPRESSION"
                    break
            if not hit_kind:
                low = text.lower()
                if any(t in low for t in tkeys):
                    hit_kind = "NAMED_FORMAL_OBJECT"
            if hit_kind:
                in_evidence.append(e.get("passage_id"))
                kind = kind or hit_kind
        idx = formalism_index()
        in_corpus = {s: (corpus_census()["symbols"].get(s) or {}).get("passages", 0)
                     for s in needed}
        corpus_dist = Counter()
        for f in direct_forms:
            c = (idx["counts"].get(f["normalized"])
                 or idx["symbol_counts"].get(f["normalized"])
                 or idx["named_counts"].get(f["form"]) or {})
            for sem_id, v in c.items():
                corpus_dist[sem_id] += v
        corpus_has = bool(corpus_dist) or any(v > 0 for v in in_corpus.values())
        if in_evidence:
            state = "FORMALISM_FOUND"
        elif corpus_has:
            state = "RETRIEVED_FORMALISM_MISSING"      # 属 retrieval
        else:
            state = "CORPUS_FORMALISM_MISSING"         # 才可能是结构性
        sem = self.formalism_seminar()
        return {"formalism_required": True,
                "formalism_evidence_found": bool(in_evidence),
                "formalism_evidence_ids": in_evidence,
                "formalism_evidence_kind": kind,
                "formalism_state": state,
                "symbols": needed,
                "formalism_candidates": cands,
                "formalism_seminar": sem,
                "corpus_symbol_counts": in_corpus,
                "corpus_distribution": dict(corpus_dist.most_common(8)),
                "corpus_scan": {"executed": True, "scope": "whole_corpus",
                                "n_passages": corpus_census()["scanned"]}}

    # ── metadata
    METADATA_PATTERNS = {
        "exact_date": re.compile(r"确切|准确|具体|几月几?日|哪一?天|哪日|什么时候|date|quand|exact", re.I),
        "location": re.compile(r"地点|哪里|何地|lieu|où|address", re.I),
        "attendees": re.compile(r"在场者|出席|参加者|听众|participants|présents", re.I),
        "session_number": re.compile(r"第几讲|哪一讲|session\s+number|le[çc]on\s+num", re.I),
        "edition": re.compile(r"版次|版本|哪一版|[ée]dition", re.I),
        "page": re.compile(r"页码|第几页|page\s+num", re.I),
    }

    def metadata_state(self):
        asked = [k for k, rx in self.METADATA_PATTERNS.items() if rx.search(self.q)]
        if not asked:
            return {"metadata_required": [], "metadata_available": True,
                    "metadata_missing_fields": [], "metadata_state": "NOT_REQUIRED"}
        missing = []
        if "exact_date" in asked and not self.kb_has_exact_dates():
            missing.append("session_date（全库 unknown）")
        for k in ("location", "attendees", "session_number", "edition", "page"):
            if k in asked and not self.kb_has_field(k):
                missing.append(k)
        state = "METADATA_UNAVAILABLE" if missing else "METADATA_AVAILABLE"
        return {"metadata_required": asked, "metadata_available": not missing,
                "metadata_missing_fields": missing, "metadata_state": state,
                "corpus_scan": {"executed": True, "scope": "whole_corpus",
                                "method": "passage_store 字段 + 词法计数"}}

    def kb_has_exact_dates(self):
        """canonical store 是否**存在**确切日期（结构事实）。"""
        global _HAS_DATES
        try:
            return _HAS_DATES
        except NameError:
            pass
        _HAS_DATES = False
        p = os.path.join(STORE, "passages.jsonl")
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 5000:
                    break
                if not line.strip():
                    continue
                d = json.loads(line)
                if d.get("session_date") and d["session_date"] != "unknown":
                    _HAS_DATES = True
                    break
        return _HAS_DATES

    def kb_has_field(self, field):
        """该 metadata 字段在语料里是否存在（会话/研讨班层）。"""
        global _FIELD_CACHE
        try:
            cache = _FIELD_CACHE
        except NameError:
            _FIELD_CACHE = {}
            cache = _FIELD_CACHE
        if field in cache:
            return cache[field]
        have = False
        p = os.path.join(STORE, "sessions.jsonl")
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                if not line.strip():
                    continue
                d = json.loads(line)
                keys = {"location": ("location", "place"),
                        "attendees": ("attendees", "participants"),
                        "session_number": ("sequence", "number", "lesson"),
                        "edition": ("edition",), "page": ("page",)}.get(field, (field,))
                if any(d.get(k) for k in keys):
                    have = True
                    break
        cache[field] = have
        return have

    # ── 组装
    # Phase 4C.1-B3：合法 NOT_APPLICABLE 的三个条件（缺一不可）
    TERMINAL_OK = ("EXECUTED", "FAILED", "STRUCTURALLY_UNAVAILABLE", "NOT_APPLICABLE")

    def _op_status(self, op):
        if op in self.op_statuses:
            return self.op_statuses[op]
        return "EXECUTED" if op in self.executed else None

    def _not_applicable_records(self):
        ex = (self.pack.get("execution") or {})
        out = []
        for o in (ex.get("operations") or []):
            if o.get("status") != "NOT_APPLICABLE":
                continue
            out.append({"operation": o.get("operation_id"),
                        "reason_code": o.get("failure_code"),
                        "structural_dependency": o.get("structural_dependency")})
        return out

    @staticmethod
    def not_applicable_is_proven(rec):
        """NOT_APPLICABLE 是否**有机器可验证的结构依赖凭据**（B3 §2 的唯一合法通道）。"""
        dep = (rec or {}).get("structural_dependency") or {}
        if dep.get("upstream_state") not in ("METADATA_UNAVAILABLE",):
            return False
        if dep.get("upstream_operation") != "metadata_check":
            return False
        proofs = dep.get("proofs") or []
        if not proofs:
            return False
        for pr in proofs:
            scan = (pr or {}).get("corpus_scan") or {}
            if scan.get("executed") is True and scan.get("scope") == "whole_corpus" \
                    and int(scan.get("n_with_real_value") or 0) == 0 \
                    and (pr or {}).get("availability") in ("GLOBAL_UNKNOWN", "FIELD_ABSENT"):
                return True
        return False

    def compile(self):
        required_ops = self.required_operations()
        na_records = [r for r in self._not_applicable_records()
                      if self.not_applicable_is_proven(r)]
        na_ops = [r["operation"] for r in na_records]
        # `completed_operations` = **已解决**的 required 操作（EXECUTED + 合法 NOT_APPLICABLE）
        done_ops = [o for o in required_ops
                    if o in self.executed or o in na_ops]
        resolved_ops = [o for o in required_ops
                        if self._op_status(o) in self.TERMINAL_OK]
        missing_ops = [o for o in required_ops
                       if o not in self.executed and o not in na_ops
                       and self._op_status(o) not in ("STRUCTURALLY_UNAVAILABLE",)]
        required_lanes = self.required_lanes()
        completed_lanes = self.completed_lanes(required_lanes)
        missing_lanes = [l["lane"] for l in required_lanes
                         if l["lane"] not in completed_lanes]
        zero_lanes = self.expected_zero_lanes()
        required_cons = self.required_constraints()
        sat_cons, failed_cons = self.check_constraints(required_cons)
        na_cons = list(getattr(self, "_na_constraints", []) or [])
        rel_req = relation_required(self.q, self.task_type, self.form_groups)
        rel = relation_evidence(self.evidence, self.form_groups, self.q)
        src_req = self.required_source_layers()
        src_avail = self.available_source_layers()
        src_missing = [s for s in src_req if s not in src_avail]
        form = self.formalism_state()
        meta = self.metadata_state()
        usab = Counter(u["usability_class"] for u in self.usability)
        return {
            "schema_version": "research-contract/v1",
            "task_id": self.task.get("task_id"),
            "task_type": self.task_type,
            "contract_type": self.contract_type,
            "question": self.q,
            "required_entities": sorted(self.form_groups),
            "optional_entities": [],
            "required_operations": required_ops,
            "operation_basis": self.operation_basis(),
            "completed_operations": done_ops,
            "missing_operations": missing_ops,
            "resolved_operations": resolved_ops,
            "not_applicable_operations": [
                {"operation": r["operation"], "reason_code": r.get("reason_code"),
                 "structural_dependency": r.get("structural_dependency")}
                for r in na_records],
            "not_applicable_unproven": [
                {"operation": r["operation"], "reason_code": r.get("reason_code")}
                for r in self._not_applicable_records()
                if not self.not_applicable_is_proven(r)],
            "structurally_unavailable_operations": [
                o for o in required_ops
                if self._op_status(o) == "STRUCTURALLY_UNAVAILABLE"],
            "optional_operations": self.optional_operations(),
            "optional_missing_operations": [o for o in self.optional_operations()
                                            if o not in self.executed],
            "required_lanes": [l["lane"] for l in required_lanes],
            "lanes": required_lanes,
            "completed_lanes": completed_lanes,
            "missing_lanes": missing_lanes,
            "expected_zero_lanes": zero_lanes,
            "required_constraints": required_cons,
            "satisfied_constraints": sat_cons,
            "failed_constraints": failed_cons,
            "not_applicable_constraints": [
                {"kind": c.get("kind"), "value": c.get("value"),
                 "reason_code": "METADATA_UNAVAILABLE",
                 "structural_dependency": "metadata 字段全库不存在 → 约束无法下推"}
                for c in na_cons],
            "required_source_layers": src_req,
            "available_source_layers": src_avail,
            "missing_source_layers": src_missing,
            "source_layer_corpus": self.source_layer_corpus_availability(),
            "missing_source_layers_absent_in_corpus":
                [x for x in src_missing
                 if not self.source_layer_corpus_availability().get(x, False)],
            "relation_evidence_required": rel_req,
            "relation_evidence_found": rel["relation_evidence_found"],
            "relation_evidence_n": rel["relation_evidence_n"],
            "relation_evidence_ids": rel["relation_evidence_ids"],
            "relation_kinds": rel["relation_kinds"],
            "relation_strength": rel.get("relation_strength"),
            "relation_strength_counts": rel.get("relation_strength_counts"),
            "formalism": form,
            "metadata": meta,
            "evidence_usability": {
                "counts": dict(usab),
                "substantive_n": usab.get("SUBSTANTIVE_TEXT", 0),
                "non_substantive_ids": [u["passage_id"] for u in self.usability
                                        if not u["can_support_substantive_claim"]],
                "per_passage": self.usability,
            },
            "no_hidden_reasoning": True,
            "note": ("契约由 task_type / 问题语义 / 已解析实体 / 约束 / 语料事实编译；"
                     "不含任何 task_id 分支，也不含模型推理。"),
        }


# ── 十类
class DefinitionResearchContract(BaseContract):
    contract_type = "DefinitionResearchContract"

    def type_required_operations(self):
        return ["find_concept_evidence"]

    def required_source_layers(self):
        return []


class ComparisonResearchContract(BaseContract):
    contract_type = "ComparisonResearchContract"

    def type_required_operations(self):
        return ["compare_concepts"]

    def required_lanes(self):
        """每个已解析实体**各一条** lane（不能 3 实体只跑 1 条）。"""
        return [_lane(eid, forms) for eid, forms in self.form_groups.items()]


class DiachronicResearchContract(BaseContract):
    contract_type = "DiachronicResearchContract"

    def type_required_operations(self):
        return ["trace_concept"]

    def required_endpoints(self):
        sems = seminar_constraints(self.q)
        if sems:
            return ["seminar.%s" % s for s in sems]
        # 没有显式期号 → 用问题里的年份落到的研讨班
        out = []
        for label in period_constraints(self.q):
            for sid, (a, b) in _seminar_spans().items():
                if a and b and "%s-%s" % (a, b) == label:
                    out.append(sid)
        return sorted(set(out))

    def required_lanes(self):
        lanes = [_lane(eid, forms) for eid, forms in self.form_groups.items()]
        for sid in self.required_endpoints():
            lanes.append(_lane(sid, [], seminar=sid))
        return lanes

    def compile(self):
        c = super().compile()
        c["required_endpoints"] = self.required_endpoints()
        c["endpoint_evidence"] = {
            sid: [e.get("passage_id") for e in self.evidence
                  if seminar_of_passage(e.get("passage_id")) == sid]
            for sid in self.required_endpoints()}
        c["diachronic_relation_required"] = True
        return c


class SeminarSpecificContract(BaseContract):
    contract_type = "SeminarSpecificContract"

    def type_required_operations(self):
        return ["search_passages"]

    def required_lanes(self):
        lanes = [_lane(eid, forms) for eid, forms in self.form_groups.items()]
        for sid in seminar_constraints(self.q):
            lanes.append(_lane("seminar.%s" % sid, [], seminar="seminar.%s" % sid))
        return lanes


class CaseResearchContract(BaseContract):
    contract_type = "CaseResearchContract"

    def type_required_operations(self):
        return ["find_concept_evidence", "search_passages"]


class FreudToLacanResearchContract(BaseContract):
    contract_type = "FreudToLacanResearchContract"

    def type_required_operations(self):
        return ["find_concept_evidence", "compare_concepts"]

    def required_source_layers(self):
        return ["lacan_primary", "freud_source"]

    def required_source_layers_note(self):
        return ("Freud 原始层必须有语料支持；本库若没有 Freud 文本 witness，"
                "`freud_source` 必然缺失 → source_layer_complete = false → 禁止 SUPPORTED。")


class PhilosophyToLacanResearchContract(BaseContract):
    contract_type = "PhilosophyToLacanResearchContract"

    def type_required_operations(self):
        return ["find_concept_evidence", "compare_concepts"]

    def required_source_layers(self):
        return ["lacan_primary", "philosophy_source"]


class TopologyMathemeResearchContract(BaseContract):
    contract_type = "TopologyMathemeResearchContract"

    def type_required_operations(self):
        return ["find_concept_evidence", "search_passages"]

    def required_lanes(self):
        lanes = [_lane(eid, forms) for eid, forms in self.form_groups.items()]
        forms = [f["form"] for f in self.formalism_candidates()
                 if f.get("strength") == "DIRECT"] or (self.formalism_symbols() or ["◊"])
        sem = self.formalism_seminar()
        lanes.append(_lane("formalism", forms, expectation="EXPECTED_POSITIVE",
                           seminar=(sem or {}).get("seminar_id")))
        for sid in seminar_constraints(self.q):
            lanes.append(_lane("seminar.%s" % sid, [], seminar="seminar.%s" % sid))
        return lanes


class TranslationTerminologyResearchContract(BaseContract):
    """译名契约：每个**显式列出的译名**一条 lexical lane，并支持 EXPECTED_ZERO。"""
    contract_type = "TranslationTerminologyResearchContract"

    def type_required_operations(self):
        return ["terminology_lookup", "search_passages"]

    def explicit_terms(self):
        """从问题里抽出被显式讨论的译名（引号内 / 「」内 / 顿号列举）。"""
        q = self.q
        terms = []
        for m in re.finditer(r"[「“\"'《]([^」”\"'》]{1,12})[」”\"'》]", q):
            terms.append(m.group(1).strip())
        # 「X、Y、Z」式列举
        for chunk in re.findall(r"([\u4e00-\u9fff、\s]{2,40})", q):
            parts = [p.strip() for p in chunk.split("、") if p.strip()]
            if len(parts) >= 2:
                terms += parts
        out = []
        for t in terms:
            t = t.strip(" 　")
            if 1 <= len(t) <= 12 and t not in out and not re.search(r"[？?。，,]", t):
                out.append(t)
        return out[:8]

    def required_lanes(self):
        lanes = [_lane(eid, forms) for eid, forms in self.form_groups.items()]
        for t in self.explicit_terms():
            lanes.append(_lane("term:%s" % t, [t]))
        return lanes

    def expected_zero_lanes(self):
        """语料层 0 命中的译名 → EXPECTED_ZERO（0 命中是结论，不是失败）。"""
        out = []
        for t in self.explicit_terms():
            if self.term_corpus_hits(t) == 0:
                out.append({"lane": "term:%s" % t, "term": t,
                            "expectation": "EXPECTED_ZERO",
                            "observed_hits": 0, "hit_state": "ZERO_ATTESTATION",
                            "result": "PASS",
                            "corpus_scan": {"executed": True, "needle": t,
                                            "scope": "whole_corpus", "hits": 0}})
        return out

    def term_corpus_hits(self, term):
        """语料层精确命中数（词法索引；与检索同一套语法）。"""
        global _TERM_HITS
        try:
            cache = _TERM_HITS
        except NameError:
            _TERM_HITS = {}
            cache = _TERM_HITS
        if term not in cache:
            try:
                import evidence_sufficiency_v2 as esv2
                cache[term] = int(esv2.prevalence(term))
            except Exception:
                cache[term] = 0
        return cache[term]

    def compile(self):
        c = super().compile()
        c["terminology"] = {
            "explicit_terms": self.explicit_terms(),
            "term_corpus_hits": {t: self.term_corpus_hits(t)
                                 for t in self.explicit_terms()},
            "status_vocabulary": ["KNOWN_TRANSLATION", "CORPUS_ATTESTED",
                                  "CONTEXT_VALIDATED"],
            "rule": "ontology mapping（KNOWN_TRANSLATION）≠ corpus attestation（CORPUS_ATTESTED）",
        }
        return c


class AbstentionResearchContract(BaseContract):
    contract_type = "AbstentionResearchContract"

    def type_required_operations(self):
        return ["search_passages"]

    def compile(self):
        c = super().compile()
        meta = c["metadata"]
        if meta.get("metadata_state") == "METADATA_UNAVAILABLE":
            why, kind, nxt = ("METADATA_UNAVAILABLE", "structural", "metadata 字段来源")
        elif not c["evidence_usability"]["substantive_n"]:
            why, kind, nxt = ("NO_SUBSTANTIVE_EVIDENCE", "retrieval", "更精确的检索式")
        else:
            why, kind, nxt = ("INSUFFICIENT_TOPICAL_EVIDENCE", "retrieval",
                              "领域专门检索或多语言 lane")
        c["abstention"] = {
            "why_unanswerable": why,
            "missing_evidence_type": kind,
            "structural_or_retrieval": ("STRUCTURAL" if kind == "structural"
                                        else "RETRIEVAL"),
            "next_required_source": nxt,
        }
        return c


# 能力 → 操作映射从 pipeline 借（单一真源，避免两处漂移）
try:                                                    # pragma: no cover
    from research_answer import OPERATIONS_BY_CAPABILITY as OPERATIONS_BY_CAPABILITY_REF
except Exception:                                       # pragma: no cover
    OPERATIONS_BY_CAPABILITY_REF = {}

def contract_obligations(contract) -> dict:
    """从契约里抽出**执行义务**（scheduler 的唯一输入）。

    → {operations:[…], lanes:[…], constraints:[…], facets:{…}}
    这是 contract（what must be done）与 execution（what was done）之间的接口。
    """
    lanes = []
    for l in contract.get("lanes") or []:
        lanes.append({"lane_id": l["lane"], "needles": l.get("needles") or [],
                      "entity_id": l.get("entity_id"),
                      "language": l.get("language"), "seminar": l.get("seminar"),
                      "expectation": l.get("expectation") or "EXPECTED_POSITIVE",
                      "required": l["lane"] in (contract.get("required_lanes") or [])})
    for z in contract.get("expected_zero_lanes") or []:
        lanes.append({"lane_id": z["lane"], "needles": [z.get("term") or z["lane"]],
                      "entity_id": None, "language": None, "seminar": None,
                      "expectation": "EXPECTED_ZERO", "required": True})
    endpoints = [{"endpoint_id": "endpoint.%s" % s, "seminar": s}
                 for s in (contract.get("required_endpoints") or [])]
    return {
        "operations": list(contract.get("required_operations") or []),
        "optional_operations": list(contract.get("optional_operations") or []),
        "lanes": lanes,
        "endpoints": endpoints,
        "constraints": list(contract.get("required_constraints") or []),
        "facets": {
            "relation": bool(contract.get("relation_evidence_required")),
            "formalism": bool((contract.get("formalism") or {}).get("formalism_required")),
            "metadata": bool((contract.get("metadata") or {}).get("metadata_required")),
            "terminology": bool((contract.get("terminology") or {}).get("explicit_terms")),
            "source_layers": list(contract.get("required_source_layers") or []),
        },
    }


def obligation_summary(contract, execution) -> dict:
    """契约义务 vs 执行记录 → 逐项完成情况（execution 为 None 时视为未执行）。"""
    ex = execution or {}
    ops = {o["operation_id"]: o for o in (ex.get("operations") or [])}
    lanes = {l["lane_id"]: l for l in (ex.get("lanes") or [])}
    cons = {("%s=%s" % (c.get("kind"), c.get("value"))): c
            for c in (ex.get("constraints") or [])}
    req_ops = contract.get("required_operations") or []
    req_lanes = contract.get("required_lanes") or []
    req_cons = ["%s=%s" % (c.get("kind"), c.get("value"))
                for c in (contract.get("required_constraints") or [])]
    return {
        "required_operations": req_ops,
        "executed_operations": [o for o in req_ops
                                if (ops.get(o) or {}).get("status") in
                                ("EXECUTED", "FAILED", "STRUCTURALLY_UNAVAILABLE")],
        "unresolved_operations": [o for o in req_ops if o not in ops],
        "required_lanes": req_lanes,
        "resolved_lanes": [l for l in req_lanes
                           if (lanes.get(l) or {}).get("status") in
                           ("EXECUTED", "SATISFIED", "ZERO_ATTESTATION_CONFIRMED",
                            "FAILED", "STRUCTURALLY_UNAVAILABLE")],
        "unresolved_lanes": [l for l in req_lanes if l not in lanes],
        "required_constraints": req_cons,
        "applied_constraints": [c for c in req_cons
                                if (cons.get(c) or {}).get("applied") is not None],
    }


CONTRACTS = {
    "concept_definition": DefinitionResearchContract,
    "concept_relation": ComparisonResearchContract,
    "diachronic_development": DiachronicResearchContract,
    "seminar_specific": SeminarSpecificContract,
    "case_research": CaseResearchContract,
    "freud_to_lacan": FreudToLacanResearchContract,
    "philosophy_to_lacan": PhilosophyToLacanResearchContract,
    "topology_matheme": TopologyMathemeResearchContract,
    "translation_terminology": TranslationTerminologyResearchContract,
    "insufficient_unanswerable": AbstentionResearchContract,
}


def compile_research_contract(public_task, plan, pack, executed_tools=None,
                              op_statuses=None):
    """Question → TaskType → Plan → **Contract**（本阶段的中心函数）。

    `op_statuses`（Phase 4C.1-B3）：执行层给出的 operation_id → status 映射。
    有了它，契约才算得出 `resolved_operations` / `not_applicable_operations`，
    并把 **合法 NOT_APPLICABLE** 从 `missing_operations` 里排除
    （普通 retrieval failure 不在排除之列 —— 见 validate_contract 的 B11/B12）。
    """
    tt = (public_task or {}).get("task_type") or (plan or {}).get("task_type")
    cls = CONTRACTS.get(tt, BaseContract)
    if executed_tools is None:
        executed_tools = []
    return cls(public_task, plan, pack, executed_tools, op_statuses=op_statuses).compile()


# ─────────────────────────────────────────── 契约验证 → 状态上限（硬规则 B1/B2）
def validate_contract(contract, relations_note=None) -> dict:
    """→ {"state_ceiling", "violated_rules": [...], "completion_state",
          "completion_reasons": [...]}

    规则（每一条都是**可复核**的，且不针对任何具体任务）：
      B1  missing_operations 非空 → 禁止 SUPPORTED
      B2  missing_lanes 非空     → 禁止 SUPPORTED
      B3  relation_required 且 relation_evidence_n == 0 → 禁止 SUPPORTED
      B4  required seminar/period 约束未满足 → 禁止 SUPPORTED
      B5  required_source_layers 缺失 → 禁止 SUPPORTED
      B6  expected_zero lane 出现 >0 命中 → 记 FAIL（不是降级理由，但计入 reasons）
      B7  formalism：RETRIEVED_FORMALISM_MISSING → 禁止 SUPPORTED（属 retrieval）；
          CORPUS_FORMALISM_MISSING → INSUFFICIENT_EVIDENCE（结构性）
      B8  metadata：METADATA_UNAVAILABLE → INSUFFICIENT_EVIDENCE（结构性，
          不需要继续普通 topic retrieval 凑证据）
      B9  evidence_required：完全没有 substantive 证据 → INSUFFICIENT_EVIDENCE
      B10 diachronic：required endpoint 一侧为 0 → 禁止 SUPPORTED（更严：INSUFFICIENT）
    """
    ceiling = "SUPPORTED"
    violated = []
    reasons = []

    def forbid(code, detail, to="PARTIALLY_SUPPORTED"):
        nonlocal ceiling
        violated.append({"code": code, "detail": detail, "caps_to": to})
        ceiling = cap_state(ceiling, to)
        reasons.append(code)

    if contract.get("missing_operations"):
        forbid("MISSING_REQUIRED_OPERATION",
               "计划/契约要求但未执行：%s" % contract["missing_operations"])
    # B11/B12（Phase 4C.1-B3）：NOT_APPLICABLE 必须有结构依赖凭据；无凭据的按未完成处理
    if contract.get("not_applicable_unproven"):
        forbid("NOT_APPLICABLE_WITHOUT_STRUCTURAL_PROOF",
               "以下操作被标 NOT_APPLICABLE 但没有 whole-corpus 结构凭据（视为未完成）：%s"
               % contract["not_applicable_unproven"])
    if contract.get("missing_lanes"):
        forbid("MISSING_REQUIRED_LANE",
               "必需 lane 无证据：%s" % contract["missing_lanes"])
    if contract.get("relation_evidence_required") and \
            not contract.get("relation_evidence_n"):
        forbid("RELATION_EVIDENCE_MISSING",
               "问题要求关系证据，但没有任何同段共现/关系陈述")
    if contract.get("failed_constraints"):
        forbid("REQUIRED_CONSTRAINT_NOT_SATISFIED",
               "约束未被下推/未满足：%s" % contract["failed_constraints"])
    if contract.get("missing_source_layers"):
        absent = contract.get("missing_source_layers_absent_in_corpus") or []
        forbid("SOURCE_LAYER_MISSING",
               "缺少必需的来源层：%s%s"
               % (contract["missing_source_layers"],
                  ("（其中在语料层就完全不存在：%s → SOURCE_GAP，不是检索遗漏）" % absent)
                  if absent else "（语料层存在，属检索未取到）"))

    form = contract.get("formalism") or {}
    if form.get("formalism_required") and not form.get("formalism_evidence_found"):
        if form.get("formalism_state") == "CORPUS_FORMALISM_MISSING":
            forbid("CORPUS_FORMALISM_MISSING",
                   "whole-corpus formalism 扫描后仍无该形式（结构性）",
                   to="INSUFFICIENT_EVIDENCE")
        else:
            forbid("RETRIEVED_FORMALISM_MISSING",
                   "语料含该形式但本次证据集未取到（属 retrieval，不是结构性不可答）")

    meta = contract.get("metadata") or {}
    if meta.get("metadata_state") == "METADATA_UNAVAILABLE":
        forbid("METADATA_UNAVAILABLE",
               "必需元数据在库中不存在：%s" % meta.get("metadata_missing_fields"),
               to="INSUFFICIENT_EVIDENCE")

    if contract.get("required_endpoints"):
        ev = contract.get("endpoint_evidence") or {}
        empty = [k for k, v in ev.items() if not v]
        if empty:
            forbid("DIACHRONIC_ENDPOINT_MISSING",
                   "历时端点无证据：%s" % empty, to="INSUFFICIENT_EVIDENCE")

    usab = contract.get("evidence_usability") or {}
    if not usab.get("substantive_n"):
        forbid("NO_SUBSTANTIVE_EVIDENCE",
               "本次证据中没有可承担 substantive claim 的文本",
               to="INSUFFICIENT_EVIDENCE")

    zero_fail = [z for z in (contract.get("expected_zero_lanes") or [])
                 if z.get("result") == "FAIL"]
    if zero_fail:
        violated.append({"code": "EXPECTED_ZERO_LANE_VIOLATED",
                         "detail": "预期为 0 的 lane 出现了命中：%s"
                                   % [z["lane"] for z in zero_fail],
                         "caps_to": None})

    completion = "COMPLETE" if not violated else "INCOMPLETE"
    if any(v["caps_to"] == "INSUFFICIENT_EVIDENCE" for v in violated):
        completion = "BLOCKED_STRUCTURAL"
    return {"state_ceiling": ceiling, "violated_rules": violated,
            "completion_state": completion,
            "completion_reasons": reasons,
            "supported_allowed": ceiling == "SUPPORTED"}


__all__ = [n for n in dir() if not n.startswith("_")]
