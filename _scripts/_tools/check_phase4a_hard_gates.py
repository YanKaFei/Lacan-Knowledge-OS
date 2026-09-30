#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase4a_hard_gates.py — Phase 4A §27：**11 项硬门禁，必须全为 0**

与 §23 的 17 项（Phase 3 沿用）不同，这 11 项是 **Phase 4A 新增能力**带来的风险面：

| # | 门禁 | 为什么它必须为 0 |
|---|---|---|
| 1 | tool 参数含写入词根 | 「支持写入」只需要一个参数名 |
| 2 | tool 名暗示写入 | 名字是契约的一部分，`update_passage` 会教坏调用方 |
| 3 | canonical passage store 被改动 | 唯一事实来源，任何写入都是致命 |
| 4 | 派生索引被改动 | 索引可重建，但**不可被访问层修改** |
| 5 | 原始语料被改动 | 原始材料只读（§0/§29） |
| 6 | 响应里出现编造的 `passage_id` | 编造引用比「查不到」严重得多 |
| 7 | `L4 → canonical` 的写入路径 | AI 输出**永远不得**晋级 canonical |
| 8 | 缺口队列出现非 `candidate` / 提议改 canonical | §22：只发现，不修 |
| 9 | 未声明参数被静默接受 | 静默忽略等于悄悄扩大契约 |
| 10 | `evidence_state` 含 0–1 confidence 或 cosine 阈值 | §7：余弦阈值在这里是错的 |
| 11 | 自动修复 unresolved / collision / trace 缺口的代码路径 | §29：不许自动修 |

判法：**静态扫描 + 实跑比对**。凡是「扫一遍源码就能确定」的就不用跑的，
凡是要跑才知道的就实跑（tool 调用 + 前后哈希）。

产物：`_data/index/PHASE4A_HARD_GATES.json`
用法：`python3 _scripts/_tools/check_phase4a_hard_gates.py [--verify]`
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
MCP = os.path.join(HERE, "lacan_mcp")
IDX = os.path.join(VAULT, "_data", "index")
STORE = os.path.join(VAULT, "_data", "passage_store")
ATLAS = os.path.join(VAULT, ".lacan-build", "atlas")
OUT = os.path.join(IDX, "PHASE4A_HARD_GATES.json")

sys.path.insert(0, HERE)
sys.path.insert(0, MCP)

# 门禁 7 只扫**访问层本身**（lacan_mcp/*.py）：它是唯一可能在服务请求时写盘的东西。
# 上游的 verifier 脚本（readonly/gate/render）写的是派生验收产物，由门禁 3/4/5 的哈希覆盖。
SRC = [os.path.join(MCP, f) for f in sorted(os.listdir(MCP)) if f.endswith(".py")]
ALL_SRC = SRC + [os.path.join(HERE, f) for f in
                 ("render_contracts.py", "check_phase4a_readonly.py",
                  "eval_research_agent.py", "check_phase4a_hard_gates.py")]

# 提成模块级常量：这样测试可以拿**合成违规**验证「门禁真的会红」——
# 一个从不失败的门禁等于没有门禁。
# ⚠️ 第一版是 `open\([^)]*["'](a|w|..)["']` —— `[^)]*` **过不了嵌套括号**，
#    于是 `open(os.path.join(STORE, "concepts.jsonl"), "w")` 这种真实违规
#    根本抓不到（合成测试当场发现）。允许一层嵌套：
WRITE_RE = re.compile(r"open\((?:[^()\n]|\([^()\n]*\))*[\"'](a|w|ab|wb)[\"']")
FIX_RE = re.compile(r"(?:def\s+|(?<![\w.])|(?<=\.))"
                    r"(auto_?fix|autofix|canonicalize|auto_?promote|auto_?merge|"
                    r"resolve_collision|repair_trace)\s*\(", re.I)
CANONICAL_TRUE_RE = re.compile(r"[\"']canonical[\"']\s*:\s*True")
WRITE_ALLOW = ("QUEUE", "save_trace_dir")
CANONICAL_PATH_MARKERS = ("passage_store", "concepts.jsonl", "terminology_bridge",
                          "lexical.sqlite", "concept_states", "claims.jsonl")


