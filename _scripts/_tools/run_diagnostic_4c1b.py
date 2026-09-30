#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_diagnostic_4c1b.py — Phase 4C.1-B §22：**DIAGNOSTIC** rerun（不覆盖任何历史）

用途
────
在所有契约代码就位后跑一遍 27 个任务，观察：
    required / completed / missing operations
    lane completion
    constraint completion
    relation / source-layer / formalism / metadata completion
    sufficiency state（v2 → v2.1）
    failure reason codes

纪律（§22）
──────────
* 输出到**新目录** `_data/eval/research_traces_4c1b/`（旧目录一字不改）；
* 每条 trace 标 `"marker": "DIAGNOSTIC"`；
* **不是** Phase 4C 的最终 scholarly evaluation，也不是新 benchmark 结果；
* 不修改 human review baseline / adjudication / 任何 frozen 产物；
* 评测行写到 `_data/eval/research_eval_results.4c1b.json`（新文件，不覆盖 v4c）。

用法
────
    python3 run_diagnostic_4c1b.py                 # 全部 27 题
    python3 run_diagnostic_4c1b.py --limit 3       # 只跑前 3 题（冒烟）
    python3 run_diagnostic_4c1b.py --quiet
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
TRACE_DIR = os.path.join(EVAL, "research_traces_4c1b")
OUT = os.path.join(EVAL, "research_eval_results.4c1b.json")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_answer as ans          # noqa: E402
import research_eval_4b as ev4b        # noqa: E402
import eval_integrity as ei            # noqa: E402

SCHEMA = "research-run-4c1b/v1"


def public_view(t):
    return {k: t[k] for k in ("task_id", "question", "language", "task_type",
                              "required_capabilities", "split")}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--tasks", default="")
    a = ap.parse_args(argv)

    tasks = [json.loads(l) for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"),
                                        encoding="utf-8") if l.strip()]
    if a.tasks:
        want = set(a.tasks.split(","))
        tasks = [t for t in tasks if t["task_id"] in want]
    if a.limit:
        tasks = tasks[:a.limit]

    os.makedirs(TRACE_DIR, exist_ok=True)
    rows, summaries = [], []
    t0 = time.time()
    for t in tasks:
        pub = public_view(t)
        run = ans.run_task(pub, record_gaps=False)
        row = ev4b.evaluate(t, run)
        trace = run["trace"]
        trace["marker"] = "DIAGNOSTIC"
        trace["diagnostic_phase"] = "Phase 4C.1-B"
        trace["diagnostic_disclaimer"] = (
            "DIAGNOSTIC run：用于观察 contract / lane / constraint 完成度，"
            "**不是** Phase 4C 最终 scholarly evaluation，也不得当作新 benchmark 结果。")
        with open(os.path.join(TRACE_DIR, "%s.json" % t["task_id"]), "w",
                  encoding="utf-8") as f:
            json.dump(run, f, ensure_ascii=False, indent=1)
        c = trace["research_contract"]
        v21 = trace["sufficiency_v21"]
        row.update({
            "schema_version": SCHEMA,
            "marker": "DIAGNOSTIC",
            "contract_type": c["contract_type"],
            "required_operations": len(c["required_operations"]),
            "missing_operations": c["missing_operations"],
            "required_lanes": c["required_lanes"],
            "missing_lanes": c["missing_lanes"],
            "failed_constraints": [x["value"] for x in c["failed_constraints"]],
            "relation_required": c["relation_evidence_required"],
            "relation_n": c["relation_evidence_n"],
            "missing_source_layers": c["missing_source_layers"],
            "formalism_state": (c.get("formalism") or {}).get("formalism_state"),
            "metadata_state": (c.get("metadata") or {}).get("metadata_state"),
            "evidence_usability": c["evidence_usability"]["counts"],
            "state_v2_only": v21["v2_final_state"],
            "state": v21["final_state"],
            "state_ceiling": v21["state_ceiling"],
            "completion_state": v21["completion_state"],
            "violated_rules": [v["code"] for v in v21["violated_rules"]],
            "transition": v21["transition"],
        })
        rows.append(row)
        summaries.append({"task_id": t["task_id"], "task_type": t["task_type"],
                          "state_v1_gold": t["answerability"],
                          "state_v2": v21["v2_final_state"],
                          "state_v21": v21["final_state"],
                          "violated": [v["code"] for v in v21["violated_rules"]]})
        if not a.quiet:
            print("  %-7s %-26s %-21s → %-21s %s" % (
                t["task_id"], t["task_type"], v21["v2_final_state"],
                v21["final_state"], [v["code"] for v in v21["violated_rules"]]))

    doc = {
        "schema_version": "research-eval-4c1b/v1",
        "marker": "DIAGNOSTIC",
        "phase": "Phase 4C.1-B",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - t0, 1),
        "tasks_n": len(rows),
        "evaluation_run_manifest": ei.jd(os.path.join(EVAL, "manifests", "latest.json")) or {},
        "state_counts_v2_only": dict(Counter(r["state_v2_only"] for r in rows)),
        "state_counts_v21": dict(Counter(r["state"] for r in rows)),
        "violated_rule_counts": dict(Counter(c for r in rows for c in r["violated_rules"])),
        "rows": rows,
        "summary": summaries,
        "disclaimer": ("DIAGNOSTIC：只用于观察契约/完成度判定，"
                       "不构成新的 scholarly evaluation，也不修改任何 frozen 结果。"),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    if not a.quiet:
        print("\nstate（v2 only）:", doc["state_counts_v2_only"])
        print("state（v2.1）   :", doc["state_counts_v21"])
        print("violated rules  :", doc["violated_rule_counts"])
        print("-> %s" % os.path.relpath(OUT, VAULT))
        print("-> %s/*.json" % os.path.relpath(TRACE_DIR, VAULT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
