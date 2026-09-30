#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase4b_hard_gates.py — Phase 4B §33：**12 项硬门禁，必须全为 0**

| # | 门禁 | 怎么判 |
|---|---|---|
| 1 | fabricated passage ID | 评测行 + 回答 claim 里的 id 必须都在 store 里 |
| 2 | citation nonexistent | 同上（citation 层） |
| 3 | source mutation | 受保护文件逐字节未变 |
| 4 | canonical mutation | 同上（含 concept/relation） |
| 5 | silent provenance upgrade | recovered 中译不得被当 L1 primary 引用 |
| 6 | candidate ontology auto-promoted | v4a1 实体/映射全部仍 `candidate`，未被写进 Gold |
| 7 | ENTITY_COLLISION silently resolved | 旧碰撞必须仍以 `ontology_repairs`/告警出现，不得静默 |
| 8 | ambiguous entity silently resolved | 上下文受限别名不得静默解析 |
| 9 | primary/secondary silently conflated | `source_layer_confusions` 计数 |
| 10 | SOURCE_TRACE_INCOMPLETE hidden | 有该状态时必须出现在回答限制里 |
| 11 | Research Agent canonical write | 评测/回答路径无写盘（脚本静态扫描 + 队列未被评测写入） |
| 12 | Gold leakage into Agent | 送进 Agent 的字段只有公开 6 项，且 trace 里不出现 gold 字段名 |

产物：`_data/index/PHASE4B_HARD_GATES.json`
用法：`python3 check_phase4b_hard_gates.py [--verify] [--json]`
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
EVAL = os.path.join(VAULT, "_data", "eval")
IDX = os.path.join(VAULT, "_data", "index")
LAYER = os.path.join(VAULT, "_data", "ontology", "v4a1")
STORE = os.path.join(VAULT, "_data", "passage_store")
OUT = os.path.join(IDX, "PHASE4B_HARD_GATES.json")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

GOLD_FIELD_NAMES = ("gold_evidence", "acceptable_evidence", "expected_entities",
                    "expected_operations", "expected_seminars", "expected_periods",
                    "answerability", "evaluation_notes", "forbidden_shortcuts",
                    "lane_eval_sets")