def _read(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv):
    import schemas
    import knowledge_api as api
    import argcheck
    import validate as vd

    violations = {}

    def add(gate, item):
        violations.setdefault(gate, []).append(item)

    # ── 门禁 1：tool 参数含写入词根
    for t in schemas.TOOLS:
        for p in (t["inputSchema"].get("properties") or {}):
            for pat in schemas.FORBIDDEN_PARAM_PATTERNS:
                if pat in p.lower():
                    add(1, "%s.%s" % (t["name"], p))

    # ── 门禁 2：tool 名暗示写入
    for t in schemas.TOOLS:
        for pat in schemas.FORBIDDEN_PARAM_PATTERNS:
            if pat in t["name"]:
                add(2, t["name"])

    # ── 门禁 3/4/5：实跑全部 tool，比对三类路径的哈希
    watch_store = [os.path.join(STORE, n) for n in sorted(os.listdir(STORE))
                   if n.endswith(".jsonl")] if os.path.isdir(STORE) else []
    # §21 点名 concept/relation 文件：`_data/relations/` 也必须在门禁 3 的监控里
    reldir = os.path.join(VAULT, "_data", "relations")
    if os.path.isdir(reldir):
        watch_store += [os.path.join(reldir, n) for n in sorted(os.listdir(reldir))
                        if n.endswith(".jsonl")]
    watch_idx = [os.path.join(IDX, n) for n in ("lexical.sqlite", "alias_index.jsonl")]
    watch_raw = [os.path.join(ATLAS, n) for n in
                 ("segments.jsonl", "french_staferla.jsonl", "seminars.json")]
    b3 = {p: sha(p) for p in watch_store if os.path.isfile(p)}
    b4 = {p: sha(p) for p in watch_idx if os.path.isfile(p)}
    b5 = {p: sha(p) for p in watch_raw if os.path.isfile(p)}
    pid = api.search_passages("objet a", top_k=1)["evidence"][0]["passage_id"]
    for name, args in (("search_passages", {"query": "凝视", "top_k": 5}),
                       ("get_passage", {"passage_id": pid}),
                       ("get_context", {"passage_id": pid}),
                       ("resolve_entity", {"term": "gaze"}),
                       ("get_concept", {"entity_id": "concept.jouissance"}),
                       ("find_concept_evidence", {"concept": "concept.desir"}),
                       ("trace_concept", {"concept": "concept.jouissance",
                                          "per_period": 2}),
                       ("compare_concepts", {"concept_a": "concept.desir",
                                             "concept_b": "concept.jouissance"}),
                       ("trace_source", {"passage_id": pid}),
                       ("terminology_lookup", {"term": "objet a"})):
        api.call(name, args)
    for gate, before in ((3, b3), (4, b4), (5, b5)):
        for p, h in before.items():
            if not os.path.isfile(p) or sha(p) != h:
                add(gate, os.path.relpath(p, VAULT))

    # ── 门禁 6：响应里出现编造的 passage_id
    known = vd.passage_ids()
    for name, args in (("search_passages", {"query": "jouissance", "top_k": 5}),
                       ("find_concept_evidence", {"concept": "concept.jouissance"}),
                       ("compare_concepts", {"concept_a": "concept.desir",
                                             "concept_b": "concept.jouissance"})):
        for e in api.call(name, args).get("evidence") or []:
            if e["passage_id"] not in known:
                add(6, e["passage_id"])

    # ── 门禁 7：L4 → canonical 的写入路径（静态，**白名单**判法）
    # 访问层里每一个写盘点在下面被逐个点名：只允许
    #   (a) 派生缺口队列（§22，且只写 candidate）
    #   (b) 调用方显式指定的 trace 目录（调试产物）
    # 任何**未被白名单覆盖**的写点都是违规 —— 这比「扫关键词黑名单」严，
    # 因为新增一个写点会立刻暴露，而不是等它命中某个关键词。
    write_re, allow = WRITE_RE, WRITE_ALLOW
    write_sites = []
    for p in SRC:
        src = _read(p)
        for m in write_re.finditer(src):
            line = src[:m.start()].count("\n") + 1
            seg = src[max(0, m.start() - 500):m.start() + 200]
            name = "%s:%d" % (os.path.basename(p), line)
            write_sites.append(name)
            if not any(k in seg for k in allow):
                add(7, name)
            if any(k in seg for k in CANONICAL_PATH_MARKERS):
                add(7, "%s → canonical 路径" % name)
        if CANONICAL_TRUE_RE.search(src):
            add(7, "%s: canonical=True" % os.path.basename(p))

    # ── 门禁 8：缺口队列状态
    # Phase 4A.1（§9）起，同一 issue_id 允许有 `resolved` / `invalidated` 的
    # 状态更新行（保留 audit trail）。门禁因此改成**更强**的三条：
    #   a) 新发现行必须是 candidate；状态只能取三者之一
    #   b) 任何行都不得提议改动 canonical
    #   c) 每条 resolved 必须带 resolution_commit +（实体或理由）
    qpath = os.path.join(VAULT, "_data", "ontology_gap_queue.jsonl")
    if os.path.isfile(qpath):
        for i, line in enumerate(open(qpath, encoding="utf-8"), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            st = row.get("status")
            if st not in ("candidate", "resolved", "invalidated"):
                add(8, "line %d status=%s" % (i, st))
            if not row.get("status_updated_by") and st != "candidate":
                add(8, "line %d 新发现行状态不是 candidate（%s）" % (i, st))
            if row.get("canonical_change_proposed"):
                add(8, "line %d canonical_change_proposed=true" % i)
            if st == "resolved" and not (row.get("resolution_commit")
                                         and (row.get("resolved_entity_ids")
                                              or row.get("resolution_reason"))):
                add(8, "line %d resolved 缺审计字段" % i)

    # ── 门禁 9：未声明参数必须被拒
    sch = [t for t in schemas.TOOLS if t["name"] == "search_passages"][0]["inputSchema"]
    ok, _ = argcheck.validate({"query": "x", "canonicalize": True}, sch)
    if ok:
        add(9, "additionalProperties 未生效")
    if sch.get("additionalProperties") is not False:
        add(9, "additionalProperties != False")

    # ── 门禁 10：evidence_state 不得含 confidence / cosine 阈值
    st = api.search_passages("objet a", top_k=2)["evidence_state"]
    if st.get("method") != "structural_only_no_cosine_threshold":
        add(10, "method=%s" % st.get("method"))
    for bad in ("confidence", "cosine_threshold", "score_threshold"):
        if bad in st:
            add(10, bad)
    for k in st.get("signals") or {}:
        if "cosine" in k or "similarity" in k:
            add(10, "signal %s" % k)

    # ── 门禁 11：自动修复缺口的**代码路径**（静态）
    # ⚠️ 必须匹配「定义或调用」，不能匹配字符串里出现的词 ——
    #    第一版扫裸词，于是 FORBIDDEN_PARAM_PATTERNS 里那句 `"canonicalize"`
    #    与「用 canonicalize 做否定测试」的那一行都成了违规：
    #    **门禁在自己的守卫上误报，就是坏门禁。**
    fix_re = FIX_RE
    for p in SRC:
        src = _read(p)
        for m in fix_re.finditer(src):
            line = src[:m.start()].count("\n") + 1
            add(11, "%s:%d %s" % (os.path.basename(p), line, m.group(1)))

    gates = {}
    for i in range(1, 12):
        items = violations.get(i, [])
        gates[i] = {"violations": len(items), "examples": items[:5]}
    total = sum(g["violations"] for g in gates.values())
    doc = {
        "schema_version": "phase4a-hard-gates/v1",
        "purpose": "§27：Phase 4A 新增能力带来的 11 项风险面，必须全为 0",
        "gate_count": 11,
        "gates": gates,
        "total_violations": total,
        "all_zero": total == 0,
        "scanned_sources": [os.path.relpath(p, VAULT) for p in SRC],
        "access_layer_write_sites": write_sites,
        "access_layer_write_policy": ("只允许写 (a) _data/ontology_gap_queue.jsonl "
                                      "（candidate）与 (b) 调用方指定的 trace 目录；"
                                      "其余任何写点都算违规"),
        "monitored": {
            "store": [os.path.relpath(p, VAULT) for p in b3],
            "index": [os.path.relpath(p, VAULT) for p in b4],
            "raw": [os.path.relpath(p, VAULT) for p in b5],
        },
    }
    os.makedirs(IDX, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if "--json" in argv:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for i in sorted(gates):
            g = gates[i]
            print("  %-5s gate %-2d  %s"
                  % ("PASS" if g["violations"] == 0 else "FAIL", i,
                     ("violations=%d %s" % (g["violations"], g["examples"]))
                     if g["violations"] else "0"))
        print("[hard-gates-4a] %d/%d gates are 0（total_violations=%d）"
              % (sum(1 for g in gates.values() if g["violations"] == 0), 11, total))
        print("wrote %s" % os.path.relpath(OUT, VAULT))
    if "--verify" in argv:
        return 0 if doc["all_zero"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
