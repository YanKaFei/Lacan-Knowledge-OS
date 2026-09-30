#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ontology_v4a1.py — Phase 4A.1 版本化本体层的**加载器 + 解析包装 + 缺陷重分类**

它在两层之间做什么
──────────────────
```
Phase 3 层（**一行不改**）                Phase 4A.1 叠加层（本模块）
  entity_resolution.resolve()   ──┐
  terminology_bridge            ──┤──► ontology_v4a1.resolve()      → 访问层
  lacanian_semantic_guard       ──┘    ontology_v4a1.terminology_lookup()
                                       ontology_v4a1.guard_view()
```

为什么是**包装**而不是改 Phase 3
────────────────────────────────
Phase 3 的 resolver/bridge/guard 是历史 benchmark 的测量对象：
改它们等于让 3A/3B/3C 的数字失效。所以本层：

* **不动** `entity_resolution.py` / `terminology_bridge.jsonl` / `lacanian_semantic_guard.py`
  的任何行为；
* 修复只在**合并读取**时生效：新实体、上下文策略、旧 id 的后继优先，
  全部由本模块在 Phase 3 结果之上叠加；
* 因此「修复前 / 修复后」可以在同一份数据上并列展示（`guard_view()`），
  而不是靠覆盖旧结果。

三条硬规则
──────────
1. **后继优先**：`concept.l-autre` 与后继实体持有同一别名时，解析结果只保留后继，
   旧实体降为审计记录（`superseded_notes`），**不删除**。
2. **上下文受限的别名不得静默解析**：`regard` / `autre` / `moi` / `demande` / `besoin` /
   `signifie` 命中但上下文不满足时 → `AMBIGUOUS` + `context_required: true`。
3. **单字符别名不参与解析**：沿用 Phase 3 的 guard（`query_router.py:201`），
   本层把它显式写进实体声明（`single_char_aliases_excluded`）。

用法
────
    import ontology_v4a1 as onto
    onto.resolve("regard")                    # → AMBIGUOUS + context_required
    onto.resolve("regard", context="凝视")     # → RESOLVED concept.gaze
    onto.entities(); onto.entity("concept.gaze")
    onto.terminology_lookup("regard")
    onto.guard_view()                          # 缺陷重分类（修复前/后并列）
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
LAYER = os.path.join(VAULT, "_data", "ontology", "v4a1")
sys.path.insert(0, HERE)

LAYER_ID = "ontology.v4a1"

_APOS = re.compile(r"['’`]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)
_MIN_CJK = 2
_MIN_LATIN = 3

_CACHE = {}


def fold(s):
    """与 `entity_resolution.fold` 同一套归一化（不另立规矩）。"""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s.lower()).strip()


def _read(name, default=None):
    p = os.path.join(LAYER, name)
    if not os.path.isfile(p):
        return default
    if name.endswith(".jsonl"):
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def reload():
    _CACHE.clear()
    return load()


def load():
    if _CACHE:
        return _CACHE
    _CACHE.update({
        "entities": _read("entities.jsonl", []) or [],
        "evidence": _read("evidence.jsonl", []) or [],
        "mappings": _read("term_mappings.jsonl", []) or [],
        "relations": _read("relations.jsonl", []) or [],
        "migrations": _read("migrations.jsonl", []) or [],
        "vocabulary": _read("vocabulary.json", {}) or {},
        "manifest": _read("MANIFEST.json", {}) or {},
    })
    return _CACHE


def available():
    return bool(load()["entities"])


def layer_meta():
    m = load()["manifest"]
    return {"layer_id": LAYER_ID, "resolution_ref": m.get("resolution_ref"),
            "content_hash": m.get("content_hash"),
            "entity_count": len(load()["entities"]),
            "gold_concepts_untouched": m.get("gold_concepts_untouched", True)}


# ─────────────────────────────────────────────── 实体与别名

def entities():
    return load()["entities"]


def entity(eid):
    for e in load()["entities"]:
        if e["id"] == eid:
            return e
    return None


def entity_ids():
    return [e["id"] for e in load()["entities"]]


_GOLD = None


def gold_concept(eid):
    """Gold Concept Set（53）里的概念行 —— **只读**，本层从不修改它。

    为什么这里要读 gold：规范名精确匹配消歧必须能查到 gold 实体的规范名
    （`concept.signifiant` 是 gold，不在叠加层里）。
    """
    global _GOLD
    if _GOLD is None:
        _GOLD = {}
        p = os.path.join(VAULT, "_data", "passage_store", "concepts.jsonl")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        c = json.loads(line)
                        _GOLD[c["id"]] = c
    return _GOLD.get(eid)


