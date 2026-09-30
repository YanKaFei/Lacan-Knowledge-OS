#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_alias_index.py — §4 Terminology / Alias Index

职责
────
把 Gold Concept Set（53 条）与术语实体的**别名**抽出来，建一个独立索引：

    alias / language / entity_id / status / source / review_status
  + alias_folded（NFKC + casefold，用于大小写不敏感的候选召回）
  + canonical_form（该实体的规范拼写）
  + ambiguous_with（与哪些条目存在**有意义**的大小写碰撞）

核心纪律（用户 §4）
───────────────────
> 禁止未经 review 自动合并：Autre / autre，以及其他大小写或术语差异
> 具有理论意义的词。

拉康的 `l'Autre`（大他者）与 `l'autre`（小他者）是**两个概念**。大小写本身
携带理论差异，所以：

1. 索引**保留原文大小写**，同时另存 `alias_folded` 供折叠召回；
2. 折叠后碰撞时**不合并**，而是把候选全部返回并标 `ambiguous_with`；
3. 只有在「该写法的实际大小写**不同于**其所指实体的规范拼写」时才算**有意义**碰撞
   —— 否则只是同一实体的两种写法（`objet a` / `Objet a`），不算歧义。

产出（派生物，不进 git；manifest 进 git）
──────────────────────────────────────
    _data/index/alias_index.jsonl

用法
────
    python3 build_alias_index.py
    python3 build_alias_index.py --stamp
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from deterministic import add_stamp_flag  # noqa: E402

STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
OUT = os.path.join(IDX, "alias_index.jsonl")

# 大小写差异具有理论意义的已知组（人工登记，非自动推导）
# 依据：拉康用法中大小写区分概念本身（大他者/小他者）。
THEORY_BEARING_CASE = {
    "autre": "l'Autre（大他者）vs l'autre（小他者）：大小写区分概念，禁止折叠",
    "other": "the Other（大他者）vs the other（小他者）",
}


def fold(s):
    """NFKC + casefold —— 只用于**召回**，不用于存储。"""
    return unicodedata.normalize("NFKC", str(s)).casefold().strip()


_CJK = __import__("re").compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LATIN = __import__("re").compile(r"[A-Za-z]")


def detect_lang(text, fallback="und"):
    """按字符谱判定**这一条别名自己**的语言。

    为什么不能沿用 concept 的 language 字段：53 条 Gold Concept 的
    `language` 多是 `mul`（多语并列）。若把它当作别名的语言，就会把
    `对象a`（中文）与 `objet a`（法文）都标成 `mul` —— 实测踩过，
    语言分布直接变成 `{mul: 369}`，中文条目全部丢失可检索性。
    """
    t = str(text or "")
    if not t.strip():
        return fallback
    n_cjk = len(_CJK.findall(t))
    n_lat = len(_LATIN.findall(t))
    if n_cjk and n_lat:
        return "mul"
    if n_cjk:
        return "zh"
    if n_lat:
        return "und"      # 纯拉丁：不硬猜 fr/en（避免编造）
    return fallback