def jd(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    import knowledge_api as api
    import ontology_v4a1 as onto
    import research_answer as rans
    import research_eval_4b as rev

    violations = {}

    def add(gate, item):
        violations.setdefault(gate, []).append(item)

    known = set(api.KB_.meta())
    dev = jd(os.path.join(EVAL, "research_eval_results_v1.dev.json"), {})
    hold = jd(os.path.join(EVAL, "research_eval_results_v1.holdout.json"), {})
    rows = (dev.get("rows") or []) + (hold.get("rows") or [])

    # 1/2 编造 id + 不存在的引用
    trace_dir = os.path.join(EVAL, "research_traces_4b")
    for fn in sorted(os.listdir(trace_dir)) if os.path.isdir(trace_dir) else []:
        d = jd(os.path.join(trace_dir, fn), {})
        for pid in d["trace"]["passages_seen"]:
            if pid not in known:
                add(1, "%s %s" % (fn, pid))
        for cl in d["answer"]["claims"]:
            for pid in cl["citations"]:
                if pid not in known:
                    add(2, "%s %s" % (fn, pid))
    for r in rows:
        if (r.get("fabricated_citations") or 0) > 0:
            add(2, "%s fabricated=%s" % (r["task_id"], r["fabricated_citations"]))

    # 3/4 语料与 canonical 未被修改（以 Phase 4B 开始时的值为基线）
    # ⚠️ `_data/ontology_gap_queue.jsonl` 是**派生发现记录**，§28 明确要求
    #    Phase 4B 发现 gap 时继续往它写 candidate —— 所以它**允许增长**。
    #    但「允许增长」必须有边界：下面单独验证它只以合法状态增长，
    #    其余受保护文件仍必须逐字节不变。
    APPEND_ALLOWED = "_data/ontology_gap_queue.jsonl"
    base_file = os.path.join(IDX, "PHASE4B_BASELINE_HASHES.json")
    if os.path.isfile(base_file):
        base = jd(base_file, {})
        for rel, want in base.items():
            if rel == APPEND_ALLOWED:
                continue
            p = os.path.join(VAULT, rel)
            if not os.path.isfile(p):
                add(3, "缺文件 %s" % rel)
                continue
            if sha(p) != want:
                add(4 if ("concept" in rel or "relation" in rel) else 3, rel)
    else:
        add(3, "缺基线文件 PHASE4B_BASELINE_HASHES.json（先跑 --stamp-baseline）")
    # 队列：只允许 candidate/resolved/invalidated，且永不提议改 canonical
    q = os.path.join(VAULT, APPEND_ALLOWED)
    if os.path.isfile(q):
        for i, line in enumerate(open(q, encoding="utf-8"), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") not in ("candidate", "resolved", "invalidated"):
                add(3, "queue line %d status=%s" % (i, row.get("status")))
            if row.get("canonical_change_proposed"):
                add(4, "queue line %d 提议改 canonical" % i)

    # 5/9/10 溯源层级
    for fn in sorted(os.listdir(trace_dir)) if os.path.isdir(trace_dir) else []:
        d = jd(os.path.join(trace_dir, fn), {})
        chk = (d.get("answer_check") or {}).get("metrics") or {}
        if chk.get("provenance_upgrades"):
            add(5, fn)
        if chk.get("source_layer_confusions"):
            add(9, fn)
        pack = d.get("evidence_pack") or {}
        inc = [e for e in pack.get("evidence") or []
               if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"]
        limits = ((d.get("answer") or {}).get("sections") or {}).get(
            "evidence_limitations", "") or ""
        if inc and "SOURCE_TRACE_INCOMPLETE" not in limits:
            add(10, "%s（%d 条）" % (fn, len(inc)))

    # 6 candidate ontology 未被自动晋级
    for e in onto.entities():
        if e.get("review_status") != "candidate":
            add(6, "%s review_status=%s" % (e["id"], e.get("review_status")))
        if e["id"] in known and e["id"].startswith("concept."):
            pass
    gold_ids = {c["id"] for c in jl(os.path.join(STORE, "concepts.jsonl"))}
    leaked = sorted(set(onto.entity_ids()) & gold_ids)
    if leaked:
        add(6, "v4a1 实体出现在 Gold 里：%s" % leaked)
    for m in jl(os.path.join(LAYER, "term_mappings.jsonl")):
        if m.get("review_status") != "candidate":
            add(6, "mapping %s review_status=%s" % (m["mapping_id"], m.get("review_status")))

    # 7/8 旧碰撞与歧义不得被静默处理
    exp = os.path.join(IDX, "ONTOLOGY_V4A1_REGRESSION.json")
    reg = jd(exp, {})
    if not reg:
        add(7, "缺 ontology v4a1 回归记录")
    else:
        if not any(c["name"].startswith("所有 Phase 3 配对缺陷已重分类") and c["passed"]
                   for c in reg.get("checks", [])):
            add(7, "Phase 3 配对缺陷未重分类")
        for term in ("autre", "regard", "demande", "besoin", "moi", "signifie"):
            r = api.resolve_entity(term)["resolution"]
            if r["resolution_status"] != "AMBIGUOUS" or not r.get("context_required"):
                add(8, "%s → %s（应为 AMBIGUOUS + context_required）"
                    % (term, r["resolution_status"]))
        old = [x for x in (reg.get("resolver") or []) if x["term"] == "autre"]
        if old and old[0].get("mcp_status") == "RESOLVED":
            add(7, "bare autre 被静默解析")

    # 11 Research Agent canonical write（静态扫描 Phase 4B 脚本的写盘目标）
    write_re = re.compile(r"open\([^)]*[\"'](a|w|ab|wb)[\"']")
    for name in ("research_answer.py", "research_eval_4b.py"):
        p = os.path.join(HERE, name)
        src = open(p, encoding="utf-8").read()
        for m in write_re.finditer(src):
            seg = src[max(0, m.start() - 400):m.start() + 200]
            if any(k in seg for k in ("passage_store", "concepts.jsonl",
                                      "terminology_bridge", "lexical.sqlite",
                                      "relations/", "concept_states")):
                add(11, "%s:%d" % (name, src[:m.start()].count("\n") + 1))

    # 12 Gold 不得泄漏给 Agent
    for fn in sorted(os.listdir(trace_dir)) if os.path.isdir(trace_dir) else []:
        d = jd(os.path.join(trace_dir, fn), {})
        fields = set((d.get("public_task") or {}).keys())
        bad = fields & set(GOLD_FIELD_NAMES)
        if bad:
            add(12, "%s 公开任务含 gold 字段 %s" % (fn, sorted(bad)))
        blob = json.dumps({k: d[k] for k in ("trace", "plan", "evidence_pack")},
                          ensure_ascii=False)
        for g in ("expected_operations", "evaluation_notes", "forbidden_shortcuts",
                  "answerability", "gold_evidence"):
            if '"%s"' % g in blob:
                add(12, "%s trace/plan 里出现 gold 字段名 %s" % (fn, g))

    gates = {i: {"violations": len(violations.get(i, [])),
                 "examples": violations.get(i, [])[:5]} for i in range(1, 13)}
    total = sum(g["violations"] for g in gates.values())
    doc = {"schema_version": "phase4b-hard-gates/v1",
           "purpose": "§33：Phase 4B 的 12 项硬门禁，必须全为 0",
           "gate_count": 12, "gates": gates, "total_violations": total,
           "all_zero": total == 0,
           "evaluated_tasks": len(rows)}
    os.makedirs(IDX, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for i in sorted(gates):
            g = gates[i]
            print("  %-5s gate %-2d %s" % ("PASS" if not g["violations"] else "FAIL", i,
                                           g["examples"] or "0"))
        print("[hard-gates-4b] %d/%d gates are 0（total_violations=%d）"
              % (sum(1 for g in gates.values() if not g["violations"]), 12, total))
    if a.verify:
        return 0 if doc["all_zero"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