def entity_forms(eid):
    """该实体可用于「规范名精确匹配」的形式（叠加实体 ∪ Gold 概念）。"""
    out = []
    e = entity(eid)
    if e:
        out += [e.get("canonical_name"), e.get("fr"), e.get("en"), e.get("zh")]
    g = gold_concept(eid)
    if g:
        out += [g.get("canonical_name"), g.get("fr"), g.get("en"), g.get("zh")]
    return [x for x in out if x]


def _context_rule_for_alias(e, alias):
    """从 entity 的 context_required_aliases 取上下文规则（规则本体在 spec 的 context_rules）。

    这里把「哪个别名需要上下文」与「需要什么上下文」分开存：
    前者在实体上（可读），后者在映射/裸形策略里（可复用）。
    """
    if alias in (e.get("context_required_aliases") or []):
        return e, True
    return e, False


def form_norm(s):
    """**保留大小写与变音**的规范化（NFKC + 撇号统一 + 空白折叠）。

    与 `fold()` 的分工：
      * `form_norm` 用于**理论相关**的形式（大小写/变音携带差异）；
      * `fold()` 仍用于宽松召回（`entity_resolution` 的既有行为）。
    """
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _APOS.sub("'", s)
    return re.sub(r"\s+", " ", s).strip()


def _alias_tables():
    """→ (exact, folded, ctx_exact, ctx_folded, excludes)

    `exact` / `ctx_*` 的键是 `form_norm(alias)`（**保留大小写与变音**）；
    `folded` / `ctx_folded` 的键是 `fold(alias)`，仅作兜底。
    单字符别名不进任何表（沿用 Phase 3 的 guard）。
    """
    exact, folded, cexact, cfolded, excludes = {}, {}, {}, {}, {}
    for e in load()["entities"]:
        eid = e["id"]
        excl = {fold(x) for x in (e.get("single_char_aliases_excluded") or [])}
        ctx_aliases = {form_norm(x) for x in (e.get("context_required_aliases") or [])}
        excludes[eid] = [form_norm(x) for x in (e.get("alias_exclude_forms") or [])]
        for a in e.get("aliases") or []:
            fa, fn = fold(a), form_norm(a)
            if not fa or fa in excl:
                continue
            if len(fa.replace(" ", "")) < _MIN_CJK if re.search(r"[\u4e00-\u9fff]", fa) \
                    else len(fa) < _MIN_LATIN:
                continue
            t_ex, t_fd = (cexact, cfolded) if fn in ctx_aliases else (exact, folded)
            t_ex.setdefault(fn, [])
            t_fd.setdefault(fa, [])
            if eid not in t_ex[fn]:
                t_ex[fn].append(eid)
            if eid not in t_fd[fa]:
                t_fd[fa].append(eid)
    return exact, folded, cexact, cfolded, excludes


def alias_table():
    """兼容旧调用：→ (unambiguous_folded, context_required_folded)。"""
    ex, fd, cex, cfd, _ = _alias_tables()
    merged = dict(fd)
    for k, v in cfd.items():
        merged.setdefault(k, [])
        for eid in v:
            if eid not in merged[k]:
                merged[k].append(eid)
    return fd, cfd


def _excluded(eid, excludes, q_form, q_fold):
    for x in excludes.get(eid) or []:
        if x and (x in q_form or fold(x) in q_fold):
            return x
    return None


def _spans(fq, forms):
    """→ [(start, end, form, key)]，按**最长优先**排序。

    多词查询里「objet a」必须压过「objet」：否则裸 objet 会与 objet a 并列命中
    （实测就是 term.objet 与 concept.objet-petit-a 双命中）。
    """
    out = []
    for key in forms:
        if not key:
            continue
        for m in re.finditer(re.escape(key), fq):
            out.append((m.start(), m.end(), key))
    out.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    kept, covered = [], []
    for st, en, key in out:
        if any(st >= cs and en <= ce for cs, ce in covered):
            continue          # 被更长的匹配覆盖 → 丢弃
        kept.append(key)
        covered.append((st, en))
    return kept


# ─────────────────────────────────────────────── 上下文判定

BARE_CONTEXT = {
    "autre": {"requires_one_of": ["小他者", "petit autre", "l'autre"]},
    "moi": {"requires_one_of": ["le moi", "自我", "ego"]},
    "demande": {"requires_one_of": ["desir", "欲望", "要求"]},
    "besoin": {"requires_one_of": ["demande", "要求", "desir"]},
    "signifie": {"requires_one_of": ["signifiant", "能指"]},
    "regard": {"requires_one_of": ["凝视", "gaze"]},
}


