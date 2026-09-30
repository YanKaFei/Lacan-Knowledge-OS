#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
citations.py — Phase 4A §14/§15 Citation Contract 的**可执行**版本

§14 要求「核心理论 claim 尽量引用 Passage ID」，§15 要求区分
primary / secondary / agent synthesis，§17 要求能统计
`citation validity` 与 `unsupported claim rate`。

要把这些变成**可测量**的东西，必须能把一段文字里的引用抽出来、逐个核对。
本模块做这件事，全部是确定性规则（**没有 LLM 判断**）：

    extract_citations(text)       → [{"raw","passage_id","seminar"}]
    validate(text_or_ids)         → {valid, invalid, fabricated}
    classify_support(id)          → primary / secondary / recovered_translation
    unsupported_claim_rate(text)  → 启发式，**明确标注是启发式**

诚实边界
────────
* 「claim」的切分是**句子级启发式**，不是语义理解。它只能发现
  「这句话里一个引用都没有」这种明显情况，不能判断引用是否**真的**支持该断言。
* 因此本模块产出的是**下界**指标：unsupported_claim_rate 高 = 一定有问题；
  低 **不**代表每条断言都有据。
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(TOOLS))
CACHE = {"ids": None}

# [S11 / passage.S11.unknown.L09.P0123]  /  passage.S11....  /  【S11 / passage...】
CITE_RE = re.compile(r"passage\.[A-Za-z0-9][A-Za-z0-9.\-]*")
SEM_RE = re.compile(r"\bS(\d{1,2}[A-Z]?)\b")

# 「理论性断言」的启发式标记（中文 + 法文/英文词）
CLAIM_MARKERS = (
    "是", "即", "意味着", "指的是", "表明", "说明", "构成", "来自", "源于",
    "区分", "对立", "等同", "等于", "功能", "作用", "结构", "机制",
    "est", "signifie", "désigne", "consiste", "constitue", "distingue",
    "means", "refers", "consists",
)
# 明显不是断言的句子（问句、过渡句、表格行）
NON_CLAIM_RE = re.compile(r"^[\s\-*#>|]|^[（(]|^\|")


