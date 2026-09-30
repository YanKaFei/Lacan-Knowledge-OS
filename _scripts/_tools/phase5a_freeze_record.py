#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5a_freeze_record.py — Phase 5A §62：重建冻结并留下**可核**的修复记录。

它做四件事（顺序固定，缺一不可）：

  1. 记录**父**冻结身份（重建之前的 live manifest 字节与 hash）；
  2. `core_freeze.py --build` 重建 manifest（只允许产品边界组件变化）；
  3. 把新 manifest 的真实字节存入 `history/`，并重建 freeze lineage（新增 4E 段）；
  4. 写出 `_data/phase4e/freeze_remediation.json`：父/新 hash、变化组件、
     语义影响评估、CCR 引用、以及“runtime wiring 变了 / scholarly semantics 没变”的结论。

用法：
    python3 _scripts/_tools/phase4e_freeze_record.py            # 执行（会重写 manifest）
    python3 _scripts/_tools/phase4e_freeze_record.py --check    # 只校验现状，不写任何东西
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import core_freeze as CF                                                   # noqa: E402
FREEZE_DIR = os.path.join(VAULT, "_data", "core_freeze")
LIVE = os.path.join(FREEZE_DIR, "scholarly_core_freeze_v1.json")
HISTORY = os.path.join(FREEZE_DIR, "history")
PARENT_SNAPSHOT = os.path.join(HISTORY,
                               "scholarly_core_freeze_v1.4e-ccr0001-remediation.json")
SEGMENT_SNAPSHOT = os.path.join(HISTORY,
                                "scholarly_core_freeze_v1.5a-presentation-hardening.json")
OUT_DIR = os.path.join(VAULT, "_data", "phase5a")
OUT = os.path.join(OUT_DIR, "freeze_remediation.json")

# 已知的修复记录（--check 会逐个校验）。Phase 5A 有两段：
#   1) presentation hardening（产品边界变化）
#   2) P5A-006 remediation（**数据版本**变化：语料清单 143 → 144）
RECORDS = {
    "5a-presentation-hardening": {
        "parent": "scholarly_core_freeze_v1.4e-ccr0001-remediation.json",
        "segment": "scholarly_core_freeze_v1.5a-presentation-hardening.json",
        "out": "freeze_remediation.json",
        "phase": "Phase 5A — Scholarly Product Hardening（presentation hardening）",
    },
    "5a-p6-data-version-separation": {
        "parent": "scholarly_core_freeze_v1.5a-presentation-hardening.json",
        "segment": "scholarly_core_freeze_v1.5a-p6-data-version-separation.json",
        "out": "freeze_remediation_p6.json",
        "phase": ("Phase 5A — P5A-006：数据版本 / 学术语义分类分离"
                  "（DECISION_1 = 方案 A）"),
    },
}

PRODUCT_BOUNDARY_KEYS = ("scholarly_api_core_hash", "scholarly_api_objects_hash",
                         "scholarly_api_policy_hash")
FROZEN_SEMANTIC_KEYS = (
    "synthesis_prompt_hash", "judge_prompt_hash", "synthesis_boundary_hash",
    "claim_atom_hash", "claim_sanitize_hash", "entailment_validator_hash",
    "entailment_claim_hash", "repair_rules_hash", "citation_policy_hash",
    "source_role_policy_hash", "abstention_policy_hash",
    "gate13_hash", "gate13_baseline_hash", "gate14_adjudication_hash",
    "gate19_hash", "gate20_hash", "gate21_hash",
    "gold_v2_tasks_hash", "gold_v2_lane_overrides_hash",
    "human_review_round1_hash", "human_review_round2_hash",
    "human_adjudication_hash", "scholarly_readiness_gate_hash",
    "frozen_identity_hash", "research_contract_hash", "execution_engine_hash",
    "evidence_sufficiency_hash", "research_answer_hash",
)


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def run(tool, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, tool), *args],
                       capture_output=True, text=True, cwd=VAULT)
    if r.returncode != 0:
        print("FAIL %s %s\n%s%s" % (tool, " ".join(args), r.stdout[-800:], r.stderr[-800:]))
        raise SystemExit(1)
    return (r.stdout + r.stderr).strip()