def context_satisfied(alias, context_text):
    """别名在给定上下文里是否足以解析。规则只有一条：上下文里出现任一锚点形式。

    这不是相似度判断，是**词面共现**判断 —— 可以用一句话复核。
    """
    if not context_text:
        return False, "无上下文"
    fctx = fold(context_text)
    rule = BARE_CONTEXT.get(fold(alias))
    if not rule:
        return True, "该别名不需要上下文"
    for anchor in rule["requires_one_of"]:
        if fold(anchor) and fold(anchor) in fctx:
            return True, "上下文命中锚点 %r" % anchor
    return False, "上下文未命中任何锚点（需要：%s）" % rule["requires_one_of"]


def gazes_context_satisfied(context_text):
    return context_satisfied("regard", context_text)


# ─────────────────────────────────────────────── 解析（包装 Phase 3）

SUPERSEDE = {
    # 旧实体 → 后继实体（后继优先；旧实体不删，只降为审计记录）
    "concept.l-autre": ["concept.big-other", "concept.little-other"],
}


def resolve(term, context=None):
    """包装 Phase 3 resolver，叠加本层策略。

    → {status, entities, context_required, context_note, superseded, notes, layer}

    匹配顺序（deterministic）：
      1. **exact**（保留大小写与变音）命中 → 只用 exact 结果；
      2. exact 不中 → folded 兜底；
      3. 多词查询按**最长匹配优先**，被覆盖的短别名丢弃；
      4. `alias_exclude_forms` 命中时该实体不参与（objet vs objet a）；
      5. `context_required` 别名命中但上下文不满足 → AMBIGUOUS + context_required。
    """
    import entity_resolution as er

    # ⚠️ base resolver **只看 term**：上下文只用于「上下文规则」的判定，
    #    不得参与实体解析 —— 否则 `demande` 带上下文「désir 与 demande」会把
    #    désir 也解析出来（实测就是这样把 demande 解析成了 concept.desir）。
    q = term
    base = er.resolve(q)
    base_ids = [e["entity_id"] for e in base["entities"]]

    exact, folded, cexact, cfolded, excludes = _alias_tables()
    fn, ff = form_norm(term), fold(term)
    if fn in cexact:
        hit_ctx, hit_kind, hit_src = list(cexact[fn]), "exact", fn
    elif fn in exact:
        hit_ctx, hit_kind, hit_src = [], "exact", fn
    elif ff in cfolded:
        hit_ctx, hit_kind, hit_src = list(cfolded[ff]), "folded", ff
    elif ff in folded:
        hit_ctx, hit_kind, hit_src = [], "folded", ff
    else:
        hit_ctx, hit_kind, hit_src = [], None, None

    hits = list(exact.get(fn, [])) if hit_src == fn else list(folded.get(ff, []))
    if hit_src in (None,):
        # 多词查询：在整串上做最长优先匹配
        fq = " " + fn + " "
        for keys, table in ((_spans(fq, exact), exact), (_spans(fq, cexact), cexact)):
            for k in keys:
                for eid in table.get(k, []):
                    if eid in (cexact.get(k) or []):
                        if eid not in hit_ctx:
                            hit_ctx.append(eid)
                    elif eid not in hits:
                        hits.append(eid)
        hit_kind = "multiword"
    if hit_src == fn and fn in exact:
        hits = list(exact.get(fn, []))
        hit_ctx = list(cexact.get(fn, []))

    fq_norm = form_norm(q)
    fq_fold = fold(q)
    dropped = []
    for eid in list(hits) + list(hit_ctx):
        why = _excluded(eid, excludes, fq_norm, fq_fold)
        if why:
            dropped.append({"entity_id": eid, "excluded_by": why})
            if eid in hits:
                hits.remove(eid)
            if eid in hit_ctx:
                hit_ctx.remove(eid)

    notes = []
    if hit_kind:
        notes.append("别名匹配：%s（键 %r）" % (hit_kind, hit_src))
    if dropped:
        notes.append("按 alias_exclude_forms 排除：%s" % dropped)

    entities = []
    for eid in hits:
        e = entity(eid)
        entities.append({"entity_id": eid, "matched_alias": term,
                         "origin": "ontology.v4a1", "entity_type": e.get("type")})
    superseded = []
    for eid in base_ids:
        succ = SUPERSEDE.get(eid) or []
        if succ and any(s in [x["entity_id"] for x in entities] + hit_ctx for s in succ):
            superseded.append({"entity_id": eid, "superseded_by": succ,
                               "note": "旧实体被后继取代（保留为审计记录，解析结果不再返回它）"})
            notes.append("旧实体 %s 被 %s 取代 → 不返回旧实体" % (eid, succ))
            continue
        if eid not in [x["entity_id"] for x in entities]:
            matched = next((x["matched_alias"] for x in base["entities"]
                            if x["entity_id"] == eid), None)
            entities.append({"entity_id": eid, "matched_alias": matched,
                             "origin": "entity_resolution", "entity_type": None})

    status = "RESOLVED" if entities else "UNRESOLVED"
    ctx_required, ctx_note = False, None
    if not entities and hit_ctx:
        ok, why = context_satisfied(term, context)
        if ok:
            for eid in hit_ctx:
                e = entity(eid)
                entities.append({"entity_id": eid, "matched_alias": term,
                                 "origin": "ontology.v4a1.context",
                                 "entity_type": e.get("type")})
            status = "RESOLVED"
            notes.append("上下文限定别名 %r 已满足：%s" % (term, why))
        else:
            ctx_required, ctx_note, status = True, why, "AMBIGUOUS"
            notes.append("别名 %r 需要上下文才能解析：%s" % (term, why))

    ids = [x["entity_id"] for x in entities]
    if len(ids) > 1:
        still = [i for i in ids if i not in {s["entity_id"] for s in superseded}]
        # ── 规则式消歧：**规范名精确匹配**者胜出（大小写/变音敏感）。
        #    为什么可以这样判：这不是相似度，而是「这个词就是该实体的规范名」。
        #    例：`signifiant` 同时是 concept.signifiant 的规范名与 concept.le-symbolique
        #    的别名 → 取前者。其余实体记录在 notes 里，不静默丢弃。
        canon_hits = []
        for eid in still:
            if any(form_norm(c) == fn for c in entity_forms(eid)):
                canon_hits.append(eid)
        if len(canon_hits) == 1:
            keep = canon_hits[0]
            others = [i for i in still if i != keep]
            entities = [x for x in entities if x["entity_id"] not in others]
            notes.append("规范名精确匹配消歧：保留 %s，其余 %s 不返回"
                         "（disambiguated_by=canonical_name_exact）" % (keep, others))
            status = "RESOLVED"
        else:
            status = "AMBIGUOUS"
            notes.append("同一别名命中多个实体（未被静默解析）：%s" % still)

    return {"term": term, "context": context, "status": status,
            "entities": entities, "ambiguous": base.get("ambiguous") or [],
            "context_required": ctx_required, "context_note": ctx_note,
            "context_required_entities": hit_ctx,
            "superseded": superseded, "match_kind": hit_kind,
            "disambiguated_by": (("canonical_name_exact" if status == "RESOLVED"
                                  and any("规范名精确匹配" in n for n in notes)
                                  else None)),
            "alias_excluded": dropped, "notes": notes,
            "base_status": ("RESOLVED" if base["entities"] else "UNRESOLVED"),
            "base_entity_ids": base_ids, "layer": LAYER_ID}


