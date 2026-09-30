#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_gold_lanes.py — Phase 4C.1-A §A4：gold lane 的**跨 token 假阳性审计**

背景
────
`build_research_tasks_v1.py` 的 v1 `squash()` 删标点后去空白，会把原本分开的
token 粘成一个词，从而在语料里造出并不存在的命中（Phase 4C 人工评审实证：
`rt-J02` 的 `frmi` 全部来自 URL `perso.univ-rennes1.fr/michel`）。

本脚本**不改 v1 gold**，只做审计：
对每个任务的每条 lane（以及 acceptable needle 集合）分别用
  * v1 语义（`squash_v1`，冻结）与
  * v2 语义（`gold_normalization.contains_v2`，token 边界安全）
重新计算命中，并对「v1 命中但 v2 不命中」的每一条给出**机制诊断**。

分类（确定性）
──────────────
    SAFE                     v1 与 v2 命中集一致（无跨 token 膨胀）
    LIKELY_FALSE_POSITIVE    多出的命中全部由 url_join / clause_boundary_join /
                             short_piece_join 解释
    NEEDS_MANUAL_REVIEW      多出的命中里至少有一条只跨引号/括号（`punctuation_join`）
                             或无法解释（`unknown`） —— 可能是合法变体（如 `objet (a)`）

产物
────
    _data/eval/gold_lane_audit_v1.jsonl     每 lane 一行
    stdout 摘要（写入 evaluation_integrity_audit.json 的由 build_evaluation_integrity_audit.py 负责）

用法
────
    python3 audit_gold_lanes.py [--quiet] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
STORE = os.path.join(VAULT, "_data", "passage_store")
OUT = os.path.join(EVAL, "gold_lane_audit_v1.jsonl")
SUMMARY = os.path.join(EVAL, "gold_lane_audit_v1.summary.json")
sys.path.insert(0, HERE)

import gold_normalization as gn  # noqa: E402


