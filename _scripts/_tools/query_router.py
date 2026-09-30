#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
query_router.py — §5 Query Normalization / Router（deterministic first）

设计纪律（用户 §5）
───────────────────
> 优先 deterministic parsing。能够 deterministic 完成的工作不得强制交给 LLM。
> LLM query analyzer 只能作为可选 fallback。

因此本模块**纯规则**，不调用任何模型。它识别：

  * explicit seminar        研讨班 XI / S11 / Seminar 11 / 第十一期
  * explicit concept/entity 别名命中（走 alias index，含歧义暴露）
  * quoted phrase            "…" / “…” / 「…」
  * language                fr/en/zh（按字符谱 + 关键词）
  * source authority constr  primary / secondary / L1 / L2 …
  * historical period       1953–1955 / 早期 / Encore 时期 / S23 时期 …
  * case name               Schreber / 小汉斯 / Aimée …
  * topology / matheme      Borromean / 莫比乌斯 / S(Ⱥ) / objet a / 四种话语 …
  * source constraint       lacan.com / Freud / 二手

输出是一个**结构化 QueryPlan**，retrieval 各组件据此过滤与加权；
`--explain` 会把它原样展示出来，让检索可解释。
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# ---- 期号：S11 / 研讨班 11 / Seminar XI / 第十一期
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
          "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13,
          "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19,
          "xx": 20, "xxi": 21, "xxii": 22, "xxiii": 23, "xxiv": 24,
          "xxv": 25, "xxvi": 26, "xxvii": 27}
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
           "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13,
           "十四": 14, "十五": 15, "十六": 16, "十七": 17, "十八": 18,
           "十九": 19, "二十": 20, "二十一": 21, "二十二": 22, "二十三": 23}

# ---- 理论分期（映射到 Phase 1 的 concept_period 枚举）
PERIODS = [
    (re.compile(r"1953\s*[-–~]\s*1955|早期|罗马报告"), "1953-1955"),
    (re.compile(r"1955\s*[-–~]\s*1958|精神病时期|S3|第三期"), "1955-1958"),
    (re.compile(r"1959\s*[-–~]\s*1963|伦理学|S7|第七期"), "1959-1963"),
    (re.compile(r"1964\s*[-–~]\s*1966|四个基本概念|S11|第十一期"), "1964-1966"),
    (re.compile(r"1967\s*[-~–]\s*1971|四种话语|S17|第十七期"), "1967-1971"),
    (re.compile(r"1972\s*[-–~]\s*1973|Encore|S20|第二十期|性分化"), "1972-1973"),
    (re.compile(r"1974\s*[-–~]\s*1976|圣状|S23|第二十三期|波罗米|RSI"), "1974-1976"),
    (re.compile(r"1976\s*[-–~]\s*1981|晚期|结的拓扑"), "1976-1981"),
    (re.compile(r"pre[- ]?1953|1953\s*前"), "pre-1953"),
]

# ---- 拓扑 / 数学型 / 话语
TOPOLOGY = {
    "borromean": "topology.borromean-knot", "波罗米": "topology.borromean-knot",
    "borroméen": "topology.borromean-knot", "莫比乌斯": "topology.mobius-strip",
    "mobius": "topology.mobius-strip", "möbius": "topology.mobius-strip",
    "torus": "topology.torus", "环面": "topology.torus",
    "cross-cap": "topology.cross-cap", "crosscap": "topology.cross-cap",
    "十字帽": "topology.cross-cap",
}
DISCOURSE = {
    "四种话语": "discourse.four-discourses", "four discourses": "discourse.four-discourses",
    "分析家话语": "discourse.analyst", "analyst's discourse": "discourse.analyst",
    "主人话语": "discourse.master", "hysteric": "discourse.hysteric",
    "大学话语": "discourse.university",
}
MATHEME = {
    "objet a": "matheme.objet-a", "对象a": "matheme.objet-a",
    "s(Ⱥ)": "matheme.S-barred-A", "s(а̸)": "matheme.S-barred-A",
    "幻想公式": "formula.fantasy", "$◇a": "formula.fantasy",
    "性分化": "formula.sexuation", "sexuation": "formula.sexuation",
    "$<>a": "formula.fantasy",
}
# ---- 个案
CASES = {
    "schreber": "case.schreber", "施雷伯": "case.schreber",
    "小汉斯": "case.petit-hans", "petit hans": "case.petit-hans",
    "little hans": "case.petit-hans", "aimée": "case.aimee",
    "艾梅": "case.aimee", "狼人": "case.wolf-man", "wolf man": "case.wolf-man",
    "鼠人": "case.rat-man", "rat man": "case.rat-man",
    "朵拉": "case.dora", "dora": "case.dora",
    "布尔邦": "case.bourbon-brigitte",
}
# ---- 权威/来源约束
AUTHORITY_WORDS = {
    "primary": "L1", "一手": "L1", "原文": "L1", "原典": "L1",
    "secondary": "L2", "二手": "L2", "研究": "L2",
    "note": "L3", "笔记": "L3", "synthesis": "L4", "综合": "L4",
}
SOURCE_HINTS = {
    "freud": "freud", "弗洛伊德": "freud", "佛洛依德": "freud",
    "lacan.com": "lacan.com", "seminar": "seminar", "研讨班": "seminar",
    "écrits": "ecrits", "ecrits": "ecrits", "écrit": "ecrits",
}

