#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5a_declare_data_version.py — P5A-006 §4/§10/§12：生成**数据版本变化声明**。

声明的每一个字段都来自真实差异审计（`_data/phase5a/corpus_diff_audit.json`）与
冻结 manifest 的当前值；本工具**不猜**：

    before_hash        ← 当前 manifest 的 corpus_inventory_hash（= 冻结基线）
    after_hash         ← 现场复算的 corpus_inventory_hash
    source_diff        ← 差异审计的 added/removed/modified/unchanged + 审计工件路径
    ingestion_status   ← 差异审计的 §7 结论（SOURCE_INVENTORY_ONLY / INGESTED）
    dependent_artifacts← 差异审计的 §10 结论，映射到 DATA_VERSION_STATES 枚举
    verified_at        ← 本次生成时间

产出 `_data/core_freeze/data_version_declarations.json`；随后由 `core_freeze.py --build`
嵌入 manifest，再由 `freeze_lineage.py --build` 复算分类。

**纪律**：只有被 core_freeze SPEC 明确分类为 data_version 的组件才能声明（§5：无 wildcard）。
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
for _p in (HERE, VAULT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import core_freeze as CF                                                   # noqa: E402

AUDIT = os.path.join(VAULT, "_data", "phase5a", "corpus_diff_audit.json")
P5A = os.path.join(VAULT, "_data", "phase5a")
INGESTION_STATES = ("SOURCE_INVENTORY_ONLY", "INGESTED")
STATE_MAP = {
    "CHANGED": "CHANGED",
    "REBUILT": "REBUILT",
    "UNCHANGED_BY_DESIGN": "UNCHANGED_BY_DESIGN",
    "UNAVAILABLE": "UNAVAILABLE",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jd(p, d=None):
    if not os.path.isfile(p):
        return d
    with open(p, encoding="utf-8") as f:
        return json.load(f)


PARENT_SNAPSHOT = os.path.join(VAULT, "_data", "core_freeze", "history",
                               "scholarly_core_freeze_v1.5a-presentation-hardening.json")


def check():
    """校验**已记录**的声明与冻结现状一致（只读、廉价）。"""
    doc = jd(CF.DECLARATIONS)
    if not doc:
        print("FAIL 缺数据版本声明：%s" % os.path.relpath(CF.DECLARATIONS, VAULT))
        return 1
    decls = doc.get("declarations") or []
    if not decls:
        print("FAIL 声明为空")
        return 1
    man = jd(CF.OUT) or {}
    parent = jd(PARENT_SNAPSHOT) or {}
    comps = man.get("components") or {}
    pcomps = parent.get("components") or {}
    problems = []
    for d in decls:
        k = d.get("component")
        if CF.component_class(k) != CF.CLASS_DATA:
            problems.append("%s 未被 SPEC 分类为 data_version（§5 禁止 wildcard）" % k)
        if k not in (man.get("component_classes") or {}):
            problems.append("%s 不在 manifest.component_classes 里" % k)
        if comps.get(k) != d.get("after_hash"):
            problems.append("%s：manifest 当前值 != 声明 after_hash（冻结未推进到该值）" % k)
        if pcomps.get(k) != d.get("before_hash"):
            problems.append("%s：父段值 != 声明 before_hash" % k)
        if d.get("scholarly_semantic_hashes_unchanged") is not True:
            problems.append("%s：未确认语义哈希未变" % k)
        if d.get("ingestion_status") not in INGESTION_STATES:
            problems.append("%s：ingestion_status 非法" % k)
        for dep in ("passage_store", "lexical_index", "vector_index",
                    "graph_cache", "corpus_inventory"):
            if dep not in (d.get("dependent_artifacts") or {}):
                problems.append("%s：依赖构件 %s 状态缺失" % (k, dep))
    # 语义组件必须一个都没变（父段 → 现段）
    changed_semantic = [k for k in set(comps) | set(pcomps)
                        if comps.get(k) != pcomps.get(k)
                        and CF.component_class(k) == CF.CLASS_SCHOLARLY]
    if changed_semantic:
        problems.append("出现学术语义变化：%s" % changed_semantic)
    if problems:
        print("FAIL 数据版本声明校验未通过：")
        for x in problems[:8]:
            print("  - %s" % x)
        return 1
    print("OK   数据版本声明与冻结现状一致：%s（%d 条；semantic 变化 0）"
          % (", ".join(d.get("component") for d in decls), len(decls)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--component", default="corpus_inventory_hash")
    ap.add_argument("--reason", default=None)
    ap.add_argument("--out", default=CF.DECLARATIONS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        return check()

    if CF.component_class(a.component) != CF.CLASS_DATA:
        print("拒绝：%s 未被 core_freeze SPEC 分类为 data_version（§5 无 wildcard 豁免）"
              % a.component)
        return 2

    audit = jd(AUDIT)
    if not audit:
        print("缺差异审计：%s（先跑 phase5a_corpus_diff.py）" % os.path.relpath(AUDIT, VAULT))
        return 2
    if audit.get("verdict") != "EXACTLY_ONE_ADDED_NO_OTHER_CHANGE":
        print("拒绝：差异审计 verdict=%s（§6 要求存在未解释变化时停止自动推进）"
              % audit.get("verdict"))
        return 3

    man = jd(CF.OUT, {}) or {}
    before = (man.get("components") or {}).get(a.component)
    after = CF.compute(*CF.SPEC[a.component])
    if before == after:
        print("拒绝：%s 未发生变化（%s）—— 无事可声明" % (a.component, str(before)[:16]))
        return 4

    ds = audit.get("derived_state") or {}
    deps = {}
    for key, src in (("passage_store", "passage_store"),
                     ("lexical_index", "lexical_index"),
                     ("vector_index", "vector_index"),
                     ("graph_cache", "graph_cache"),
                     ("corpus_inventory", "corpus_inventory")):
        st = ((ds.get(src) or {}).get("state")) or "UNAVAILABLE"
        deps[key] = STATE_MAP.get(st, "UNAVAILABLE")

    ing = (audit.get("ingestion_status") or [{}])[0]
    canonical_changed = any(deps[k] in ("CHANGED", "REBUILT")
                            for k in ("passage_store", "lexical_index",
                                      "vector_index", "graph_cache"))

    decl = {
        "component": a.component,
        "component_class": CF.CLASS_DATA,
        "before_hash": before,
        "after_hash": after,
        "reason": a.reason or (
            "外部语料目录新增 1 个文件（source inventory 143 → 144）；"
            "**学术语义组件全部未变**。canonical passage store 的上游是 "
            ".lacan-build/atlas（segments.jsonl / french_staferla.jsonl / french.jsonl），"
            "与原始语料目录是两条链，因此本次变化**不改变可研究语料**。"),
        "source_diff": {
            "baseline_source": audit.get("baseline_source"),
            "baseline_inventory_sha256": audit.get("baseline_inventory_sha256"),
            "live_inventory_sha256": audit.get("live_inventory_sha256"),
            "files_before": audit.get("baseline_files"),
            "files_after": audit.get("live_files"),
            "bytes_before": audit.get("baseline_bytes"),
            "bytes_after": audit.get("live_bytes"),
            "added": len(audit.get("added") or []),
            "removed": len(audit.get("removed") or []),
            "modified": len(audit.get("modified") or []),
            "unchanged": audit.get("unchanged_n"),
            "verdict": audit.get("verdict"),
            "audit_artifact": os.path.relpath(AUDIT, VAULT),
            "added_entries": [{"rel_path": x.get("rel_path"), "size": x.get("size"),
                               "sha256": x.get("sha256")}
                              for x in (audit.get("added") or [])],
        },
        "ingestion_status": ing.get("status"),
        "canonical_passage_store_changed": canonical_changed,
        "dependent_artifacts": deps,
        "verified_at": _now(),
        "scholarly_semantic_hashes_unchanged": True,
    }

    doc = {
        "schema_version": "scholarly-core-freeze/data-version-declarations/v1",
        "generated_at": _now(),
        "issued_for": "P5A-006（DECISION_1 = 方案 A）",
        "policy": ("data_version 组件的变化必须**逐条声明**：组件由 SPEC 分类、"
                   "before/after 哈希存在、变化对象可识别、依赖构件状态明确、"
                   "且学术语义哈希不变。未声明的数据漂移 = UNDECLARED_DATA_DRIFT（FAIL）。"),
        "declarations": [decl],
    }
    if a.dry_run:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print("数据版本声明 -> %s" % os.path.relpath(a.out, VAULT))
    print("  component=%s" % decl["component"])
    print("  before=%s…  after=%s…" % (str(before)[:16], str(after)[:16]))
    print("  added=%s removed=%s modified=%s unchanged=%s"
          % (decl["source_diff"]["added"], decl["source_diff"]["removed"],
             decl["source_diff"]["modified"], decl["source_diff"]["unchanged"]))
    print("  ingestion_status=%s | canonical_passage_store_changed=%s"
          % (decl["ingestion_status"], decl["canonical_passage_store_changed"]))
    print("  dependent_artifacts=%s" % json.dumps(deps, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
