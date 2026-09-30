#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gold_normalization.py — Phase 4C.1-A §A4：gold needle 匹配的**安全归一化**

问题（Phase 4C 人工评审实证）
─────────────────────────────
`build_research_tasks_v1.py` 的 v1 `squash()` 在归一化时**删除全部标点后去空白**：

    NFKC → 去撇号 → 去变音 → 删除所有非 word 字符 → 去空白 → lower

标点被「删除」而不是「变成边界」，于是原本分开的 token 会**粘成一个词**，
在语料里制造并不存在的命中。实测案例（Phase 4C Human Review）：

* `rt-J02` 的 lane `zh_frmi`：needle `frmi` 的 3 条「命中」全部来自 URL
  `http://perso.univ-rennes1.fr/michel.coste/…` —— 删标点后成为
  `…univrennes1frmichelcoste…`，其中 `fr`+`michel` 相邻成 `frmi`。**3/3 假阳性**。
* `objet, a fait des…` → `…aucunobjetafaitdes…` 含 `objeta`（`objet a` lane）
* `le « veau d'or » a une sorte` → `…leveaudoraunesorte…` 含 `dora`（`rt-E02`）
* `radicale, réelle ?` → `radicalereelle` 含 `lereel`（`le reel` lane）
* `pas-tout` / `pas tout`：这一条是**合法**的（连字符/空格变体应统一）

本模块的修复原则
────────────────
1. **标点是边界，不是删除对象**：任何非 word 字符都不会把两侧 token 粘起来。
2. **软分隔符**（空白、连字符/各类 dash、撇号）统一为 token 边界 —— 因此
   `plus-de-jouir` = `plus de jouir` = `plus de jouir`，与 v1 的设计意图一致。
3. **子句标点**（`, ; : . ! ? …`）切断可匹配区间 —— `objet, a` 不再匹配 `objet a`。
4. **CJK needle 允许「无空格连写」**：中文里 `对象a` / `对象 a` 必须都算命中，
   因此含 CJK 的 needle 额外允许在**同一子句区间内**按紧凑串匹配；
   拉丁 needle 一律要求 token 边界（这正是 `frmi` / `dora` 类假阳性的来源）。
5. v1 的 `squash()` **保持原样**（`research_tasks_v1.jsonl` 必须可复现），
   本模块只在**新**推导（gold lane audit / gold_v2）中使用。

用法
────
    from gold_normalization import token_spans_v2, contains_v2, squash_v1

    contains_v2("…univ-rennes1.fr/michel…", "frmi")   # False
    contains_v2("l'objet petit a", "objet petit a")   # True
    contains_v2("le « veau d'or » a une sorte", "dora")  # False
    contains_v2("对象a", "对象 a")                     # True
