#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_freeze_record.py — Phase 4E §18/§19/§56：重建冻结并留下**可核**的修复记录。

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
FREEZE_DIR = os.path.join(VAULT, "_data", "core_freeze")
LIVE = os.path.join(FREEZE_DIR, "scholarly_core_freeze_v1.json")
HISTORY = os.path.join(FREEZE_DIR, "history")
PARENT_SNAPSHOT = os.path.join(HISTORY,
                               "scholarly_core_freeze_v1.4d2-workspace-registered.json")
SEGMENT_SNAPSHOT = os.path.join(HISTORY,
                                "scholarly_core_freeze_v1.4e-ccr0001-remediation.json")
OUT_DIR = os.path.join(VAULT, "_data", "phase4e")
OUT = os.path.join(OUT_DIR, "freeze_remediation.json")

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


def build_record(parent_doc, live_doc, parent_hash, live_hash):
    oc, nc = parent_doc.get("components") or {}, live_doc.get("components") or {}
    changed = sorted(k for k in set(oc) | set(nc) if oc.get(k) != nc.get(k))
    semantic = [k for k in changed if k not in PRODUCT_BOUNDARY_KEYS]
    return {
        "schema_version": "phase4e-freeze-remediation/v1",
        "phase": "Phase 4E — Scholarly Core Remediation: Real Provider Path",
        "ccr": "CCR-0001",
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
                "manifest 原地更新 + lineage 第 5 段（phase=4E, ccr=CCR-0001）；"
                "不新建 `scholarly_core_freeze_v1.1.json`，以免与既有消费方"
                "（policy / 测试 / 报告里的 v1 名称）不一致。"),
            "release_candidate": "RC1.1",
        },
        "parent_freeze": {"manifest": os.path.relpath(PARENT_SNAPSHOT, VAULT),
                          "sha256": parent_hash,
                          "components_n": len(oc)},
        "new_freeze": {"manifest": os.path.relpath(LIVE, VAULT), "sha256": live_hash,
                       "components_n": len(nc),
                       "lineage_segment_snapshot": os.path.relpath(SEGMENT_SNAPSHOT, VAULT),
                       "lineage_segment_sha256": sha(SEGMENT_SNAPSHOT)
                       if os.path.isfile(SEGMENT_SNAPSHOT) else None},
        "changed_components": [
            {"component": k, "class": ("product_boundary" if k in PRODUCT_BOUNDARY_KEYS
                                       else "SCHOLARLY_SEMANTIC"),
             "before": oc.get(k), "after": nc.get(k),
             "file": {"scholarly_api_core_hash": "scholarly_api/core.py",
                      "scholarly_api_objects_hash": "scholarly_api/objects.py",
                      "scholarly_api_policy_hash": "scholarly_api/policy.py"}.get(k)}
            for k in changed],
        "unchanged_components_n": len(set(oc) | set(nc)) - len(changed),
        "semantic_impact_assessment": {
            "runtime_wiring_changed": bool(
                [k for k in changed if k in PRODUCT_BOUNDARY_KEYS]),
            "scholarly_semantics_changed": bool(semantic),
            "semantic_change_keys": semantic,
            "rationale": (
                "唯一改动集中在产品边界的 provider/adapter 选择、provider 错误翻译与"
                "只读审计接收器：llm 分支由 `OpenAICompatibleProvider(...)`（低层"
                "completion provider）改为经既有工厂 `make_adapter(\"llm\", provider)` "
                "得到 `ScholarlySynthesisAdapter`；mock 分支同样改走 `make_adapter(\"mock\")`。"
                "prompt / judge prompt / SynthesisInputContract / ClaimAtom / entailment / "
                "repair / citation / source-role / abstention / Gate13/19/20/21 / Gold v2 / "
                "Human Review R1,R2 / readiness gate / D2 frozen identity 全部哈希未变。"),
            "frozen_semantic_components_verified_unchanged": [
                k for k in FROZEN_SEMANTIC_KEYS if k in nc and oc.get(k) == nc.get(k)],
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E freeze remediation record")
    ap.add_argument("--check", action="store_true", help="只校验，不写")
    a = ap.parse_args(argv)

    if a.check:
        rec = load(OUT) if os.path.isfile(OUT) else {}
        # 与**自身 lineage 段快照**比对（不可变），而不是与 live manifest 比对：
        # live 会随后续 phase 正常前移，把 live 当历史记录的基准是工具缺陷（P5A 实测踩过）。
        snap = rec.get("new_freeze", {}).get("lineage_segment_snapshot")
        snap_hash = sha(os.path.join(VAULT, snap)) if snap and \
            os.path.isfile(os.path.join(VAULT, snap)) else None
        ok = (bool(snap_hash)
              and rec.get("new_freeze", {}).get("sha256") == snap_hash
              and not rec.get("semantic_impact_assessment",
                              {}).get("scholarly_semantics_changed"))
        print("%s %s：recorded=%s segment_snapshot=%s 语义变化=%s"
              % ("OK  " if ok else "FAIL", "phase4e_freeze_record",
                 str(rec.get("new_freeze", {}).get("sha256"))[:16],
                 str(snap_hash)[:16],
                 rec.get("semantic_impact_assessment", {})
                    .get("scholarly_semantics_changed")))
        return 0 if ok else 1

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(HISTORY, exist_ok=True)
    parent_doc = load(PARENT_SNAPSHOT)
    parent_hash = sha(PARENT_SNAPSHOT)
    print("parent freeze:", parent_hash[:16])

    print(run("core_freeze.py", "--build"))
    live_doc = load(LIVE)
    live_hash = sha(LIVE)

    with open(SEGMENT_SNAPSHOT, "wb") as f:              # 真实字节快照（不是重新生成）
        f.write(open(LIVE, "rb").read())
    print(run("freeze_lineage.py", "--build"))
    print(run("core_freeze.py", "--verify", "--quiet"))
    print(run("freeze_lineage.py", "--verify"))

    rec = build_record(parent_doc, live_doc, parent_hash, live_hash)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("-> %s" % os.path.relpath(OUT, VAULT))
    print("changed: %s | unchanged: %d | semantic_changes: %s"
          % ([c["component"] for c in rec["changed_components"]],
             rec["unchanged_components_n"],
             rec["semantic_impact_assessment"]["scholarly_semantics_changed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
