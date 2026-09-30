#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_diagnostic_4c1b2.py — Phase 4C.1-B2 §27/§29：执行层 diagnostic rerun

与 4C.1-B 的 diagnostic 的区别
──────────────────────────────
* 4C.1-B（`research_traces_4c1b/`）：契约只是**事后校验**，27/27 missing operation。
* 4C.1-B2（`research_traces_4c1b2/`）：契约**先于执行**，调度器逐项执行 required
  obligations；本 diagnostic 用来度量 execution completion，而不是 SUPPORTED 数量。

纪律
────
* 新目录，**不覆盖** `research_traces_4c1b/` 或任何历史产物；
* 每条 trace 标 `marker: DIAGNOSTIC`、`phase: 4C.1-B2`；
* 不修改 human review baseline / adjudication / gold v1；
* §28：**不设 SUPPORTED 数量目标**，只报执行层指标。

用法
────
    python3 run_diagnostic_4c1b2.py [--limit N] [--quiet]
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
TRACE_DIR = os.path.join(EVAL, "research_traces_4c1b2")
OUT = os.path.join(EVAL, "research_eval_results.4c1b2.json")
PREV = os.path.join(EVAL, "research_eval_results.4c1b.json")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_answer as ans          # noqa: E402
import research_eval_4b as ev4b        # noqa: E402
import eval_integrity as ei            # noqa: E402

SCHEMA = "research-run-4c1b2/v1"


def public_view(t):
    return {k: t[k] for k in ("task_id", "question", "language", "task_type",
                              "required_capabilities", "split")}


def _rate(n, d):
    return round(n / d, 4) if d else None


