#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regress_ontology_v4a1.py — Phase 4A.1 §7/§8：**新版本**的回归结果（不覆盖旧报告）

为什么要单独跑一套
──────────────────
§6 的纪律：修复本体**不得改写 Phase 3 的历史 benchmark**。所以：

* Phase 3/4A 的既有报告与结果文件**一行不动**；
* 本脚本产出的是**叠加层之后**的新测量，写进**新文件**：
      `_data/index/ONTOLOGY_V4A1_REGRESSION.json`
* 每一段都**并列**「Phase 3 层结论」与「ontology.v4a1 层结论」，
  于是「改了什么」是可见的，而不是被覆盖掉的。

五段
────
1. **resolver**：§7 点名的那批词，逐词给出两层结果
2. **terminology**：受控映射（含上下文条件）的可用性
3. **guard**：7 组 pair 的缺陷类别重分类（ENTITY_COLLISION / ONTOLOGY_MISSING /
   MODEL_COLLAPSE → RESOLVED / RESOLVED_CONTEXT_REQUIRED）
4. **mcp**：6 个 tool 在指定输入上的实跑结果（state / 证据数 / 告警）
5. **integrity**：canonical / source / 索引哈希前后不变；passage 数不变；无编造 id

用法
────
    python3 regress_ontology_v4a1.py [--json] [--verify]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

OUT = os.path.join(VAULT, "_data", "index", "ONTOLOGY_V4A1_REGRESSION.json")
STORE = os.path.join(VAULT, "_data", "passage_store")
RELATIONS = os.path.join(VAULT, "_data", "relations")
IDX = os.path.join(VAULT, "_data", "index")

