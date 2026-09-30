#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase4a1_completion.py — Phase 4A.1 §10 完成判据

每条判据都指向**一个已经存在、可复算的产物**，不在门里放宽任何阈值。
未全过 → 只能说 PARTIAL / BLOCKED。

判据（§10 的原文逐条 + 本阶段自身的审计要求）
─────────────────────────────────────────────
 1  gaze/regard/凝视 受控映射存在
 2  普通 regard 不被全量误解析（无上下文不解析）
 3  Big Other / little other 已拆分
 4  bare autre 保留 ambiguity
 5  reality 独立于 Real
 6  signified 独立于 signifier
 7  demand 独立于 desire
 8  need 独立于 demand
 9  objet 与 objet a 不再发生错误解析
10  所有新增 canonical entity 有真实 Passage 支持
11  所有新增 canonical relation 有 evidence
12  MCP regressions 通过（6 类 tool 全覆盖）
13  canonical / source corpus 未被修改
14  passage IDs 未改变
15  Phase 1–4A 无回归（完整 run 全绿，含本阶段套件）
16  validator 0 error（叠加层 + vault）
17  hard gates = 0（Phase 4A 的 11 项仍全为 0；本层未引入 canonical 写路径）
18  缺口队列已按 §9 更新（追加 resolved/invalidated，保留 audit trail）

用法
────
    python3 check_phase4a1_completion.py [--verify] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
IDX = os.path.join(VAULT, "_data", "index")
LAYER = os.path.join(VAULT, "_data", "ontology", "v4a1")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

OUT = os.path.join(IDX, "PHASE4A1_COMPLETION_GATE.json")


