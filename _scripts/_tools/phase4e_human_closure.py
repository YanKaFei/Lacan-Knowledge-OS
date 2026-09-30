#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_human_closure.py — Phase 4E E14 人工复核的**闭合评估**（只读 Gate / 不改历史）

背景：冻结 Gate 的 E14 逐字要求 `human spot review FAIL = 0`。Phase 4E 期间做的是
agent-mediated 预审（不满足 E14）。本工具在**人工复核记录**到位后补 E14，
并**重新执行** Phase 4E Remediation Gate v1 的完整评估：

    E1–E13, E15–E17  ← 复用 parent acceptance run 里**已验证**的证据（不重跑回归/provider）
    E14               ← 用人类复核文件重新判定

判定：
    人工文件缺失 / 不完整 / 非 human → `PHASE_4E_AWAITING_HUMAN_SPOT_REVIEW`（E14 = PENDING）
    任一题 FAIL                      → `PHASE_4E_BLOCKED`（列出 failed task / comment /
                                       是否 adapter 引入 / 最小补救）
    concern_class = phase4e_adapter_induced → **升级处理**，同样 BLOCKED
    FAIL = 0 且记录合法             → `PHASE_4E_COMPLETE`

本工具**不修改**：Gate、parent acceptance run、真实 provider run、RC artifact、任何历史。
用法：
    python3 _scripts/_tools/phase4e_human_closure.py \
        [--human _data/phase4e/human_spot_review_v2.jsonl] \
        [--parent 4e_acceptance_20260926T145239Z_dbd37bd0]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
P4E = os.path.join(VAULT, "_data", "phase4e")
GATE = os.path.join(P4E, "phase4e_remediation_gate_v1.json")
PARENT_DEFAULT = "4e_acceptance_20260926T145239Z_dbd37bd0"
HUMAN_DEFAULT = "_data/phase4e/human_spot_review_v2.jsonl"
TASKS = ["rt-D01", "rt-I02", "rt-H02", "rt-C03", "rt-J02", "rt-G01"]
VERDICTS = ("PASS", "WITH_CONCERN", "FAIL")
CHECK_KEYS = ("scholarly_degradation", "citation_evidence_mismatch", "new_overclaim",
              "abstention_leakage", "malformed_or_truncated_synthesis")
