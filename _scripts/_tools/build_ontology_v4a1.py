#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_ontology_v4a1.py — Phase 4A.1：从 `spec.json` 生成**版本化本体层**

为什么要「spec → 生成」而不是直接手写 jsonl
────────────────────────────────────────────
1. **证据必须可复算**：每个新实体的 supporting passage 都由声明的词面/上下文规则
   在 canonical store 上现算，而不是我手抄一段 id。`--check` 能证明产物与 spec 一致。
2. **Gold Concept Set 不动**：53 条住 `_data/passage_store/concepts.jsonl`，
   由 `seed_concepts_and_claims.py` 生成（Phase 2 纪律 + 测试钉死 53）。
   本层是**叠加层**，产物住 `_data/ontology/v4a1/`，由 Phase 4A 访问层合并读取。
3. **不写理论定义**：`definition` 一律 `null`，并记 `definition_status`；
   不编造任何理论表述（§30）。

产物（全部 deterministic，无墙钟）
──────────────────────────────────
    _data/ontology/v4a1/entities.jsonl        9 个新实体（concept.* / term.*）
    _data/ontology/v4a1/evidence.jsonl        逐条 supporting passage（含规则与 caveat）
    _data/ontology/v4a1/term_mappings.jsonl   受控术语映射（entity/context aware）
    _data/ontology/v4a1/relations.jsonl       typed 区分关系（含 evidence）
    _data/ontology/v4a1/migrations.jsonl      旧 id 迁移记录（不删旧实体）
    _data/ontology/v4a1/vocabulary.json       词表**最小扩展**声明
    _data/ontology/v4a1/MANIFEST.json         计数 + 逐文件 hash + content_hash

用法
────
    python3 build_ontology_v4a1.py            # 生成
    python3 build_ontology_v4a1.py --check    # 只校验产物与 spec 是否一致
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
LAYER = os.path.join(VAULT, "_data", "ontology", "v4a1")
SPEC = os.path.join(LAYER, "spec.json")
PASSAGES = os.path.join(STORE, "passages.jsonl")

PER_SEMINAR_CAP = 3
TOTAL_CAP = 40
ENTITY_PASSAGE_CAP = 20
RELATION_EVIDENCE_CAP = 3