# ─────────────────────────────────────────────── 术语映射

def mappings_for(form):
    ff = fold(form)
    out = []
    for m in load()["mappings"]:
        if ff and (fold(m["source_form"]) == ff or fold(m["target_form"]) == ff):
            out.append(m)
    return out


def terminology_lookup(term):
    """→ {mappings, auto_resolvable, context_required, entity_ids, layer}"""
    ms = mappings_for(term)
    auto = [m for m in ms if m.get("auto_resolution")]
    need_ctx = [m for m in ms if not m.get("auto_resolution")]
    return {
        "term": term,
        "mappings": ms,
        "entity_ids": sorted({m["entity_id"] for m in ms}),
        "auto_resolvable": bool(auto),
        "context_required": bool(need_ctx) and not auto,
        "context_rule": (need_ctx[0].get("context_rule") if need_ctx else None),
        "relation_type": "controlled_term_mapping",
        "layer": LAYER_ID,
        "note": ("controlled_term_mapping 不是普通同义：每个形式各自带 "
                 "context_requirement 与 auto_resolution 策略。"),
    }


# ─────────────────────────────────────────────── 缺陷重分类（§8）

DEFECT_CODES = ("ENTITY_COLLISION", "COUNTERPART_ENTITY_MISSING",
                "BOTH_ENTITIES_MISSING")


