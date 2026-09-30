#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_diagnostic_4c1b3.py — Phase 4C.1-B3：Execution Closure diagnostic rerun

与 4C.1-B 的 diagnostic 的区别
──────────────────────────────
* 4C.1-B（`research_traces_4c1b/`）：契约只是**事后校验**，27/27 missing operation。
* 4C.1-B2（`research_traces_4c1b2/`）：契约**先于执行**，调度器逐项执行 required obligations。
* 4C.1-B3（`research_traces_4c1b3/`）：执行**闭环** —— metadata→NOT_APPLICABLE、
  预算类别隔离、formalism 分级检索、terminology 三层完成语义；本 diagnostic 同时报
  `raw_executed_rate`（真执行）与 `resolved_obligation_rate`（含合法 NOT_APPLICABLE /
  结构性不可得），两者不得互相冒充。

纪律
────
* 新目录，**不覆盖** `research_traces_4c1b/` 或任何历史产物；
* 每条 trace 标 `marker: DIAGNOSTIC`、`phase: 4C.1-B3`；
* 不修改 human review baseline / adjudication / gold v1；
* §28：**不设 SUPPORTED 数量目标**，只报执行层指标。

用法
────
    python3 run_diagnostic_4c1b3.py [--limit N] [--quiet]
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
TRACE_DIR = os.path.join(EVAL, "research_traces_4c1b3")
OUT = os.path.join(EVAL, "research_eval_results.4c1b3.json")
PREV = os.path.join(EVAL, "research_eval_results.4c1b2.json")
PREV_SNAPSHOT = os.path.join(EVAL,
                             "research_eval_results.4c1b2.metrics_snapshot.json")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_answer as ans          # noqa: E402
import research_eval_4b as ev4b        # noqa: E402
import eval_integrity as ei            # noqa: E402

SCHEMA = "research-run-4c1b3/v1"



# ── 写前守卫（事故防复发，见 research_traces_4c1b2/RESTORATION_NOTE.md）：
#    本脚本**只允许**写自己的 B3 产物；任何越界路径直接拒绝。
ALLOWED_TRACE_DIR = os.path.join(EVAL, "research_traces_4c1b3")
ALLOWED_OUT = os.path.join(EVAL, "research_eval_results.4c1b3.json")


def _guard_paths():
    if os.path.abspath(TRACE_DIR) != os.path.abspath(ALLOWED_TRACE_DIR):
        raise SystemExit("拒绝写入：TRACE_DIR=%s 不在 B3 产物路径下" % TRACE_DIR)
    if os.path.abspath(OUT) != os.path.abspath(ALLOWED_OUT):
        raise SystemExit("拒绝写入：OUT=%s 不是 B3 汇总文件" % OUT)


def _trace_path(task_id):
    p = os.path.abspath(os.path.join(TRACE_DIR, "%s.json" % task_id))
    if not p.startswith(os.path.abspath(ALLOWED_TRACE_DIR) + os.sep):
        raise SystemExit("拒绝写入：trace 路径越界 %s" % p)
    return p



def rc_not_applicable_ok(rec):
    """Gate 19 同款判据：NOT_APPLICABLE 是否有 whole-corpus 结构凭据。"""
    dep = (rec or {}).get("structural_dependency") or {}
    if dep.get("upstream_operation") != "metadata_check":
        return False
    for pr in dep.get("proofs") or []:
        scan = (pr or {}).get("corpus_scan") or {}
        if (scan.get("executed") is True and scan.get("scope") == "whole_corpus"
                and int(scan.get("n_with_real_value") or 0) == 0
                and (pr or {}).get("availability") in ("GLOBAL_UNKNOWN", "FIELD_ABSENT")):
            return True
    return False


def public_view(t):
    return {k: t[k] for k in ("task_id", "question", "language", "task_type",
                              "required_capabilities", "split")}


def _rate(n, d):
    return round(n / d, 4) if d else None