def metrics(rows):
    """§29 执行层指标（全部来自 trace 的 execution 段，可逐条回查）。

    行的字段是 execution 段的**扁平化**投影（见 main 里的 row.update），
    这样结果文件不会把整份 execution 文档重复一遍。
    """
    def _rate(n, d):
        return round(n / d, 4) if d else None

    req_ops = [o for r in rows for o in (r.get("required_operations") or [])]
    # 「已执行的必需操作」= required ∩ executed（executed 里还含调度器新增的专项调用，
    # 直接拿它当分子会得到 >1 的假比率）
    done_ops = [o for r in rows for o in (r.get("required_operations") or [])
                if o in (r.get("executed_operations") or [])]
    skipped = [o for r in rows for o in (r.get("skipped_operations") or [])]
    req_lanes = [l for r in rows for l in (r.get("lanes") or []) if l.get("required")]
    resolved = ("EXECUTED", "SATISFIED", "ZERO_ATTESTATION_CONFIRMED",
                "STRUCTURALLY_UNAVAILABLE", "FAILED")
    done_lanes = [l for l in req_lanes if l.get("status") in resolved]
    cons = [c for r in rows for c in (r.get("constraints") or [])]
    app_cons = [c for c in cons if c.get("applied") is not None]
    rel_req = [r for r in rows if r.get("relation_required")]
    rel_exec = [r for r in rows if "find_relation_evidence" in
                (r.get("executed_operations") or [])]
    ep_req = [e for r in rows for e in (r.get("endpoints") or [])]
    ep_done = [e for e in ep_req if e.get("completion") == "COMPLETE"]
    term_req = [l for l in req_lanes if str(l.get("lane_id", "")).startswith("term:")]
    term_done = [l for l in term_req if l.get("status") in
                 ("SATISFIED", "ZERO_ATTESTATION_CONFIRMED")]
    form_req = [r for r in rows if r.get("formalism_state")]
    form_done = [r for r in form_req if r.get("formalism_evidence_n")]
    meta_req = [r for r in rows if r.get("metadata_state")]
    meta_done = [r for r in meta_req if r.get("metadata_state") != "NOT_REQUIRED"]
    src_req = [r for r in rows if r.get("source_layers")]
    src_done = [r for r in src_req
                if all(v in ("SATISFIED", "STRUCTURALLY_UNAVAILABLE")
                       for v in r["source_layers"].values())]
    return {
        "required_operation_completion_rate": _rate(len(done_ops), len(req_ops)),
        "required_operation_n": len(req_ops),
        "required_operation_executed_n": len(done_ops),
        "required_operation_skipped_n": len(skipped),
        "required_lane_completion_rate": _rate(len(done_lanes), len(req_lanes)),
        "required_lane_n": len(req_lanes),
        "required_lane_resolved_n": len(done_lanes),
        "required_constraint_completion_rate": _rate(len(app_cons), len(cons)),
        "required_constraint_n": len(cons),
        "required_constraint_recorded_n": len(app_cons),
        "relation_required_n": len(rel_req),
        "relation_executed_n": len(rel_exec),
        "diachronic_endpoint_required_n": len(ep_req),
        "diachronic_endpoint_completed_n": len(ep_done),
        "terminology_lane_required_n": len(term_req),
        "terminology_lane_completed_n": len(term_done),
        "formalism_required_n": len(form_req),
        "formalism_completed_n": len(form_done),
        "metadata_required_n": len(meta_req),
        "metadata_checked_n": len(meta_done),
        "source_layer_required_n": len(src_req),
        "source_layer_completed_n": len(src_done),
        "generic_fallback_used_n": sum(1 for r in rows
                                       if r.get("generic_fallback_used")),
        "generic_fallback_satisfied_required_lane_n":
            sum(int(r.get("generic_fallback_satisfied_required_lane_n") or 0)
                for r in rows),
        "execution_state_counts": dict(Counter(r.get("execution_state") for r in rows)),
        "lane_status_counts": dict(Counter(l.get("status") for l in req_lanes)),
        "operation_status_counts": dict(Counter(
            o.get("status") if isinstance(o, dict) else o
            for r in rows for o in (r.get("operation_statuses") or []))),
    }


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    tasks = [json.loads(l) for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"),
                                        encoding="utf-8") if l.strip()]
    if a.limit:
        tasks = tasks[:a.limit]
    prev = ei.jd(PREV) or {}
    prev_rows = {r["task_id"]: r for r in (prev.get("rows") or [])}

    os.makedirs(TRACE_DIR, exist_ok=True)
    rows, t0 = [], time.time()
    for t in tasks:
        pub = public_view(t)
        run = ans.run_task(pub, record_gaps=False)
        row = ev4b.evaluate(t, run)
        tr = run["trace"]
        tr["marker"] = "DIAGNOSTIC"
        tr["diagnostic_phase"] = "Phase 4C.1-B2"
        tr["diagnostic_disclaimer"] = (
            "DIAGNOSTIC（4C.1-B2）：用于度量 required operation / lane / constraint 的**执行完成度**，"
            "**不是** scholarly evaluation，也不得当作 SUPPORTED 数量的目标。")
        with open(os.path.join(TRACE_DIR, "%s.json" % t["task_id"]), "w",
                  encoding="utf-8") as f:
            json.dump(run, f, ensure_ascii=False, indent=1)
        ex = tr["execution"]
        row.update({
            "schema_version": SCHEMA, "marker": "DIAGNOSTIC",
            "execution_state": ex["state"],
            "required_operations": ex["required_operations"],
            "executed_operations": ex.get("executed_operations"),
            "skipped_operations": ex.get("skipped_operations"),
            "structurally_unavailable_operations":
                ex.get("structurally_unavailable_operations"),
            "lanes": [{"lane_id": l["lane_id"], "lane_type": l.get("lane_type"),
                       "required": l.get("required", True), "status": l["status"],
                       "usable_hit_count": l["usable_hit_count"],
                       "hit_count": l.get("hit_count"),
                       "constraint_applied": l["constraint_applied"]}
                      for l in ex["lanes"]],
            "constraints": ex["constraints"],
            "endpoints": ex.get("endpoints"),
            "formalism_evidence_n": (ex.get("formalism") or {}).get("formalism_evidence_n"),
            "operation_statuses": [{"operation_id": o["operation_id"],
                                    "status": o["status"]} for o in ex["operations"]],
            "generic_fallback_used": ex["generic_fallback"]["used"],
            "relation_required": bool((ex.get("relation") or {}).get("required")),
            "relation_n": (ex.get("relation") or {}).get("relation_evidence_n"),
            "relation_strength": (ex.get("relation") or {}).get("relation_strength"),
            "formalism_state": (ex.get("formalism") or {}).get("formalism_state"),
            "metadata_state": (ex.get("metadata") or {}).get("metadata_state"),
            "terminology": ex.get("terminology", {}).get("terms"),
            "source_layers": {k: v.get("status")
                              for k, v in (ex.get("source_layers") or {}).items()},
            "generic_fallback_satisfied_required_lane_n":
                ex["generic_fallback"]["satisfied_required_lane_n"],
            "budget": ex["budget"],
            "state_v2": (tr.get("sufficiency_v21") or {}).get("v2_final_state"),
            "state_v21": tr.get("final_state"),
            "violated_rules": [v["code"] for v in
                               (tr.get("sufficiency_v21") or {}).get("violated_rules") or []],
            "state_prev_4c1b": (prev_rows.get(t["task_id"]) or {}).get("state"),
            "missing_operations": tr["missing_operations"],
            "missing_lanes": tr["missing_lanes"],
        })
        rows.append(row)
        if not a.quiet:
            print("  %-7s %-24s exec=%-18s lanes=%d/%d ops=%d/%d %s" % (
                t["task_id"], t["task_type"], ex["state"],
                len([l for l in ex["lanes"] if l["required"] and l["status"] in
                     ("SATISFIED", "EXECUTED", "ZERO_ATTESTATION_CONFIRMED",
                      "STRUCTURALLY_UNAVAILABLE", "FAILED")]),
                len([l for l in ex["lanes"] if l["required"]]),
                len(ex.get("executed_operations") or []), len(ex["required_operations"]),
                ex.get("skipped_operations")))

    doc = {
        "schema_version": "research-eval-4c1b2/v1",
        "marker": "DIAGNOSTIC", "phase": "Phase 4C.1-B2",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - t0, 1),
        "tasks_n": len(rows),
        "evaluation_run_manifest": ei.jd(os.path.join(EVAL, "manifests", "latest.json")) or {},
        "metrics": metrics(rows),
        "state_counts_v21": dict(Counter(r["state_v21"] for r in rows)),
        "state_counts_exec": dict(Counter(r["execution_state"] for r in rows)),
        "state_counts_prev_4c1b": dict(Counter(r["state_prev_4c1b"] for r in rows)),
        "rows": rows,
        "disclaimer": ("DIAGNOSTIC 4C.1-B2：只度量执行完成度；"
                       "SUPPORTED 数量不是本阶段的成功指标（§28）。"),
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        m = doc["metrics"]
        print("\n执行层指标（§29）：")
        for k in ("required_operation_completion_rate", "required_lane_completion_rate",
                  "required_constraint_completion_rate", "relation_required_n",
                  "relation_executed_n", "diachronic_endpoint_required_n",
                  "diachronic_endpoint_completed_n", "terminology_lane_required_n",
                  "terminology_lane_completed_n", "formalism_required_n",
                  "formalism_completed_n", "metadata_required_n", "metadata_checked_n",
                  "source_layer_required_n", "source_layer_completed_n",
                  "generic_fallback_used_n",
                  "generic_fallback_satisfied_required_lane_n"):
            print("  %-46s %s" % (k, m.get(k)))
        print("  execution_state_counts:", m["execution_state_counts"])
        print("  lane_status_counts   :", m["lane_status_counts"])
        print("-> %s" % os.path.relpath(OUT, VAULT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