CHECK_VALUES = ("none", "minor", "major", "not_applicable")


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def validate(records, problems):
    """逐条校验人类记录；返回 {task_id: record}。"""
    by_task = {}
    for i, r in enumerate(records, 1):
        tid = r.get("task_id")
        if tid not in TASKS:
            problems.append("第 %d 行 task_id 非法：%r" % (i, tid))
            continue
        if tid in by_task:
            problems.append("task_id 重复：%s" % tid)
        if r.get("reviewer_type") != "human":
            problems.append("%s reviewer_type=%r（E14 要求 human）"
                            % (tid, r.get("reviewer_type")))
        if r.get("verdict") not in VERDICTS:
            problems.append("%s verdict 非法：%r" % (tid, r.get("verdict")))
        if not r.get("reviewed_at") or len(str(r.get("reviewed_at"))) < 10:
            problems.append("%s 缺 reviewed_at" % tid)
        if not str(r.get("comment") or "").strip():
            problems.append("%s 缺 comment（人工判断必须写明理由）" % tid)
        checks = r.get("checks") or {}
        for k in CHECK_KEYS:
            v = checks.get(k)
            if v not in CHECK_VALUES:
                problems.append("%s checks.%s 非法：%r" % (tid, k, v))
        if r.get("verdict") == "WITH_CONCERN" and r.get("concern_class") not in (
                "existing_scholarly_limitation", "phase4e_adapter_induced", "unclear"):
            problems.append("%s verdict=WITH_CONCERN 但缺 concern_class"
                            "（必须判断是否 adapter 引入）" % tid)
        by_task[tid] = r
    for tid in TASKS:
        if tid not in by_task:
            problems.append("缺题：%s" % tid)
    return by_task


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E E14 human closure evaluation")
    ap.add_argument("--human", default=HUMAN_DEFAULT)
    ap.add_argument("--parent", default=PARENT_DEFAULT)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)

    gate = json.load(open(GATE, encoding="utf-8"))
    parent_dir = os.path.join(P4E, a.parent)
    parent = json.load(open(os.path.join(parent_dir, "final_decision.json"),
                            encoding="utf-8"))
    human_path = a.human if os.path.isabs(a.human) else os.path.join(VAULT, a.human)
    human_exists = os.path.isfile(human_path)
    records, problems = [], []
    if human_exists:
        with open(human_path, encoding="utf-8") as f:
            records = [json.loads(l) for l in f if l.strip()]
        by_task = validate(records, problems)
    else:
        by_task = {}
        problems.append("缺人工复核文件：%s（人类 reviewer 尚未填写）" % a.human)

    fails = [t for t, r in by_task.items() if r.get("verdict") == "FAIL"]
    concerns = [t for t, r in by_task.items() if r.get("verdict") == "WITH_CONCERN"]
    induced = [t for t in concerns
               if (by_task[t].get("concern_class") == "phase4e_adapter_induced")]
    ambiguous = [t for t in concerns if by_task[t].get("concern_class") == "unclear"]

    if not human_exists or problems:
        e14 = {"status": "PENDING", "detail": problems[:12],
               "human_file": a.human, "fail_n": None}
        decision = "PHASE_4E_AWAITING_HUMAN_SPOT_REVIEW"
    elif fails or induced:
        e14 = {"status": "FAIL",
               "failed_tasks": [{"task_id": t, "verdict": by_task[t]["verdict"],
                                 "comment": by_task[t].get("comment"),
                                 "concern_class": by_task[t].get("concern_class")}
                                for t in (fails + induced)],
               "adapter_induced": induced, "human_file": a.human, "fail_n": len(fails)}
        decision = "PHASE_4E_BLOCKED"
    else:
        e14 = {"status": "PASS", "human_file": a.human,
               "fail_n": 0, "with_concern": concerns,
               "concern_classes": {t: by_task[t].get("concern_class") for t in concerns},
               "ambiguous": ambiguous}
        decision = "PHASE_4E_COMPLETE"

    # E1–E13 / E15–E17：复用 parent 已验证证据（不重跑）
    items = []
    for it in parent.get("items") or []:
        if it["id"] == "E14":
            items.append({"id": "E14", "requirement": it["requirement"],
                          "status": e14["status"], "blocking": True,
                          "evidence": json.dumps(e14, ensure_ascii=False),
                          "source": ("human closure" if e14["status"] != "PENDING"
                                     else "human closure（人工记录未到位）")})
        else:
            items.append(dict(it, source="parent_acceptance_run:%s" % a.parent))
    failed = [i["id"] for i in items if i["status"] == "FAIL"]

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_id = a.run_id or "4e_human_closure_%s_%s" % (
        stamp, hashlib.sha256(stamp.encode()).hexdigest()[:8])
    run_dir = os.path.join(P4E, run_id)
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)

    def wr(name, obj):
        with open(os.path.join(run_dir, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")

    wr("manifest.json", {
        "schema_version": "phase4e-human-closure-manifest/v1", "run_id": run_id,
        "created_at": utcnow(), "head": subprocess.run(
            ["git", "-C", VAULT, "rev-parse", "HEAD"], capture_output=True,
            text=True).stdout.strip(),
        "parent_acceptance_run": a.parent,
        "parent_final_decision_sha256": sha_file(
            os.path.join(parent_dir, "final_decision.json")),
        "gate_id": gate["gate_id"], "gate_hash": gate["gate_hash"],
        "gate_file_sha256": sha_file(GATE),
        "human_review_file": a.human,
        "human_review_sha256": sha_file(human_path) if human_exists else None,
        "agent_pre_review": "_data/phase4e/agent_pre_review.jsonl（是 AI 预审，不是 E14 证据）",
        "reused_evidence": "E1–E13/E15–E17 来自 parent acceptance run（未重跑）",
        "decision": decision})
    wr("e14_evaluation.json", {
        "schema_version": "phase4e-e14-evaluation/v1",
        "gate_e14_requirement_verbatim": next(c["requirement"] for c in gate["criteria"]
                                              if c["id"] == "E14"),
        "gate_e14_evidence_verbatim": next(c["evidence"] for c in gate["criteria"]
                                           if c["id"] == "E14"),
        "human_required": True,
        "agent_mediated_review_satisfies_e14": False,
        "human_records": len(records), "validation_problems": problems,
        "verdicts": {t: r.get("verdict") for t, r in by_task.items()},
        "fail_n": e14.get("fail_n"), "with_concern": concerns,
        "adapter_induced": induced, "status": e14["status"]})
    wr("gate_results.json", {"gate_id": gate["gate_id"], "gate_hash": gate["gate_hash"],
                             "items": items, "failed": failed,
                             "decision": decision})
    wr("final_decision.json", {
        "schema_version": "phase4e-human-closure-decision/v1", "run_id": run_id,
        "parent_acceptance_run": a.parent, "decision": decision,
        "items": items, "failed": failed,
        "ccr_0001_status": ("RESOLVED" if decision == "PHASE_4E_COMPLETE" else
                            "ACCEPTED_FOR_REMEDIATION"),
        "ccr_0001_technical_remediation": "COMPLETE",
        "capability": {"real_llm_scholarly_research":
                       "READY（技术已打通并封存验证）",
                       "acceptance_obligation": (
                           "E14 human spot review 已完成" if decision == "PHASE_4E_COMPLETE"
                           else "E14 human spot review 未完成 → 不得宣称 PHASE_4E COMPLETE")},
        "finished_at": utcnow()})

    print("== Phase 4E human closure ==")
    print("parent_acceptance_run:", a.parent)
    print("gate E14 原文:", next(c["requirement"] for c in gate["criteria"]
                                 if c["id"] == "E14"))
    print("agent-mediated 是否满足 E14:", False)
    for i in items:
        print("  %-4s %-8s %s" % (i["id"], i["status"], str(i["evidence"])[:100]))
    print("decision:", decision, "| failed:", failed)
    print("artifacts:", os.path.relpath(run_dir, VAULT))
    return 0 if decision == "PHASE_4E_COMPLETE" else (2 if decision.startswith("PHASE_4E_AWAITING")
                                                      else 1)


if __name__ == "__main__":
    raise SystemExit(main())