_QUOTE_RE = re.compile(r'["“”「『]([^"“”」』]{2,})["“”」』]')


def _seminar_from(text):
    out = []
    m = re.search(r"研讨班\s*(\d{1,2})\s*期", text)
    if m:
        out.append(int(m.group(1)))
    # 「研讨班 XI」/「Seminar XI 期」这类**中文 + 罗马数字**写法（实测原先解析失败）
    # 「研讨班 11」/「研讨班11」这类**阿拉伯数字无「期」字**写法（实测原先失败）
    m = re.search(r"研讨班\s*(\d{1,2})(?![0-9])", text)
    if m:
        out.append(int(m.group(1)))
    # 罗马数字后可能直接接汉字（「研讨班XI里的…」），\b 在此不成立，故不用 \b
    m = re.search(r"研讨班\s*([IVXLC]{1,7})(?![A-Za-z])", text, re.I)
    if m:
        out.append(_ROMAN.get(m.group(1).lower()))
    m = re.search(r"第\s*([IVXLC]{1,7})\s*期", text, re.I)
    if m:
        out.append(_ROMAN.get(m.group(1).lower()))
    m = re.search(r"第([一二三四五六七八九十]+)期", text)
    if m:
        out.append(_CN_NUM.get(m.group(1)))
    m = re.search(r"\bS(\d{1,2})\b", text)
    if m:
        out.append(int(m.group(1)))
    m = re.search(r"[Ss]eminar\s*(?:of\s*Jacques\s*Lacan,?\s*)?(?:Book\s*)?"
                  r"([IVXLC]{1,7}|\d{1,2})\b", text)
    if m:
        t = m.group(1)
        out.append(int(t) if t.isdigit() else _ROMAN.get(t.lower()))
    # 去重并只保留 S1–S27
    return sorted({x for x in out if x and 1 <= x <= 27})


