#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_eval_manifest.py — Phase 4C.1-A §A3：Artifact / Engine Version Pinning

Phase 4C 审计证明：`_data/eval/research_traces_4b/` 里的 frozen trace **早于**
后续 engine revision，无法从任何现有 commit 完整重现 —— 因为没有版本绑定。

本脚本为**未来**的每次 evaluation / research run 生成一份 `EvaluationRunManifest`，
使它能够回答：

    这个结果到底是由哪一版代码、哪一版 ontology、哪一版 corpus、
    哪一版 Gold / task set、哪一版 schema 生成的？

绑定内容（全部为确定性 sha256）
────────────────────────────────
    engine_hashes         research_answer / research_agent / evidence_sufficiency_v2 /
                          evidence_sufficiency / knowledge_api / ontology_gaps /
                          citations / gold_normalization / eval_integrity
    engine_hash           上述的合并摘要
    data_hashes           gold / task set / v4c 结果 / 人工基线 / 裁决队列 /
                          seminars / ontology v4a1 / alias_index / terminology_bridge
    gold_version          research_tasks_v1.jsonl + gold_derivation 的合并摘要
    task_set_version      research_tasks_v1.public.jsonl 的合并摘要
    ontology_version      ontology 数据集的合并摘要
    passage_store_version passages.jsonl 的 sha256（另记 size / n_lines）
    schema_versions       research_trace / research_answer / evidence_pack /
                          gold_lane_audit / scholarly_regression
    git_commit / git_dirty

用法
────
    python3 build_eval_manifest.py                # 写 _data/eval/manifests/<run_id>.json + latest.json
    python3 build_eval_manifest.py --verify       # 重算并与 latest.json 比对（忽略 generated_at/run_id）
    python3 build_eval_manifest.py --check-schema # 用 jsonschema 校验 manifest 符合 schema
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
MANIFEST_DIR = os.path.join(EVAL, "manifests")
LATEST = os.path.join(MANIFEST_DIR, "latest.json")
SCHEMA = os.path.join(EVAL, "evaluation_run_manifest.schema.json")
sys.path.insert(0, HERE)
import eval_integrity as ei  # noqa: E402

ENGINE_VERSION = "phase4c.1-d/claim-evidence-entailment-1"
SCHEMA_VERSIONS = {
    "research_trace": "research-trace/v2（4C.1-B 起；历史 trace 为 research-trace-4b/v1）",
    "research_contract": "research-contract/v1",
    "gold": "research-task/v2（gold_v2；v1 为 research-task/v1，只读保留）",
    "research_answer": "research-answer-4b/v1",
    "evidence_pack": "evidence-pack/v1",
    "gold_lane_audit": "gold-lane-audit/v1",
    "scholarly_regression": "scholarly-regression/v1",
    "evaluation_run_manifest": "evaluation-run-manifest/v1",
}
# 忽略比对字段（非确定性）
VOLATILE = ("generated_at", "run_id", "seconds")
# 派生视图每次都重写（含 generated_at）→ 记录但不参与内容比对
CONTENT_VOLATILE = VOLATILE + ("git_commit", "git_dirty", "derived_hashes")


def build(now=None):
    now = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    commit = ei.git_commit()
    eng = ei.engine_hashes()
    data = ei.data_hashes()
    heavy = ei.passage_store_digest()
    ontology = {k: v for k, v in data.items() if k.startswith("ontology_")
                or k in ("alias_index", "terminology_bridge")}
    gold = {k: v for k, v in data.items()
            if k in ("research_tasks_v1", "gold_derivation_v1")}
    taskset = {k: v for k, v in data.items() if k == "research_tasks_v1"}
    doc = {
        "schema_version": "evaluation-run-manifest/v1",
        "run_id": "run-%s-%s" % (now.replace("-", "").replace(":", ""), commit[:7]),
        "generated_at": now,
        "git_commit": commit,
        "git_dirty": ei.git_dirty(),
        "engine_version": ENGINE_VERSION,
        "engine_hashes": eng,
        "engine_hash": ei.combined_digest(eng),
        "data_hashes": data,
        "derived_hashes": ei.derived_hashes(),
        "ontology_version": ei.combined_digest(ontology),
        "passage_store_version": ei.combined_digest(heavy),
        "passage_store": heavy,
        "gold_version": ei.combined_digest(gold),
        "task_set_version": ei.combined_digest(taskset),
        "schema_versions": SCHEMA_VERSIONS,
        "artifacts": {
            "gold_lane_audit": "_data/eval/gold_lane_audit_v1.jsonl",
            "scholarly_regression": "_data/eval/scholarly_regression_v1.jsonl",
            "adjudicated_truth": "_data/eval/evaluation_truth_adjudicated_v1.json",
            "lane_semantics": "_data/eval/lane_semantics_v1.json",
            "failure_class_mapping": "_data/eval/failure_class_mapping_v1.json",
            "trace_integrity_baseline": "_data/eval/trace_integrity_baseline_v1.json",
            "evaluation_integrity_audit": "_data/eval/evaluation_integrity_audit.json",
            "frozen_phase4c_results": "_data/eval/research_eval_results.v4c.json",
        },
        "notes": ("历史 frozen trace（_data/eval/research_traces_4b/）**没有**本清单，"
                  "因此不可从任何 commit 完整重现 —— 这正是 Phase 4C 审计的结论；"
                  "新 run 必须声明 research-trace/v2 并写出本清单。"),
    }
    return doc


