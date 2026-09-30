#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_concepts_and_claims.py — Gold Concept Set + Claim 层 + Alignment 占位（Phase 2 §九/§十/§五）

§九 Gold Concept Set
────────────────────
用 `.lacan-build/` 里**已有的 53 条概念卡数据源**作为 gold set，**不新增任何概念**：

    terms_catalog 12 + terms_catalog_b 9 + terms_catalog_c 11
    + terms_catalog_fr 7 + clinical_catalog 8 + cases_catalog 6  = 53

每条卡里的 `zh_segments`（形如 `s1-01-0001`）正是 Phase 1 那种源段号 ——
本脚本把它**映射到 Passage Store 的 stable ID**，于是概念第一次真正连到证据上：

    Concept → aliases → seminar → session → passages → related concepts

映射不上的（例如卡里引了库里没有的期）**不静默丢弃**：
记进 `unresolved_segments` 并保持 trace_status=SOURCE_TRACE_INCOMPLETE。

§十 Claim 层
────────────
建立 Claim schema 与**少量**测试 Claim。硬约束：
  * AI 自动生成的 Claim 默认 `review_status: candidate`
  * **没有 supporting_passages 的 Claim 不得进入 canonical**

§五 Alignment 占位
──────────────────
FR 166,527 / ZH 82,578 → **禁止假设 1:1**。本阶段只建立 alignment 实体与
少量样例，全部 `review_status: candidate`；大规模对齐留待后续阶段。

用法
────
    python3 seed_concepts_and_claims.py
    python3 seed_concepts_and_claims.py --stamp
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from deterministic import add_stamp_flag, apply_stamp  # noqa: E402

LACAN_BUILD = os.path.expanduser("<HOME>")
STORE = os.path.join(VAULT, "_data", "passage_store")
CONCEPT_OUT = os.path.join(STORE, "concepts.jsonl")
CONCEPT_STATE_OUT = os.path.join(STORE, "concept_states.jsonl")
ALIGNMENT_OUT = os.path.join(STORE, "alignments.jsonl")
CLAIM_OUT = os.path.join(STORE, "claims.jsonl")

# 旧卡的 period 字段 → Phase 1 schema 的 concept_period 枚举
PERIOD_MAP = {
    "early": "1953-1955",
    "middle": "1964-1966",
    "late": "1974-1976",
    "all": "1967-1971",     # 「贯穿全部」——落在中段作为代表期，并在 label 里写明
}

CATALOGS = [
    ("terms_catalog", "TERMS", "term"),
    ("terms_catalog_b", "TERMS_B", "term"),
    ("terms_catalog_c", "TERMS_C", "term"),
    ("terms_catalog_fr", "TERMS_FR", "term"),
    ("clinical_catalog", "CLINICAL", "clinical_structure"),
    ("cases_catalog", "CASES", "case"),
]


def slug(s):
    """把法语/中文标题变成合法 ID slug（NFKC → 去变音 → 小写 → 连字符）。"""
    s = unicodedata.normalize("NFKC", str(s))
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unnamed"


