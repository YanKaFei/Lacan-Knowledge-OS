#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_gold_v2.py — Phase 4C.1-B §16：**gold_v2**（版本化，绝不覆盖 v1）

规则（用户明令）
────────────────
1. 不覆盖 v1：`research_tasks_v1.jsonl` / `gold_derivation` 逐字节不动（`--check` 会验）；
2. provenance 指向：人工评审 / 三个人工裁决 / lane audit；
3. **17 条 LIKELY_FALSE_POSITIVE lane** 按新 normalization（token 边界安全）重建；
4. **6 条 NEEDS_MANUAL_REVIEW lane 不得自动猜** → 原样保留并标 `review_status`；
5. 无法确定 → `review_status = NEEDS_MANUAL_REVIEW`；
6. `rt-G01` 保持 `UNDETERMINED_PENDING_RELATION_RETRIEVAL`。

产物
────
    _data/eval/gold_v2/research_tasks_v2.jsonl      新 gold（含 per-task provenance）
    _data/eval/gold_v2/gold_v2_derivation.json      lane 级推导记录（含 v1→v2 差异）
    _data/eval/gold_v2/MANIFEST.json                输入哈希 + 计数 + 不变式

用法
────
    python3 build_gold_v2.py             # 生成
    python3 build_gold_v2.py --check     # 校验可复现 + v1 未变 + 计数不变式
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
STORE = os.path.join(VAULT, "_data", "passage_store")
OUTDIR = os.path.join(EVAL, "gold_v2")
OUT = os.path.join(OUTDIR, "research_tasks_v2.jsonl")
DERIV = os.path.join(OUTDIR, "gold_v2_derivation.json")
MANIFEST = os.path.join(OUTDIR, "MANIFEST.json")
OVERRIDES = os.path.join(OUTDIR, "lane_overrides_v1.json")
V1 = os.path.join(EVAL, "research_tasks_v1.jsonl")
AUDIT = os.path.join(EVAL, "gold_lane_audit_v1.jsonl")
REGRESSION = os.path.join(EVAL, "scholarly_regression_v1.jsonl")
ADJ = os.path.join(EVAL, "human_adjudication_queue.jsonl")
REVIEW = os.path.join(EVAL, "research_human_review.jsonl")
sys.path.insert(0, HERE)
import eval_integrity as ei            # noqa: E402
import gold_normalization as gn        # noqa: E402

