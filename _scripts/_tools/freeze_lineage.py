#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""freeze_lineage.py — 冻结谱系（4D.0 → … → 5A）

问题：产品阶段会改产品边界、也会发生**数据版本**变化（语料清单长大、段落库/索引重建）。
重建不得静默覆盖历史，也不得把「数据版本变了」和「学术语义变了」混为一谈。

Phase 5A / P5A-006 修复（**分类实现缺陷**，不是学术语义漂移）：
    `core_freeze.py` 的 SPEC 早就把 6 个组件放在「# ── 数据版本」里，
    但 `freeze_lineage.py` 只认识两类（产品边界 / 其余皆为语义），
    于是任何数据版本变化都被计入 `scholarly_semantic_changes` → 谱系必然 FAIL；
    而如实重建基线又会让 FAIL 发生 —— 两个方向都被堵死。
    现在按 `core_freeze.component_class()` 的**三类**判定：

        scholarly_semantic  语义单元     变化 → SEMANTIC_DRIFT（硬失败，绝不放宽）
        product_boundary    产品边界     变化 → PRODUCT_RUNTIME_CHANGE（记录，不失败）
        data_version        数据版本     变化 → 必须**被声明且一致**，否则失败

判定结果（§13）：
    情形 1  语义哈希变化                → FAIL SEMANTIC_DRIFT
    情形 2  已声明且一致的 data 变化    → PASS（semantic=0, data_version=N）
    情形 3  无法定位类的哈希变化        → FAIL UNCLASSIFIED_DRIFT
    情形 4  data 变化但依赖构件不一致   → FAIL DATA_VERSION_INCONSISTENT
    另有：data_version 组件变化但**没有声明** → FAIL UNDECLARED_DATA_DRIFT（§4）

做法：
  * `_data/core_freeze/history/` 保存**真实字节**的历史 manifest 快照；
  * `_data/core_freeze/freeze_lineage.json` 记录每段的 manifest hash、parent hash、
    三类变化清单与逐段判定；
  * 若某段字节不可得，如实记 `historical_artifact: "unavailable"`（**不伪造文件**）。

用法：
    python3 _scripts/_tools/freeze_lineage.py --build
    python3 _scripts/_tools/freeze_lineage.py --verify     # 供套件调用
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, VAULT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import core_freeze as CF                                                   # noqa: E402

FREEZE_DIR = os.path.join(VAULT, "_data", "core_freeze")
LIVE = os.path.join(FREEZE_DIR, "scholarly_core_freeze_v1.json")
HISTORY_DIR = os.path.join(FREEZE_DIR, "history")
LINEAGE = os.path.join(FREEZE_DIR, "freeze_lineage.json")

# 产品边界组件（仓库既有名称：产品边界 / product boundary）。
# 兼容旧字段 `changed_product_boundary` / `runtime_wiring_changed`。
PRODUCT_BOUNDARY_KEYS = CF.PRODUCT_BOUNDARY_KEYS
# 数据版本组件（由 core_freeze SPEC 明确声明；**没有 wildcard 豁免**）
DATA_VERSION_KEYS = CF.DATA_VERSION_KEYS
DATA_VERSION_STATES = CF.DATA_VERSION_STATES

# 失败码（§13）
FAIL_SEMANTIC = "SEMANTIC_DRIFT"
FAIL_UNDECLARED = "UNDECLARED_DATA_DRIFT"
FAIL_UNCLASSIFIED = "UNCLASSIFIED_DRIFT"
FAIL_INCONSISTENT = "DATA_VERSION_INCONSISTENT"

INGESTION_STATES = ("SOURCE_INVENTORY_ONLY", "INGESTED")

# 依赖构件 → 必须同步变化的冻结组件（§10）
DEPENDENT_GUARDS = {
    "passage_store": ("passage_store_version", "passage_store_passages_sha256"),
    "lexical_index": ("retrieval_index_lexical",),
    "vector_index": ("retrieval_index_vector",),
    "corpus_inventory": ("corpus_inventory_hash",),
    "graph_cache": (),                     # 无对应冻结组件：仅要求状态合法
}