def build_record(parent_doc, live_doc, parent_hash, live_hash,
                 parent_rel=None, segment_rel=None, phase_label=None, out_rel=None):
    oc, nc = parent_doc.get("components") or {}, live_doc.get("components") or {}
    changed = sorted(k for k in set(oc) | set(nc) if oc.get(k) != nc.get(k))
    # ★ P5A-006：用 core_freeze 的**三类**判定，不再用「非产品边界即语义」的旧二分
    classes = live_doc.get("component_classes") or CF.component_classes()
    semantic = [k for k in changed
                if classes.get(k, CF.component_class(k)) == CF.CLASS_SCHOLARLY]
    data_keys = [k for k in changed
                 if classes.get(k, CF.component_class(k)) == CF.CLASS_DATA]
    runtime = [k for k in changed
               if classes.get(k, CF.component_class(k)) == CF.CLASS_PRODUCT]
    declarations = {d.get("component"): d
                    for d in (live_doc.get("data_version_declarations") or [])}
    return {
        "schema_version": "phase4e-freeze-remediation/v1",
        "phase": phase_label or "Phase 5A — Scholarly Product Hardening",
        "ccr": None,
        "pdr": "PDR-0001",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout.strip(),
        "freeze_identity": {
            "schema_version": parent_doc.get("schema_version"),
            "freeze_version": parent_doc.get("freeze_version"),
            "manifest_file": os.path.relpath(LIVE, VAULT),
            "representation_note": (
                "仓库既有版本规范 = **同一 manifest 版本名 + 谱系新增一段**"
                "（4D.0/4D.1/4D.2 同样做法）。因此 Phase 4E 的 “v1.1” 表示为："
                "manifest 原地更新 + lineage 第 6 段（phase=5A, pdr=PDR-0001）；"
                "不新建 `scholarly_core_freeze_v1.1.json`，以免与既有消费方"
                "（policy / 测试 / 报告里的 v1 名称）不一致。"),
            "release_candidate": "RC1.2",
        },
        "parent_freeze": {"manifest": parent_rel or os.path.relpath(PARENT_SNAPSHOT, VAULT),
                          "sha256": parent_hash, "components_n": len(oc)},
        "new_freeze": {
            "manifest": os.path.relpath(LIVE, VAULT), "sha256": live_hash,
            "components_n": len(nc),
            "lineage_segment_snapshot": segment_rel or os.path.relpath(SEGMENT_SNAPSHOT,
                                                                      VAULT),
            "lineage_segment_sha256": sha(os.path.join(VAULT, segment_rel))
            if segment_rel else (sha(SEGMENT_SNAPSHOT)
                                 if os.path.isfile(SEGMENT_SNAPSHOT) else None),
            "record_file": out_rel},
        "changed_components": [
            {"component": k, "class": classes.get(k, CF.component_class(k)),
             "before": oc.get(k), "after": nc.get(k),
             "declaration": declarations.get(k),
             "file": {"scholarly_api_core_hash": "scholarly_api/core.py",
                      "scholarly_api_objects_hash": "scholarly_api/objects.py",
                      "scholarly_api_policy_hash": "scholarly_api/policy.py"}.get(k)}
            for k in changed],
        # ── 三类变化（§2/§11/§12）
        "scholarly_semantic_changes": semantic,
        "data_version_changes": data_keys,
        "data_version_changes_n": len(data_keys),
        "product_runtime_changes": runtime,
        "product_runtime_changes_n": len(runtime),
        "data_version_change_details": [
            {"component": k, "before_hash": oc.get(k), "after_hash": nc.get(k),
             "reason": (declarations.get(k) or {}).get("reason"),
             "source_diff": (declarations.get(k) or {}).get("source_diff"),
             "ingestion_status": (declarations.get(k) or {}).get("ingestion_status"),
             "canonical_passage_store_changed": (declarations.get(k) or {}).get(
                 "canonical_passage_store_changed"),
             "dependent_artifacts": (declarations.get(k) or {}).get("dependent_artifacts"),
             "verified_at": (declarations.get(k) or {}).get("verified_at")}
            for k in data_keys],
        "unchanged_components_n": len(set(oc) | set(nc)) - len(changed),
        "semantic_impact_assessment": {
            "runtime_wiring_changed": bool(
                [k for k in changed if k in PRODUCT_BOUNDARY_KEYS]),
            "scholarly_semantics_changed": bool(semantic),
            "semantic_change_keys": semantic,
            "data_version_changed": bool(data_keys),
            "rationale": (
                "唯一改动集中在**产品呈现层与产品 API schema 演化**：① 产品边界"
                "（`scholarly_api/core.py::_final_answer`）把校验器诊断（reject 日志 / 验证计量）"
                "从用户可见 `sections` **结构化地**路由到 `audit_diagnostics`；"
                "② `FinalScholarlyAnswer` 增字段 → schema v1 → v1.1（4D.0「加字段=新版本」）；"
                "③ 各出口默认呈现策略（UI / MCP meta / Obsidian / Export / Audit Bundle）。"
                "prompt / judge prompt / SynthesisInputContract / ClaimAtom / entailment / "
                "repair / citation / source-role / abstention / Gate13/19/20/21 / Gold v2 / "
                "Human Review R1,R2 / readiness gate / D2 frozen identity 全部哈希未变。"),
            "frozen_semantic_components_verified_unchanged": [
                k for k in FROZEN_SEMANTIC_KEYS if k in nc and oc.get(k) == nc.get(k)],
        },
    }


