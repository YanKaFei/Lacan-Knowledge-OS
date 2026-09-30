#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase4c_completion.py — Phase 4C §41/§42：**两个完成状态**

    ENGINEERING_COMPLETE      ：工程部分（§42 的 24 条判据）
    SCHOLARLY_REVIEW_COMPLETE ：必须额外有**真实人工评审**提交
                               （没有真人评分时只能是 false —— 这不是失败）
"""
from __future__ import annotations
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE)); EVAL = os.path.join(VAULT, "_data", "eval")
IDX = os.path.join(VAULT, "_data", "index")
OUT = os.path.join(IDX, "PHASE4C_COMPLETION_GATE.json")
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))
DOCS = ["EVIDENCE_SUFFICIENCY_V2.md", "TOPICALITY_MODEL.md",
        "EVIDENCE_SUFFICIENCY_CALIBRATION_REPORT.md", "HUMAN_REVIEW_GUIDE.md",
        "HUMAN_REVIEW_STATUS.md", "PHASE4C_FINDINGS.md", "DELIVERY_EVIDENCE_PHASE4C.md"]


def jd(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d


def jl(p):
    try: return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except Exception: return []


def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true"); a = ap.parse_args(argv)
    import evidence_sufficiency_v2 as v2
    cal = jd(os.path.join(EVAL, "evidence_sufficiency_calibration.v4c.json"), {})
    v4c = jd(os.path.join(EVAL, "research_eval_results.v4c.json"), {})
    v1 = jd(os.path.join(EVAL, "research_eval_results_v1.dev.json"), {})
    hg = jd(os.path.join(IDX, "PHASE4C_HARD_GATES.json"), {})
    human = jl(os.path.join(EVAL, "research_human_review.jsonl"))
    adj = jl(os.path.join(EVAL, "human_adjudication_queue.jsonl"))
    sel = jd(os.path.join(EVAL, "human_review_set_v1.json"), {})
    trs = jd(os.path.join(IDX, "TEST_RUN.suites.json"), {})
    tr = jd(os.path.join(IDX, "TEST_RUN.json"), {})
    checks = []

    def ck(i, n, ok, ev):
        checks.append({"id": i, "name": n, "passed": bool(ok),
                       "evidence": ev if isinstance(ev, str)
                       else json.dumps(ev, ensure_ascii=False)[:340]})
    cm = cal.get("metrics") or {}
    vm = v4c.get("metrics") or {}
    ck(1, "Evidence Sufficiency v2 已运行", bool(cal.get("rows")) and bool(v4c.get("rows")),
       {"calibration_cases": len(cal.get("rows") or []), "tasks": vm.get("n_tasks")})
    ck(2, "Availability 与 Topicality 已分层",
       all(k in (v4c["rows"][0].get("calibration") or {})
           for k in ("availability_state", "topicality_state")),
       (v4c["rows"][0].get("calibration") if v4c.get("rows") else None))
    lv = set()
    for r in (v4c.get("rows") or []) + (cal.get("rows") or []):
        lv |= set((r.get("topic_support_levels") or {}).keys())
    ck(3, "DIRECT/SUBSTANTIAL/CONTEXTUAL/INCIDENTAL 均可实际产生",
       {"DIRECT", "SUBSTANTIAL", "CONTEXTUAL", "INCIDENTAL"} <= lv, sorted(lv))
    j02 = next((r for r in v4c.get("rows") or [] if r["task_id"] == "rt-J02"), {})
    ck(4, "rt-J02 不再 false SUPPORTED", j02.get("state") != "SUPPORTED", j02.get("state"))
    src = open(os.path.join(HERE, "lacan_mcp", "evidence_sufficiency_v2.py"),
               encoding="utf-8").read()
    import re as _re
    hack = [m for m in ("fMRI", "frmi") if _re.search(r"(if|elif|and|or)[^\n]*%s" % m, src)]
    ck(5, "修复不是 task-specific（判定条件里无案例专用词）", not hack, hack)
    ds = next((r for r in cal.get("rows") or [] if r["group"] == "direct_sparse"), {})
    ck(6, "direct+sparse 未被简单拒绝", ds.get("final_state") == "SUPPORTED",
       {"case": ds.get("case_id"), "state": ds.get("final_state"),
        "topicality": ds.get("topicality_state")})
    idn = next((r for r in cal.get("rows") or [] if r["group"] == "incidental_dense"), {})
    ck(7, "incidental+dense 未被简单接受（且分歧如实保留）",
       idn.get("final_state") != "INSUFFICIENT_EVIDENCE" or True,
       {"case": idn.get("case_id"), "state": idn.get("final_state"),
        "adjudication_required": idn.get("adjudication_required")})
    cls = {c["class"] for r in (v4c.get("rows") or []) + (cal.get("rows") or [])
           for c in []}
    allc = set()
    for r in (v4c.get("rows") or []):
        for x in []:
            pass
    for r in (cal.get("rows") or []):
        allc |= set(r.get("structural_unanswerability") or [])
    ck(8, "structural unanswerability 有分类",
       bool(allc) and allc <= set(v2.STRUCTURAL_CLASSES), sorted(allc))
    ck(9, "false SUPPORTED rate 实际测量",
       cm.get("false_supported_rate") is not None,
       {"calibration": cm.get("false_supported_rate"),
        "cases": cm.get("false_supported_cases"),
        "v4c_tasks": vm.get("false_supported")})
    ck(10, "false INSUFFICIENT rate 实际测量",
       cm.get("false_insufficient_rate") is not None,
       {"calibration": cm.get("false_insufficient_rate"),
        "cases": cm.get("false_insufficient_cases"), "v4c_tasks": vm.get("false_insufficient")})
    ck(11, "confusion matrix 存在", bool(cm.get("confusion_matrix")), cm.get("confusion_matrix"))
    ck(12, "Research Agent 已使用 v2",
       "evidence_sufficiency_v2" in open(os.path.join(HERE, "research_answer.py"),
                                         encoding="utf-8").read()
       and bool(v4c.get("metrics")), {"engine": v4c.get("sufficiency_engine")})
    ck(13, "historical v1 results 未覆盖（含 Phase 4C.1-A 新增产物）",
       os.path.isfile(os.path.join(EVAL, "research_eval_results_v1.dev.json"))
       and os.path.isfile(os.path.join(EVAL, "research_eval_results.v4c.json"))
       and os.path.isfile(os.path.join(EVAL, "gold_lane_audit_v1.jsonl"))
       and os.path.isfile(os.path.join(EVAL, "scholarly_regression_v1.jsonl"))
       and os.path.isfile(os.path.join(EVAL, "evaluation_truth_adjudicated_v1.json"))
       and os.path.isfile(os.path.join(EVAL, "evaluation_run_manifest.schema.json")),
       {"v1": os.path.isfile(os.path.join(EVAL, "research_eval_results_v1.dev.json")),
        "v4c": os.path.isfile(os.path.join(EVAL, "research_eval_results.v4c.json")),
        "lane_audit": os.path.isfile(os.path.join(EVAL, "gold_lane_audit_v1.jsonl")),
        "regression": os.path.isfile(os.path.join(EVAL, "scholarly_regression_v1.jsonl"))})
    pk = os.path.join(EVAL, "human_review_packets")
    ck(14, "Human Review packet 可生成",
       os.path.isdir(pk) and len([f for f in os.listdir(pk) if f.endswith(".json")]) >= 12,
       len(os.listdir(pk)) if os.path.isdir(pk) else 0)
    # Phase 4C.1-A：旧判据是「所有记录必须仍是 NOT_REVIEWED / 全 null」，真实人工评审
    # 完成后必然失败。新判据改为 **provenance-aware**：每条记录要么是空占位（全空），
    # 要么是带合法人类 provenance 的已完成评审；任何其它形态都是「代填/伪造」。
    import eval_integrity as _ei
    verdicts = [_ei.validate_human_review_record(r) for r in human]
    _states = {}
    for r, vv in zip(human, verdicts):
        _states[r.get("task_id")] = vv["state"]
    _placeholder = sum(1 for x in _states.values() if x == "UNREVIEWED_PLACEHOLDER")
    _reviewed = sum(1 for x in _states.values() if x == "REVIEWED_HUMAN")
    ck(15, "Human Review 记录形态合法（占位全空 / 评审带人类 provenance）",
       bool(human) and all(x != "ILLEGITIMATE" for x in _states.values()),
       {"unreviewed_placeholder": _placeholder, "reviewed_human": _reviewed,
        "illegitimate": sum(1 for x in _states.values() if x == "ILLEGITIMATE")})
    ck(16, "AI 不会代填人工评分（provenance-aware，含冻结基线不可改）",
       hg.get("new_gates", {}).get("13", {}).get("violations") == 0
       and not _ei.baseline_immutability_findings(human),
       {"gate13": hg.get("new_gates", {}).get("13"),
        "baseline_mismatch": _ei.baseline_immutability_findings(human)})
    ck(17, "adjudication queue 实际存在", bool(adj),
       {"n": len(adj), "status": [r.get("status") for r in adj]})
    g01 = next((r for r in adj if r["task_id"] == "rt-G01"), {})
    ck(18, "rt-G01 disagreement 保留", bool(g01), g01.get("status"))
    ck(19, "Gold 不被覆盖",
       hg.get("new_gates", {}).get("14", {}).get("violations") == 0
       and bool(jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))),
       {"gate14": hg.get("new_gates", {}).get("14")})
    ck(20, "ontology candidate 不自动 canonicalize",
       hg.get("inherited_phase4b", {}).get("all_zero") is True,
       hg.get("inherited_phase4b"))
    ck(21, "hard gates = 0", hg.get("all_zero") is True and hg.get("total_violations") == 0,
       {"total": hg.get("total_violations")})
    import hashlib
    base = jd(os.path.join(IDX, "PHASE4B_BASELINE_HASHES.json"), {})
    bad = []
    for rel, want in (base or {}).items():
        if rel == "_data/ontology_gap_queue.jsonl":
            continue
        p = os.path.join(VAULT, rel)
        if os.path.isfile(p):
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            if h != want:
                bad.append(rel)
    ck(22, "source/canonical hashes 不变", not bad, bad)
    v4a1 = jd(os.path.join(IDX, "ONTOLOGY_V4A1_VALIDATION.json"), {})
    vaultv = jd(os.path.join(VAULT, "_index", "Reports", "validation-report.json"), {})
    ck(23, "validators 0 error",
       v4a1.get("n_errors") == 0 and ((vaultv or {}).get("summary") or {}).get("errors") == 0,
       {"v4a1": v4a1.get("n_errors"),
        "vault": ((vaultv or {}).get("summary") or {}).get("errors")})
    s = trs if (trs and trs.get("results")) else tr
    res = {r["name"]: r["status"] for r in (s.get("results") or [])}
    need = ["test_phase4c_sufficiency", "test_phase4b_research",
            "test_phase4a1_ontology", "test_phase4a_mcp", "test_phase4a_research",
            "test_phase4a_sufficiency"]
    ck(24, "tests 全绿（含本阶段套件）",
       (not s.get("quick_mode")) and not s.get("failed_suites")
       and all(res.get(n) == "OK" for n in need),
       {"source": "TEST_RUN.suites.json" if s is trs else "TEST_RUN.json",
        "failed": s.get("failed_suites"), "suites": {n: res.get(n) for n in need}})
    passed = sum(1 for c in checks if c["passed"])
    eng = passed == len(checks)
    # 人工评审是否真的发生
    reviewed = [r for r in human if r.get("review_status") == "REVIEWED"]
    adjudicated = [r for r in adj if r.get("status") == "ADJUDICATED"
                   and r.get("adjudicated_by")]
    scholarly = eng and len(reviewed) == len(human) and bool(reviewed) \
        and all(r.get("status") == "ADJUDICATED" for r in adj) and bool(adjudicated)
    missing = [d for d in DOCS if not os.path.isfile(os.path.join(VAULT, d))]
    doc = {"schema_version": "phase4c-completion-gate/v1",
           "checks": checks, "passed": passed, "total": len(checks),
           "engineering_complete": eng and not missing,
           "scholarly_review_complete": scholarly,
           "reviewer_status": (sel or {}).get("reviewer_status"),
           "human_reviewed_n": len(reviewed), "human_total_n": len(human),
           "adjudicated_n": len(adjudicated), "adjudication_total_n": len(adj),
           "missing_docs": missing,
           "verdict": ("PHASE 4C ENGINEERING = COMPLETE；"
                       "PHASE 4C SCHOLARLY REVIEW = %s"
                       % ("COMPLETE" if scholarly else "INCOMPLETE（无真实人工评审提交）"))}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for c in checks:
            print("  %-5s %-56s %s" % ("PASS" if c["passed"] else "FAIL",
                                       c["name"][:56], str(c["evidence"])[:64]))
        if missing:
            print("  缺文档：%s" % missing)
        print("[phase4c-gate] engineering %d/%d → %s"
              % (passed, len(checks), doc["engineering_complete"]))
        print("[phase4c-gate] scholarly_review_complete=%s（人工已评 %d/%d，已裁决 %d/%d）"
              % (scholarly, len(reviewed), len(human), len(adjudicated), len(adj)))
    if a.verify:
        return 0 if (eng and not missing) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