def _passage_ids():
    if CACHE["ids"] is None:
        import sqlite3
        con = sqlite3.connect(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
        try:
            CACHE["ids"] = {r[0]: r[1] for r in con.execute(
                "SELECT id, language FROM passage_meta")}
        finally:
            con.close()
    return CACHE["ids"]


def extract_citations(text):
    """抽出所有 passage 引用。返回 [{raw, passage_id, seminar, valid}]。"""
    ids = _passage_ids()
    out, seen = [], set()
    for m in CITE_RE.finditer(text or ""):
        raw = m.group(0).rstrip(".。，,;；)")
        if raw in seen:
            continue
        seen.add(raw)
        parts = raw.split(".")
        sem = parts[1] if len(parts) > 1 and parts[1].startswith("S") else None
        out.append({"raw": raw, "passage_id": raw,
                    "seminar": ("seminar." + sem) if sem else None,
                    "valid": raw in ids})
    return out


def validate(text_or_ids):
    """→ {valid, invalid, fabricated, citation_validity}"""
    if isinstance(text_or_ids, str):
        cites = extract_citations(text_or_ids)
    else:
        ids = _passage_ids()
        cites = [{"raw": i, "passage_id": i, "valid": i in ids} for i in text_or_ids]
    valid = [c for c in cites if c["valid"]]
    invalid = [c for c in cites if not c["valid"]]
    n = len(cites)
    return {
        "citations": cites,
        "valid_n": len(valid),
        "invalid_n": len(invalid),
        "fabricated": [c["passage_id"] for c in invalid],
        "citation_validity": (len(valid) / n) if n else None,
    }


# §15：引用层级必须**显式**区分这三类，且分不开时不许猜。
# L0 RAW / L1 PRIMARY / L2 SECONDARY 是**源**；
# L3 RESEARCH NOTE / L4 AI SYNTHESIS 是**人/AI 写的东西** ——
# 它们可以被引用，但绝不能被当成 source（更不能晋级 canonical）。
SUPPORT_LEVELS = ("primary", "secondary", "secondary_recovered_translation",
                  "research_note", "agent_synthesis", "unknown")
AUTHORITY_TO_LEVEL = {"L3": "research_note", "L4": "agent_synthesis"}


def classify_support(passage_id):
    """证据层级：primary（L1 法文原文）/ secondary（L2 中译·二手）/
    research_note（L3 研究笔记）/ agent_synthesis（L4 AI 生成）/ unknown。

    `agent_synthesis` 单列的理由（§15）：AI 生成物必须一眼可辨 ——
    否则它会在下游被当成 source 引用，而那是本系统最不能犯的错。
    """
    import sqlite3
    con = sqlite3.connect(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
    try:
        row = con.execute("SELECT language, authority_level, text_role, trace_status "
                          "FROM passage_meta WHERE id=?", (passage_id,)).fetchone()
    finally:
        con.close()
    if not row:
        return {"passage_id": passage_id, "level": "unknown", "exists": False}
    lang, auth, role, trace = row
    if auth in AUTHORITY_TO_LEVEL:
        # L3/L4 优先判定：它们是**非源**层级，语言/角色不该改变这个事实
        level = AUTHORITY_TO_LEVEL[auth]
    elif auth == "L1" and lang == "fr":
        level = "primary"
    elif auth == "L2" or lang == "zh" or role == "translation":
        level = "secondary_recovered_translation" if trace == "SOURCE_TRACE_INCOMPLETE" \
            else "secondary"
    else:
        level = "unknown"
    warn = None
    if trace == "SOURCE_TRACE_INCOMPLETE":
        warn = ("SOURCE_TRACE_INCOMPLETE —— 引用时必须保留该告警，"
                "不得伪装成已闭合的 primary source")
    if level in ("agent_synthesis", "research_note"):
        warn = ("非源层级（%s）：可以引用，但**不得**当作 source，"
                "也不得据此声称「拉康原文说」" % auth)
    return {"passage_id": passage_id, "level": level, "exists": True,
            "language": lang, "authority_level": auth, "text_role": role,
            "trace_status": trace, "is_source": level in ("primary", "secondary",
                                                          "secondary_recovered_translation"),
            "warning": warn}


def split_claims(text):
    """句子级切分 → [{text, has_citation, theoryish}]。启发式，非语义理解。"""
    claims = []
    for raw in re.split(r"(?<=[。！？!?；;])\s*|\n+", text or ""):
        s = raw.strip()
        if not s or len(s) < 6 or NON_CLAIM_RE.match(s):
            continue
        theoryish = any(mk in s for mk in CLAIM_MARKERS)
        claims.append({"text": s, "has_citation": bool(CITE_RE.search(s)),
                       "theoryish": theoryish})
    return claims


def unsupported_claim_rate(text):
    """理论性断言里**完全没有引用**的比例。**下界指标**（见模块说明）。"""
    claims = split_claims(text)
    th = [c for c in claims if c["theoryish"]]
    bad = [c for c in th if not c["has_citation"]]
    return {
        "claims_total": len(claims),
        "theoryish_claims": len(th),
        "theoryish_without_citation": len(bad),
        "unsupported_claim_rate": (len(bad) / len(th)) if th else None,
        "examples": [c["text"][:120] for c in bad[:5]],
        "method": "sentence_level_heuristic",
        "caveat": ("启发式下界：高 = 一定有问题；低 **不** 代表每条断言都有据。"
                   "它不判断引用是否真的支持该断言。"),
    }


def citation_report(text):
    v = validate(text)
    levels = {}
    for c in v["citations"]:
        if c["valid"]:
            lv = classify_support(c["passage_id"])["level"]
            levels[lv] = levels.get(lv, 0) + 1
    return {"citation_validity": v["citation_validity"],
            "valid_n": v["valid_n"], "invalid_n": v["invalid_n"],
            "fabricated": v["fabricated"],
            "support_levels": levels,
            "has_primary": bool(levels.get("primary")),
            "has_recovered_secondary": bool(levels.get("secondary_recovered_translation")),
            "unsupported": unsupported_claim_rate(text)}


if __name__ == "__main__":
    print(json.dumps(citation_report(sys.stdin.read()), ensure_ascii=False, indent=1))
