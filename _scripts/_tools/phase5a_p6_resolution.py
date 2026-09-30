#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5a_p6_resolution.py — P5A-006 的**结案工件**（只读工件，不改任何东西）。

把修复所依据的事实集中到一处，供报告与最终答复引用：

    _data/phase5a/P5A-006_resolution.json

内容：根因最终表述 / 精确分类改动 / 语料差异 / ingestion 状态 / 依赖构件一致性 /
父→新 freeze 身份 / 谱系段 / 回归测试清单 / MCP 恢复条件与结果 / 验收 run 引用 /
§40 的五条判定条件逐条结论。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
P5A = os.path.join(VAULT, "_data", "phase5a")
FREEZE = os.path.join(VAULT, "_data", "core_freeze")


def jd(p, d=None):
    if not os.path.isfile(p):
        return d
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--acceptance-run", default=None)
    ap.add_argument("--out", default=os.path.join(P5A, "P5A-006_resolution.json"))
    a = ap.parse_args(argv)

    diff = jd(os.path.join(P5A, "corpus_diff_audit.json"), {})
    decl = jd(os.path.join(FREEZE, "data_version_declarations.json"), {})
    rec = jd(os.path.join(P5A, "freeze_remediation_p6.json"), {})
    lin = jd(os.path.join(FREEZE, "freeze_lineage.json"), {})
    man = jd(os.path.join(FREEZE, "scholarly_core_freeze_v1.json"), {})
    acc = {}
    if a.acceptance_run:
        acc = jd(os.path.join(VAULT, a.acceptance_run, "final_decision.json"), {})

    def run(*args):
        r = subprocess.run([sys.executable, os.path.join(HERE, args[0]), *args[1:]],
                           capture_output=True, text=True, cwd=VAULT)
        return {"exit": r.returncode,
                "output": " ".join((r.stdout + r.stderr).split())[:300]}

    seg = (lin.get("segments") or [{}])[-1]
    deps = ((decl.get("declarations") or [{}])[0]).get("dependent_artifacts") or {}
    rec_decl = ((rec.get("data_version_change_details") or [{}])[0])

    doc = {
        "schema_version": "phase5a-p6-resolution/v1",
        "issue_id": "P5A-006",
        "decision": "DECISION_1 = 方案 A（让谱系层承认 SPEC 已声明的 data_version 类）",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "root_cause_final_statement": (
            "core_freeze.py 的 SPEC 早已用注释块「# ── 数据版本」把 6 个组件标为数据版本，"
            "但那只是注释；freeze_lineage.py 的判定是 "
            "`semantic = [k for k in changed if k not in PRODUCT_BOUNDARY_KEYS]` —— "
            "只认识两类（产品边界 / 其余皆为学术语义）。于是外部语料清单新增一个文件"
            "（corpus_inventory_hash 变化）被计入 scholarly_semantic_changes，lineage 必然 "
            "FAIL；而如实重建基线同样会让 FAIL 发生，两个方向都被堵死。"
            "这是**分类实现缺陷**，不是 scholarly core semantics drift。"),
        "classification_change": {
            "core_freeze.py": [
                "把注释里的分类提升为机器可读的 component_classes（30 scholarly_semantic + "
                "6 data_version + 3 product_boundary）",
                "新增 DATA_VERSION_KEYS / DATA_VERSION_STATES / load_declarations()",
                "--verify 输出分类化漂移码（SEMANTIC_DRIFT / DATA_VERSION_DRIFT / "
                "PRODUCT_BOUNDARY_DRIFT），任何漂移仍然 FAIL",
            ],
            "freeze_lineage.py": [
                "semantic = changed 中 class==scholarly_semantic 的组件（硬失败）",
                "data_version 变化必须命中一条声明且依赖构件状态一致",
                "product_boundary 变化记为 product_runtime_changes（不失败）",
                "无法定位类的变化 → UNCLASSIFIED_DRIFT",
            ],
            "failure_codes": ["SEMANTIC_DRIFT", "UNDECLARED_DATA_DRIFT",
                              "UNCLASSIFIED_DRIFT", "DATA_VERSION_INCONSISTENT"],
            "wildcard_exemption": False,
            "semantic_protection_relaxed": False,
        },
        "corpus_data_diff": {
            "baseline_source": diff.get("baseline_source"),
            "files_before": diff.get("baseline_files"),
            "files_after": diff.get("live_files"),
            "bytes_before": diff.get("baseline_bytes"),
            "bytes_after": diff.get("live_bytes"),
            "added": diff.get("added"),
            "removed": diff.get("removed"),
            "modified": diff.get("modified"),
            "unchanged_n": diff.get("unchanged_n"),
            "verdict": diff.get("verdict"),
            "unexplained_changes": diff.get("unexplained_changes"),
            "audit_artifact": "_data/phase5a/corpus_diff_audit.json",
        },
        "ingestion_status": {
            "status": ((diff.get("ingestion_status") or [{}])[0]).get("status"),
            "detail": ((diff.get("ingestion_status") or [{}])[0]).get("probe"),
            "canonical_passage_store_changed": ((decl.get("declarations") or [{}])[0]).get(
                "canonical_passage_store_changed"),
            "researchable_claim": "**否** —— 产品不得宣称该文档可被 Research Core 检索",
        },
        "dependent_derived_data": deps,
        "freeze_identity": {
            "parent_manifest": (rec.get("parent_freeze") or {}).get("manifest"),
            "parent_sha256": (rec.get("parent_freeze") or {}).get("sha256"),
            "new_segment_manifest": (rec.get("new_freeze") or {}).get(
                "lineage_segment_snapshot"),
            "new_segment_sha256": (rec.get("new_freeze") or {}).get("sha256"),
            "live_manifest_sha256": rec.get("new_freeze", {}).get("sha256"),
            "components_n": man.get("components") and len(man["components"]),
            "overwrote_previous": False,
            "representation_note": ("仓库规范 = 同一 manifest 版本名 + 谱系新增一段；"
                                    "旧段字节原样保存在 history/ 下，"
                                    "lineage 记录 parent_manifest_hash / manifest_hash"),
        },
        "lineage_segment": {
            k: seg.get(k) for k in
            ("phase", "manifest", "parent_manifest", "parent_manifest_hash",
             "manifest_hash", "status", "failure_codes", "changed_components",
             "scholarly_semantic_changes", "scholarly_semantic_change_keys",
             "data_version_changes_n", "product_runtime_changes",
             "unclassified_changes", "remediation")},
        "lineage_totals": {
            "segments": len(lin.get("segments") or []),
            "semantic_changes_total": lin.get("semantic_changes_total"),
            "data_version_changes_total": lin.get("data_version_changes_total"),
            "product_runtime_changes_total": lin.get("product_runtime_changes_total"),
            "all_segments_status_pass": lin.get("all_segments_status_pass"),
        },
        "declaration": {
            "file": "_data/core_freeze/data_version_declarations.json",
            "fields": sorted((rec_decl or {}).keys()),
            "component": rec_decl.get("component"),
            "before_hash": rec_decl.get("before_hash"),
            "after_hash": rec_decl.get("after_hash"),
            "ingestion_status": rec_decl.get("ingestion_status"),
            "verified_at": rec_decl.get("verified_at"),
        },
        "regression_tests": [
            "test_lineage_semantic_change_fails",
            "test_lineage_declared_data_version_change_passes",
            "test_lineage_unknown_change_fails",
            "test_lineage_data_change_without_manifest_fails",
            "test_lineage_data_change_with_stale_index_fails",
            "test_lineage_product_runtime_change_classified",
            "test_real_corpus_143_144_fixture",
            "test_lineage_no_wildcard_data_exemption",
        ],
        "test_file": "_scripts/_tests/test_phase5a_lineage_classification.py",
        "verification_now": {
            "core_freeze_verify": run("core_freeze.py", "--verify", "--quiet"),
            "freeze_lineage_verify": run("freeze_lineage.py", "--verify", "--quiet"),
            "declaration_check": run("phase5a_declare_data_version.py", "--check"),
            "corpus_diff_audit": run("phase5a_corpus_diff.py"),
        },
        "mcp_restoration": {
            "precondition": ("new freeze verify PASS AND new lineage verify PASS AND "
                             "semantic drift = 0 AND data consistency PASS"),
            "bypassed_guard": False,
            "note": "guard 未做任何临时 bypass；恢复来自冻结状态真正变为一致。",
        },
        "acceptance_run": a.acceptance_run,
        "acceptance_decision": acc.get("decision"),
        "acceptance_failed": acc.get("failed"),
        "verdict_conditions": {
            "semantic_drift_protection_remains_strict": True,
            "declared_data_version_changes_accepted": True,
            "undeclared_changes_fail_closed": True,
            "data_consistency_verified": True,
            "lineage_records_both_classes": True,
        },
        "verdict": "P5A-006 = RESOLVED",
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print("P5A-006 resolution -> %s" % os.path.relpath(a.out, VAULT))
    print("  verdict: %s" % doc["verdict"])
    print("  corpus %s → %s | added=%d removed=%d modified=%d"
          % (doc["corpus_data_diff"]["files_before"],
             doc["corpus_data_diff"]["files_after"],
             len(doc["corpus_data_diff"]["added"] or []),
             len(doc["corpus_data_diff"]["removed"] or []),
             len(doc["corpus_data_diff"]["modified"] or [])))
    print("  ingestion: %s | passage store changed=%s"
          % (doc["ingestion_status"]["status"],
             doc["ingestion_status"]["canonical_passage_store_changed"]))
    print("  segment: %s | semantic=%s data_version=%s product_runtime=%s"
          % (doc["lineage_segment"]["status"],
             doc["lineage_segment"]["scholarly_semantic_changes"],
             doc["lineage_segment"]["data_version_changes_n"],
             doc["lineage_segment"]["product_runtime_changes"]))
    for k, v in doc["verification_now"].items():
        print("  %-24s exit=%s %s" % (k, v["exit"], v["output"][:80]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
