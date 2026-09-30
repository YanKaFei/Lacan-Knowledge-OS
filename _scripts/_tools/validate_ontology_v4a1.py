#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_ontology_v4a1.py — Phase 4A.1 本体层的**独立校验器**（必须 0 error）

它和 `validate_vault.py` 的分工
───────────────────────────────
* `validate_vault.py` 校验 vault（Markdown 呈现层）+ `_data/relations/**`；
  叠加层**刻意不住在那两个位置**，所以它看不到、也不该看到本层。
* 本校验器只校验叠加层自身的硬约束，并且**独立复核**证据段号是真实存在的
  （不信生成器自报）。「validator 0 error」这条完成判据由两个校验器共同满足。

检查项（每条失败都是 error）
────────────────────────────
1.  **ID 规范**：`concept.<slug>` / `term.<slug>`（小写字母数字连字符）
2.  **不与 Gold Concept Set 撞 id**（叠加层只能新增）
3.  **实体必有真实证据**：`passages` 非空且每个 id 在 canonical store 里
4.  **实体必带 provenance 与 review_status**，且 `definition` 显式为 null
5.  **证据行**：entity/rule 必须在 spec 里声明过；段号真实；上下文受限规则必须带 caveat
6.  **映射**：`relation_type=controlled_term_mapping`；`auto_resolution=false`
    必须给出 `context_requirement != none` 与 `context_rule`
7.  **关系**：谓词 ∈ 17 基础 ∪ 声明的扩展；两端实体存在；**至少 1 条真实证据段号**
8.  **迁移**：`kept_in_store=true` 且 `deleted=false`（不得删旧实体）
9.  **MANIFEST 完整性**：逐文件 hash 与 content_hash 可复算；`gold_concepts_untouched=true`
10. **确定性**：产物里不出现墙钟时间戳

用法
────
    python3 validate_ontology_v4a1.py [--json] [--verify]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
LAYER = os.path.join(VAULT, "_data", "ontology", "v4a1")
STORE = os.path.join(VAULT, "_data", "passage_store")
sys.path.insert(0, HERE)

ID_RE = re.compile(r"^(concept|term)\.[a-z0-9][a-z0-9-]*$")
GOLD_RELATION_PREDICATES = {
    "defines", "redefines", "develops", "references", "contradicts", "influenced_by",
    "criticizes", "translates_as", "formalized_as", "represented_by", "appears_in",
    "related_to", "clinical_application", "case_example", "topological_model",
    "primary_source", "secondary_interpretation",
}
REQUIRED_ENTITY_FIELDS = ("id", "type", "entity_role", "canonical_name", "title",
                          "aliases", "status", "review_status", "authority_level",
                          "passages", "trace_status", "definition",
                          "definition_status", "rationale", "source_notes", "layer")