PER_SEMINAR_CAP = 3
PER_LANE_CAP = 20


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def jd(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def load_rows():
    rows = []
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            rows.append((d["id"], d.get("seminar_id"), d.get("language"),
                         d.get("raw_text") or ""))
    return rows


def derive_all(rows, specs):
    """**一次遍历**完成所有 lane 的 v2 匹配（needle 与 passage 都只预处理一次）。

    specs: [{"id":…, "needles":[…], "language":…, "seminar":…}, …]
    → {spec_id: [(pid, sem, lang), …]}
    这是 4C.1-A lane audit 用过的加速方式：逐 needle 重新 token 化 249k 段会慢两个数量级。
    """
    preps = {}
    for sp in specs:
        pns = [gn.prepare_needle(n) for n in sp["needles"]]
        preps[sp["id"]] = ([p for p in pns if p], sp)
    hits = defaultdict(list)
    for pid, sem, lang, raw in rows:
        prep = gn.precompute_v2(raw)
        for sid, (pns, sp) in preps.items():
            if sp.get("language") and lang != sp["language"]:
                continue
            if sp.get("seminar") and sem != sp["seminar"]:
                continue
            if any(gn.contains_prepared(prep, pn, raw) for pn in pns):
                hits[sid].append((pid, sem, lang))
    return hits


def sample_lane(hits, per_seminar=PER_SEMINAR_CAP, cap=PER_LANE_CAP):
    by_sem = defaultdict(list)
    for h in hits:
        by_sem[h[1] or "unknown"].append(h)
    picked = []
    for sem in sorted(by_sem):
        picked.extend(by_sem[sem][:per_seminar])
    return picked[:cap], len(hits), len(by_sem)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    v1 = {r["task_id"]: r for r in jl(V1)}
    audit_rows = jl(AUDIT)
    audit = defaultdict(dict)
    for r in audit_rows:
        audit[r["task_id"]][r["lane"]] = r
    reg = {r["task_id"]: r for r in jl(REGRESSION)}
    adj = {r["task_id"]: r for r in jl(ADJ)}
    review = {r["task_id"]: r for r in jl(REVIEW)}
    ov = (jd(OVERRIDES) or {}).get("overrides") or {}

    rows = load_rows()
    # ── 第一步：收集本次需要匹配的所有 lane 规格，**一次遍历**算出命中
    specs = []
    for tid, t in sorted(v1.items()):
        for lane in ((t.get("gold_derivation") or {}).get("lanes") or []):
            specs.append({"id": "%s|%s" % (tid, lane["lane"]),
                          "needles": lane["needles"], "language": lane.get("language"),
                          "seminar": lane.get("seminar")})
        for extra in (ov.get(tid, {}).get("add_lanes") or []):
            specs.append({"id": "%s|%s" % (tid, extra["lane"]),
                          "needles": extra["needles"], "language": extra.get("language"),
                          "seminar": extra.get("seminar")})
    HITS = derive_all(rows, specs)

    def pick(sid):
        return sample_lane(HITS.get(sid) or [])

    out, deriv = [], []
    for tid, t in sorted(v1.items()):
        lanes_v1 = (t.get("gold_derivation") or {}).get("lanes") or []
        new_lanes, lane_deriv = [], []
        flags = []
        for lane in lanes_v1:
            au = (audit.get(tid) or {}).get(lane["lane"]) or {}
            cls = au.get("classification", "UNKNOWN")
            if cls == "SAFE":
                got, n_hits, n_sem = pick("%s|%s" % (tid, lane["lane"]))
                new_lanes.append({"lane": lane["lane"], "needles": lane["needles"],
                                  "language": lane.get("language"),
                                  "seminar": lane.get("seminar"),
                                  "role": "gold", "source": "v1_safe_recheck",
                                  "classification": cls, "passages": [g[0] for g in got],
                                  "hits_total": n_hits})
            elif cls == "LIKELY_FALSE_POSITIVE":
                got, n_hits, n_sem = pick("%s|%s" % (tid, lane["lane"]))
                new_lanes.append({"lane": lane["lane"], "needles": lane["needles"],
                                  "language": lane.get("language"),
                                  "seminar": lane.get("seminar"),
                                  "role": "gold", "source": "v2_normalization_rebuild",
                                  "classification": cls, "passages": [g[0] for g in got],
                                  "hits_total": n_hits,
                                  "v1_hits": (au.get("v1_hits")),
                                  "dropped_v1_false_positives": au.get("extra_v1_only")})
                flags.append({"lane": lane["lane"], "from": "LIKELY_FALSE_POSITIVE",
                              "action": "rebuilt_with_v2_normalization",
                              "dropped": au.get("extra_v1_only")})
            else:
                # NEEDS_MANUAL_REVIEW（或未知）：**不自动改**，原样保留
                new_lanes.append({"lane": lane["lane"], "needles": lane["needles"],
                                  "language": lane.get("language"),
                                  "seminar": lane.get("seminar"),
                                  "role": "gold", "source": "v1_unchanged_needs_manual_review",
                                  "classification": cls,
                                  "passages": list(lane.get("passages") or []),
                                  "hits_total": lane.get("hits_total"),
                                  "review_status": "NEEDS_MANUAL_REVIEW"})
                flags.append({"lane": lane["lane"], "from": cls,
                              "action": "kept_as_v1_needs_manual_review"})
            lane_deriv.append({"lane": lane["lane"], "classification": cls,
                               "v1_hits": lane.get("hits_total"),
                               "v2_hits": new_lanes[-1].get("hits_total")})

        o = ov.get(tid)
        review_status = "script_assisted_unreviewed"
        if o:
            for extra in o.get("add_lanes") or []:
                got, n_hits, n_sem = pick("%s|%s" % (tid, extra["lane"]))
                new_lanes.append({"lane": extra["lane"], "needles": extra["needles"],
                                  "language": extra.get("language"),
                                  "seminar": extra.get("seminar"),
                                  "role": "gold",
                                  "source": "adjudication_override",
                                  "basis": extra.get("basis"),
                                  "expectation": extra.get("expectation"),
                                  "passages": [g[0] for g in got],
                                  "hits_total": n_hits})
            if o.get("demote_v1_lanes_to"):
                for l in new_lanes:
                    if l.get("source", "").startswith("v1"):
                        l["role"] = o["demote_v1_lanes_to"]

        gold, seen = [], set()
        for l in new_lanes:
            if l.get("role") != "gold":
                continue
            for pid in l.get("passages") or []:
                if pid not in seen:
                    seen.add(pid)
                    gold.append(pid)
        if o and o.get("no_gold_evidence_reason"):
            gold = []

        answerability = t["answerability"]
        if o and o.get("answerability_v2"):
            answerability = o["answerability_v2"]

        row = {
            "schema_version": "research-task/v2",
            "task_id": tid,
            "question": t["question"],
            "language": t["language"],
            "task_type": t["task_type"],
            "split": t.get("split"),
            "required_capabilities": t.get("required_capabilities"),
            "expected_entities": t.get("expected_entities"),
            "desirable_entities": t.get("desirable_entities"),
            "expected_operations": t.get("expected_operations"),
            "expected_seminars": t.get("expected_seminars"),
            "expected_periods": t.get("expected_periods"),
            "expected_periods_declared": t.get("expected_periods_declared"),
            "forbidden_shortcuts": t.get("forbidden_shortcuts"),
            "evaluation_notes": t.get("evaluation_notes"),
            "answerability": answerability,
            "answerability_v1": t["answerability"],
            "gold_evidence": gold,
            "lanes": new_lanes,
            "acceptable_evidence": t.get("acceptable_evidence"),
            "review_status": ("NEEDS_MANUAL_REVIEW"
                              if any(l.get("review_status") == "NEEDS_MANUAL_REVIEW"
                                     for l in new_lanes) else review_status),
            "followup_required": bool(o and o.get("followup_required")),
            "no_gold_reason": (o.get("no_gold_evidence_reason")
                               if o and o.get("no_gold_evidence_reason")
                               else (t.get("gold_derivation") or {}).get("no_gold_reason")),
            "provenance": {
                "derived_from": ["research_tasks_v1.jsonl（只读）",
                                 "gold_lane_audit_v1.jsonl",
                                 "human_adjudication_queue.jsonl",
                                 "research_human_review.jsonl",
                                 "gold_v2/lane_overrides_v1.json"],
                "v1_sha256": ei.sha256_file(V1),
                "audit_sha256": ei.sha256_file(AUDIT),
                "normalization": ("gold_normalization.contains_v2"
                                  "（token 边界安全；标点不作删除拼接）"),
                "human_review": ({"scores": review[tid]["human_scores"],
                                  "citation_support": review[tid]["citation_support"],
                                  "scholarly_usable": review[tid]["scholarly_usable"]}
                                 if tid in review else None),
                "adjudication": ({"decision": adj[tid].get("decision"),
                                  "status": adj[tid].get("status")}
                                 if tid in adj else None),
                "lane_classification": {l["lane"]: (audit.get(tid) or {})
                                        .get(l["lane"], {}).get("classification")
                                        for l in new_lanes
                                        if l["lane"] in (audit.get(tid) or {})},
            },
            "note": ("gold_v2：SAFE lane 按 v2 语义复核；LIKELY_FALSE_POSITIVE lane 按 token 边界"
                     "安全归一化重建（去掉跨 token 假阳性）；NEEDS_MANUAL_REVIEW lane 一律原样"
                     "保留；三个裁决题按人工裁决的 lane override 处理。v1 未被修改。"),
        }
        out.append(row)
        deriv.append({"task_id": tid, "contract_type": reg.get(tid, {}).get("task_type"),
                      "lanes": lane_deriv, "flags": flags,
                      "gold_n": len(gold),
                      "answerability_v1": t["answerability"],
                      "answerability_v2": answerability,
                      "overridden": bool(o)})

    if a.check:
        have = jl(OUT)
        key = lambda rs: json.dumps([{k: v for k, v in r.items()
                                      if k != "provenance"} for r in rs],
                                    ensure_ascii=False, sort_keys=True)
        problems = []
        if len(have) != len(out):
            problems.append("任务数不符：%d vs %d" % (len(have), len(out)))
        elif key(have) != key(out):
            problems.append("内容与输入不一致（重跑 build_gold_v2.py）")
        # 不变式：v1 未被改；裁决题保持人工裁定的 answerability
        man = jd(MANIFEST) or {}
        if man.get("v1_sha256") != ei.sha256_file(V1):
            problems.append("v1 任务集 hash 变化 → gold_v2 过期或 v1 被改")
        for tid, want in (("rt-J01", "PARTIALLY_SUPPORTED"),
                          ("rt-H02", "SUPPORTED"),
                          ("rt-G01", "UNDETERMINED_PENDING_RELATION_RETRIEVAL")):
            got = next((r["answerability"] for r in have if r["task_id"] == tid), None)
            if got != want:
                problems.append("%s answerability=%s（应为 %s）" % (tid, got, want))
        for p in problems:
            print("  FAIL", p)
        return 1 if problems else 0

    os.makedirs(OUTDIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    cls_counter = Counter(l["classification"] for r in out for l in r["lanes"]
                          if l.get("classification"))
    json.dump({"schema_version": "gold-v2-derivation/v1",
               "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "tasks": deriv}, open(DERIV, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    man = {
        "schema_version": "gold-v2-manifest/v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator": "build_gold_v2.py",
        "inputs": {"research_tasks_v1.jsonl": ei.sha256_file(V1),
                   "gold_lane_audit_v1.jsonl": ei.sha256_file(AUDIT),
                   "scholarly_regression_v1.jsonl": ei.sha256_file(REGRESSION),
                   "human_adjudication_queue.jsonl": ei.sha256_file(ADJ),
                   "research_human_review.jsonl": ei.sha256_file(REVIEW),
                   "gold_v2/lane_overrides_v1.json": ei.sha256_file(OVERRIDES)},
        "v1_sha256": ei.sha256_file(V1),
        "outputs": {"research_tasks_v2.jsonl": ei.sha256_file(OUT),
                    "gold_v2_derivation.json": ei.sha256_file(DERIV)},
        "counts": {"tasks": len(out),
                   "lane_classification": dict(cls_counter),
                   "needs_manual_review_tasks": [r["task_id"] for r in out
                                                 if r["review_status"] == "NEEDS_MANUAL_REVIEW"],
                   "adjudicated_tasks": [r["task_id"] for r in out
                                         if r["provenance"]["adjudication"]]},
        "invariants": {
            "v1_untouched": True,
            "no_task_id_branch_in_code": ("per-task 事实只存在于 lane_overrides_v1.json"
                                          "（数据），builder 代码不含 task_id 分支"),
            "needs_manual_review_not_auto_guessed": True,
        },
    }
    json.dump(man, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        print("wrote %s（%d 任务）" % (os.path.relpath(OUT, VAULT), len(out)))
        print("  lane 分类：%s" % dict(cls_counter))
        print("  NEEDS_MANUAL_REVIEW 任务：%s" % man["counts"]["needs_manual_review_tasks"])
        print("  裁决题：%s" % man["counts"]["adjudicated_tasks"])
        for r in out:
            if r["provenance"]["adjudication"]:
                print("    %-7s v1=%-22s v2=%-42s gold_n=%d"
                      % (r["task_id"], r["answerability_v1"], r["answerability"],
                         len(r["gold_evidence"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