_APOS = re.compile(r"['’`]")
_HYPH = re.compile(r"[-–—‐]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s):
    """宽容归一化（与 Phase 3 gold 推导同一套）：大小写/变音/撇号/连字符/标点全抹平。"""
    s = unicodedata.normalize("NFKC", str(s))
    s = _APOS.sub("", s)
    s = _HYPH.sub("", s)
    s = strip_accents(s)
    s = _NONWORD.sub("", s)
    return re.sub(r"\s+", " ", s).lower().strip()


def raw_norm(s):
    """保大小写的轻归一化（只做 NFKC + 撇号统一 + 空白折叠）。"""
    s = unicodedata.normalize("NFKC", str(s))
    s = _APOS.sub("'", s)
    return re.sub(r"\s+", " ", s).strip()


def match_rule(rule, raw_text, ntext):
    """→ matched_forms 或 None。规则语义全部是**可复算**的词面/上下文判定。"""
    kind = rule.get("match", "normalized_ci")
    forms = rule.get("forms") or []
    hits = []
    if kind == "normalized_ci":
        for f in forms:
            if norm(f) and norm(f) in ntext:
                hits.append(f)
    elif kind == "case_sensitive":
        for f in forms:
            if f in raw_text:
                hits.append(f)
    elif kind == "case_sensitive_word":
        for f in forms:
            if re.search(r"(?<![\w'’])%s(?![\w'’])" % re.escape(f), raw_text):
                hits.append(f)
    else:
        raise ValueError("未知 match 类型：%s" % kind)
    if not hits:
        return None
    # 上下文要求：组内任一形式出现即满足
    for grp in rule.get("require_cooccurrence") or []:
        if not any(norm(g) in ntext for g in grp):
            return None
    # 排除：任一组内形式出现即排除
    for grp in rule.get("exclude_cooccurrence") or []:
        if any(norm(g) in ntext for g in grp):
            return None
    return hits


def scan(passages_path):
    """一次扫描：→ {(entity_id, rule_id): [(passage_id, seminar, language, hits)]}"""
    spec = json.load(open(SPEC, encoding="utf-8"))
    wanted = []
    for e in spec["entities"]:
        for r in e["evidence_rules"]:
            wanted.append((e["id"], r))
    out = collections.defaultdict(list)
    with open(passages_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            raw_text = raw_norm(d.get("raw_text") or "")
            ntext = norm(raw_text)
            for eid, rule in wanted:
                sem = d.get("seminar_id")
                if rule.get("scope_seminar") and sem != rule["scope_seminar"]:
                    continue
                hits = match_rule(rule, raw_text, ntext)
                if hits:
                    out[(eid, rule["rule_id"])].append(
                        (d["id"], sem, d.get("language"), hits))
    return spec, out


def stratified(rows, per_seminar=PER_SEMINAR_CAP, total=TOTAL_CAP):
    """按 seminar 分层抽样（与 Phase 3 gold 推导同法），消除「偏向低期号」。"""
    by_sem = collections.defaultdict(list)
    for r in rows:
        by_sem[r[1] or "unknown"].append(r)
    picked = []
    for sem in sorted(by_sem):
        picked.extend(by_sem[sem][:per_seminar])
    return picked[:total]


def build():
    spec, hits = scan(PASSAGES)
    files = {}

    # ── evidence.jsonl（逐条 supporting passage）
    ev_rows = []
    first_ev = {}
    for e in spec["entities"]:
        eid = e["id"]
        for rule in e["evidence_rules"]:
            rows = stratified(hits.get((eid, rule["rule_id"]), []))
            for pid, sem, lang, forms in rows:
                ev = {
                    "schema_version": "ontology-evidence/v1",
                    "evidence_id": "ev.v4a1.%s.%s.%s" % (eid.split(".", 1)[1],
                                                         rule["rule_id"].split(".")[-1],
                                                         pid.split(".")[-1]),
                    "entity_id": eid,
                    "rule_id": rule["rule_id"],
                    "tier": rule.get("tier"),
                    "passage_id": pid,
                    "seminar_id": sem,
                    "language": lang,
                    "matched_forms": forms,
                    "match_kind": rule.get("match"),
                    "scope": {"seminar": rule.get("scope_seminar")},
                    "assertion_type": rule.get("assertion_type"),
                    "selection_method": ("normalized_substring_or_case_sensitive match on "
                                         "canonical raw_text + stratified sample "
                                         "(per_seminar<=%d,total<=%d)" % (PER_SEMINAR_CAP,
                                                                          TOTAL_CAP)),
                    "derived_by": "script:build_ontology_v4a1.py",
                    "review_status": "candidate",
                    "layer": "ontology.v4a1",
                    "caveat": rule.get("caveat"),
                }
                ev_rows.append(ev)
                first_ev.setdefault((eid, rule["rule_id"]), []).append(pid)
    ev_rows.sort(key=lambda r: (r["entity_id"], r["rule_id"], r["passage_id"]))
    files["evidence.jsonl"] = ev_rows

    # ── entities.jsonl
    ent_rows = []
    for e in spec["entities"]:
        pids = []
        for rule in e["evidence_rules"]:
            for pid in first_ev.get((e["id"], rule["rule_id"]), []):
                if pid not in pids:
                    pids.append(pid)
        row = {
            "schema_version": "ontology-entity/v1",
            "id": e["id"], "type": e.get("type"), "entity_role": e.get("entity_role"),
            "canonical_name": e["canonical_name"], "title": e["title"],
            "fr": e.get("fr"), "en": e.get("en"), "zh": e.get("zh"),
            "language": e.get("language"),
            "aliases": e.get("aliases") or [],
            "context_required_aliases": e.get("context_required_aliases") or [],
            "single_char_aliases_excluded": e.get("single_char_aliases_excluded") or [],
            "alias_exclude_forms": e.get("alias_exclude_forms") or [],
            "bare_form_policy": e.get("bare_form_policy"),
            "upgrade_path": e.get("upgrade_path"),
            "distinction_from": e.get("distinction_from") or [],
            "status": e.get("status", "active"),
            "review_status": e.get("review_status", "candidate"),
            "authority_level": e.get("authority_level", "L2"),
            "canonical": False,
            "passages": pids[:ENTITY_PASSAGE_CAP],
            "passage_evidence_n": len(pids),
            "trace_status": ("COMPLETE" if pids else "SOURCE_TRACE_INCOMPLETE"),
            "trace_missing": ([] if pids else ["passages"]),
            "definition": None,
            "definition_status": e.get("definition_status", "not_written_backlog"),
            "rationale": e.get("rationale"),
            "source_notes": e.get("source_notes") or [],
            "layer": "ontology.v4a1",
            "generated_by": "script:build_ontology_v4a1.py",
        }
        ent_rows.append(row)
    ent_rows.sort(key=lambda r: r["id"])
    files["entities.jsonl"] = ent_rows

    # ── term_mappings.jsonl
    map_rows = []
    for m in spec["mappings"]:
        row = dict(m)
        row["schema_version"] = "ontology-term-mapping/v1"
        row["context_rule"] = spec["context_rules"].get(m["mapping_id"])
        row["evidence"] = first_ev.get((m["entity_id"], "gaze.core.en"), [])[:2] + \
                          first_ev.get((m["entity_id"], "gaze.core.zh"), [])[:2]
        map_rows.append(row)
    files["term_mappings.jsonl"] = map_rows

    # ── relations.jsonl（把 EVIDENCE:<rule_id> 解析成真实段号）
    rel_rows = []
    for r in spec["relations"]:
        row = dict(r)
        row["schema_version"] = "ontology-relation/v1"
        pids = []
        for ref in r["evidence"]["passage_id"]:
            if ref.startswith("EVIDENCE:"):
                rid = ref.split(":", 1)[1]
                subj = r["subject"]
                # 规则可能属于 subject 或 object（例如 besoin→demande 的证据在两侧）
                for eid in (subj, r["object"]):
                    for pid in first_ev.get((eid, rid), []):
                        if pid not in pids:
                            pids.append(pid)
            else:
                pids.append(ref)
        row["evidence"] = dict(r["evidence"])
        row["evidence"]["passage_id"] = pids[:RELATION_EVIDENCE_CAP]
        row["evidence"]["must_have_passage"] = True
        rel_rows.append(row)
    rel_rows.sort(key=lambda r: r["relation_id"])
    files["relations.jsonl"] = rel_rows

    # ── migrations.jsonl（把证据 ref 也解析掉）
    mig_rows = []
    for m in spec["migrations"]:
        row = dict(m)
        row["schema_version"] = "ontology-migration/v1"
        pids = []
        for ref in row.get("evidence") or []:
            if isinstance(ref, str) and ref.startswith("EVIDENCE:"):
                rid = ref.split(":", 1)[1]
                for eid in ([row["from_entity"]] if row.get("from_entity") else []) + \
                        (row.get("to_entities") or []):
                    for pid in first_ev.get((eid, rid), []):
                        if pid not in pids:
                            pids.append(pid)
            else:
                pids.append(ref)
        row["evidence"] = pids[:RELATION_EVIDENCE_CAP]
        row["evidence_n"] = len(pids)
        mig_rows.append(row)
    files["migrations.jsonl"] = mig_rows

    # ── vocabulary.json
    files["vocabulary.json"] = {
        "schema_version": "ontology-vocabulary/v1",
        "layer_id": spec["layer_id"],
        "phase": spec["phase"],
        "base_relation_predicates": 17,
        "base_relation_predicates_source": "RELATION_MODEL.md §3（原为封闭枚举）",
        "extension": spec["vocabulary_extension"],
        "base_term_mapping_types": ["equivalent", "distinct_from"],
        "gold_concepts_untouched": True,
    }

    # ── MANIFEST.json
    hashes = {}
    for name in sorted(files):
        blob = json.dumps(files[name], ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        hashes[name] = hashlib.sha256(blob).hexdigest()
    content_hash = hashlib.sha256(
        json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": "ontology-layer-manifest/v1",
        "layer_id": spec["layer_id"],
        "phase": spec["phase"],
        "spec_file": os.path.relpath(SPEC, VAULT),
        "generated_by": "script:build_ontology_v4a1.py",
        "counts": {k: len(v) if isinstance(v, list) else 1 for k, v in files.items()},
        "entity_ids": [e["id"] for e in ent_rows],
        "file_hashes": hashes,
        "content_hash": content_hash,
        "resolution_ref": "%s#%s" % (spec["layer_id"], content_hash[:12]),
        "gold_concepts_untouched": True,
        "no_wall_clock": True,
    }
    return files, manifest


def write(files, manifest):
    os.makedirs(LAYER, exist_ok=True)
    for name in sorted(files):
        with open(os.path.join(LAYER, name), "w", encoding="utf-8") as f:
            if isinstance(files[name], list):
                for row in files[name]:
                    f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            else:
                json.dump(files[name], f, ensure_ascii=False, indent=1, sort_keys=True)
                f.write("\n")
    with open(os.path.join(LAYER, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


# 本生成器**只负责**这些文件；同目录下的其它文件（如
# `gap_resolutions.jsonl`，由 apply_ontology_v4a1_repairs.py 产出）不属于它，
# 不能拿来做 --check 比较（第一版就是这么误报不一致的）。
OWN_OUTPUTS = ("entities.jsonl", "evidence.jsonl", "term_mappings.jsonl",
               "relations.jsonl", "migrations.jsonl", "vocabulary.json")


def current():
    out = {}
    for name in sorted(os.listdir(LAYER)):
        if not name.endswith((".jsonl", ".json")) or name == "spec.json":
            continue
        if name not in OWN_OUTPUTS + ("MANIFEST.json",):
            continue
        p = os.path.join(LAYER, name)
        raw = open(p, encoding="utf-8").read()
        if name.endswith(".jsonl"):
            out[name] = [json.loads(l) for l in raw.split("\n") if l.strip()]
        else:
            out[name] = json.loads(raw)
    man = out.pop("MANIFEST.json", None)
    return out, man


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    files, manifest = build()
    if a.check:
        have, have_man = current()
        bad = []
        for k in sorted(set(files) | set(have)):
            if json.dumps(files.get(k), ensure_ascii=False, sort_keys=True) != \
               json.dumps(have.get(k), ensure_ascii=False, sort_keys=True):
                bad.append(k)
        if json.dumps(manifest, ensure_ascii=False, sort_keys=True) != \
           json.dumps(have_man, ensure_ascii=False, sort_keys=True):
            bad.append("MANIFEST.json")
        if bad:
            print("本体层产物与 spec.json 不一致（重跑 build_ontology_v4a1.py）：")
            for b in bad:
                print("  ✗ %s" % b)
            return 1
        print("本体层与 spec 一致：%s（%d 实体 / %d 证据 / %d 映射 / %d 关系 / %d 迁移）"
              % (manifest["resolution_ref"], len(files["entities.jsonl"]),
                 len(files["evidence.jsonl"]), len(files["term_mappings.jsonl"]),
                 len(files["relations.jsonl"]), len(files["migrations.jsonl"])))
        return 0
    write(files, manifest)
    print("wrote %s" % os.path.relpath(LAYER, VAULT))
    for k in sorted(manifest["counts"]):
        print("  %-22s %s" % (k, manifest["counts"][k]))
    print("  resolution_ref: %s" % manifest["resolution_ref"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