def _check_one(name):
    spec = RECORDS[name]
    out = os.path.join(OUT_DIR, spec["out"])
    rec = load(out) if os.path.isfile(out) else {}
    # 与**自身 lineage 段快照**比对（不可变），而不是与 live manifest 比对：
    # live 会随后续 phase 正常前移，把 live 当历史记录的基准是工具缺陷（P5A 实测踩过）。
    snap = rec.get("new_freeze", {}).get("lineage_segment_snapshot")
    snap_hash = sha(os.path.join(VAULT, snap)) if snap and \
        os.path.isfile(os.path.join(VAULT, snap)) else None
    sia = rec.get("semantic_impact_assessment", {})
    ok = (bool(snap_hash)
          and rec.get("new_freeze", {}).get("sha256") == snap_hash
          and not sia.get("scholarly_semantics_changed")
          and not (rec.get("scholarly_semantic_changes") or []))
    print("%s phase5a_freeze_record[%s]：recorded=%s segment_snapshot=%s "
          "语义变化=%s data_version_changes=%s"
          % ("OK  " if ok else "FAIL", name,
             str(rec.get("new_freeze", {}).get("sha256"))[:16],
             str(snap_hash)[:16], sia.get("scholarly_semantics_changed"),
             rec.get("data_version_changes_n")))
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 5A freeze remediation record")
    ap.add_argument("--check", action="store_true", help="只校验，不写")
    ap.add_argument("--segment", default="5a-presentation-hardening",
                    choices=sorted(RECORDS), help="要记录哪一段")
    ap.add_argument("--record-only", action="store_true",
                    help="不重建 manifest（manifest 已由更早步骤推进），只写记录")
    a = ap.parse_args(argv)

    if a.check:
        return 0 if all(_check_one(n) for n in sorted(RECORDS)) else 1

    spec = RECORDS[a.segment]
    parent_snapshot = os.path.join(HISTORY, spec["parent"])
    segment_snapshot = os.path.join(HISTORY, spec["segment"])
    out = os.path.join(OUT_DIR, spec["out"])
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(HISTORY, exist_ok=True)

    parent_doc = load(parent_snapshot)
    parent_hash = sha(parent_snapshot)
    print("segment: %s | parent: %s (%s)"
          % (a.segment, spec["parent"], parent_hash[:16]))

    if not a.record_only:
        print(run("core_freeze.py", "--build"))
        with open(segment_snapshot, "wb") as f:          # 真实字节快照（不是重新生成）
            f.write(open(LIVE, "rb").read())
        print(run("freeze_lineage.py", "--build"))
    live_doc = load(segment_snapshot)
    live_hash = sha(segment_snapshot)
    print(run("core_freeze.py", "--verify", "--quiet"))
    print(run("freeze_lineage.py", "--verify"))

    rec = build_record(parent_doc, live_doc, parent_hash, live_hash,
                       parent_rel=os.path.relpath(parent_snapshot, VAULT),
                       segment_rel=os.path.relpath(segment_snapshot, VAULT),
                       phase_label=spec["phase"],
                       out_rel=os.path.relpath(out, VAULT))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("-> %s" % os.path.relpath(out, VAULT))
    print("changed: %s | semantic=%s | data_version=%s | product_runtime=%s"
          % ([c["component"] for c in rec["changed_components"]],
             rec["scholarly_semantic_changes"], rec["data_version_changes"],
             rec["product_runtime_changes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