# 谱系顺序（历史 → 现在）。phase 标签用于报告，可扩充。
SEGMENTS = [
    ("4D.0", "history/scholarly_core_freeze_v1.4d0-final.json"),
    ("4D.1", "history/scholarly_core_freeze_v1.4d1-policy-registered.json"),
    ("4D.1", "history/scholarly_core_freeze_v1.4d1-final.json"),
    ("4D.2", "history/scholarly_core_freeze_v1.4d2-workspace-registered.json"),
    # Phase 4E：CCR-0001 remediation（real provider wiring）。
    ("4E", "history/scholarly_core_freeze_v1.4e-ccr0001-remediation.json"),
    # Phase 5A：presentation hardening（PDR-0001）。
    ("5A", "history/scholarly_core_freeze_v1.5a-presentation-hardening.json"),
    # Phase 5A：P5A-006 remediation（数据版本 / 学术语义分类分离）。
    #   本段的变化**只有数据版本组件**（corpus_inventory_hash）：外部语料目录新增 1 文件。
    #   学术语义组件全部未变 —— 由 core_freeze.component_classes 逐项判定。
    ("5A", "history/scholarly_core_freeze_v1.5a-p6-data-version-separation.json"),
]

# 段 → 标签（可选；仅用于报告可追溯性，不参与判定）
SEGMENT_CCR = {
    "history/scholarly_core_freeze_v1.4e-ccr0001-remediation.json": "CCR-0001",
    "history/scholarly_core_freeze_v1.5a-presentation-hardening.json": "PDR-0001",
    "history/scholarly_core_freeze_v1.5a-p6-data-version-separation.json": "PDR-0001",
}
SEGMENT_REMEDIATION = {
    "history/scholarly_core_freeze_v1.5a-p6-data-version-separation.json": "P5A-006",
}


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _diff(a, b):
    ca, cb = (a.get("components") or {}), (b.get("components") or {})
    return sorted(k for k in set(ca) | set(cb) if ca.get(k) != cb.get(k))


def _class_of(name, *manifests):
    """→ 组件类；**任何** manifest 都没声明过这个组件 → None（UNCLASSIFIED）。"""
    for m in manifests:
        cls = (m.get("component_classes") or {}).get(name)
        if cls:
            return cls
    if name in PRODUCT_BOUNDARY_KEYS:
        return CF.CLASS_PRODUCT
    if name in DATA_VERSION_KEYS:
        return CF.CLASS_DATA
    if name in CF.SPEC:
        return CF.CLASS_SCHOLARLY
    return None


def _check_declaration(decl, key, prev, cur, semantic_changes, changed):
    """→ 问题列表（空 = 该声明完整且与依赖构件状态一致）。§4/§10/§12。"""
    bad = []
    for req in ("component", "before_hash", "after_hash", "reason", "source_diff",
                "ingestion_status", "dependent_artifacts", "verified_at"):
        if decl.get(req) in (None, "", {}, []):
            bad.append("声明缺字段 %s" % req)
    if decl.get("component") != key:
        bad.append("声明 component=%s 与漂移组件 %s 不符" % (decl.get("component"), key))
    if decl.get("before_hash") != (prev.get("components") or {}).get(key):
        bad.append("声明 before_hash 与上一段不一致")
    if decl.get("after_hash") != (cur.get("components") or {}).get(key):
        bad.append("声明 after_hash 与本段不一致")
    if decl.get("scholarly_semantic_hashes_unchanged") is not True:
        bad.append("声明未确认 scholarly_semantic_hashes_unchanged")
    if semantic_changes:
        bad.append("存在学术语义变化，数据版本声明不得通过：%s" % semantic_changes[:4])
    if decl.get("ingestion_status") not in INGESTION_STATES:
        bad.append("ingestion_status 非法：%r" % decl.get("ingestion_status"))

    deps = decl.get("dependent_artifacts") or {}
    for dep, state in deps.items():
        if dep not in DEPENDENT_GUARDS:
            bad.append("未知依赖构件 %s" % dep)
            continue
        if state not in DATA_VERSION_STATES:
            bad.append("依赖构件 %s 状态非法：%r" % (dep, state))
            continue
        guards = DEPENDENT_GUARDS[dep]
        for g in guards:
            g_changed = g in changed
            if state in ("CHANGED", "REBUILT") and not g_changed:
                bad.append("依赖构件 %s=%s 但冻结组件 %s 未变化（stale index 风险）"
                           % (dep, state, g))
            if state in ("UNCHANGED_BY_DESIGN", "UNAVAILABLE") and g_changed:
                bad.append("依赖构件 %s=%s 但冻结组件 %s 已变化（自相矛盾）"
                           % (dep, state, g))
    missing_deps = [d for d in DEPENDENT_GUARDS if d not in deps]
    if missing_deps:
        bad.append("声明未覆盖依赖构件：%s" % missing_deps)

    # canonical passage store 的声明必须与 passage_store 状态一致
    ps_changed = deps.get("passage_store") in ("CHANGED", "REBUILT")
    if bool(decl.get("canonical_passage_store_changed")) != bool(ps_changed):
        bad.append("canonical_passage_store_changed 与 passage_store 状态不一致")
    # 新文件真的被 ingestion 了，passage store 就必须动过 —— 否则是在宣称检索能力
    if decl.get("ingestion_status") == "INGESTED" and not ps_changed:
        bad.append("声明 INGESTED 但 passage store 未变化（不得宣称可检索）")
    return bad