def route(query, llm_fallback=None):
    """把查询解析成结构化 QueryPlan。

    参数
    ----
    llm_fallback : 可选可调用对象 `f(query) -> dict`。
        **默认 None** —— 规则能做的绝不交给 LLM（用户 §5）。
        只有当调用方显式传入，且规则解析不出任何实体时，才会被调用，
        且其结果会被标注 `from_llm_fallback=True` 以便审计。
    """
    q = str(query or "").strip()
    plan = {
        "query": q,
        "intent": "unknown",
        "seminars": [],
        "entities": [],          # [{entity_id, matched_alias, ambiguous, ...}]
        "ambiguous_entities": [],
        "quoted_phrases": [],
        "language": None,
        "periods": [],
        "topology": [], "discourses": [], "mathemes": [], "cases": [],
        "authority": [],
        "source_hints": [],
        "filters": {},
        "from_llm_fallback": False,
    }
    if not q:
        return plan

    # ---- quoted phrases
    plan["quoted_phrases"] = [m.group(1).strip() for m in _QUOTE_RE.finditer(q)]

    # ---- language（字符谱）
    n_cjk = len(_CJK.findall(q))
    n_lat = len(re.findall(r"[A-Za-z]", q))
    if n_cjk and n_lat:
        plan["language"] = "mul"
    elif n_cjk:
        plan["language"] = "zh"
    elif n_lat:
        plan["language"] = "fr" if re.search(r"[àâäéèêëïîôöùûüÿçœæ]", q, re.I) else "en"

    # ---- seminars
    sems = _seminar_from(q)
    plan["seminars"] = ["seminar.S%02d" % s for s in sems]
    if sems:
        plan["filters"]["seminar_ids"] = plan["seminars"]

    # ---- entities via alias index（含歧义暴露）
    try:
        import alias_index
        seen = set()
        for tok in _candidate_aliases(q):
            for h in alias_index.exact_lookup(tok):
                key = (h["entity_id"], h["matched_alias"])
                if key in seen:
                    continue
                seen.add(key)
                # 单字符别名（如 concept.l-autre 的 `A`）不参与实体解析：
                # 实测它会让「含字母 A 的任意查询」都解析出该实体，
                # 实体数虚增 → intent 从 concept_lookup 误跳到 concept_relationship。
                import re as _re
                if len(_re.sub(r"\W", "", h["matched_alias"])) < 2:
                    continue
                rec = {"entity_id": h["entity_id"], "matched_alias": h["matched_alias"],
                       "exact_case": h["exact_case"], "match_type": h["match_type"],
                       "language": h["language"]}
                if h.get("ambiguous_with") or h.get("case_variant_of"):
                    rec["ambiguous_with"] = h.get("ambiguous_with") or []
                    rec["ambiguity_reason"] = h.get("ambiguity_reason")
                    if h.get("case_variant_of"):
                        rec["case_variant_of"] = h["case_variant_of"]
                    plan["ambiguous_entities"].append(rec)
                plan["entities"].append(rec)
    except Exception:
        pass

    # ---- periods
    for pat, period in PERIODS:
        if pat.search(q):
            plan["periods"].append(period)
    plan["periods"] = sorted(set(plan["periods"]))
    if plan["periods"]:
        plan["filters"]["periods"] = plan["periods"]

    # ---- topology / discourse / matheme / case
    low = q.lower()
    for table, key in ((TOPOLOGY, "topology"), (DISCOURSE, "discourses"),
                       (MATHEME, "mathemes"), (CASES, "cases")):
        for needle, eid in table.items():
            if needle.lower() in low:
                if eid not in plan[key]:
                    plan[key].append(eid)

    # ---- authority / source hints
    for w, lvl in AUTHORITY_WORDS.items():
        if w in low:
            plan["authority"].append(lvl)
    plan["authority"] = sorted(set(plan["authority"]))
    if plan["authority"]:
        plan["filters"]["authority_levels"] = plan["authority"]
    for w, hint in SOURCE_HINTS.items():
        if w in low:
            plan["source_hints"].append(hint)
    plan["source_hints"] = sorted(set(plan["source_hints"]))

    # ---- intent（确定性判定，顺序即优先级）
    #
    # 任务书 §2 要求评测集覆盖 13 类。原先 router 缺 philosophy_relation /
    # secondary_interpretation，且 translation_terminology 因判定顺序不可达
    # （entities 分支在前，任何含实体的译法问题都被 concept_lookup 吃掉）。
    # 这里补齐，并把译法/哲学/二手的判定**提到 entities 之前**。
    _low = q.lower()
    _TRANSL = ("翻译", "译法", "怎么译", "译成", "译作", "中译", "中文说法",
               "对应哪个法文", "which french word", "translation")
    _PHILO = ("黑格尔", "海德格尔", "笛卡尔", "康德", "kojeve", "kojève",
              "主奴", "我思", "尼采", "亚里士多德", "柏拉图", "哲学",
              "hegel", "heidegger", "descartes", "kant", "aristotle", "plato",
              "禅宗", "佛教", "道家", "庄子", "老子")
    _SECOND = ("miller", "米勒", "fink", "芬克", "soler", "索莱尔",
               "齐泽克", "zizek", "žizek", "maleval", "拉普朗什",
               "laplanche", "二手", "解读", "谁提出", "谁提出的", "学派")
    if any(w in q or w in _low for w in _TRANSL):
        plan["intent"] = "translation_terminology"
    elif any(w in q or w in _low for w in _PHILO):
        plan["intent"] = "philosophy_relation"
    elif any(w in q or w in _low for w in _SECOND):
        plan["intent"] = "secondary_interpretation"
    elif plan["quoted_phrases"]:
        plan["intent"] = "exact_quotation"
    elif plan["cases"]:
        plan["intent"] = "case_analysis"
    elif plan["topology"] or plan["mathemes"]:
        plan["intent"] = "topology_matheme"
    elif plan["discourses"]:
        plan["intent"] = "discourse"
    elif plan["periods"] and len(plan["entities"]) >= 1:
        plan["intent"] = "diachronic_concept"
    elif plan["seminars"] and plan["entities"]:
        plan["intent"] = "seminar_specific"
    elif len(plan["entities"]) >= 2:
        plan["intent"] = "concept_relationship"
    elif plan["entities"]:
        plan["intent"] = "concept_lookup"
    elif "freud" in low or "弗洛伊德" in q or "佛洛依德" in q:
        plan["intent"] = "freud_lacan_comparison"
    elif plan["language"] == "mul":
        plan["intent"] = "cross_language"

    # ---- 可选 LLM fallback（默认不启用）
    if plan["intent"] == "unknown" and not plan["entities"] and callable(llm_fallback):
        extra = llm_fallback(q) or {}
        if isinstance(extra, dict):
            for k in ("intent", "entities", "seminars"):
                if extra.get(k):
                    plan[k] = extra[k]
            plan["from_llm_fallback"] = True

    return plan