def inputs_sha256():
    """本审计依赖的冻结输入（用于 --check 判过期）。"""
    import hashlib
    out = {}
    for rel in ("_data/eval/research_tasks_v1.jsonl",
                "_data/passage_store/passages.jsonl"):
        h = hashlib.sha256()
        with open(os.path.join(VAULT, rel), "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        out[rel] = h.hexdigest()
    return out


def read_summary():
    try:
        return json.load(open(SUMMARY, encoding="utf-8"))
    except Exception:
        return {}


def load_passages():
    rows = []
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            raw = d.get("raw_text") or ""
            rows.append({
                "id": d["id"], "sem": d.get("seminar_id"), "lang": d.get("language"),
                "raw": raw, "v1": gn.squash_v1(raw), "v2": gn.precompute_v2(raw),
            })
    return rows


def audit_lane(rows, needles, language, seminar):
    """→ (v1_ids, v2_ids)；按 language / seminar 过滤，与 v1 derive() 口径一致。"""
    v1_ids, v2_ids = set(), set()
    for r in rows:
        if language and r["lang"] != language:
            continue
        if seminar and r["sem"] != seminar:
            continue
        if any(gn.squash_v1(n) and gn.squash_v1(n) in r["v1"] for n in needles):
            v1_ids.add(r["id"])
        if any(gn.contains_v2_prepared(r["v2"], n) for n in needles):
            v2_ids.add(r["id"])
    return v1_ids, v2_ids


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)

    if a.check:
        old = read_summary()
        if not old:
            print("缺 %s（先跑 audit_gold_lanes.py）" % os.path.relpath(SUMMARY, VAULT))
            return 1
        sha = inputs_sha256()
        bad = [k for k, v in (old.get("inputs_sha256") or {}).items() if sha.get(k) != v]
        if bad:
            print("lane 审计已过期（输入变化：%s）—— 重跑 audit_gold_lanes.py" % bad)
            return 1
        print("lane 审计与当前任务集/语料一致（%d lane，%s）"
              % (old.get("lanes_audited"), old.get("classification")))
        return 0

    tasks = [json.loads(l) for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"),
                                        encoding="utf-8") if l.strip()]
    rows = load_passages()
    by_id = {r["id"]: r for r in rows}
    print("passages: %d；tasks: %d" % (len(rows), len(tasks)))

    out_rows = []
    for t in tasks:
        lanes = list(t.get("gold_derivation", {}).get("lanes") or [])
        for lane in lanes:
            v1_ids, v2_ids = audit_lane(rows, lane["needles"], lane.get("language"),
                                        lane.get("seminar"))
            extra = sorted(v1_ids - v2_ids)
            gained = sorted(v2_ids - v1_ids)
            diags = []
            for pid in extra[:25]:
                d = gn.diagnose_v1_only_hit(by_id[pid]["raw"], lane["needles"][0]) \
                    if len(lane["needles"]) == 1 else \
                    gn.diagnose_v1_only_hit(by_id[pid]["raw"], _first_hitting_needle(
                        by_id[pid], lane["needles"]))
                diags.append(dict(d, passage_id=pid))
            klass, reasons = classify(extra, diags, gained)
            out_rows.append({
                "schema_version": "gold-lane-audit/v1",
                "task_id": t["task_id"], "task_type": t["task_type"],
                "lane": lane["lane"], "kind": "gold_lane",
                "needles": lane["needles"], "language": lane.get("language"),
                "seminar": lane.get("seminar"),
                "declared_hits_total": lane.get("hits_total"),
                "v1_hits": len(v1_ids), "v2_hits": len(v2_ids),
                "extra_v1_only": len(extra), "v2_only_gained": len(gained),
                "classification": klass,
                "reasons": reasons,
                "examples": diags[:8],
                "extra_ids": extra[:20],
            })
        # acceptable needle 集合（语言不限，与 v1 derive 口径一致）
        acc = t.get("acceptable_needles") or []
        if acc:
            v1_ids, v2_ids = audit_lane(rows, acc, None, None)
            extra = sorted(v1_ids - v2_ids)
            gained = sorted(v2_ids - v1_ids)
            diags = [dict(gn.diagnose_v1_only_hit(by_id[p]["raw"],
                                                  _first_hitting_needle(by_id[p], acc)),
                          passage_id=p) for p in extra[:25]]
            klass, reasons = classify(extra, diags, gained)
            out_rows.append({
                "schema_version": "gold-lane-audit/v1",
                "task_id": t["task_id"], "task_type": t["task_type"],
                "lane": "__acceptable__", "kind": "acceptable_needles",
                "needles": acc, "language": None, "seminar": None,
                "declared_hits_total": None,
                "v1_hits": len(v1_ids), "v2_hits": len(v2_ids),
                "extra_v1_only": len(extra), "v2_only_gained": len(gained),
                "classification": klass, "reasons": reasons,
                "examples": diags[:8], "extra_ids": extra[:20],
            })

    with open(OUT, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    counts = Counter(r["classification"] for r in out_rows)
    reason_counts = Counter(x for r in out_rows for x in r["reasons"])
    flagged = [r for r in out_rows if r["classification"] != "SAFE"]
    summary = {
        "schema_version": "gold-lane-audit-summary/v1",
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ",
                                                    __import__("time").gmtime()),
        "inputs_sha256": inputs_sha256(),
        "lanes_audited": len(out_rows),
        "classification": dict(counts),
        "reasons": dict(reason_counts),
        "flagged": [{"task_id": r["task_id"], "lane": r["lane"],
                     "classification": r["classification"],
                     "v1_hits": r["v1_hits"], "v2_hits": r["v2_hits"],
                     "extra_v1_only": r["extra_v1_only"],
                     "reasons": r["reasons"]} for r in flagged],
        "output": os.path.relpath(OUT, VAULT),
        "note": ("v1 = 冻结的 squash()（research_tasks_v1 用它推导，不得改）；"
                 "v2 = gold_normalization.contains_v2（标点作 token 边界）。"
                 "本审计只读取，不修改任何 v1 gold。"),
    }
    json.dump(summary, open(SUMMARY, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    if not a.quiet:
        print("lane 总数 %d → %s" % (len(out_rows), dict(counts)))
        print("机制分布：%s" % dict(reason_counts))
        print("\n受影响 lane：")
        for r in flagged:
            print("  %-7s %-18s %-22s v1=%-4d v2=%-4d extra=%-3d %s"
                  % (r["task_id"], r["lane"], r["classification"], r["v1_hits"],
                     r["v2_hits"], r["extra_v1_only"], r["reasons"]))
        print("\n-> %s" % os.path.relpath(OUT, VAULT))
    return 0


def _first_hitting_needle(row, needles):
    """多条 needle 时，取第一条只被 v1 命中的 needle（用于诊断原因）。"""
    for n in needles:
        sn = gn.squash_v1(n)
        if sn and sn in row["v1"] and not gn.contains_v2_prepared(row["v2"], n):
            return n
    return needles[0]


def classify(extra, diags, gained):
    if not extra:
        return "SAFE", []
    reasons = sorted({d["reason"] for d in diags})
    fp = [r for r in reasons if r in gn.FALSE_POSITIVE_REASONS]
    manual = [r for r in reasons if r in gn.MANUAL_REVIEW_REASONS]
    if manual:
        return "NEEDS_MANUAL_REVIEW", reasons
    if fp:
        return "LIKELY_FALSE_POSITIVE", reasons
    return "NEEDS_MANUAL_REVIEW", reasons or ["unknown"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