def jl(name):
    p = os.path.join(LAYER, name)
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def jd(name, default=None):
    p = os.path.join(LAYER, name)
    if not os.path.isfile(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def passage_ids():
    ids = set()
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                ids.add(json.loads(line)["id"])
    return ids


def validate():
    errors, warnings, checks = [], [], []

    def ck(name, ok, detail=""):
        checks.append({"name": name, "passed": bool(ok), "detail": str(detail)[:200]})
        if not ok:
            errors.append("%s: %s" % (name, detail))

    spec = jd("spec.json", {})
    ents = jl("entities.jsonl")
    ev = jl("evidence.jsonl")
    maps = jl("term_mappings.jsonl")
    rels = jl("relations.jsonl")
    migs = jl("migrations.jsonl")
    vocab = jd("vocabulary.json", {})
    man = jd("MANIFEST.json", {})
    known = passage_ids()
    gold = {json.loads(l)["id"] for l in
            open(os.path.join(STORE, "concepts.jsonl"), encoding="utf-8") if l.strip()}
    gold_defs = {json.loads(l)["id"]: json.loads(l) for l in
                 open(os.path.join(STORE, "concepts.jsonl"), encoding="utf-8") if l.strip()}
    overlay_ids = {e["id"] for e in ents}

    # 1. ID 规范
    bad_ids = [e["id"] for e in ents if not ID_RE.match(e.get("id") or "")]
    ck("ID 规范（concept.* / term.*）", not bad_ids, bad_ids)

    # 2. 不撞 Gold id
    collide = sorted(overlay_ids & gold)
    ck("不与 Gold Concept Set 撞 id", not collide, collide)

    # 3. 实体必有真实证据
    no_ev = [e["id"] for e in ents if not e.get("passages")]
    bad_pid = [(e["id"], p) for e in ents for p in (e.get("passages") or [])
               if p not in known]
    ck("每个新实体都有真实 supporting passage", not no_ev and not bad_pid,
       {"no_evidence": no_ev, "fabricated": bad_pid[:5]})

    # 4. 实体字段完整 + provenance + 定义显式为空
    missing = [(e.get("id"), f) for e in ents for f in REQUIRED_ENTITY_FIELDS
               if f not in e]
    no_prov = [e["id"] for e in ents if not e.get("source_notes")]
    has_def = [e["id"] for e in ents if e.get("definition") is not None]
    ck("实体字段完整 + 有 provenance + 不写理论定义",
       not missing and not no_prov and not has_def,
       {"missing": missing[:3], "no_provenance": no_prov, "fabricated_definitions": has_def})

    # 5. 证据行
    rule_ids = {(e["id"], r["rule_id"]) for e in spec.get("entities", [])
                for r in e.get("evidence_rules", [])}
    bad_rule = [(r["entity_id"], r["rule_id"]) for r in ev
                if (r["entity_id"], r["rule_id"]) not in rule_ids]
    bad_ev_pid = [r["evidence_id"] for r in ev if r["passage_id"] not in known]
    no_caveat = [r["evidence_id"] for r in ev
                 if r.get("tier") == "context_scoped" and not r.get("caveat")]
    ck("证据行：规则已声明 / 段号真实 / 上下文规则带 caveat",
       not bad_rule and not bad_ev_pid and not no_caveat,
       {"undeclared_rules": bad_rule[:3], "fabricated": bad_ev_pid[:3],
        "missing_caveat": no_caveat[:3]})

    # 6. 映射
    bad_map = []
    for m in maps:
        if m.get("relation_type") != "controlled_term_mapping":
            bad_map.append((m.get("mapping_id"), "wrong relation_type"))
        if m.get("entity_id") not in (overlay_ids | gold):
            bad_map.append((m.get("mapping_id"), "unknown entity"))
        if m.get("auto_resolution") is False:
            if m.get("context_requirement") in (None, "none"):
                bad_map.append((m.get("mapping_id"), "auto_resolution=false 但无上下文要求"))
            if not m.get("context_rule"):
                bad_map.append((m.get("mapping_id"), "缺 context_rule"))
        if not m.get("evidence"):
            bad_map.append((m.get("mapping_id"), "缺证据段号"))
    ck("受控术语映射：类型/实体/上下文条件/证据", not bad_map, bad_map)

    # 7. 关系
    ext_preds = {p["predicate"] for p in
                 (vocab.get("extension", {}).get("relation_predicates_added") or [])}
    bad_rel = []
    for r in rels:
        if r["predicate"] not in (GOLD_RELATION_PREDICATES | ext_preds):
            bad_rel.append((r["relation_id"], "未声明谓词 %s" % r["predicate"]))
        for end in (r["subject"], r["object"]):
            if end not in (overlay_ids | gold) and not end.startswith("seminar."):
                bad_rel.append((r["relation_id"], "未知端点 %s" % end))
        pids = (r.get("evidence") or {}).get("passage_id") or []
        if not pids:
            bad_rel.append((r["relation_id"], "无证据段号"))
        for pid in pids:
            if pid not in known:
                bad_rel.append((r["relation_id"], "段号不存在 %s" % pid))
    ck("关系：谓词已声明 / 端点存在 / 每条有真实证据", not bad_rel, bad_rel)

    # 8. 迁移不得删实体
    bad_mig = []
    for m in migs:
        if not m.get("kept_in_store") or m.get("deleted"):
            bad_mig.append((m.get("migration_id"), "可能删除了旧实体"))
        for eid in (m.get("to_entities") or []):
            if eid not in (overlay_ids | gold):
                bad_mig.append((m.get("migration_id"), "后继实体不存在 %s" % eid))
        if m.get("from_entity") and m["from_entity"] not in gold:
            bad_mig.append((m.get("migration_id"),
                            "旧实体不在 Gold 里（不得删除/伪造）%s" % m["from_entity"]))
    ck("迁移：旧实体保留（kept_in_store & not deleted）", not bad_mig, bad_mig)

    # 9. MANIFEST 完整性
    man_ok, detail = True, {}
    for name, want in (man.get("file_hashes") or {}).items():
        p = os.path.join(LAYER, name)
        if not os.path.isfile(p):
            man_ok, detail[name] = False, "缺文件"
            continue
        rows = jl(name) if name.endswith(".jsonl") else jd(name, {})
        blob = json.dumps(rows, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        got = hashlib.sha256(blob).hexdigest()
        if got != want:
            man_ok, detail[name] = False, "hash 不符"
    want_ch = hashlib.sha256(json.dumps(man.get("file_hashes"), sort_keys=True)
                             .encode("utf-8")).hexdigest()
    if want_ch != man.get("content_hash"):
        man_ok, detail["content_hash"] = False, "content_hash 不符"
    ck("MANIFEST：逐文件 hash 与 content_hash 可复算", man_ok, detail)
    # Gold 计数**由 spec 声明**（参考语料 53）——校验的是「本层没有改动 Gold」，
    # 不是「世界上只能有 53 条概念」：自建 / demo 语料用同一个校验器。
    gold_declared = (spec.get("base_layer") or {}).get("gold_concept_count")
    ck("Gold Concept Set 未被本层修改（声明 + 计数）",
       man.get("gold_concepts_untouched") is True and len(gold) == gold_declared,
       {"on_disk": len(gold), "declared_in_spec": gold_declared})

    # 10. 确定性（无墙钟）
    wall = []
    for name in ("entities.jsonl", "evidence.jsonl", "term_mappings.jsonl",
                 "relations.jsonl", "migrations.jsonl", "vocabulary.json",
                 "MANIFEST.json"):
        p = os.path.join(LAYER, name)
        if os.path.isfile(p):
            txt = open(p, encoding="utf-8").read()
            if re.search(r"20\d\d-\d\d-\d\dT", txt):
                wall.append(name)
    ck("确定性：产物不含墙钟时间戳", not wall, wall)

    return {"schema_version": "ontology-v4a1-validation/v1",
            "layer": "ontology.v4a1",
            "checks": checks, "errors": errors, "n_errors": len(errors),
            "warnings": warnings, "n_warnings": len(warnings),
            "counts": {"entities": len(ents), "evidence": len(ev),
                       "mappings": len(maps), "relations": len(rels),
                       "migrations": len(migs), "gold_concepts": len(gold)},
            "resolution_ref": man.get("resolution_ref"),
            "all_passed": not errors}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    doc = validate()
    out = os.path.join(VAULT, "_data", "index", "ONTOLOGY_V4A1_VALIDATION.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for c in doc["checks"]:
            print("  %-5s %-52s %s" % ("PASS" if c["passed"] else "FAIL",
                                       c["name"][:52], c["detail"][:70]))
        print("[ontology.v4a1 validator] %d checks, %d error(s) → %s"
              % (len(doc["checks"]), doc["n_errors"],
                 "OK" if doc["all_passed"] else "FAILED"))
        print("wrote %s" % os.path.relpath(out, VAULT))
    if a.verify:
        return 0 if doc["all_passed"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