# §7 指定的回归词表
RESOLVER_TERMS = [
    ("gaze", None), ("regard", None), ("regard", "Seminar XI 谈凝视与 regard"),
    ("凝视", None),
    ("l'Autre", None), ("l'autre", None), ("Autre", None), ("autre", None), ("A", None),
    ("Réel", None), ("réalité", None), ("实在界", None), ("现实", None),
    ("signifiant", None), ("signifié", None), ("signifie", None),
    ("désir", None), ("demande", None),
    ("demande", "désir 与 demande 的区别"), ("besoin", None),
    ("besoin", "demande 与 besoin 的区别"), ("moi", "le moi 与 sujet"),
    ("objet", None), ("objet a", None),
]
MCP_CALLS = [
    ("resolve_entity", {"term": "gaze"}),
    ("resolve_entity", {"term": "l'Autre"}),
    ("resolve_entity", {"term": "autre"}),
    ("resolve_entity", {"term": "A"}),
    ("terminology_lookup", {"term": "regard"}),
    ("terminology_lookup", {"term": "凝视"}),
    ("get_concept", {"entity_id": "concept.gaze"}),
    ("get_concept", {"entity_id": "concept.big-other"}),
    ("get_concept", {"entity_id": "concept.realite"}),
    ("find_concept_evidence", {"concept": "concept.gaze", "top_k": 5}),
    ("find_concept_evidence", {"concept": "concept.demande", "top_k": 5}),
    ("find_concept_evidence", {"concept": "term.objet", "top_k": 5}),
    ("compare_concepts", {"concept_a": "concept.big-other",
                          "concept_b": "concept.little-other", "top_k": 3}),
    ("compare_concepts", {"concept_a": "concept.le-reel",
                          "concept_b": "concept.realite", "top_k": 3}),
    ("compare_concepts", {"concept_a": "concept.signifiant",
                          "concept_b": "concept.signifie", "top_k": 3}),
    ("compare_concepts", {"concept_a": "concept.besoin",
                          "concept_b": "concept.demande", "top_k": 3}),
    ("trace_concept", {"concept": "concept.gaze", "per_period": 3}),
    ("trace_concept", {"concept": "concept.signifie", "per_period": 3}),
]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def snapshot():
    snap = {}
    for n in sorted(os.listdir(STORE)):
        if n.endswith(".jsonl"):
            snap["store/" + n] = sha(os.path.join(STORE, n))
    for n in sorted(os.listdir(RELATIONS)):
        if n.endswith(".jsonl"):
            snap["relations/" + n] = sha(os.path.join(RELATIONS, n))
    for n in ("lexical.sqlite", "alias_index.jsonl"):
        p = os.path.join(IDX, n)
        if os.path.isfile(p):
            snap["index/" + n] = sha(p)
    p = os.path.join(VAULT, "_data", "terminology_bridge.jsonl")
    if os.path.isfile(p):
        snap["terminology_bridge.jsonl"] = sha(p)
    return snap


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)

    import knowledge_api as api
    import ontology_v4a1 as onto
    import validate as vd
    import evidence_sufficiency  # noqa: F401  （确保引擎可导入）
    import entity_resolution as er

    before = snapshot()
    known = vd.passage_ids()

    # ── 1. resolver 回归（两层并列）
    resolver = []
    for term, ctx in RESOLVER_TERMS:
        ph3 = er.resolve(term)
        v4 = onto.resolve(term, ctx)
        r = api.resolve_entity(term, context=ctx)["resolution"]
        resolver.append({
            "term": term, "context": ctx,
            "phase3_status": "RESOLVED" if ph3["entities"] else "UNRESOLVED",
            "phase3_entities": [e["entity_id"] for e in ph3["entities"]],
            "v4a1_layer_status": v4["status"],
            "v4a1_layer_entities": [e["entity_id"] for e in v4["entities"]],
            "v4a1_context_required": v4["context_required"],
            "v4a1_context_required_entities": v4["context_required_entities"],
            "mcp_status": r["resolution_status"],
            "mcp_entities": [c["entity_id"] for c in r["candidates"]],
            "mcp_context_required": r.get("context_required"),
            "mcp_context_note": r.get("context_note"),
        })

    # ── 2. terminology 回归
    terminology = []
    for form in ("gaze", "regard", "le regard", "凝视"):
        ov = onto.terminology_lookup(form)
        mcp = api.terminology_lookup(form)
        terminology.append({
            "form": form,
            "mappings": len(ov["mappings"]),
            "relation_type": ov["relation_type"],
            "auto_resolvable": ov["auto_resolvable"],
            "context_required": ov["context_required"],
            "entity_ids": ov["entity_ids"],
            "mcp_resolution_status": mcp["resolution"]["resolution_status"],
            "mcp_rows": [{"source_form": m.get("source_form"),
                          "relation_type": m.get("relation_type"),
                          "context_requirement": m.get("context_requirement"),
                          "auto_resolution": m.get("auto_resolution")}
                         for m in (mcp["retrieval"].get("controlled_term_mapping") or [])],
        })

    # ── 3. guard 重分类
    guard = onto.guard_view()
    guard_summary = onto.guard_summary()

    # ── 4. MCP 实跑
    mcp = []
    fabricated = []
    for name, args in MCP_CALLS:
        try:
            r = api.call(name, args)
        except Exception as e:      # noqa: BLE001
            mcp.append({"tool": name, "args": args, "error": "%s: %s"
                        % (type(e).__name__, e)})
            continue
        for e in r.get("evidence") or []:
            if e["passage_id"] not in known:
                fabricated.append(e["passage_id"])
        mcp.append({
            "tool": name, "args": args,
            "state": r["evidence_state"]["state"],
            "evidence_n": len(r.get("evidence") or []),
            "resolution_status": (r.get("resolution") or {}).get("resolution_status"),
            "entities": [c.get("entity_id")
                         for c in (r.get("resolution") or {}).get("candidates") or []],
            "warnings": [w["code"] for w in r.get("warnings") or []],
            "ontology_layer": (r.get("resolution") or {}).get("ontology_layer"),
            "sections_ok": sorted(r.keys()) == sorted(
                ["request", "resolution", "retrieval", "evidence", "coverage",
                 "provenance", "warnings", "evidence_state"]),
        })

    after = snapshot()
    changed = [k for k in before if before[k] != after.get(k)]
    store_hash = before.get("store/passages.jsonl")
    n_passages = len(known)

    checks = []

    def ck(name, ok, detail=""):
        checks.append({"name": name, "passed": bool(ok), "detail": str(detail)[:220]})

    # 完成判据里的十余条都在这里被**实测**
    def mcp_state(tool, **match):
        return [m for m in mcp if m.get("tool") == tool and all(
            m.get("args", {}).get(k) == v for k, v in match.items())]

    ck("gaze/regard/凝视 受控映射存在",
       all(t["mappings"] > 0 for t in terminology
           if t["form"] in ("gaze", "regard", "凝视")),
       [{"form": t["form"], "mappings": t["mappings"],
         "ctx": t["context_required"]} for t in terminology])
    reg = [r for r in resolver if r["term"] == "regard" and not r["context"]][0]
    ck("普通 regard 不被全量解析（无上下文 → 不解析）",
       reg["mcp_status"] == "AMBIGUOUS" and reg["mcp_context_required"]
       and not reg["mcp_entities"], reg)
    regc = [r for r in resolver if r["term"] == "regard" and r["context"]][0]
    ck("regard + 上下文 → 解析到 concept.gaze",
       regc["mcp_status"] == "RESOLVED"
       and regc["mcp_entities"] == ["concept.gaze"], regc)
    bo = [r for r in resolver if r["term"] == "l'Autre"][0]
    lo = [r for r in resolver if r["term"] == "l'autre"][0]
    ck("Big Other / little other 已拆分",
       bo["mcp_entities"] == ["concept.big-other"]
       and lo["mcp_entities"] == ["concept.little-other"], {"big": bo, "little": lo})
    ba = [r for r in resolver if r["term"] == "autre"][0]
    ck("bare autre 保留 ambiguity（不自动解析成 little other）",
       ba["mcp_status"] == "AMBIGUOUS" and ba["mcp_context_required"]
       and not ba["mcp_entities"], ba)
    A = [r for r in resolver if r["term"] == "A"][0]
    ck("单字符 A 仍不解析（沿用 Phase 3 ambiguity guard）",
       A["mcp_status"] == "UNRESOLVED" and not A["mcp_entities"], A)
    rl = {r["term"]: r for r in resolver}
    ck("reality 独立于 Real",
       rl["réalité"]["mcp_entities"] == ["concept.realite"]
       and rl["Réel"]["mcp_entities"] == ["concept.le-reel"], {"realite": rl["réalité"],
                                                              "reel": rl["Réel"]})
    ck("signified 独立于 signifier",
       rl["signifié"]["mcp_entities"] == ["concept.signifie"]
       and rl["signifiant"]["mcp_entities"] == ["concept.signifiant"], rl["signifié"])
    dem = [r for r in resolver if r["term"] == "demande" and not r["context"]][0]
    demc = [r for r in resolver if r["term"] == "demande" and r["context"]][0]
    ck("demand 独立于 desire",
       dem["v4a1_context_required_entities"] == ["concept.demande"]
       and demc["mcp_entities"] == ["concept.demande"]
       and rl["désir"]["mcp_entities"] == ["concept.desir"]
       and set(dem["v4a1_context_required_entities"]) != set(rl["désir"]["mcp_entities"]),
       {"demande_bare": dem["v4a1_context_required_entities"],
        "demande_ctx": demc["mcp_entities"], "desir": rl["désir"]["mcp_entities"]})
    ck("need 独立于 demand",
       rl["besoin"]["v4a1_context_required_entities"] == ["concept.besoin"]
       and rl["demande"]["v4a1_context_required_entities"] == ["concept.demande"],
       {"besoin": rl["besoin"], "demande": rl["demande"]})
    ck("objet 与 objet a 不再错误解析（objet a → concept.objet-petit-a；裸 objet → term.objet）",
       rl["objet a"]["mcp_entities"] == ["concept.objet-petit-a"]
       and rl["objet"]["mcp_entities"] == ["term.objet"],
       {"objet": rl["objet"], "objet_a": rl["objet a"]})
    ck("所有 Phase 3 配对缺陷已重分类（无 live 缺陷）",
       not guard_summary["still_defective"], guard_summary)
    ck("MCP 回归：全部调用成功且返回 8 段",
       all(m.get("sections_ok") and "error" not in m for m in mcp),
       [m for m in mcp if "error" in m or not m.get("sections_ok")][:3])
    ck("MCP 回归：无编造 passage_id", not fabricated, fabricated[:5])
    ck("canonical / source / 索引未被修改（逐字节）", not changed, changed)
    ck("passage IDs 未改变（store hash 与计数）",
       bool(store_hash) and n_passages == 249105,
       {"store_sha256": store_hash, "n_passages": n_passages})

    doc = {
        "schema_version": "ontology-v4a1-regression/v1",
        "layer": "ontology.v4a1",
        "resolution_ref": onto.layer_meta().get("resolution_ref"),
        "supersedes_nothing": ("本文件是**新增**结果；Phase 3 / 4A 的既有报告与结果"
                               "文件均未被覆盖（§6）。"),
        "resolver": resolver,
        "terminology": terminology,
        "guard": guard,
        "guard_summary": guard_summary,
        "mcp": mcp,
        "integrity": {"monitored_files": len(before), "changed": changed,
                      "passages": n_passages, "passages_sha256": store_hash,
                      "fabricated_passage_ids": fabricated},
        "checks": checks,
        "passed": sum(1 for c in checks if c["passed"]), "total": len(checks),
        "all_passed": all(c["passed"] for c in checks),
    }
    os.makedirs(IDX, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for c in checks:
            print("  %-5s %-58s %s" % ("PASS" if c["passed"] else "FAIL",
                                       c["name"][:58], c["detail"][:80]))
        print("[ontology.v4a1 regression] %d/%d passed" % (doc["passed"], doc["total"]))
        print("wrote %s" % os.path.relpath(OUT, VAULT))
    if a.verify:
        return 0 if doc["all_passed"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