"""
from __future__ import annotations

import re
import unicodedata

# ── v1 语义（冻结）：从 spec 脚本导入，保证与 research_tasks_v1 逐字一致 ──────────
try:  # 正常路径：同目录工具
    from build_research_tasks_v1 import squash as squash_v1
except Exception:  # pragma: no cover - 兜底，语义与 v1 相同
    _APOS = re.compile(r"['’`]")
    _NONWORD = re.compile(r"[^\w\s]", re.UNICODE)

    def squash_v1(s):
        s = unicodedata.normalize("NFKC", str(s))
        s = _APOS.sub("", s)
        s = "".join(c for c in unicodedata.normalize("NFD", s)
                    if unicodedata.category(c) != "Mn")
        s = _NONWORD.sub("", s).lower()
        return re.sub(r"\s+", "", s)


# ── v2：token 边界安全归一化 ──────────────────────────────────────────────────
_CLAUSE = re.compile(r"[,;:.!?…]+")
_NONWORD = re.compile(r"[^\w]+", re.UNICODE)
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")

# 会被 v1 删除、从而可能把两侧 token 粘起来的字符（诊断用）
URLISH = re.compile(r"(?:https?://|www\.|\b[\w-]+\.(?:fr|com|org|net|edu|html?|jpe?g|png|pdf)\b)",
                    re.IGNORECASE)


def strip_marks(s) -> str:
    """NFKC + 去变音符（保留撇号与标点，供后续做边界判断）。"""
    s = unicodedata.normalize("NFKC", str(s))
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def token_chunks_v2(text):
    """→ [(chunk_raw, [token, …]), …]；子句标点处切断，其余标点作 token 边界。"""
    out = []
    for chunk in _CLAUSE.split(strip_marks(text)):
        toks = _NONWORD.sub(" ", chunk).lower().split()
        if toks:
            out.append((chunk, toks))
    return out


def needle_tokens_v2(needle):
    """needle 归一化为 token 序列（needle 内的标点一律视为边界）。"""
    toks = []
    for _chunk, tk in token_chunks_v2(needle):
        toks.extend(tk)
    return toks


def _is_cjk_needle(toks) -> bool:
    return any(_CJK.search(t) for t in toks)


def contains_v2(text, needle) -> bool:
    """needle 是否在 text 中命中，且**不跨 token 边界**。

    规则（写死，可复核）：
      * needle 归一化为 **1 个 token**（如 `frmi` / `désir` / `regard`）：
        合法命中 = 该 token 是**某一个** text token 的子串（保留 v1 的词形召回：
        `desir` ⊂ `desirs`），**不允许**跨两个 token 拼出来（`fr`+`michel` → `frmi`）。
      * needle 归一化为 **多个 token**（如 `objet petit a` / `le reel` / `plus de jouir`）：
        合法命中 = 这些 token 在**同一子句区间内**连续出现（`l'objet petit a` 命中
        `objet petit a`；`objet, a fait` 因 `,` 切断子句而**不**命中）。
      * 含 CJK 的 needle 额外允许同一子句区间内的紧凑串匹配（`对象a` = `对象 a`）。
    """
    nt = needle_tokens_v2(needle)
    if not nt:
        return False
    return contains_v2_prepared(precompute_v2(text), needle)


def contains_v2_prepared(prep, needle) -> bool:
    """与 `contains_v2` 同语义，但接受 `precompute_v2` 的产物。"""
    nt = needle_tokens_v2(needle)
    if not nt:
        return False
    chunks, compacts = prep
    if len(nt) == 1:
        t = nt[0]
        return any(t in tok for toks in chunks for tok in toks)
    cjk = _is_cjk_needle(nt)
    compact_needle = "".join(nt)
    n = len(nt)
    for i, toks in enumerate(chunks):
        for j in range(len(toks) - n + 1):
            if toks[j:j + n] == nt:
                return True
        if cjk and compact_needle in compacts[i]:
            return True
    return False


def match_positions_v1(text, needle):
    """v1 语义下的命中区间（在 squash 空间里），用于假阳性诊断。

    → [(start, end, raw_start, raw_end), …]；raw_* 是映射回原文的区间，
    可用于判断被 v1 删掉的是哪些字符。
    """
    import bisect
    s = unicodedata.normalize("NFKC", str(text))
    s = re.sub(r"['’`]", "", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    kept, idx = [], []
    for i, c in enumerate(s):
        if re.match(r"[\w\s]", c, re.UNICODE):
            kept.append(c)
            idx.append(i)
    squashed, mapping, buf = [], [], []
    for c, i in zip(kept, idx):
        if c.isspace():
            continue
        squashed.append(c.lower())
        mapping.append(i)
    squashed = "".join(squashed)
    sq_needle = squash_v1(needle)
    out = []
    if not sq_needle:
        return out
    start = squashed.find(sq_needle)
    while start != -1:
        end = start + len(sq_needle)
        out.append((start, end, mapping[start], mapping[end - 1]))
        start = squashed.find(sq_needle, start + 1)
    return out


def match_positions_v2(text, needle):
    """v2 语义下的命中区间（在原文里的字符区间），用于给出上下文。"""
    nt = needle_tokens_v2(needle)
    if not nt:
        return []
    cjk = _is_cjk_needle(nt)
    compact_needle = "".join(nt)
    out = []
    for chunk in _CLAUSE.split(strip_marks(text)):
        toks = [(m.group(0).lower(), m.start(), m.end())
                for m in re.finditer(r"[\w]+", chunk, re.UNICODE)]
        n = len(nt)
        for i in range(len(toks) - n + 1):
            if [t[0] for t in toks[i:i + n]] == nt:
                out.append((toks[i][1], toks[i + n - 1][2]))
        if cjk and toks:
            if compact_needle in "".join(t[0] for t in toks):
                out.append((toks[0][1], toks[-1][2]))
    return out


def _pieces(span):
    """把命中原文按「非 word 字符」切成片段（用于判断是不是跨 token 拼接）。"""
    return [p for p in re.split(r"[^\w]+", span, flags=re.UNICODE) if p]


def diagnose_v1_only_hit(raw_text, needle):
    """一条「v1 命中但 v2 不命中」的命中，为什么会发生？

    → dict(reason, deleted, pieces, raw_span, context)；reason ∈
      {url_join, clause_boundary_join, short_piece_join, punctuation_join, unknown}

    判定顺序（确定性，写死在这里，便于复核）：
      1. 命中原文或上下文像 URL/域名/文件名 → `url_join`（`rt-J02` 的 `frmi`）
      2. 被删掉的字符含子句标点 `, ; : . ! ? …` → `clause_boundary_join`
      3. 命中跨度里含空白（v1 去空白把两个词粘起来，如 `radicale réelle` → `lereel`）
         → `whitespace_boundary_join`
      4. 被删字符切出的片段全部 ≤2 字符 → `short_piece_join`（如 `d'or » a` → d/or/a）
      5. 其它（只跨引号/括号/撇号等） → `punctuation_join`（**保守**：留人工判断，
         因为 `objet (a)` 这类合法变体也走这条路）
    """
    for _s, _e, rs, re_ in match_positions_v1(raw_text, needle):
        span = raw_text[rs:re_ + 1]
        context = raw_text[max(0, rs - 40):re_ + 40]
        deleted = "".join(c for c in span if not re.match(r"[\w\s]", c, re.UNICODE))
        pieces = _pieces(span)
        base = {"deleted": deleted, "pieces": pieces[:6],
                "raw_span": span[:80], "context": context[:120]}
        if URLISH.search(span) or URLISH.search(context):
            return dict(base, reason="url_join")
        if any(c in ",;:.!?…" for c in deleted):
            return dict(base, reason="clause_boundary_join")
        if re.search(r"\s", span):
            # v1 去空白 → 两个词被粘起来（`fait des ironies` → `desir`；
            # `l'objet attirant` → `objeta`）。合法命中在 v2 里同样命中，不会被诊断到；
            # 因此出现在这里的空白一律是跨 token 拼接。
            return dict(base, reason="whitespace_boundary_join")
        if len(pieces) >= 2 and all(len(p) <= 2 for p in pieces):
            return dict(base, reason="short_piece_join")
        if deleted:
            return dict(base, reason="punctuation_join")
        # 兜底：把窗口左右各扩一个字符再看一次（映射可能恰好切掉了分隔符）
        wide = raw_text[max(0, rs - 2):re_ + 3]
        wide_deleted = "".join(c for c in wide if not re.match(r"[\w\s]", c, re.UNICODE))
        if any(c in ",;:.!?…" for c in wide_deleted):
            return dict(base, reason="clause_boundary_join")
        if re.search(r"\s", wide):
            return dict(base, reason="whitespace_boundary_join")
        if wide_deleted:
            return dict(base, reason="punctuation_join")
        return dict(base, reason="unknown")
    return {"reason": "unknown", "deleted": "", "pieces": [], "raw_span": "", "context": ""}


# 分类：哪些 reason 可以直接判为假阳性，哪些必须留人工
FALSE_POSITIVE_REASONS = ("url_join", "clause_boundary_join", "short_piece_join",
                          "whitespace_boundary_join")
MANUAL_REVIEW_REASONS = ("punctuation_join", "unknown")


# ── 纯符号 needle（如 `◊` / `S ◊ a` / `(S ◊ a)`）──────────────────────────
# 这类 needle 里的符号是**语义的一部分**，不能被当作 token 分隔符丢掉
# （否则 `S ◊ a` 会退化成 `s a` 两 token 序列，在 41k 段里假命中）。
_SOFT_CHARS = "-‐‑–—'’`"
SYMBOLIC = re.compile(r"[^\w\s%s]" % re.escape(_SOFT_CHARS), re.UNICODE)


def is_symbolic_needle(needle) -> bool:
    return bool(SYMBOLIC.search(strip_marks(str(needle))))


def symbolic_needle_regex(needle, relaxed=False):
    """把含符号的 needle 编译成「保留符号字面 + 允许软分隔」的正则。

    子句标点（`, ; : . ! ? …`）**不**在允许的软分隔里 → 仍不跨子句匹配。
    """
    parts = [p for p in re.split(r"\s+", strip_marks(str(needle)).strip()) if p]
    if not parts:
        return None
    sep_chars = list(_SOFT_CHARS) + ["(", ")", "[", "]", "{", "}", "\u00ab",
                                     "\u00bb", "\u201c", "\u201d", "/"]
    sep = "[" + re.escape("".join(sep_chars)) + r"\s" + "]" + ("*" if relaxed else "+")
    return re.compile(sep.join(re.escape(p) for p in parts), re.IGNORECASE)


def contains_v2_symbolic(text, needle) -> bool:
    rx = symbolic_needle_regex(needle)
    if rx is None:
        return False
    return bool(rx.search(strip_marks(str(text))))


def precompute_v2(text):
    """→ (chunks, compacts)：供批量审计复用，避免对同一段重复做正则。"""
    chunks = [toks for _c, toks in token_chunks_v2(text)]
    return chunks, ["".join(t) for t in chunks]


# `contains_v2_prepared` 定义在上面（与 `contains_v2` 同一实现）。


def prepare_needle(needle):
    """把 needle 预先编译成可复用的匹配结构（批量匹配时避免逐次正则）。"""
    if is_symbolic_needle(needle):
        return {"symbolic": True, "rx": symbolic_needle_regex(needle),
                "raw_forms": [strip_marks(str(needle))]}
    nt = needle_tokens_v2(needle)
    if not nt:
        return None
    return {"symbolic": False, "tokens": nt, "cjk": _is_cjk_needle(nt),
            "compact": "".join(nt)}


def contains_prepared(prep, pn, raw="") -> bool:
    """与 `contains_v2` 同语义，但两侧都已预编译（批量 lane 匹配用）。"""
    if not pn:
        return False
    if pn.get("symbolic"):
        rx = pn.get("rx")
        return bool(rx and rx.search(strip_marks(str(raw))))
    nt = pn["tokens"]
    chunks, compacts = prep
    if len(nt) == 1:
        t = nt[0]
        return any(t in tok for toks in chunks for tok in toks)
    n = len(nt)
    for i, toks in enumerate(chunks):
        for j in range(len(toks) - n + 1):
            if toks[j:j + n] == nt:
                return True
        if pn["cjk"] and pn["compact"] in compacts[i]:
            return True
    return False


__all__ = ["squash_v1", "strip_marks", "token_chunks_v2", "needle_tokens_v2",
           "is_symbolic_needle", "symbolic_needle_regex", "contains_v2_symbolic",
           "contains_v2", "precompute_v2", "contains_v2_prepared",
           "prepare_needle", "contains_prepared",
           "match_positions_v1", "match_positions_v2",
           "diagnose_v1_only_hit", "URLISH",
           "FALSE_POSITIVE_REASONS", "MANUAL_REVIEW_REASONS"]
