#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
query_terms.py — Phase 4A 访问层的**确定性查询词规划**

它为什么必须存在（实测教训，不是设计偏好）
────────────────────────────────────────────
Phase 3 的词法层是**由紧到松**的：

* 中文：整段 query 切成 bigram 再做**短语**匹配
  （`syntax_variants` 的第一档 `"如何 何讨 讨论 论凝 凝视"`）；
* 法文：所有 token 做 **AND**。

MCP 的调用方是 DSH / Codex / 人，送进来的是**自然语言**：

| query | 直接送进词法层 | 语料里的真实情况 |
|---|---|---|
| `如何讨论凝视` | **0 命中** | 含「凝视」的段 **341** 段，S11 内 **93** 段 |
| `jouissance 在研讨班七期` | **0 命中**（`在研讨班七期` AND 掉了法文侧） | S07 内 jouissance **7+** 段 |
| `Seminar XI 如何讨论 gaze？` | **0 命中** | 全库 `gaze` **7** 段（S11 内 **0**） |

所以访问层必须自己做一步规划，否则「检索不到」会被误当成「知识库没有」——
那是本相位最不能犯的错（§7：判断的是**知识库是否支持这次研究操作**，
而不是「某一条字符串能不能命中」）。

规划是**确定性**的，只有三步
────────────────────────────
1. 删掉疑问/功能片段（`QUESTION_FRAGMENTS`）与期号写法；
2. 从**知识库自己的别名表**里找出问题中真实出现的别名（`alias_terms`）——
   `objet a` / `the Symbolic` / `l'Autre` 这类多词写法，任何正则都切不干净，
   而知识库里本来就有这些别名，用它们才是**结构性**的（不猜、不翻译）；
3. 把候选词**逐个探测**是否在语料词表里（`probe_terms`），
   只用真实存在的词重查；探测不到的词如实报为「语料无词法证据」。

不做什么
────────
* 不做机器翻译（§18 属于 Terminology Bridge 的职权，且只走 `equivalent`）；
* 不猜同义词；
* 不改 Phase 3 的 `lacan_search` / `syntax_variants` 行为 ——
  规划只发生在**调用之前**，Phase 3 的数字因此仍可复现。
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, TOOLS)

CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]{2,}")

# ── 疑问 / 功能片段：在切词**之前**整段删除 ───────────────────────────────
# 为什么整段删而不是放进 STOP：CJK 是按「连续汉字片段」切的，
# `desire 和 demand 有什么区别` 会切出一个 5 字片段「有什么区别」。
# 第一版就是把它当成了显著词，最后成了对比 lane 的名字 ——
# 实测输出 `lane「有什么区别」证据数 = 0`，两侧对比变成一侧独白。
QUESTION_FRAGMENTS = (
    "有什么区别和联系", "有什么区别", "有何区别", "差异是什么", "是什么关系",
    "的关系是什么", "的关系", "是什么意思", "是什么", "什么是", "怎么样",
    "如何讨论", "如何理解", "怎么理解", "怎么说", "是如何", "为什么",
    "有哪些", "请问", "请说明", "请解释", "介绍一下", "讲讲", "谈谈",
    "如何", "怎么", "区别", "差异", "对比", "比较", "不同",
    # Phase 4B 实测补充：研究问题里常见但无检索价值的片段
    "到底", "究竟", "所谓", "所谓的", "指的是", "意味着", "意味着什么",
    "请给出", "请说明", "请区分", "三者", "哪些阶段", "发生了什么变化",
)

# ── 单字/单词级停用词 ────────────────────────────────────────────────────
STOP = {
    # 中文功能词
    "在", "的", "和", "与", "及", "里", "中", "对", "从", "到", "了", "吗", "呢",
    "是", "有", "他", "她", "它", "这", "那", "个", "些", "为", "被", "把",
    # 英文
    "the", "and", "or", "not", "what", "how", "why", "is", "are", "was", "were",
    "of", "in", "on", "to", "for", "from", "with", "between", "about", "does",
    "do", "did", "mean", "means", "meaning", "difference", "differences",
    "versus", "vs", "a", "an", "say", "says", "said", "work", "works",
    # 法文
    "quelle", "quel", "comment", "pourquoi", "est", "ce", "que", "qui", "dans",
    "difference", "différence", "entre", "et", "ou", "le", "la", "les", "un",
    "une", "des", "du", "au", "aux", "il", "elle", "on", "nous", "vous", "ils",
    "sont", "etre", "être", "avoir", "fait", "faire", "dit", "dire", "selon",
    "chez", "aussi", "meme", "même", "bien", "peut", "doit", "plus", "tout",
    "pas", "ne", "sur", "avec", "sans", "mais", "donc", "car", "son", "sa",
    "ses", "cette",
    # Phase 4C 实测补充：中文动词/元词 —— 它们不是内容词，却会和主题词并列进入
    # 「辨别性术语」集合，把主题词淹掉（实测 rt-J02 的 `看待` 命中 140 段，
    # 而真正的主题词 `fMRI` = 0 段）。
    "看待", "认为", "提出", "理解", "处理", "回答", "讨论", "说明", "涉及",
    "形成", "构成", "变化", "影响", "作用", "意义", "内容", "研究", "理论",
    "概念", "术语", "问题", "方面", "情况", "过程", "方式", "结果", "部分",
    "阶段", "角色", "功能", "位置", "区别", "关系", "比较", "分析",
    # 期号语境词（期号本身由 router / `seminar_hint` 处理）
    "seminar", "séminaire", "seminaire", "seance", "séance", "lesson", "研讨班",
    "期", "课程", "讲座",
}