def jd(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    import ontology_v4a1 as onto
    import knowledge_api as api

    checks = []

    def ck(cid, name, ok, evidence):
        checks.append({"id": cid, "name": name, "passed": bool(ok),
                       "evidence": evidence if not isinstance(evidence, (dict, list))
                       else json.dumps(evidence, ensure_ascii=False)[:400]})

    reg = jd(os.path.join(IDX, "ONTOLOGY_V4A1_REGRESSION.json"), {})
    val = jd(os.path.join(IDX, "ONTOLOGY_V4A1_VALIDATION.json"), {})
    rc = {c["name"]: c for c in reg.get("checks", [])}
    rl = {r["term"] + ("|ctx" if r.get("context") else ""): r
          for r in reg.get("resolver", [])}
    term = {t["form"]: t for t in reg.get("terminology", [])}

    ck(1, "gaze/regard/凝视 受控映射存在",
       bool(term.get("gaze", {}).get("mappings")) and
       bool(term.get("regard", {}).get("mappings")) and
       bool(term.get("凝视", {}).get("mappings")) and
       all(t.get("relation_type") == "controlled_term_mapping"
           for t in term.values() if t.get("mappings")),
       {k: {"mappings": v.get("mappings"), "ctx": v.get("context_required"),
            "type": v.get("relation_type")} for k, v in term.items()})

    bare_regard = rl.get("regard", {})
    ck(2, "普通 regard 不被全量误解析（无上下文 → AMBIGUOUS/context_required）",
       bare_regard.get("mcp_status") == "AMBIGUOUS"
       and bare_regard.get("mcp_context_required") is True
       and not bare_regard.get("mcp_entities"),
       bare_regard)

    ck(3, "Big Other / little other 已拆分",
       rl.get("l'Autre", {}).get("mcp_entities") == ["concept.big-other"]
       and rl.get("l'autre", {}).get("mcp_entities") == ["concept.little-other"]
       and rc.get("Big Other / little other 已拆分", {}).get("passed"),
       {"big": rl.get("l'Autre", {}).get("mcp_entities"),
        "little": rl.get("l'autre", {}).get("mcp_entities")})

    ck(4, "bare autre 保留 ambiguity",
       rl.get("autre", {}).get("mcp_status") == "AMBIGUOUS"
       and rl.get("autre", {}).get("mcp_context_required") is True
       and not rl.get("autre", {}).get("mcp_entities"),
       rl.get("autre"))

    ck(5, "reality 独立于 Real",
       rl.get("réalité", {}).get("mcp_entities") == ["concept.realite"]
       and rl.get("Réel", {}).get("mcp_entities") == ["concept.le-reel"],
       {"réalité": rl.get("réalité", {}).get("mcp_entities"),
        "Réel": rl.get("Réel", {}).get("mcp_entities")})

    ck(6, "signified 独立于 signifier",
       rl.get("signifié", {}).get("mcp_entities") == ["concept.signifie"]
       and rl.get("signifiant", {}).get("mcp_entities") == ["concept.signifiant"],
       {"signifié": rl.get("signifié", {}).get("mcp_entities"),
        "signifiant": rl.get("signifiant", {}).get("mcp_entities")})

    ck(7, "demand 独立于 desire",
       rl.get("demande", {}).get("v4a1_context_required_entities") == ["concept.demande"]
       and rl.get("demande|ctx", {}).get("mcp_entities") == ["concept.demande"]
       and rl.get("désir", {}).get("mcp_entities") == ["concept.desir"],
       {"demande": rl.get("demande", {}).get("v4a1_context_required_entities"),
        "demande_ctx": rl.get("demande|ctx", {}).get("mcp_entities"),
        "désir": rl.get("désir", {}).get("mcp_entities")})

    ck(8, "need 独立于 demand",
       rl.get("besoin", {}).get("v4a1_context_required_entities") == ["concept.besoin"]
       and rl.get("besoin|ctx", {}).get("mcp_entities") == ["concept.besoin"],
       {"besoin": rl.get("besoin", {}).get("v4a1_context_required_entities"),
        "besoin_ctx": rl.get("besoin|ctx", {}).get("mcp_entities")})

    ck(9, "objet 与 objet a 不再发生错误解析",
       rl.get("objet a", {}).get("mcp_entities") == ["concept.objet-petit-a"]
       and rl.get("objet", {}).get("mcp_entities") == ["term.objet"]
       and rc.get("objet 与 objet a 不再错误解析（objet a → concept.objet-petit-a；裸 objet → term.objet）",
                  {}).get("passed"),
       {"objet_a": rl.get("objet a", {}).get("mcp_entities"),
        "objet": rl.get("objet", {}).get("mcp_entities")})

    ck(10, "所有新增 canonical entity 有真实 Passage 支持",
       val.get("n_errors") == 0 and any(c["name"].startswith("每个新实体都有真实")
                                        and c["passed"] for c in val.get("checks", [])),
       {"counts": val.get("counts"), "n_errors": val.get("n_errors")})

    rel_ok = next((c for c in val.get("checks", [])
                   if c["name"].startswith("关系：谓词已声明")), {})
    ck(11, "所有新增 canonical relation 有 evidence",
       rel_ok.get("passed") is True and val.get("counts", {}).get("relations", 0) >= 10,
       {"relations": val.get("counts", {}).get("relations"), "check": rel_ok})

    mcp_tools = {m["tool"] for m in reg.get("mcp", [])}
    ck(12, "MCP regressions 通过（6 类 tool 全覆盖）",
       reg.get("all_passed") is True
       and {"resolve_entity", "terminology_lookup", "get_concept",
            "find_concept_evidence", "compare_concepts",
            "trace_concept"} <= mcp_tools
       and all(m.get("sections_ok") and "error" not in m for m in reg.get("mcp", [])),
       {"passed": "%s/%s" % (reg.get("passed"), reg.get("total")),
        "tools": sorted(mcp_tools)})

    ck(13, "canonical / source corpus 未被修改（逐字节）",
       reg.get("integrity", {}).get("changed") == []
       and reg.get("integrity", {}).get("fabricated_passage_ids") == [],
       {"monitored": reg.get("integrity", {}).get("monitored_files"),
        "changed": reg.get("integrity", {}).get("changed")})

    ck(14, "passage IDs 未改变",
       reg.get("integrity", {}).get("passages") == 249105
       and bool(reg.get("integrity", {}).get("passages_sha256")),
       {"n": reg.get("integrity", {}).get("passages"),
        "sha256": reg.get("integrity", {}).get("passages_sha256")})

    # 优先读**本次运行**的套件中间记录（TEST_RUN.suites.json，在产物校验前写入）；
    # 没有它才退回上一轮的完整记录。否则门会在同一次 run 里读旧记录 → 假红。
    tr_s = jd(os.path.join(IDX, "TEST_RUN.suites.json"))
    tr = jd(os.path.join(IDX, "TEST_RUN.json"), {})
    src = tr_s if (tr_s and tr_s.get("results")) else tr
    results = {r["name"]: r["status"] for r in (src.get("results") or [])}
    need = ["test_phase4a1_ontology", "test_phase4a_mcp", "test_phase4a_research",
            "test_phase4a_sufficiency"]
    suites_ok = (not src.get("quick_mode")) and not src.get("failed_suites") \
        and all(results.get(n) == "OK" for n in need)
    tools_ok = True
    if src is tr:      # 用完整记录时，连产物校验的失败也一并要求为空
        tools_ok = tr.get("exit_code") == 0
    ck(15, "Phase 1–4A 无回归（完整 run 全绿，含本阶段套件）",
       suites_ok and tools_ok,
       {"source": ("TEST_RUN.suites.json" if src is tr_s else "TEST_RUN.json"),
        "exit_code": tr.get("exit_code"), "failed": src.get("failed_suites"),
        "suites": {n: results.get(n) for n in need},
        "total_suites": src.get("suites")})

    vault_val = jd(os.path.join(VAULT, "_index", "Reports", "validation-report.json"), {})
    vsum = (vault_val or {}).get("summary") or {}
    ck(16, "validator 0 error（叠加层 + vault）",
       val.get("n_errors") == 0 and vsum.get("errors") == 0,
       {"overlay_errors": val.get("n_errors"),
        "vault_errors": vsum.get("errors"),
        "vault_relation_errors": vsum.get("relation_errors")})

    hg = jd(os.path.join(IDX, "PHASE4A_HARD_GATES.json"), {})
    # 本层不得引入 canonical 写路径：生成器只能写 _data/ontology/** 与缺口队列
    write_re = re.compile(r"open\([^)]*[\"'](a|w|ab|wb)[\"']")
    offenders = []
    for name in ("build_ontology_v4a1.py", "apply_ontology_v4a1_repairs.py",
                 "ontology_v4a1.py", "regress_ontology_v4a1.py",
                 "validate_ontology_v4a1.py"):
        p = os.path.join(HERE, name)
        if not os.path.isfile(p):
            continue
        src = open(p, encoding="utf-8").read()
        for m in write_re.finditer(src):
            seg = src[max(0, m.start() - 400):m.start() + 200]
            if any(k in seg for k in ("passage_store", "concepts.jsonl",
                                      "terminology_bridge", "lexical.sqlite",
                                      "alias_index", "relations/")):
                offenders.append("%s:%d" % (name, src[:m.start()].count("\n") + 1))
    ck(17, "hard gates = 0（Phase 4A 11 项仍为 0；本层无 canonical 写路径）",
       hg.get("gate_count") == 11 and hg.get("all_zero") is True
       and hg.get("total_violations") == 0 and not offenders,
       {"phase4a_gates": hg.get("gate_count"),
        "violations": hg.get("total_violations"), "offenders": offenders})

    import ontology_gaps as ogq
    rows = ogq.read_all()
    n_lines = sum(1 for l in open(ogq.QUEUE, encoding="utf-8") if l.strip())
    resolved = [r for r in rows if r["status"] == "resolved"]
    invalid = [r for r in rows if r["status"] == "invalidated"]
    ck(18, "缺口队列已按 §9 更新（追加 resolved/invalidated，保留 audit trail）",
       bool(resolved) and bool(invalid) and n_lines > len(rows)
       and all(r.get("resolution_commit") for r in resolved)
       and all(r.get("resolution_reason") for r in invalid)
       and not any(r.get("canonical_change_proposed") for r in rows),
       {"resolved": len(resolved), "invalidated": len(invalid),
        "ids": len(rows), "file_lines": n_lines,
        "layer_ref": onto.layer_meta().get("resolution_ref")})

    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    doc = {
        "schema_version": "phase4a1-completion-gate/v1",
        "phase": "Phase 4A.1 — Ontology Repair & Terminology Control",
        "layer": "ontology.v4a1",
        "resolution_ref": onto.layer_meta().get("resolution_ref"),
        "checks": checks, "passed": passed, "total": total,
        "closable": passed == total,
        "verdict": ("PHASE 4A.1 ONTOLOGY REPAIR = COMPLETE" if passed == total
                    else "PARTIAL / BLOCKED —— 未过条目见 checks"),
        "rule": ("§10 的完成判据必须逐条证明；未全过只能说 PARTIAL/BLOCKED，"
                 "且不得为了过关降低任何判据。"),
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
                                       c["name"][:58], str(c["evidence"])[:70]))
        print("[phase4a1-gate] %d/%d -> %s" % (passed, total, doc["verdict"]))
    if a.verify:
        return 0 if doc["closable"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