def metrics(rows):
    """Phase 4C.1-B3 §6 指标（全部来自 trace 的 execution / research_contract 段）。

    §6 的关键区分：
      raw_executed_rate        = EXECUTED / required_operation
      resolved_obligation_rate = (EXECUTED + 合法 NOT_APPLICABLE + STRUCTURALLY_UNAVAILABLE)
                                 / required_operation
    两者分开报；NOT_APPLICABLE 永不进 raw 分子，因此不会用语义手段制造假的 100%。
    """
    def _rate(n, d):
        return round(n / d, 4) if d else None

    req_ops = [o for r in rows for o in (r.get("required_operations") or [])]
    status_of = {}
    for r in rows:
        for o in (r.get("operation_statuses") or []):
            if isinstance(o, dict):
                status_of[(r["task_id"], o.get("operation_id"))] = o.get("status")
        for op in (r.get("required_operations") or []):
            status_of.setdefault((r["task_id"], op), None)
    def _st(r, op):
        return (({o.get("operation_id"): o.get("status")
                  for o in (r.get("operation_statuses") or []) if isinstance(o, dict)})
                .get(op))
    raw_done = [op for r in rows for op in (r.get("required_operations") or [])
                if _st(r, op) == "EXECUTED"]
    na_proven = [op for r in rows for op in (r.get("required_operations") or [])
                 if _st(r, op) == "NOT_APPLICABLE"
                 and (r.get("not_applicable_proven") or {}).get(op)]
    struct = [op for r in rows for op in (r.get("required_operations") or [])
              if _st(r, op) == "STRUCTURALLY_UNAVAILABLE"]
    req_lanes = [l for r in rows for l in (r.get("lanes") or []) if l.get("required")]
    resolved_lane_states = ("EXECUTED", "SATISFIED", "ZERO_ATTESTATION_CONFIRMED",
                            "STRUCTURALLY_UNAVAILABLE", "NOT_APPLICABLE", "FAILED")
    done_lanes = [l for l in req_lanes if l.get("status") in resolved_lane_states]
    cons = [c for r in rows for c in (r.get("constraints") or [])]
    app_cons = [c for c in cons if c.get("applied") is not None]
    rel_req = [r for r in rows if r.get("relation_required")]
    rel_exec = [r for r in rows
                if _st(r, "find_relation_evidence") == "EXECUTED"]
    ep_req = [e for r in rows for e in (r.get("endpoints") or [])]
    ep_done = [e for e in ep_req if e.get("completion") == "COMPLETE"]
    term_req = [l for l in req_lanes if str(l.get("lane_id", "")).startswith("term:")]
    term_done = [l for l in term_req if l.get("status") in
                 ("SATISFIED", "ZERO_ATTESTATION_CONFIRMED")]
    # 行的 formalism_state / metadata_state 来自 execution 段（已扁平化）；
    # NOT_REQUIRED / None 表示该任务没有该义务
    form_req = [r for r in rows
                if (r.get("formalism_state") or "") not in ("", "NOT_REQUIRED", None)]
    form_done = [r for r in form_req if (r.get("formalism_evidence_n") or 0) > 0]
    meta_req = [r for r in rows
                if (r.get("metadata_state") or "") not in ("", "NOT_REQUIRED", None)]
    meta_checked = [r for r in meta_req
                    if r.get("metadata_state") in ("METADATA_AVAILABLE",
                                                   "METADATA_UNAVAILABLE")]
    src_lanes = [l for l in req_lanes if str(l.get("lane_id", "")).startswith("source_layer:")]
    src_resolved = [l for l in src_lanes if l.get("status") in resolved_lane_states]
    # terminology 三层（**分开**统计，不合并成一个「完成率」）
    tmap, tatt, tctx = Counter(), Counter(), Counter()
    for r in rows:
        terms = r.get("terminology") or {}
        if isinstance(terms, dict) and "terms" in terms:
            terms = terms.get("terms") or {}
        for t_, v in (terms or {}).items():
            if not isinstance(v, dict):
                continue
            tmap[v.get("mapping_completion")] += 1
            tatt[v.get("attestation_completion")] += 1
            tctx[v.get("context_validation")] += 1
    strategies = Counter()
    for r in rows:
        for k, v in ((r.get("formalism") or {}).get("strategy_counts") or {}).items():
            strategies[k] += int(v or 0)
    return {
        # ── §6 两个完成率
        "required_operation_n": len(req_ops),
        "required_operation_executed_n": len(raw_done),
        "required_operation_not_applicable_n": len(na_proven),
        "required_operation_structurally_unavailable_n": len(struct),
        "raw_executed_rate": _rate(len(raw_done), len(req_ops)),
        "resolved_obligation_rate": _rate(len(raw_done) + len(na_proven) + len(struct),
                                          len(req_ops)),
        # 兼容 B2 口径（= raw，等价旧 required_operation_completion_rate）
        "required_operation_completion_rate": _rate(len(raw_done), len(req_ops)),
        "required_operation_skipped_n": sum(
            1 for r in rows for o in (r.get("operation_statuses") or [])
            if isinstance(o, dict) and o.get("status") == "SKIPPED_WITH_REASON"),
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
        "terminology_mapping_completion": dict(tmap),
        "terminology_attestation_completion": dict(tatt),
        "terminology_context_validation_completion": dict(tctx),
        "formalism_required_n": len(form_req),
        "formalism_completed_n": len(form_done),
        "formalism_match_strategies": dict(strategies),
        "metadata_required_n": len(meta_req),
        "metadata_checked_n": len(meta_checked),
        "source_layer_lane_n": len(src_lanes),
        "source_layer_lane_resolved_n": len(src_resolved),
        "source_layer_budget_starved_n": sum(
            1 for l in src_lanes if l.get("status") in ("NOT_STARTED", "SKIPPED_WITH_REASON")),
        "generic_fallback_used_n": sum(1 for r in rows if r.get("generic_fallback_used")),
        "generic_fallback_satisfied_required_lane_n":
            sum(int(r.get("generic_fallback_satisfied_required_lane_n") or 0)
                for r in rows),
        "budget_overcommit_n": sum(1 for r in rows
                                   if (r.get("budget_plan") or {}).get("overcommit")),
        "budget_exhausted_n": sum(1 for r in rows
                                  if (r.get("budget") or {}).get("exhausted")),
        "budget_class_exhausted_counts": dict(Counter(
            c for r in rows for c in ((r.get("budget") or {}).get("exhausted_classes") or []))),
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
    if len(prev_rows) < len(tasks):
        # B2 汇总文件在 B3 开发期被一次 --limit 3 覆盖过（见 RESTORATION_NOTE.md）：
        # 回退到事故前恢复出来的**指标快照**里的逐任务摘要（只取 state / exec_state）。
        snap = ei.jd(PREV_SNAPSHOT) or {}
        prev_rows = {}
        for line in (snap.get("per_task_summary") or []):
            parts = str(line).split()
            if len(parts) >= 4 and parts[0].startswith("rt-"):
                prev_rows[parts[0]] = {"state": parts[2], "execution_state": parts[3]}

    _guard_paths()
    os.makedirs(TRACE_DIR, exist_ok=True)
    rows, t0 = [], time.time()
    for t in tasks:
        pub = public_view(t)
        run = ans.run_task(pub, record_gaps=False)
        row = ev4b.evaluate(t, run)
        tr = run["trace"]
        tr["marker"] = "DIAGNOSTIC"
        tr["diagnostic_phase"] = "Phase 4C.1-B3"
        tr["diagnostic_disclaimer"] = (
            "DIAGNOSTIC（4C.1-B3）：度量 required operation / lane / constraint 的**执行闭环**"
            "（NOT_APPLICABLE 语义 / 预算类别隔离 / formalism 分级检索 / terminology 三层完成），"
            "**不是** scholarly evaluation，也不得当作 SUPPORTED 数量的目标。")
        with open(_trace_path(t["task_id"]), "w",
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
            "budget_plan": (ex.get("budget") or {}).get("plan") or {},
            "formalism": ex.get("formalism") or {},
            "terminology_completion": {
                "mapping": (ex.get("terminology") or {}).get("mapping_completion_counts"),
                "attestation": (ex.get("terminology") or {}).get(
                    "attestation_completion_counts"),
                "context_validation": (ex.get("terminology") or {}).get(
                    "context_validation_counts")},
            "not_applicable_proven": {
                o["operation_id"]: bool(rc_not_applicable_ok(o))
                for o in (ex.get("operations") or [])
                if o.get("status") == "NOT_APPLICABLE"},
            "raw_executed_rate": tr["execution_completion"].get("raw_executed_rate"),
            "resolved_obligation_rate":
                tr["execution_completion"].get("resolved_obligation_rate"),
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
        "schema_version": "research-eval-4c1b3/v1",
        "marker": "DIAGNOSTIC", "phase": "Phase 4C.1-B3",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - t0, 1),
        "tasks_n": len(rows),
        "evaluation_run_manifest": ei.jd(os.path.join(EVAL, "manifests", "latest.json")) or {},
        "metrics": metrics(rows),
        "state_counts_v21": dict(Counter(r["state_v21"] for r in rows)),
        "state_counts_exec": dict(Counter(r["execution_state"] for r in rows)),
        "state_counts_prev_4c1b": dict(Counter(r["state_prev_4c1b"] for r in rows)),
        "rows": rows,
        "disclaimer": ("DIAGNOSTIC 4C.1-B3：度量执行闭环与义务解决率；"
                       "raw_executed_rate 与 resolved_obligation_rate 分开报，"
                       "SUPPORTED 数量不是本阶段的成功指标。"),
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        m = doc["metrics"]
        print("\n执行层指标（B3 §6）：")
        for k in ("raw_executed_rate", "resolved_obligation_rate",
                  "required_operation_n", "required_operation_executed_n",
                  "required_operation_not_applicable_n",
                  "required_operation_structurally_unavailable_n",
                  "required_lane_completion_rate",
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
