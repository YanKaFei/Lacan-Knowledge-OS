#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_entity_registries.py — Phase 5B：**受审**人员/个案登记表的确定性构建。

铁律（Phase 5B §28/§30/§31）：
  * **禁止自动全库 NER promotion**：本工具不做命名实体识别。它只对**显式声明**的
    控制对象（§29）做**确定性字符串匹配**，并把「有证据」与「无证据」分开登记。
  * 只有通过证据阈值的实体才进入 `reviewed` 登记表；其余进 `candidates`
    （`review_status = candidate_insufficient_evidence`），**不晋级**。
  * `mention != influence`：登记表只记录**提及**证据；`influence_asserted` 一律 false。
  * `person.schreber != case.schreber`：同一名称的「人」与「个案」是两个不同实体；
    `Case → Subject Person` 的连线**只在有证据时**建立，否则保持 null。
  * 不编造引文/日期；匹配到的 passage_id 全部可回查。

输入：`_data/passage_store/passages.jsonl`（确定性单遍扫描）
输出：`_data/entities/{person_registry.json, case_registry.json,
        mention_index.jsonl, registry_manifest.json}`

用法：
    python3 _scripts/_tools/build_entity_registries.py [--min-mentions 3] [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
OUT_DIR = os.path.join(VAULT, "_data", "entities")
PASSAGES = os.path.join(VAULT, "_data", "passage_store", "passages.jsonl")
MENTION_CAP = 4000          # 每个实体的 mention 索引上限（超出则如实标 truncated）

# ── §29：控制对象（**人工声明**，不是 NER 产物）
#    kind: person | case ；aliases 为确定性匹配面（fr / zh / en）
SEED = [
    {"id": "person.freud", "kind": "person", "label": "Sigmund Freud", "label_zh": "弗洛伊德",
     "aliases": ["Freud", "弗洛伊德", "弗洛依德"]},
    {"id": "person.hegel", "kind": "person", "label": "G. W. F. Hegel", "label_zh": "黑格尔",
     "aliases": ["Hegel", "黑格尔"]},
    {"id": "person.kojeve", "kind": "person", "label": "Alexandre Kojève", "label_zh": "科耶夫",
     "aliases": ["Kojève", "Kojeve", "科耶夫", "科热夫", "科耶夫"]},
    {"id": "person.descartes", "kind": "person", "label": "René Descartes", "label_zh": "笛卡尔",
     "aliases": ["Descartes", "笛卡尔", "笛卡儿"]},
    {"id": "person.saussure", "kind": "person", "label": "Ferdinand de Saussure", "label_zh": "索绪尔",
     "aliases": ["Saussure", "索绪尔"]},
    {"id": "person.levi-strauss", "kind": "person", "label": "Claude Lévi-Strauss",
     "label_zh": "列维-斯特劳斯",
     "aliases": ["Lévi-Strauss", "Levi-Strauss", "列维-斯特劳斯", "列维·斯特劳斯", "列维斯特劳斯"]},
    # 人：Schreber 本人（与个案严格分开）
    {"id": "person.schreber", "kind": "person", "label": "Daniel Paul Schreber",
     "label_zh": "施雷伯（本人）",
     "aliases": ["Schreber", "施雷伯", "施瑞伯"]},
    {"id": "case.schreber", "kind": "case", "label": "the Schreber case", "label_zh": "施雷伯个案",
     "aliases": ["Schreber", "施雷伯", "施瑞伯"],
     "case_markers": ["cas", "case", "psychose", "psychosis", "parano", "个案", "案例",
                      "精神病", "妄想", "偏执"]},
    {"id": "case.aimee", "kind": "case", "label": "the Aimée case", "label_zh": "埃梅个案",
     "aliases": ["Aimée", "Aimee", "埃梅", "艾梅", "爱梅"],
     "case_markers": ["cas", "case", "parano", "psychose", "个案", "案例", "精神病", "妄想"]},
    {"id": "case.dora", "kind": "case", "label": "the Dora case", "label_zh": "朵拉个案",
     "aliases": ["Dora", "朵拉", "多拉"],
     "case_markers": ["cas", "case", "hystér", "hyster", "个案", "案例", "癔症", "歇斯底里"]},
    {"id": "case.little-hans", "kind": "case", "label": "the Little Hans case", "label_zh": "小汉斯个案",
     "aliases": ["Little Hans", "小汉斯", "小汉斯个案"],
     "case_markers": ["cas", "case", "phobie", "phobia", "个案", "案例", "恐惧症", "恐怖症"]},
    {"id": "case.wolf-man", "kind": "case", "label": "the Wolf Man case", "label_zh": "狼人个案",
     "aliases": ["Wolf Man", "wolf-man", "狼人", "狼人个案"],
     "case_markers": ["cas", "case", "névrose", "neurosis", "个案", "案例", "神经症"]},
]

CASE_LANGUAGE = ["cas", "case", "个案", "案例", "observation", "histoire de", "病史"]


def _norm(s):
    s = unicodedata.normalize("NFC", str(s or ""))
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", s).strip()


def _alias_re(alias):
    """拉丁字母别名要求词边界（避免 Hans 命中 chansons 等）；CJK 直接子串。"""
    a = re.escape(alias)
    if re.match(r"^[A-Za-z]", alias):
        return re.compile(r"(?<![A-Za-z])%s(?![A-Za-z])" % a, re.IGNORECASE)
    return re.compile(a, re.IGNORECASE)


def build(min_mentions=3, cap=MENTION_CAP):
    pats = [(e, [(al, _alias_re(al)) for al in e["aliases"]],
             [_alias_re(m) for m in e.get("case_markers") or []]) for e in SEED]
    stats = {e["id"]: {"mentions": 0, "sample": [], "by_language": {}, "by_authority": {},
                       "by_trace": {}, "witnesses": {}, "case_marker_hits": 0}
             for e in SEED}
    rows_written = {e["id"]: 0 for e in SEED}
    mf = open(os.path.join(OUT_DIR, "mention_index.jsonl"), "w", encoding="utf-8")
    truncated = {}
    n = 0
    with open(PASSAGES, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            p = json.loads(line)
            n += 1
            text = _norm(p.get("raw_text") or "") + " \u0001 " + _norm(
                p.get("normalized_text") or "")
            if not text.strip(" \u0001"):
                continue
            for e, apats, cpats in pats:
                hit = next((al for al, rx in apats if rx.search(text)), None)
                if not hit:
                    continue
                s = stats[e["id"]]
                s["mentions"] += 1
                s["by_language"][p.get("language")] = s["by_language"].get(
                    p.get("language"), 0) + 1
                s["by_authority"][p.get("authority_level")] = s["by_authority"].get(
                    p.get("authority_level"), 0) + 1
                s["by_trace"][p.get("trace_status")] = s["by_trace"].get(
                    p.get("trace_status"), 0) + 1
                s["witnesses"][p.get("witness_id")] = s["witnesses"].get(
                    p.get("witness_id"), 0) + 1
                if len(s["sample"]) < 40:
                    s["sample"].append(p["id"])
                if cpats and any(rx.search(text) for rx in cpats):
                    s["case_marker_hits"] += 1
                if rows_written[e["id"]] < cap:
                    mf.write(json.dumps({
                        "schema_version": "phase5b-mention-index/v1",
                        "entity_id": e["id"], "entity_kind": e["kind"],
                        "passage_id": p["id"], "matched_alias": hit,
                        "language": p.get("language"),
                        "authority_level": p.get("authority_level"),
                        "witness_id": p.get("witness_id"),
                        "trace_status": p.get("trace_status"),
                        "seminar_id": p.get("seminar_id"),
                        # §31：提及证据**只**证明出现，不证明影响/关系/分析
                        "asserts_influence": False,
                        "asserts_theoretical_relation": False,
                        "asserts_case_analysis": False,
                    }, ensure_ascii=False, sort_keys=True) + "\n")
                    rows_written[e["id"]] += 1
                elif e["id"] not in truncated:
                    truncated[e["id"]] = True
    mf.close()

    reviewed_p, reviewed_c, candidates = [], [], []
    for e in SEED:
        s = stats[e["id"]]
        enough = (s["mentions"] >= min_mentions and bool(s["sample"]))
        rec = {
            "id": e["id"], "kind": e["kind"], "label": e["label"],
            "label_zh": e.get("label_zh"), "aliases": e["aliases"],
            "mention_count": s["mentions"],
            "mention_sample_passage_ids": s["sample"],
            "by_language": s["by_language"], "by_authority_level": s["by_authority"],
            "by_trace_status": s["by_trace"], "witnesses": s["witnesses"],
            "case_marker_hits": s["case_marker_hits"],
            "mention_index_truncated": bool(truncated.get(e["id"])),
            "review_status": "reviewed" if enough else "candidate_insufficient_evidence",
            # §31 no-inference：登记表**只**承载提及证据
            "evidence_kind": "MENTION_ONLY",
            "asserts_influence": False,
            "asserts_theoretical_relation": False,
            "asserts_case_analysis": False,
            "provenance": {
                "source": "_data/passage_store/passages.jsonl",
                "method": "DETERMINISTIC_ALIAS_MATCH（非 NER、非 LLM）",
                "min_mentions_threshold": min_mentions,
                "reproducible": "python3 _scripts/_tools/build_entity_registries.py",
            },
        }
        if e["kind"] == "case":
            rec["subject_person"] = None      # §30：只在有证据时才连线（见下）
            (reviewed_c if enough else candidates).append(rec)
        else:
            (reviewed_p if enough else candidates).append(rec)

    # §30：Case → Subject Person 只在**有证据**时建立
    sc = next((r for r in reviewed_c + candidates if r["id"] == "case.schreber"), None)
    sp = next((r for r in reviewed_p + candidates if r["id"] == "person.schreber"), None)
    link_evidence = []
    if sc and sp:
        both = set(sp["mention_sample_passage_ids"]) & set(sc["mention_sample_passage_ids"])
        link_evidence = sorted(both)[:10]
        if sc["case_marker_hits"] > 0 and sp["mention_count"] > 0 and link_evidence:
            sc["subject_person"] = "person.schreber"
            sc["subject_person_link"] = {
                "asserted": True,
                "evidence_passage_ids": link_evidence,
                "evidence_kind": "CASE_MARKER_LANGUAGE + SAME_NAME_MENTION",
                "note": ("Schreber 是**该个案的主体**，由「个案语汇 + 同名提及」的实证支撑；"
                         "这不表示 person.schreber 与 case.schreber 是同一个实体 —— "
                         "二者 id 不同、kind 不同、不可互相折叠。"),
            }
    man = {
        "schema_version": "phase5b-entity-registry-manifest/v1",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "DETERMINISTIC_ALIAS_MATCH",
        "no_automatic_ner_promotion": True,
        "passages_scanned": n,
        "min_mentions_threshold": min_mentions,
        "seed_entities": len(SEED),
        "persons_reviewed": len(reviewed_p), "cases_reviewed": len(reviewed_c),
        "candidates_not_promoted": len(candidates),
        "reviewed_ids": sorted([r["id"] for r in reviewed_p + reviewed_c]),
        "candidate_ids": sorted([r["id"] for r in candidates]),
        "mention_index_rows": sum(rows_written.values()),
        "mention_index_truncated_entities": sorted(truncated),
        "separation_invariants": {
            "person_and_case_are_distinct_namespaces": True,
            "mention_never_implies_influence": True,
            "cooccurrence_never_implies_theoretical_relation": True,
            "case_mention_never_implies_case_analysis": True,
            "person_never_auto_collapses_into_case": True,
            "alias_never_implies_conceptual_synonym": True,
        },
        "schreber": {
            "person_id": "person.schreber", "case_id": "case.schreber",
            "distinct_ids": bool(sp and sc and sp["id"] != sc["id"]),
            "subject_person_link_asserted": bool(sc and sc.get("subject_person")),
            "link_evidence_n": len(link_evidence),
        },
    }
    return {"persons": reviewed_p, "cases": reviewed_c, "candidates": candidates,
            "manifest": man}


def write_all(res):
    os.makedirs(OUT_DIR, exist_ok=True)
    def w(name, obj):
        with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    w("person_registry.json", {
        "schema_version": "phase5b-person-registry/v1",
        "kind": "person", "reviewed": res["persons"],
        "candidates_not_promoted": [c for c in res["candidates"] if c["kind"] == "person"],
        "rules": ["reviewed 需达最小提及阈值", "禁止自动 NER 晋级",
                  "mention ≠ influence", "alias ≠ conceptual synonym"],
    })
    w("case_registry.json", {
        "schema_version": "phase5b-case-registry/v1",
        "kind": "case", "reviewed": res["cases"],
        "candidates_not_promoted": [c for c in res["candidates"] if c["kind"] == "case"],
        "rules": ["case mention ≠ case analysis", "Case → Subject Person 只在有证据时连线",
                  "person.X 与 case.X 是不同实体，不得折叠"],
    })
    w("registry_manifest.json", res["manifest"])
    print("实体登记表 -> %s" % os.path.relpath(OUT_DIR, VAULT))
    for r in res["persons"] + res["cases"]:
        print("  reviewed  %-22s mentions=%-6d case_markers=%-5d sample=%d"
              % (r["id"], r["mention_count"], r["case_marker_hits"],
                 len(r["mention_sample_passage_ids"])))
    for c in res["candidates"]:
        print("  candidate %-22s mentions=%-6d（未达阈值 %d，不晋级）"
              % (c["id"], c["mention_count"],
                 res["manifest"]["min_mentions_threshold"]))
    print("  schreber: %s" % json.dumps(res["manifest"]["schreber"], ensure_ascii=False))
    print("  mentions indexed: %d" % res["manifest"]["mention_index_rows"])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-mentions", type=int, default=3)
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)
    global OUT_DIR
    if a.out_dir:
        OUT_DIR = a.out_dir
    os.makedirs(OUT_DIR, exist_ok=True)
    return write_all(build(min_mentions=a.min_mentions))


if __name__ == "__main__":
    sys.exit(main())