def _candidate_aliases(q):
    """从查询里切出可能的别名片段。

    做法：整句 + 2–4 词的连续片段（去标点）。不做语言相关的分词 ——
    这一步只要**召回候选**，精确性由 alias index 的精确匹配保证。
    """
    clean = re.sub(r'["“”「」『』，。！？、；：,\.!\?;:]', " ", q)
    toks = [t for t in re.split(r"\s+", clean) if t]
    cands = set()
    if clean.strip():
        cands.add(clean.strip())
        cands.add(clean.strip().lower())
    for n in (2, 3, 4):
        for i in range(len(toks) - n + 1):
            cands.add(" ".join(toks[i:i + n]))
    # 单 token 也加（中文别名常常没有空格）
    cands.update(toks)
    return sorted(cands, key=lambda x: (-len(x), x))


def explain(plan):
    """把 QueryPlan 渲染成人类可读的解释（供 CLI --explain）。"""
    L = ["QueryPlan:"]
    L.append("  intent          : %s" % plan["intent"])
    L.append("  language        : %s" % plan["language"])
    L.append("  seminars        : %s" % (plan["seminars"] or "—"))
    L.append("  periods         : %s" % (plan["periods"] or "—"))
    L.append("  quoted_phrases  : %s" % (plan["quoted_phrases"] or "—"))
    L.append("  entities        : %s" % (
        ", ".join("%s(%s)" % (e["entity_id"], e["matched_alias"])
                  for e in plan["entities"]) or "—"))
    if plan["ambiguous_entities"]:
        L.append("  ⚠ ambiguous     : %s" % ", ".join(
            "%s ← %s" % (e["matched_alias"], e.get("ambiguity_reason", ""))
            for e in plan["ambiguous_entities"]))
    for k in ("topology", "discourses", "mathemes", "cases"):
        if plan[k]:
            L.append("  %-15s : %s" % (k, plan[k]))
    L.append("  authority       : %s" % (plan["authority"] or "—"))
    L.append("  source_hints    : %s" % (plan["source_hints"] or "—"))
    L.append("  filters         : %s" % json.dumps(plan["filters"], ensure_ascii=False))
    if plan["from_llm_fallback"]:
        L.append("  ⚠ 使用了 LLM fallback（规则未解析出结果）")
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Query router 调试")
    ap.add_argument("query", nargs="+")
    args = ap.parse_args()
    print(explain(route(" ".join(args.query))))