def load_jsonl(name):
    p = os.path.join(STORE, name)
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def build(stamp=False):
    os.makedirs(IDX, exist_ok=True)
    concepts = load_jsonl("concepts.jsonl")
    terms = load_jsonl("terms.jsonl") if os.path.isfile(
        os.path.join(STORE, "terms.jsonl")) else []

    rows = []

    def add(alias, entity_id, lang, source, canonical_form, status="candidate"):
        if not alias or not str(alias).strip():
            return
        a = str(alias).strip()
        rows.append({
            "alias": a,                       # 保留原文大小写
            "alias_folded": fold(a),          # 仅用于召回
            "language": lang or "und",
            "entity_id": entity_id,
            "entity_type": entity_id.split(".")[0],
            "canonical_form": canonical_form,  # 该实体的规范拼写
            "status": status,
            "source": source,
            "review_status": "candidate",      # 脚本推导，一律 candidate
            "schema_version": "1.0.0",
        })

    # ---- Gold Concept Set
    for c in concepts:
        cid = c["id"]
        canon = c.get("canonical_name") or c.get("title") or cid
        # 规范名本身
        add(canon, cid, detect_lang(canon), "concept.canonical_name", canon)
        # 三语字段
        for k, lang in (("fr", "fr"), ("en", "en"), ("zh", "zh")):
            v = c.get(k)
            if v:
                # en 字段可能是「a / b」形式的多写法
                for part in str(v).split("/"):
                    part = part.strip()
                    add(part, cid, detect_lang(part, lang), "concept.%s" % k, canon)
        # aliases
        for a in (c.get("aliases") or []):
            add(a, cid, detect_lang(a), "concept.aliases", canon)
        # 标题里的「xxx：yyy」形式，两半都收
        t = c.get("title") or ""
        if "：" in t:
            for part in t.split("："):
                part = part.strip()
                add(part, cid, detect_lang(part), "concept.title", canon)

    # ---- 术语实体（Phase 2 的 term.* 若有）
    for t in terms:
        tid = t["id"]
        canon = t.get("canonical_name") or tid
        add(canon, tid, detect_lang(canon), "term.canonical_name", canon)
        for a in (t.get("aliases") or []):
            add(a, tid, detect_lang(a), "term.aliases", canon)

    # ---- 去重（保持确定序）
    # 去重键含 entity_id：**不同实体**即使写法相同也各自保留（不合并）。
    # 同一实体同一写法的多条（来自不同 source 字段）只留一条。
    seen = set()
    uniq = []
    for r in sorted(rows, key=lambda x: (x["alias_folded"], x["alias"],
                                         x["entity_id"], x["source"])):
        # 去重键含 source：同一字符串可能来自 canonical_name / fr / en / zh
        # 等不同字段，其**语言归属与出处**不同，不能合并掉（实测踩过：
        # 只按 (alias, entity_id) 去重会把 zh 条目全部吃掉）。
        key = (fold(r["alias"]), r["entity_id"], r["source"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    # ---- 标记有意义的大小写碰撞
    by_folded = {}
    for r in uniq:
        by_folded.setdefault(r["alias_folded"], []).append(r)

    for folded, group in by_folded.items():
        # 折叠后指向多个**不同实体**才算候选碰撞
        ents = {r["entity_id"] for r in group}
        if len(ents) < 2:
            continue
        # 「有意义」= 至少一条的实际大小写不同于其自身实体的规范拼写
        meaningful = any(r["alias"] != r["canonical_form"] for r in group)
        theory = folded in THEORY_BEARING_CASE
        if not (meaningful or theory):
            continue
        for r in group:
            r["ambiguous_with"] = sorted(
                {x["alias"] for x in group if x["alias"] != r["alias"]})
            r["ambiguity_reason"] = THEORY_BEARING_CASE.get(
                folded, "折叠后大小写碰撞且写法与该实体规范拼写不同")

    # ---- 大小写敏感性标记
    #
    # 用户 §4 点名 Autre / autre：大小写携带理论差异（大他者 vs 小他者），
    # 实测语料**确实同时使用两者**（中译「大他者」2542 段 / 「小他者」279 段），
    # 而 Gold Concept Set 只收录了大他者一条（不凭空造小他者实体）。
    #
    # 处置：把这些词标为 case_sensitive。于是查询 `l'autre` 时，
    # 命中的 `l'Autre` **不会被当作 exact**，而是标 `case_variant_of` ——
    # 让人看见「你要的小他者，本库只有大他者」，而不是静默返回错的实体。
    import re as _re
    CASE_SENSITIVE_PATTERNS = [
        _re.compile(r"\bautre\b", _re.I),
        _re.compile(r"\bother\b", _re.I),
    ]

    def _is_case_sensitive(alias):
        return any(p.search(alias) for p in CASE_SENSITIVE_PATTERNS)

    for r in uniq:
        if _is_case_sensitive(r["alias"]):
            r["case_sensitive"] = True
            if r["alias"] != r["canonical_form"]:
                r["case_variant_of"] = r["canonical_form"]
                r["case_note"] = (
                    "该写法的大小写与所指实体的规范拼写不同。拉康用法中大小写"
                    "携带理论差异（大他者 l'Autre / 小他者 l'autre）—— "
                    "本库 Gold Concept Set 只收录了大他者，未凭空创建小他者。")
            if not r.get("ambiguity_reason"):
                r.setdefault("ambiguous_with", [])
                r["ambiguity_reason"] = (
                    "大小写理论词：语料同时使用大小写两种形式（中译「大他者」"
                    "2542 段 / 「小他者」279 段），禁止折叠合并")

    # ---- 跨实体同写法碰撞 → 暴露为**人工复核候选**，绝不自动合并（用户 §4）
    #
    # 实测有 9 个 alias 指向多个 concept，例如：
    #   parlêtre            → concept.etre-parlant + concept.parletre
    #   signifiant          → concept.le-symbolique + concept.signifiant
    #   sinthome / 圣状      → concept.sinthome + concept.symptome-sinthome
    #  实在界 / 想象界       → concept.le-reel / l-imaginaire + RSI 合并卡
    # 这些看起来像是**目录里本身就有重复实体**，但要由人判定，不能由脚本合并。
    collisions = []
    by_alias = {}
    for r in uniq:
        by_alias.setdefault(fold(r["alias"]), set()).add(r["entity_id"])
    for folded, ents in sorted(by_alias.items()):
        if len(ents) < 2:
            continue
        forms = sorted({r["alias"] for r in uniq if fold(r["alias"]) == folded})
        collisions.append({
            "alias_folded": folded,
            "alias_forms": forms,
            "entity_ids": sorted(ents),
            "kind": "same_alias_multiple_entities",
            "review_status": "candidate",
            "action": "REVIEW_MANUALLY — 禁止自动合并（用户 §4）",
            "note": ("同一写法指向多个实体。可能是目录里本身有重复实体，"
                     "需要人工判定是否合并；脚本不做任何合并。"),
        })
        # 同时在索引条目上标出来，让查询时可见
        for r in uniq:
            if fold(r["alias"]) == folded:
                r.setdefault("ambiguous_with", [])
                for x in sorted({y["alias"] for y in uniq
                                 if fold(y["alias"]) == folded and
                                 y["entity_id"] != r["entity_id"]}):
                    if x not in r["ambiguous_with"]:
                        r["ambiguous_with"].append(x)
                r["ambiguity_reason"] = r.get("ambiguity_reason") or (
                    "同一写法指向多个实体（%d 个），需人工复核" % len(ents))

    col_path = os.path.join(IDX, "alias_collisions.jsonl")
    with open(col_path, "w", encoding="utf-8") as f:
        for c in collisions:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")

    with open(OUT, "w", encoding="utf-8") as f:
        for r in uniq:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    n_amb = sum(1 for r in uniq if r.get("ambiguous_with"))
    return {"aliases": len(uniq), "entities": len({r["entity_id"] for r in uniq}),
            "ambiguous": n_amb, "collisions": len(collisions),
            "out": OUT, "collisions_out": col_path}


def main():
    ap = argparse.ArgumentParser(description="建立 alias index（§4）")
    ap.add_argument("--quiet", action="store_true")
    add_stamp_flag(ap)
    args = ap.parse_args()
    m = build(stamp=args.stamp)
    if not args.quiet:
        print(f"[alias] aliases={m['aliases']} entities={m['entities']} "
              f"ambiguous={m['ambiguous']} 跨实体碰撞={m['collisions']}（待人工复核）",
              file=sys.stderr)
        print(f"[alias] -> {m['out']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