# ── 冠词/限定词：别名归一化用（只用于**匹配**，不用于改写 query）──────────
# `the Symbolic`（概念卡上的 en 写法）在词表里，而用户写的是 `Symbolic`。
# 这是**写法差异**，不是语义猜测 —— 归一化后精确相等才算命中。
DETERMINERS = ("the ", "a ", "an ", "le ", "la ", "les ", "l ", "un ", "une ",
               "des ", "du ", "der ", "die ", "das ", "el ", "los ", "las ")

_SEM_PATTERNS = (
    re.compile(r"研讨班\s*[一二三四五六七八九十]+期"),
    re.compile(r"第\s*[一二三四五六七八九十]+期"),
    re.compile(r"\bSeminar\s+[IVXLC]+\b", re.I),
    re.compile(r"\bS\s?\d{1,2}\b"),
)

_ALIAS_CACHE = None


def _fold(s):
    """与 `entity_resolution.fold` 保持**同一套**归一化（不另立规矩）。"""
    import entity_resolution as er
    return er.fold(s)


def strip_fragments(query):
    """删掉疑问/功能片段与期号写法，返回**只剩内容**的字符串。"""
    q = query or ""
    for pat in _SEM_PATTERNS:
        q = pat.sub(" ", q)
    for frag in QUESTION_FRAGMENTS:
        q = q.replace(frag, " ")
    return q


def _alias_rows():
    global _ALIAS_CACHE
    if _ALIAS_CACHE is None:
        try:
            import entity_resolution as er
            _ALIAS_CACHE = er._rows_cached()
        except Exception:
            _ALIAS_CACHE = []
    return _ALIAS_CACHE


def alias_terms(query, limit=4):
    """问题里**真实出现**的知识库别名（最长优先）—— 结构性，不靠启发式。"""
    if not query:
        return []
    rows = _alias_rows()
    if not rows:
        return []
    fq = _fold(query)
    packed = fq.replace(" ", "")
    out = []
    for r in rows:
        fa = r.get("folded") or ""
        if len(fa) < 3:
            continue
        if r.get("is_cjk"):
            if fa.replace(" ", "") in packed:
                out.append(r["alias"])
        elif re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(fa), fq):
            out.append(r["alias"])
    # rows 已按「最长优先」排序；这里再去重保序
    return list(dict.fromkeys(out))[:limit]


def salient_terms(query, limit=8):
    """值得去解析的词：别名（多词优先）+ CJK 片段 + 拉丁词。"""
    q = strip_fragments(query)
    terms = alias_terms(query)
    for m in re.finditer(r"[\u4e00-\u9fff]{2,}", q):
        t = m.group(0).strip()
        if len(t) >= 2 and t not in STOP:
            terms.append(t)
    for m in LATIN.finditer(q):
        t = m.group(0)
        if t.lower() not in STOP:
            terms.append(t)
    return list(dict.fromkeys(terms))[:limit]


def probe_term(term, language=None):
    """该词在**语料词法索引**里是否有命中（有 = 词表里真实存在）。

    这是知识库事实的读取，不是启发式判断；探测成本是一次 FTS 小查询。
    """
    if not term or not str(term).strip():
        return 0
    try:
        import lacan_search
        hits = lacan_search.lexical_search(str(term), language=language, limit=1)
        return len(hits)
    except Exception:
        return -1          # 索引不可用 → 由调用方按「未知」处理，不当作 0


def probe_terms(terms, language=None):
    """→ (known, unknown)：保持原顺序。探测失败（索引不可用）时返回 ([], [])."""
    known, unknown = [], []
    for t in terms or []:
        n = probe_term(t, language=language)
        if n == 0:
            unknown.append(t)
        elif n > 0:
            known.append(t)
    return known, unknown


def determiners_stripped(form):
    """去掉开头的冠词/限定词（归一化后比较，不改写原 query）。"""
    f = _fold(form)
    out = [f]
    for d in DETERMINERS:
        if f.startswith(d):
            out.append(f[len(d):].strip())
    return [x for x in out if x]


def normalized_alias_match(term):
    """在别名表里找与 `term` **冠词归一化后精确相等**的别名。

    → [{"alias", "entity_id", "entity_type"}]，最长别名优先。
    只做确定性归一化匹配，不做相似度、不做翻译。

    ⚠️ 归一化必须**两侧都做**：概念卡上的 en 写法是 `the Symbolic`，
    用户写 `Symbolic` —— 只剥 query 一侧永远匹配不上（第一版就是这个 bug，
    实测 `Symbolic` 仍然 UNRESOLVED）。
    """
    f = _fold(term)
    if not f or CJK.search(f):
        return []
    cands = set(determiners_stripped(term))          # 含 f 本身
    out, seen = [], set()
    for r in _alias_rows():
        if r.get("is_cjk"):
            continue
        fa = r.get("folded") or ""
        # `determiners_stripped` 的结果**总包含** fa 本身，所以一个条件就够
        if fa and set(determiners_stripped(fa)) & cands:
            key = (r["entity_id"], r["alias"])
            if key in seen:
                continue          # ⚠️ alias_index 里有**重复行**（同一 alias+entity），
                seen.add(key)     #    不去重会让「一个实体」被算成两个候选
            out.append({"alias": r["alias"], "entity_id": r["entity_id"],
                        "entity_type": r.get("entity_type")})
    return out
