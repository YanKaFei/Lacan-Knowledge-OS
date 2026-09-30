#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase4a_readonly.py — Phase 4A §21/§27：**只读硬门**

它证明什么
──────────
「只读」不是一句承诺，而是**可以复算的事实**：

1. 跑**全部 10 个 tool** + Research Agent 的若干次研究（含会触发写路径的参数组合）；
2. 前后对 canonical store / 索引 / 原始语料做哈希与尺寸比对；
3. 前后必须**逐字节相同**；
4. 另外静态核：任何 tool 参数里没有写入词根（§2），且没有 tool 名暗示写入。

唯一允许变化的是 `_data/ontology_gap_queue.jsonl`（§22 的**派生发现记录**），
并且只在 `record_gaps=True` 时才会追加 —— 本门会分别验证「开/关」两种情形。

产物
────
    _data/index/READONLY_GATE.json
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import knowledge_api as api          # noqa: E402
import research_agent as ra          # noqa: E402
import schemas                       # noqa: E402

STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
OUT = os.path.join(IDX, "READONLY_GATE.json")
GAPQ = os.path.join(VAULT, "_data", "ontology_gap_queue.jsonl")
ATLAS = os.path.join(VAULT, ".lacan-build", "atlas")

# 原始材料是只读的（§0）：只比尺寸与 mtime —— 1.2 GiB 逐字节哈希没必要，
# 而且它本来就不该被本相位的代码碰到。
RAW = [os.path.join(ATLAS, n) for n in
       ("segments.jsonl", "french_staferla.jsonl", "seminars.json")]

MUST_NOT_CHANGE = (
    "passages.jsonl", "concepts.jsonl", "concept_states.jsonl", "sessions.jsonl",
    "seminars.jsonl", "witnesses.jsonl", "translations.jsonl",
    "corpus_sources.jsonl", "passage_realizations.jsonl", "passage_witnesses.jsonl",
    "claims.jsonl", "alignments.jsonl",
)
# ⚠️ §21 点名的是「canonical/source hash 与 **concept/relation** 文件」——
#    第一版只监控了 passage_store，漏掉了 `_data/relations/`。
#    漏监控等于那条判据**没有覆盖**它承诺的东西。
RELATION_FILES = ("relations.jsonl", "relations.candidate.jsonl",
                  "relations.rejected.jsonl")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def snapshot(full_hash=True):
    snap = {}
    for n in MUST_NOT_CHANGE:
        p = os.path.join(STORE, n)
        if os.path.isfile(p):
            snap["store/" + n] = {"sha256": sha(p), "size": os.path.getsize(p)}
    for rel in RELATION_FILES:
        p = os.path.join(VAULT, "_data", "relations", rel)
        if os.path.isfile(p):
            snap["relations/" + rel] = {"sha256": sha(p), "size": os.path.getsize(p)}
    for rel in ("lexical.sqlite", "alias_index.jsonl", "PHASE3_COMPLETION_GATE.json",
                "HARD_GATES.json"):
        p = os.path.join(IDX, rel)
        if os.path.isfile(p):
            snap["index/" + rel] = {"sha256": sha(p), "size": os.path.getsize(p)}
    for p in RAW:
        if os.path.isfile(p):
            snap["raw/" + os.path.basename(p)] = {"size": os.path.getsize(p),
                                                  "mtime": os.path.getmtime(p)}
    return snap


def exercise_all_tools():
    """把 10 个 tool 全部跑一遍，参数取「最容易误写」的那一组。"""
    pid = api.search_passages("objet a", top_k=1)["evidence"][0]["passage_id"]
    calls = [
        ("search_passages", {"query": "凝视 与 小客体a", "top_k": 5, "explain": True}),
        ("get_passage", {"passage_id": pid}),
        ("get_context", {"passage_id": pid, "before": 2, "after": 2}),
        ("resolve_entity", {"term": "l'Autre"}),
        ("get_concept", {"entity_id": "concept.objet-petit-a"}),
        ("find_concept_evidence", {"concept": "concept.jouissance", "top_k": 5}),
        ("trace_concept", {"concept": "concept.jouissance", "per_period": 3}),
        ("compare_concepts", {"concept_a": "concept.desir",
                              "concept_b": "concept.jouissance", "top_k": 4}),
        ("trace_source", {"passage_id": pid}),
        ("terminology_lookup", {"term": "objet a"}),
        # 恶意/错误用法也要跑：坏路径最容易顺手写点什么
        ("get_passage", {"passage_id": "passage.S99.unknown.P9999"}),
        ("search_passages", {"query": "zzzqqqxxx不存在的词"}),
    ]
    results = []
    for name, args in calls:
        r = api.call(name, args)
        results.append({"tool": name, "sections": sorted(r.keys()),
                        "evidence_n": len(r.get("evidence") or [])})
    return results


