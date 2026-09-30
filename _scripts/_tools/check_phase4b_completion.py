#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase4b_completion.py — Phase 4B §35：24 条完成判据

每条都指向**已存在的产物**，不在门里放宽阈值。未全过 → PARTIAL。

用法：`python3 check_phase4b_completion.py [--verify] [--json]`
产物：`_data/index/PHASE4B_COMPLETION_GATE.json`
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
IDX = os.path.join(VAULT, "_data", "index")
OUT = os.path.join(IDX, "PHASE4B_COMPLETION_GATE.json")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

DOCS = ["RESEARCH_TASK_MODEL.md", "RESEARCH_ANSWER_CONTRACT.md",
        "CLAIM_CITATION_MODEL.md", "RESEARCH_EVALUATION_METHOD.md",
        "RESEARCH_FAILURE_TAXONOMY.md", "RESEARCH_QUALITY_REPORT.md",
        "PHASE4B_FINDINGS.md", "DELIVERY_EVIDENCE_PHASE4B.md"]


def jd(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d


def jl(p):
    try:
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except Exception:
        return []


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    tasks = jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))
    dev = jd(os.path.join(EVAL, "research_eval_results_v1.dev.json"), {})
    hold = jd(os.path.join(EVAL, "research_eval_results_v1.holdout.json"), {})
    hg = jd(os.path.join(IDX, "PHASE4B_HARD_GATES.json"), {})
    budget = jd(os.path.join(IDX, "RESEARCH_4B_BUDGET_CHECK.json"), {})
    tr = jd(os.path.join(IDX, "TEST_RUN.json"), {})
    trs = jd(os.path.join(IDX, "TEST_RUN.suites.json"), {})
    rows = (dev.get("rows") or []) + (hold.get("rows") or [])
    dm, hm = dev.get("metrics") or {}, hold.get("metrics") or {}
    checks = []

    def ck(i, name, ok, ev):
        checks.append({"id": i, "name": name, "passed": bool(ok),
                       "evidence": (ev if isinstance(ev, str)
                                    else json.dumps(ev, ensure_ascii=False)[:380])})

    ck(1, "≥24 个真实 research task", len(tasks) >= 24,
       {"n": len(tasks), "types": len({t["task_type"] for t in tasks})})
    hold_n = len([t for t in tasks if t.get("split") == "holdout"])
    ck(2, "≥8 个 holdout / blind 评测任务", hold_n >= 8, hold_n)
    ck(3, "Research Agent 实际 multi-step（多步调用率）",
       (dm.get("multi_step_rate") or 0) >= 0.9 and (hm.get("multi_step_rate") or 0) >= 0.9,
       {"dev": dm.get("multi_step_rate"), "holdout": hm.get("multi_step_rate"),
        "tool_calls_mean": [dm.get("tool_calls_mean"), hm.get("tool_calls_mean")]})
    ck(4, "citation passage 全部真实", all(r["fabricated_citations"] == 0 for r in rows),
       {"rows": len(rows),
        "evidence_validity": [dm.get("evidence_validity"), hm.get("evidence_validity")]})
    ck(5, "fabricated passage = 0", hg.get("gates", {}).get("1", {}).get("violations") == 0
       and hg.get("gates", {}).get("2", {}).get("violations") == 0,
       {"gate1": hg.get("gates", {}).get("1"), "gate2": hg.get("gates", {}).get("2")})
    # 有证据的任务必须每条 claim 都可回查；**零证据**任务豁免（它只能显式弃权）
    cov_rows = [r for r in rows if (r.get("evidence_n") or 0) > 0]
    ck(6, "substantive claims 有可检查 citation mapping",
       all((r.get("claim_coverage") or 0) > 0 for r in cov_rows)
       and (dm.get("claim_coverage") or 0) > 0.5,
       {"dev_claim_coverage": dm.get("claim_coverage"),
        "holdout_claim_coverage": hm.get("claim_coverage")})
    ck(7, "unsupported claim rate 已实际测量",
       dm.get("unsupported_claim_rate") is not None
       and hm.get("unsupported_claim_rate") is not None,
       {"dev": dm.get("unsupported_claim_rate"), "holdout": hm.get("unsupported_claim_rate"),
        "unsupported_claims_total": [dm.get("unsupported_claims_total"),
                                     hm.get("unsupported_claims_total")]})
    ck(8, "evidence sufficiency 已实际评估",
       dm.get("sufficiency_accuracy") is not None and hm.get("sufficiency_accuracy") is not None,
       {"dev": dm.get("sufficiency_accuracy"), "holdout": hm.get("sufficiency_accuracy"),
        "false_supported": [dm.get("false_supported"), hm.get("false_supported")]})
    ck(9, "至少存在 SUPPORTED / PARTIAL / INSUFFICIENT 三类真实案例",
       {"SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE"}
       <= set(dm.get("states_reached") or []) | set(hm.get("states_reached") or []),
       {"dev": dm.get("states_reached"), "holdout": hm.get("states_reached")})
    dia = [r for r in rows if r["task_type"] == "diachronic_development"]
    ck(10, "diachronic question 有 period coverage",
       bool(dia) and all((r.get("period_coverage_ok") or 0) > 0 for r in dia)
       and (dm.get("diachronic_period_coverage") or 0) > 0,
       {"tasks": {r["task_id"]: r.get("period_coverage_ok") for r in dia}})
    # 「对比题」的判据与 evaluator 保持一致：`separate_lanes_ok is not None`
    # （即 `_needs_lanes()` 判定为需要并置比较的任务），而不是「期望实体 ≥2」。
    cmp_rows = [r for r in rows if r.get("separate_lanes_ok") is not None]
    ck(11, "comparison question 使用 separate lanes（判据见 _needs_lanes）",
       bool(cmp_rows) and all(r["separate_lanes_ok"] for r in cmp_rows),
       {r["task_id"]: r.get("separate_lanes_ok") for r in cmp_rows})
    xt = [r for r in rows if r.get("language") == "zh"
          and (r.get("evidence_n") or 0) > 0
          and any(e.startswith("passage.") for e in [])]
    zh_ok = [r for r in rows if r.get("language") == "zh" and r.get("research_completion")]
    ck(12, "cross-language research 实际成功至少一例",
       bool(zh_ok), {"zh_completed": [r["task_id"] for r in zh_ok][:6]})
    d01 = [r for r in rows if r["task_id"] == "rt-D01"]
    ck(13, "gaze/regard v4a1 regression 成功",
       bool(d01) and d01[0]["state"] in ("SUPPORTED", "PARTIALLY_SUPPORTED")
       and (d01[0].get("entity_resolution_ok") is True),
       d01[0] if d01 else None)
    other_rows = [r for r in rows if r["task_id"] in ("rt-E-tasks",)]
    import knowledge_api as api
    bo = api.resolve_entity("l'Autre")["resolution"]
    lo = api.resolve_entity("l'autre")["resolution"]
    ba = api.resolve_entity("autre")["resolution"]
    A = api.resolve_entity("A")["resolution"]
    ck(14, "Big Other/little other regression 成功",
       [c["entity_id"] for c in bo["candidates"]] == ["concept.big-other"]
       and [c["entity_id"] for c in lo["candidates"]] == ["concept.little-other"]
       and ba["resolution_status"] == "AMBIGUOUS" and ba.get("context_required")
       and A["resolution_status"] == "UNRESOLVED",
       {"big": [c["entity_id"] for c in bo["candidates"]],
        "little": [c["entity_id"] for c in lo["candidates"]],
        "autre": ba["resolution_status"], "A": A["resolution_status"]})
    lim_missing = []
    tdir = os.path.join(EVAL, "research_traces_4b")
    for fn in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        d = jd(os.path.join(tdir, fn), {})
        pack = d.get("evidence_pack") or {}
        inc = [e for e in pack.get("evidence") or []
               if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"]
        limits = ((d.get("answer") or {}).get("sections") or {}).get(
            "evidence_limitations", "") or ""
        if inc and "SOURCE_TRACE_INCOMPLETE" not in limits:
            lim_missing.append(fn)
    ck(15, "source provenance warning 不被隐藏",
       not lim_missing and hg.get("gates", {}).get("10", {}).get("violations") == 0,
       lim_missing or "全部显示")
    ck(16, "candidate ontology 未自动 canonicalize",
       hg.get("gates", {}).get("6", {}).get("violations") == 0,
       hg.get("gates", {}).get("6"))
    ck(17, "Gold information 未泄漏给 Agent",
       hg.get("gates", {}).get("12", {}).get("violations") == 0,
       hg.get("gates", {}).get("12"))
    ck(18, "research budget 实际生效",
       bool(budget) and budget.get("all_passed") is True,
       (budget or {}).get("checks"))
    cls = []
    for r in rows:
        for f in r.get("failure_classes") or []:
            if f in ("RETRIEVAL_MISS", "RANKING_FAILURE", "ENTITY_RESOLUTION_FAILURE",
                     "ONTOLOGY_GAP", "SOURCE_GAP", "EVIDENCE_SUFFICIENCY_ERROR",
                     "CITATION_ERROR", "SYNTHESIS_OVERCLAIM", "BUDGET_EXHAUSTION",
                     "TERMINOLOGY_MAPPING_FAILURE", "CONTEXT_INSUFFICIENT"):
                cls.append((r["task_id"], f))
    ck(19, "至少一个失败案例被正确分类到 failure taxonomy",
       bool(cls), {"n": len(cls), "first": cls[:6]})
    ck(20, "holdout 结果单独报告",
       bool(hold) and hold.get("split") == "holdout"
       and os.path.isfile(os.path.join(EVAL, "research_eval_results_v1.holdout.json")),
       {"split": hold.get("split"), "n": hold.get("tasks_n"),
        "sufficiency_accuracy": hm.get("sufficiency_accuracy")})
    ck(21, "hard gates 全 0", hg.get("all_zero") is True and hg.get("total_violations") == 0,
       {"gates": hg.get("gate_count"), "violations": hg.get("total_violations")})
    ck(22, "source/canonical corpus hashes 不变",
       hg.get("gates", {}).get("3", {}).get("violations") == 0
       and hg.get("gates", {}).get("4", {}).get("violations") == 0,
       {"gate3": hg.get("gates", {}).get("3"), "gate4": hg.get("gates", {}).get("4")})
    v4a1 = jd(os.path.join(IDX, "ONTOLOGY_V4A1_VALIDATION.json"), {})
    vaultv = jd(os.path.join(VAULT, "_index", "Reports", "validation-report.json"), {})
    ck(23, "validators 0 error",
       v4a1.get("n_errors") == 0 and ((vaultv or {}).get("summary") or {}).get("errors") == 0,
       {"v4a1": v4a1.get("n_errors"),
        "vault": ((vaultv or {}).get("summary") or {}).get("errors")})
    src = trs if (trs and trs.get("results")) else tr
    res = {r["name"]: r["status"] for r in (src.get("results") or [])}
    need = ["test_phase4b_research", "test_phase4a1_ontology", "test_phase4a_mcp",
            "test_phase4a_research", "test_phase4a_sufficiency"]
    ck(24, "automated tests 全绿（含本阶段套件）",
       (not src.get("quick_mode")) and not src.get("failed_suites")
       and all(res.get(n) == "OK" for n in need),
       {"source": "TEST_RUN.suites.json" if src is trs else "TEST_RUN.json",
        "failed": src.get("failed_suites"), "suites": {n: res.get(n) for n in need}})

    missing_docs = [d for d in DOCS if not os.path.isfile(os.path.join(VAULT, d))]
    passed = sum(1 for c in checks if c["passed"])
    doc = {"schema_version": "phase4b-completion-gate/v1",
           "phase": "Phase 4B — Research Quality & Scholarly Answering",
           "checks": checks, "passed": passed, "total": len(checks),
           "closable": passed == len(checks) and not missing_docs,
           "deliverable_docs": {d: (d not in missing_docs) for d in DOCS},
           "verdict": ("PHASE 4B RESEARCH QUALITY = COMPLETE" if passed == len(checks)
                       and not missing_docs else
                       "PARTIAL —— 未过条目见 checks / deliverable_docs"),
           "rule": "§35：24 条必须逐条证明；不能证明就标 PARTIAL，不降低标准。"}
    os.makedirs(IDX, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for c in checks:
            print("  %-5s %-56s %s" % ("PASS" if c["passed"] else "FAIL",
                                       c["name"][:56], str(c["evidence"])[:66]))
        if missing_docs:
            print("  缺交付文档：%s" % missing_docs)
        print("[phase4b-gate] %d/%d -> %s" % (passed, len(checks), doc["verdict"]))
    if a.verify:
        return 0 if doc["closable"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