def defect_class(binding):
    """把 Phase 3 的 `entity_binding` 映射到**缺陷类别**（§8 要求区分）。"""
    if binding == "ENTITY_COLLISION":
        # 两个理论项绑到同一 id：数据层坍缩
        return "ENTITY_COLLISION"
    if binding in ("COUNTERPART_ENTITY_MISSING", "BOTH_ENTITIES_MISSING"):
        # 缺失一侧/两侧：本体缺项
        return "ONTOLOGY_MISSING"
    return None


def _pair_side_entities(form):
    """该形式在**本层**能解析到哪些实体（两侧分别算）。"""
    r = resolve(form)
    return [e["entity_id"] for e in r["entities"]], r


def guard_view():
    """逐对重分类：修复前（Phase 3 bridge）vs 修复后（本层）。

    数据来源是 `_data/terminology_bridge.jsonl` 的 `distinct_from` 行（**只读**），
    所以这里展示的是「同一份历史数据 + 新本体层」的差异，不是覆盖旧结论。
    """
    import terminology_bridge as tb
    rows = []
    for r in tb.distinct_pairs():
        a, b = r["source_form"], r["target_form"]
        pre = defect_class(r.get("entity_binding"))
        aid, ra = _pair_side_entities(a)
        bid, rb = _pair_side_entities(b)
        # 修复后：两侧都能解析到**不同**实体 → 该配对不再有缺陷
        if aid and bid and set(aid) != set(bid):
            post = "RESOLVED"
            detail = "两侧分别解析到 %s / %s" % (aid, bid)
        elif (not aid or not bid) and (ra.get("context_required") or
                                      rb.get("context_required")):
            post = "RESOLVED_CONTEXT_REQUIRED"
            ctx_side = a if ra.get("context_required") else b
            detail = ("实体已建立，但 %r 是上下文受限别名"
                      "（context_required=%s）—— 需要上下文/显式 id 才可比较"
                      % (ctx_side, (ra if ra.get("context_required") else rb)
                         .get("context_note")))
        elif aid and bid and set(aid) == set(bid):
            post = pre or "ENTITY_COLLISION"
            detail = "两侧仍绑到同一实体 %s" % aid
        elif not aid or not bid:
            post = "ONTOLOGY_MISSING"
            detail = "仍有缺失侧：%s=%s / %s=%s" % (a, aid or "（无）", b, bid or "（无）")
        else:
            post = pre or "ONTOLOGY_MISSING"
            detail = "未分类"
        rows.append({
            "pair": [a, b], "term_id": r.get("term_id"),
            "phase3_entity_binding": r.get("entity_binding"),
            "pre_repair_class": pre,
            "post_repair_class": post,
            "pre_entities": [r.get("entity_id")] if r.get("entity_id") else [],
            "post_entities": {"a": aid, "b": bid},
            "repaired": post != pre,
            "detail": detail,
            "rationale": r.get("distinction_rationale"),
            "layer": LAYER_ID,
        })
    return rows


def disambiguate(term, ids):
    """规则式消歧：**规范名精确匹配**（大小写/变音敏感）者胜出。

    这是判定「这个词就是该实体的规范名」，不是相似度。
    返回 {kept, dropped, by}；无可判定时 by=None（调用方按 AMBIGUOUS 处理）。
    """
    fn = form_norm(term)
    hits = [eid for eid in ids if any(form_norm(c) == fn for c in entity_forms(eid))]
    if len(hits) == 1:
        return {"kept": hits, "dropped": [i for i in ids if i != hits[0]],
                "by": "canonical_name_exact"}
    return {"kept": list(ids), "dropped": [], "by": None}


def guard_summary():
    rows = guard_view()
    from collections import Counter
    return {
        "pairs": len(rows),
        "pre_classes": dict(Counter(r["pre_repair_class"] for r in rows)),
        "post_classes": dict(Counter(r["post_repair_class"] for r in rows)),
        "repaired_pairs": [r["pair"] for r in rows if r["repaired"]],
        "still_defective": [r["pair"] for r in rows
                            if r["post_repair_class"] in
                            ("ENTITY_COLLISION", "ONTOLOGY_MISSING", "MODEL_COLLAPSE")],
        "layer": LAYER_ID,
    }


def annotate_warnings(warnings):
    """给 Phase 3 guard 的告警补上缺陷类别（**不改** guard 本身）。"""
    out = []
    for w in warnings or []:
        w2 = dict(w)
        cls = defect_class(w.get("code"))
        if cls:
            w2["ontology_defect_class"] = cls
            w2["ontology_layer"] = LAYER_ID
        out.append(w2)
    return out


if __name__ == "__main__":
    print(json.dumps({"meta": layer_meta(), "entities": entity_ids(),
                      "guard": guard_summary()},
                     ensure_ascii=False, indent=1))