def classify_segment(prev, man):
    """纯函数：`prev` → `man` 的三类变化分类与判定（**不做任何文件 I/O**）。

    §14 的单元测试直接喂合成 manifest 到这里。
    """
    changed = _diff(prev, man) if prev else []
    semantic, data_keys, runtime, unclassified = [], [], [], []
    for k in changed:
        cls = _class_of(k, man, prev or {})
        if cls is None:
            unclassified.append(k)
        elif cls == CF.CLASS_SCHOLARLY:
            semantic.append(k)
        elif cls == CF.CLASS_DATA:
            data_keys.append(k)
        elif cls == CF.CLASS_PRODUCT:
            runtime.append(k)
        else:                                                             # pragma: no cover
            unclassified.append(k)

    declarations = {d.get("component"): d for d in (man.get("data_version_declarations") or [])}
    data_changes, problems = [], []
    for k in data_keys:
        decl = declarations.get(k)
        if not decl:
            problems.append((FAIL_UNDECLARED,
                             "数据版本组件 %s 变化但**没有声明**" % k))
            data_changes.append({
                "component": k, "before_hash": (prev.get("components") or {}).get(k),
                "after_hash": (man.get("components") or {}).get(k),
                "declared": False,
            })
            continue
        bad = _check_declaration(decl, k, prev, man, semantic, changed)
        if bad:
            problems.append((FAIL_INCONSISTENT, "；".join(bad[:4])))
        data_changes.append({
            "component": k,
            "before_hash": decl.get("before_hash"),
            "after_hash": decl.get("after_hash"),
            "declared": True,
            "reason": decl.get("reason"),
            "source_diff": decl.get("source_diff"),
            "ingestion_status": decl.get("ingestion_status"),
            "canonical_passage_store_changed": decl.get("canonical_passage_store_changed"),
            "dependent_artifacts": decl.get("dependent_artifacts"),
            "verified_at": decl.get("verified_at"),
            "consistent": not bad,
        })
    if semantic:
        problems.append((FAIL_SEMANTIC, "学术语义组件变化：%s" % semantic[:6]))
    for k in unclassified:
        problems.append((FAIL_UNCLASSIFIED, "无法定位组件类：%s" % k))

    codes = sorted({c for c, _ in problems})
    return {
        "freeze_version": man.get("freeze_version"),
        "scholarly_status": man.get("scholarly_status"),
        "components_n": len(man.get("components") or {}),
        "component_classes_n": {
            CF.CLASS_SCHOLARLY: sum(1 for v in (man.get("component_classes") or {}).values()
                                    if v == CF.CLASS_SCHOLARLY),
            CF.CLASS_PRODUCT: sum(1 for v in (man.get("component_classes") or {}).values()
                                  if v == CF.CLASS_PRODUCT),
            CF.CLASS_DATA: sum(1 for v in (man.get("component_classes") or {}).values()
                               if v == CF.CLASS_DATA),
        },
        "changed_components": changed,
        # ── 三类变化（§2）
        "scholarly_semantic_changes": len(semantic),
        "scholarly_semantic_change_keys": semantic,
        "data_version_changes": data_changes,
        "data_version_changes_n": len(data_changes),
        "product_runtime_changes": runtime,
        "product_runtime_changes_n": len(runtime),
        "unclassified_changes": unclassified,
        # ── 兼容旧字段（4D.x 报告与套件读它们）
        "changed_product_boundary": runtime,
        "runtime_wiring_changed": bool(runtime),
        # ── 逐段判定（§13）
        "status": "PASS" if not problems else "FAIL",
        "failure_codes": codes,
        "problems": [{"code": c, "detail": d} for c, d in problems],
        "all_data_version_changes_declared_and_consistent": (
            bool(data_changes) and all(d.get("declared") and d.get("consistent")
                                       for d in data_changes)) if data_changes else True,
    }