def main(argv):
    t0 = time.time()
    before = snapshot()
    gap_before = os.path.getsize(GAPQ) if os.path.isfile(GAPQ) else 0

    ran = exercise_all_tools()
    # Research Agent 两条路径：不记缺口（严格只读）与记缺口（只允许队列变化）
    ra.research("什么是 objet a？", record_gaps=False)
    ra.research("desir 和 demande 有什么区别？", record_gaps=False)

    mid = snapshot()
    gap_mid = os.path.getsize(GAPQ) if os.path.isfile(GAPQ) else 0
    ra.research("gaze 在知识库里有哪些证据？", record_gaps=True)
    gap_after = os.path.getsize(GAPQ) if os.path.isfile(GAPQ) else 0
    after = snapshot()

    checks = []

    def check(cid, name, passed, detail):
        checks.append({"id": cid, "name": name, "passed": bool(passed),
                       "detail": detail})

    changed = [k for k in before if before[k] != mid.get(k)]
    check(1, "跑完 10 个 tool：canonical store 逐字节未变", not changed,
          changed or "全部 %d 个受监控文件哈希一致" % len(before))
    changed2 = [k for k in before if before[k] != after.get(k)]
    check(2, "跑完 Research Agent：canonical store 逐字节未变", not changed2,
          changed2 or "一致")

    bad_params = [(t["name"], p) for t in schemas.TOOLS
                  for p in (t["inputSchema"].get("properties") or {})
                  if any(pat in p.lower() for pat in schemas.FORBIDDEN_PARAM_PATTERNS)]
    rel_monitored = [k for k in before if k.startswith("relations/")]
    check(10, "concept/relation 文件已纳入监控（§21 点名的对象）",
          len(rel_monitored) >= 1, rel_monitored or "未找到 _data/relations/*.jsonl")
    check(3, "任何 tool 都没有写入型参数（§2）", not bad_params, bad_params or "无")
    bad_names = [(t["name"], pat) for t in schemas.TOOLS
                 for pat in schemas.FORBIDDEN_PARAM_PATTERNS if pat in t["name"]]
    check(4, "没有 tool 名暗示写入", not bad_names, bad_names or "无")

    check(5, "record_gaps=False 时缺口队列不变", gap_before == gap_mid,
          "before=%d mid=%d" % (gap_before, gap_mid))
    check(6, "record_gaps=True 只追加**派生**缺口记录（且只此一处变化）",
          gap_after >= gap_mid, "before=%d mid=%d after=%d" % (gap_before, gap_mid,
                                                               gap_after))

    # 缺口队列：Phase 4A.1 起同一 issue_id 允许有 `resolved` / `invalidated`
    # 的状态更新行（§9 要求保留 audit trail）。判据因此改成**更严**的三条：
    #   a) 状态只能取三者之一；
    #   b) 任何行都不得提议改动 canonical（§22 只发现不修）；
    #   c) 每条 resolved 必须带 resolution_commit + 实体或理由（可审计）。
    ok_rows, n_rows, bad = True, 0, []
    if os.path.isfile(GAPQ):
        with open(GAPQ, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                n_rows += 1
                if row.get("status") not in ("candidate", "resolved", "invalidated"):
                    ok_rows, _ = False, bad.append("line %d status" % i)
                if row.get("canonical_change_proposed"):
                    ok_rows, _ = False, bad.append("line %d proposes canonical change" % i)
                if row.get("status") == "resolved" and not (
                        row.get("resolution_commit")
                        and (row.get("resolved_entity_ids")
                             or row.get("resolution_reason"))):
                    ok_rows, _ = False, bad.append("line %d 缺 resolution 审计字段" % i)
    check(7, "缺口队列：状态合法 / 从不提议改 canonical / resolved 可审计",
          ok_rows, bad or "%d 行" % n_rows)

    check(8, "全部 tool 的返回都带 8 段", all(
        sorted(r["sections"]) == sorted(schemas.OUTPUT_SECTIONS) for r in ran),
        "%d 次调用" % len(ran))

    # 未声明参数必须被拒（不能悄悄忽略 —— 忽略等于「看着像支持写入」）
    try:
        import argcheck
        ok, _ = argcheck.validate({"query": "x", "canonicalize": True},
                                  [t for t in schemas.TOOLS
                                   if t["name"] == "search_passages"][0]["inputSchema"])
        extra_rejected = not ok
    except Exception:
        extra_rejected = False
    check(9, "未声明参数被拒（additionalProperties=False）", extra_rejected, "ok")

    passed = sum(1 for c in checks if c["passed"])
    doc = {
        "schema_version": "readonly-gate/v1",
        "scope": "Phase 4A Knowledge Access Layer + Research Agent",
        "monitored_files": len(before),
        "monitored": sorted(before),
        "monitored_relation_files": rel_monitored,
        "tools_exercised": [r["tool"] for r in ran],
        "gap_queue": {"before": gap_before, "after_tools": gap_mid,
                      "after_research_with_gaps": gap_after,
                      "note": ("ontology_gap_queue.jsonl 是**派生发现记录**（§22），"
                               "不是 canonical knowledge；只在 record_gaps=True 时追加"),
                      "path": os.path.relpath(GAPQ, VAULT)},
        "checks": checks, "passed": passed, "total": len(checks),
        "all_passed": passed == len(checks),
        "seconds": round(time.time() - t0, 2),
    }
    os.makedirs(IDX, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if "--json" in argv:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for c in checks:
            print("  %-5s %-46s %s" % ("PASS" if c["passed"] else "FAIL",
                                       c["name"][:46], str(c["detail"])[:70]))
        print("[readonly-gate] %d/%d passed （%ss）" % (passed, len(checks),
                                                        doc["seconds"]))
        print("wrote %s" % os.path.relpath(OUT, VAULT))
    return 0 if doc["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