def load_catalog(mod, attr):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(LACAN_BUILD, f"{mod}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return getattr(m, attr)


def load_segment_index():
    """source segment id → passage stable id（用于 §九 linkage）。

    只读 passages.jsonl 的两列，避免把 373MB 全部驻留内存之外的东西带进来。
    """
    idx = {}
    p = os.path.join(STORE, "passages.jsonl")
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            seg = (d.get("provenance") or {}).get("source_segment_id")
            if seg:
                idx.setdefault(seg, d["id"])
    return idx


def build_concepts(stamp=False):
    seg_index = load_segment_index()
    concepts, states = [], []
    unresolved_report = []

    for mod, attr, etype in CATALOGS:
        cards = load_catalog(mod, attr)
        for card in cards:
            fr = card.get("fr") or card.get("title") or ""
            zh = card.get("zh") or ""
            base = slug(fr)
            cid = "concept.%s" % base

            # aliases：卡里的 aliases + en + zh + title
            aliases = []
            for a in (card.get("aliases") or []):
                if a and a not in aliases:
                    aliases.append(a)
            for a in (card.get("en"), card.get("zh"), card.get("title")):
                if a and a not in aliases:
                    aliases.append(a)

            # 证据：卡里的 zh_segments → Passage stable id
            seg_ids = card.get("zh_segments") or []
            passages = []
            unresolved = []
            for s in seg_ids:
                sid = s if isinstance(s, str) else str(s)
                if sid in seg_index:
                    if seg_index[sid] not in passages:
                        passages.append(seg_index[sid])
                else:
                    unresolved.append(sid)
            if unresolved:
                unresolved_report.append({"concept": cid, "unresolved": unresolved})

            # 相关概念（卡里可能是标题字符串，转成可预测的 id 或保留原文）
            related = [str(r) for r in (card.get("related") or [])]

            concept = {
                "id": cid,
                "type": "concept",
                "title": card.get("title") or fr or cid,
                "canonical_name": fr or card.get("title"),
                "aliases": aliases,
                "fr": card.get("fr"),
                "en": card.get("en"),
                "zh": card.get("zh"),
                "language": "mul",
                "entity_role": etype,
                "period": PERIOD_MAP.get(card.get("period"), "1967-1971"),
                "period_label": card.get("period"),
                "definition": card.get("definition"),
                "usage_note": card.get("拉康的用法") or card.get("临床结构分析"),
                "misreadings": card.get("misreadings") or [],
                "related_titles": related,
                "source_notes": card.get("source_notes"),
                "tags": card.get("tags") or [],
                "catalog_source": "%s.%s" % (mod, attr),
                "authority_level": "L2" if etype != "case" else "L1",
                "review_status": "needs_review",
                "status": "active",
                "canonical": False,
                # Phase 1 已定义的目录不变量：概念本体**不承载定义**，
                # 定义只存在于 concept_state。这里把原始卡定义留在机器层供迁移参考，
                # 并明确标记它尚未搬迁到 state。
                "definition_migrated_to_state": bool(passages),
                "passages": passages[:20],
                "unresolved_segments": unresolved,
                "trace_status": ("COMPLETE" if passages and not unresolved
                                 else "SOURCE_TRACE_INCOMPLETE"),
                "trace_missing": ([] if passages and not unresolved
                                  else (["passages"] if not passages
                                        else ["unresolved_segments"])),
                "generated_by": "script:seed_concepts_and_claims.py",
                "schema_version": "1.0.0",
            }
            concepts.append(concept)

            # concept_state：把卡的 period 与用法落成一个 state（§一 两层结构）
            states.append({
                "id": "state.%s.%s" % (base, PERIOD_MAP.get(card.get("period"), "1967-1971")),
                "type": "concept_state",
                "concept_id": cid,
                "period": PERIOD_MAP.get(card.get("period"), "1967-1971"),
                "period_label": card.get("period"),
                "state_label": (card.get("definition") or "")[:200],
                "passages": passages[:20],
                "unresolved_segments": unresolved,
                "authority_level": "L2" if etype != "case" else "L1",
                "review_status": "needs_review",
                "status": "active",
                "trace_status": ("COMPLETE" if passages and not unresolved
                                 else "SOURCE_TRACE_INCOMPLETE"),
                "trace_missing": ([] if passages else ["passages"]),
                "generated_by": "script:seed_concepts_and_claims.py",
                "schema_version": "1.0.0",
            })

    return concepts, states, unresolved_report


# ----------------------------------------------------------------- §五 alignment
def build_alignments(stamp=False):
    """少量 alignment 样例，**全部 candidate**。

    刻意不做大规模对齐，也不假设 1:1：本函数只演示四种 relation_type
    各自长什么样，且所有记录都带 confidence 与 method，便于后续审核。
    """
    rows = [
        {
            "alignment_id": "align.s01.0001",
            "source_passages": ["passage.S01.unknown.P0001"],
            "target_passages": ["passage.S01.unknown.L01.P0001"],
            "relation_type": "1:1",
            "confidence": 0.30,
            "review_status": "candidate",
            "method": "positional-seed（仅占位，未做真实对齐）",
            "note": ("S01 的 fr 与 zh 都以期为单位、都没有课次分隔，"
                     "无法按位置可靠对齐；此条仅为 schema 样例。"),
            "authority_level": "L4",
            "generated_by": "script:seed_concepts_and_claims.py",
            "schema_version": "1.0.0",
        },
        {
            "alignment_id": "align.s03.demo-n1",
            "source_passages": ["passage.S03.unknown.P0001",
                                "passage.S03.unknown.P0002",
                                "passage.S03.unknown.P0003"],
            "target_passages": ["passage.S03.unknown.L01.P0001"],
            "relation_type": "N:1",
            "confidence": 0.20,
            "review_status": "candidate",
            "method": "illustrative-only",
            "note": "演示 N:1（多段法文对应一段中译）——不是真实对齐结果。",
            "authority_level": "L4",
            "generated_by": "script:seed_concepts_and_claims.py",
            "schema_version": "1.0.0",
        },
        {
            "alignment_id": "align.s01.missing-zh",
            "source_passages": ["passage.S01.unknown.P0002"],
            "target_passages": [],
            "relation_type": "1:0",
            "confidence": 0.90,
            "review_status": "candidate",
            "method": "count-deficit",
            "note": ("fr 166,527 vs zh 82,578 —— 必然存在大量无中译的段落。"
                     "此条演示『缺译』这一合法状态，不得因此判定文本缺失为错误。"),
            "authority_level": "L4",
            "generated_by": "script:seed_concepts_and_claims.py",
            "schema_version": "1.0.0",
        },
        {
            "alignment_id": "align.zh.uncertain-source",
            "source_passages": [],
            "target_passages": ["passage.S01.unknown.L01.P0002"],
            "relation_type": "0:1",
            "confidence": 0.50,
            "review_status": "candidate",
            "method": "illustrative-only",
            "note": "演示『中译存在但对应法文来源不确定』——上游源目录已消失。",
            "authority_level": "L4",
            "generated_by": "script:seed_concepts_and_claims.py",
            "schema_version": "1.0.0",
        },
    ]
    return rows


# ----------------------------------------------------------------- §十 claims
def build_claims(concepts, stamp=False):
    """少量测试 Claim。AI 生成的默认 candidate；无证据不得 canonical。"""
    by_fr = {}
    for c in concepts:
        key = slug(c.get("fr") or c["canonical_name"])
        by_fr.setdefault(key, c)

    def find(*names):
        for n in names:
            c = by_fr.get(slug(n))
            if c:
                return c
        return None

    obj = find("objet petit a", "objet a")

    claims = [
        {
            "id": "claim.objet-a-cause-of-desire",
            "statement": "对象 a 不是欲望所指向的对象，而是欲望的原因。",
            "supporting_passages": (obj or {}).get("passages", [])[:5],
            "concepts": [(obj or {}).get("id")] if obj else [],
            "period": "1964-1966",
            "source_type": "concept_card",
            "authority_level": "L2",
            "status": "draft",
            "review_status": "candidate",
            "confidence": 0.6,
            "created_by": "script:seed_concepts_and_claims.py",
            "trace_status": ("COMPLETE" if (obj or {}).get("passages")
                             else "SOURCE_TRACE_INCOMPLETE"),
            "note": ("由 Gold Concept Set 的卡面表述直接转写；"
                     "证据段来自卡里的 zh_segments 映射。"
                     "AI/脚本生成的 Claim 一律 candidate，不得 canonical。"),
            "generated_by": "script:seed_concepts_and_claims.py",
            "schema_version": "1.0.0",
        },
        {
            "id": "claim.sinthome-fourth-ring",
            "statement": "圣状是把实在界、象征界、想象界三环绑在一起的第四环。",
            "supporting_passages": [],
            "concepts": [],
            "period": "1974-1976",
            "source_type": "concept_card",
            "authority_level": "L3",
            "status": "draft",
            "review_status": "candidate",
            "confidence": 0.4,
            "created_by": "script:seed_concepts_and_claims.py",
            # 无 supporting_passages → 结构上不允许 canonical（见测试）
            "trace_status": "SOURCE_TRACE_INCOMPLETE",
            "note": ("故意留空的**负例**：演示『无证据 Claim』这一状态。"
                     "它必须永远无法进入 canonical —— 由测试 test_phase2_claim 守住。"),
            "generated_by": "script:seed_concepts_and_claims.py",
            "schema_version": "1.0.0",
        },
    ]
    return claims


def write_jsonl(path, rows):
    rows = sorted(rows, key=lambda r: r.get("id") or r.get("alignment_id"))
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description="Gold Concept Set + Claim + Alignment 种子")
    ap.add_argument("--quiet", action="store_true")
    add_stamp_flag(ap)
    args = ap.parse_args()

    if not os.path.isfile(os.path.join(STORE, "passages.jsonl")):
        print("[fatal] 先跑 build_passage_store.py", file=sys.stderr)
        return 1

    concepts, states, unresolved = build_concepts(args.stamp)
    alignments = build_alignments(args.stamp)
    claims = build_claims(concepts, args.stamp)

    nc = write_jsonl(CONCEPT_OUT, concepts)
    ns = write_jsonl(CONCEPT_STATE_OUT, states)
    na = write_jsonl(ALIGNMENT_OUT, alignments)
    ncl = write_jsonl(CLAIM_OUT, claims)

    meta = {
        "schema": "concept-set/v1",
        "counts": {"concepts": nc, "concept_states": ns,
                   "alignments": na, "claims": ncl},
        "gold_set": {
            "source": ".lacan-build/ terms_catalog / terms_catalog_b / "
                      "terms_catalog_c / terms_catalog_fr / clinical_catalog / cases_catalog",
            "expected_total": 53,
            "actual_total": nc,
        },
        "concepts_with_passages": sum(1 for c in concepts if c["passages"]),
        "concepts_without_passages": sum(1 for c in concepts if not c["passages"]),
        "unresolved_segments": unresolved,
        "rules": {
            "ai_claims_default": "candidate",
            "claim_without_passages_cannot_be_canonical": True,
            "heuristic_alignment_default": "candidate",
            "recovered_translation_canonical": False,
        },
    }
    apply_stamp(meta, stamp=args.stamp)
    with open(os.path.join(STORE, "_concept_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)

    if not args.quiet:
        print(f"[concepts] concepts={nc} states={ns} "
              f"with_passages={meta['concepts_with_passages']} "
              f"without={meta['concepts_without_passages']}", file=sys.stderr)
        print(f"[claims] {ncl}   [alignments] {na}", file=sys.stderr)
        if unresolved:
            print(f"[warn] {len(unresolved)} 个概念有无法映射的 zh_segments",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