def _segment(phase, rel, prev, man, parent_rel=None):
    """分类结果 + 本段文件事实（hash / 历史快照身份）。"""
    entry = classify_segment(prev, man)
    entry.update({
        "phase": phase,
        "manifest": rel,
        "parent_manifest": parent_rel,
        "historical_artifact": "present",
        "manifest_hash": sha_file(os.path.join(FREEZE_DIR, rel)),
        "ccr": SEGMENT_CCR.get(rel),
        "remediation": SEGMENT_REMEDIATION.get(rel),
    })
    return entry


def _parent_hash(entries):
    """上一个 present 段的 manifest_hash（字节不可得的段跳过）。"""
    for e in reversed(entries):
        if e.get("manifest_hash"):
            return e["manifest_hash"]
    return None


def build():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    entries = []
    prev = None
    rels = [r for _, r in SEGMENTS]
    for phase, rel in SEGMENTS:
        p = os.path.join(FREEZE_DIR, rel)
        if not os.path.isfile(p):
            entries.append({
                "phase": phase, "manifest": rel,
                "historical_artifact": "unavailable",
                "manifest_hash": None,
                "note": "该段字节不可得；不伪造文件，仅保留记录位",
            })
            continue
        man = _load(p)
        idx = rels.index(rel)
        parent_rel = rels[idx - 1] if idx > 0 else None
        entry = _segment(phase, rel, prev, man, parent_rel=parent_rel)
        entry["parent_manifest_hash"] = _parent_hash(entries) if idx > 0 else None
        entries.append(entry)
        prev = man

    live = _load(LIVE)
    live_hash = sha_file(LIVE)
    present = [e for e in entries if e.get("historical_artifact") == "present"]
    doc = {
        "schema_version": "scholarly-core-freeze-lineage/v1",
        "generated_at": _utcnow(),
        "live_manifest": "scholarly_core_freeze_v1.json",
        "live_manifest_hash": live_hash,
        "live_freeze_version": live.get("freeze_version"),
        "live_scholarly_status": live.get("scholarly_status"),
        "product_boundary_keys": list(PRODUCT_BOUNDARY_KEYS),
        "data_version_keys": list(DATA_VERSION_KEYS),
        "component_classes": CF.component_classes(),
        "segments": entries,
        "rule": ("任何一段的 scholarly_semantic 变化必须为 0（产品阶段不得改核心语义）；"
                 "product_boundary 变化记为 product_runtime_changes（不失败）；"
                 "data_version 变化必须逐条**声明且与依赖构件状态一致**，"
                 "否则 UNDECLARED_DATA_DRIFT / DATA_VERSION_INCONSISTENT。"),
        "history_policy": ("历史 manifest 以**真实字节**保存在 history/ 下；"
                           "若字节不可得则标记 unavailable 并只保留 hash，**不伪造**文件。"),
    }
    doc["live_matches_last_segment"] = (
        bool(present) and present[-1].get("manifest_hash") == live_hash)
    doc["all_segments_semantic_changes_zero"] = all(
        e.get("scholarly_semantic_changes", 0) == 0 for e in present)
    doc["all_segments_status_pass"] = all(e.get("status") == "PASS" for e in present)
    doc["failure_codes"] = sorted({c for e in present for c in (e.get("failure_codes") or [])})
    doc["semantic_changes_total"] = sum(e.get("scholarly_semantic_changes", 0)
                                        for e in present)
    doc["data_version_changes_total"] = sum(e.get("data_version_changes_n", 0)
                                            for e in present)
    doc["product_runtime_changes_total"] = sum(e.get("product_runtime_changes_n", 0)
                                               for e in present)
    with open(LINEAGE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("freeze lineage -> %s（%d 段；live 与末段一致=%s；全段 PASS=%s；"
          "semantic=%d / data_version=%d / product_runtime=%d）"
          % (os.path.relpath(LINEAGE, VAULT), len(entries),
             doc["live_matches_last_segment"], doc["all_segments_status_pass"],
             doc["semantic_changes_total"], doc["data_version_changes_total"],
             doc["product_runtime_changes_total"]))
    for e in present:
        if e.get("status") != "PASS":
            print("  FAIL %s %s：%s" % (e.get("phase"), e.get("manifest"),
                                        e.get("failure_codes")))
    return 0 if (doc["all_segments_status_pass"] and doc["all_segments_semantic_changes_zero"]
                 and doc["live_matches_last_segment"]) else 1


def verify(quiet=False):
    problems, codes = [], []
    if not os.path.isfile(LINEAGE):
        print("FAIL 缺 freeze lineage：%s（先 --build）" % os.path.relpath(LINEAGE, VAULT))
        return 1
    doc = _load(LINEAGE)
    live_hash = sha_file(LIVE)
    if doc.get("live_manifest_hash") != live_hash:
        problems.append("live manifest 已变但谱系未更新（%s != %s）"
                        % (live_hash[:16], str(doc.get("live_manifest_hash"))[:16]))
    if not doc.get("live_matches_last_segment"):
        problems.append("谱系末段与 live manifest 不一致")
    if not doc.get("all_segments_semantic_changes_zero"):
        codes.append(FAIL_SEMANTIC)
        problems.append("存在核心语义变化段（产品阶段不允许）")
    if not doc.get("all_segments_status_pass"):
        codes.extend(doc.get("failure_codes") or [])
        problems.append("存在未通过的谱系段：%s" % (doc.get("failure_codes") or []))

    for e in doc.get("segments") or []:
        if e.get("historical_artifact") != "present":
            continue
        p = os.path.join(FREEZE_DIR, e["manifest"])
        if not os.path.isfile(p):
            problems.append("历史快照缺失：%s" % e["manifest"])
            continue
        if sha_file(p) != e.get("manifest_hash"):
            problems.append("历史快照字节被改动：%s" % e["manifest"])
        if e.get("scholarly_semantic_changes") != 0:
            codes.append(FAIL_SEMANTIC)
            problems.append("段 %s 有核心语义变化：%s"
                            % (e.get("phase"), e.get("scholarly_semantic_change_keys")))
        for c in (e.get("failure_codes") or []):
            codes.append(c)
            problems.append("段 %s 判定失败 %s" % (e.get("phase"), c))
        # 变化组件必须能在「本段或上一段」的 manifest 里定位
        man = _load(p)
        prev = {}
        pm = e.get("parent_manifest")
        if pm and os.path.isfile(os.path.join(FREEZE_DIR, pm)):
            prev = _load(os.path.join(FREEZE_DIR, pm))
        for k in e.get("changed_components") or []:
            if _class_of(k, man, prev) is None:
                codes.append(FAIL_UNCLASSIFIED)
                problems.append("段 %s 的 changed_component 无法定位类：%s"
                                % (e.get("phase"), k))
    if problems:
        print("FAIL freeze 谱系校验未通过：")
        for x in problems[:10]:
            print("  - %s" % x)
        print("LINEAGE_FAILURE_CODES: %s" % (",".join(sorted(set(codes))) or "NONE"))
        return 1
    if not quiet:
        print("freeze 谱系校验通过：%d 段；live=%s；semantic=%d / data_version=%d / "
              "product_runtime=%d"
              % (len(doc.get("segments") or []), live_hash[:16],
                 doc.get("semantic_changes_total", 0),
                 doc.get("data_version_changes_total", 0),
                 doc.get("product_runtime_changes_total", 0)))
    return 0


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def show():
    print(json.dumps(_load(LINEAGE), ensure_ascii=False, indent=2)[:4000])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="冻结谱系（三类变化分类）")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.build:
        return build()
    if a.show:
        return show()
    return verify(quiet=a.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