# `--verify` 用上面定义的 CONTENT_VOLATILE（排除 volatile / git 指针 / 派生视图）。


def core(doc):
    """用于 --verify 的确定性核心（去掉 volatile 字段与 git 指针）。"""
    return json.dumps({k: v for k, v in doc.items() if k not in CONTENT_VOLATILE},
                      ensure_ascii=False, sort_keys=True)


def commit_drift(have, now):
    """→ dict：记录 vs 当前的 commit 指针差异（不构成失败）。"""
    a, b = (have or {}).get("git_commit"), (now or {}).get("git_commit")
    if a == b:
        return {"recorded": a, "current": b, "drifted": False}
    import subprocess
    try:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", a, b],
                           cwd=VAULT, capture_output=True)
        ancestor = r.returncode == 0
    except Exception:                                     # pragma: no cover
        ancestor = False
    return {"recorded": a, "current": b, "drifted": True,
            "recorded_is_ancestor_of_current": ancestor,
            "content_hashes_still_match": True}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--check-schema", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    doc = build()
    os.makedirs(MANIFEST_DIR, exist_ok=True)

    if a.verify:
        have = ei.jd(LATEST)
        if not have:
            print("先运行 build_eval_manifest.py 生成 %s"
                  % os.path.relpath(LATEST, VAULT))
            return 1
        drift = commit_drift(have, doc)
        if core(have) != core(doc):
            diff = [k for k in set(list(have) + list(doc))
                    if k not in CONTENT_VOLATILE and have.get(k) != doc.get(k)]
            print("manifest 内容不一致：%s" % diff)
            return 1
        print("manifest 内容可复现（%d 个绑定字段一致；忽略 %s）"
              % (len([k for k in doc if k not in CONTENT_VOLATILE]),
                 list(CONTENT_VOLATILE)))
        if drift["drifted"]:
            print("  ⚠ git 指针漂移：记录 %s → 当前 %s（祖先关系=%s）—— "
                  "内容 hash 未变，判为可复现；漂移原因通常是 Phase 2 确定性测试的基线提交"
                  % (str(drift["recorded"])[:10], str(drift["current"])[:10],
                     drift["recorded_is_ancestor_of_current"]))
        return 0

    if a.check_schema:
        try:
            import jsonschema
        except Exception as exc:                          # pragma: no cover
            print("跳过 schema 校验（缺 jsonschema：%s）" % exc)
            return 0
        jsonschema.Draft7Validator(ei.jd(SCHEMA, {})).validate(doc)
        print("manifest 符合 %s" % os.path.relpath(SCHEMA, VAULT))
        return 0

    path = os.path.join(MANIFEST_DIR, doc["run_id"] + ".json")
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(doc, open(LATEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("engine_version=%s  git=%s%s"
              % (doc["engine_version"], doc["git_commit"][:10],
                 "（工作区非干净）" if doc["git_dirty"] else ""))
        print("  engine_hash            %s" % doc["engine_hash"][:16])
        print("  gold_version           %s" % doc["gold_version"][:16])
        print("  task_set_version       %s" % doc["task_set_version"][:16])
        print("  ontology_version       %s" % doc["ontology_version"][:16])
        print("  passage_store_version  %s（%s 行）"
              % (doc["passage_store_version"][:16],
                 (doc["passage_store"].get("passage_store") or {}).get("n_lines")))
        print("-> %s" % os.path.relpath(path, VAULT))
        print("-> %s" % os.path.relpath(LATEST, VAULT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
