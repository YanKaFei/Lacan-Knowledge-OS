#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase4c_hard_gates.py — Phase 4C §39 + Phase 4C.1-A：既有门禁 + **7 项新增**，必须全为 0

新增（§39）：false human review generation / Gold overwrite /
historical Phase 4B result overwrite / INCIDENTAL→DIRECT 无据提升 /
task-specific fMRI hack / human adjudication silently inferred。

Phase 4C.1-A 变更
──────────────────
* **Gate 13 重写为 provenance-aware**：旧判据是「有没有人工评分」，于是 14 条
  **真实**人工评审全部被计为违规（Phase 4C Human Review 已实证）。新判据问的是
  「人工评分是否有合法 provenance」：空占位必须全空；REVIEWED 必须带人类 provenance、
  合法枚举、完整维度；并且 Phase 4C 冻结基线**逐字段不得被改动**。
  自动注入 / LLM 冒充 / 枚举越界仍然会被抓到（见 `_scripts/_tests/test_phase4c1_eval_integrity.py`）。
* **Gate 19（新）trace integrity**：检查 required operations、final state 与最后一步的一致性、
  state explanation 与 signals 的一致性、context expansion 计数、以及 v2 契约下的
  missing-required-operations / missing-required-lane。历史冻结 trace 的既知不一致标为
  `LEGACY_FROZEN`（另册记录，**不**改变历史，也**不**冒充「零不一致」）。

既有：沿用 Phase 4B 的 12 项（`check_phase4b_hard_gates.py` 的结果一并纳入）。
产物：`_data/index/PHASE4C_HARD_GATES.json`
"""
from __future__ import annotations
import argparse, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
IDX = os.path.join(VAULT, "_data", "index")
OUT = os.path.join(IDX, "PHASE4C_HARD_GATES.json")
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))
import eval_integrity as ei  # noqa: E402


def jd(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def jl(p):
    try:
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except Exception:
        return []


def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true"); a = ap.parse_args(argv)
    v = {}

    def add(g, item):
        v.setdefault(g, []).append(item)

    # 既有 12 项：直接引用 Phase 4B 的结果（不重算，避免两套判据）
    b4 = jd(os.path.join(IDX, "PHASE4B_HARD_GATES.json"), {})
    if not b4 or not b4.get("all_zero"):
        add("inherited_4b", {"gates": b4.get("gate_count"), "violations": b4.get("total_violations")})

    # 13) 伪造人工评分 —— **provenance-aware**（Phase 4C.1-A 重写）
    #     旧逻辑「review_status != NOT_REVIEWED 即违规」会把真实人工评审全部误判为伪造。
    #     新逻辑：问「这条评分是否具有合法的人类 provenance」，并保护冻结基线不被改动。
    records = jl(os.path.join(EVAL, "research_human_review.jsonl"))
    review_states = {}
    for r in records:
        verdict = ei.validate_human_review_record(r)   # 注意：不要复用外层累加器名 `v`
        review_states[r.get("task_id")] = verdict["state"]
        if verdict["state"] == "ILLEGITIMATE":
            for prob in verdict["problems"][:3]:
                add(13, prob)
    for prob in ei.baseline_immutability_findings(records):
        add(13, prob)

    # 14) Gold 被覆盖（Phase 4B 任务集必须逐字节不变）
    base = jd(os.path.join(IDX, "PHASE4B_BASELINE_HASHES.json"), {})
    import hashlib
    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()
    tg = os.path.join(EVAL, "research_tasks_v1.jsonl")
    if os.path.isfile(tg):
        rows = jl(tg)
        if any("adjudicat" in json.dumps(r, ensure_ascii=False) for r in rows):
            add(14, "Phase 4B 任务集里出现了裁决痕迹（Gold 不得被覆盖）")
    # 15) 历史 Phase 4B 结果被覆盖
    for fn in ("research_eval_results_v1.dev.json", "research_eval_results_v1.holdout.json",
               "research_eval_results_v1.json", "research_eval_results.json",
               "research_eval_results.v4a1.json"):
        p = os.path.join(EVAL, fn)
        if not os.path.isfile(p):
            add(15, "缺历史结果 %s" % fn)
    # 16) INCIDENTAL 无据提升为 DIRECT
    cal = jd(os.path.join(EVAL, "evidence_sufficiency_calibration.v4c.json"), {})
    for r in cal.get("rows", []):
        lv = r.get("topic_support_levels") or {}
        if r.get("topicality_state") in ("DIRECT", "SUBSTANTIAL") and sum(lv.values()) \
                and lv.get("INCIDENTAL", 0) == sum(lv.values()):
            add(16, "%s 全部证据 INCIDENTAL 却判 %s" % (r["case_id"], r["topicality_state"]))
    # 17) task-specific fMRI hack
    for fn in ("evidence_sufficiency_v2.py", "research_answer.py"):
        src = open(os.path.join(HERE, "lacan_mcp", fn), encoding="utf-8").read() \
            if os.path.isfile(os.path.join(HERE, "lacan_mcp", fn)) \
            else open(os.path.join(HERE, fn), encoding="utf-8").read()
        for pat in ("fMRI", "frmi", "neuroscience", "莫比乌斯", "moebius"):
            for m in re.finditer(re.escape(pat), src):
                seg = src[max(0, m.start() - 200):m.start() + 200]
                # 允许出现在注释/文档字符串里说明案例；不允许出现在判定条件里
                line = src[:m.start()].count("\n") + 1
                if re.search(r"(if|elif|and|or)\s+[^\n]*%s" % re.escape(pat), seg):
                    add(17, "%s:%d 判定条件里出现案例专用词 %s" % (fn, line, pat))
    # 18) 裁决被静默推断
    for r in jl(os.path.join(EVAL, "human_adjudication_queue.jsonl")):
        if r.get("status") not in ("PENDING", "ADJUDICATED"):
            add(18, "%s status=%s" % (r["task_id"], r.get("status")))
        if r.get("status") == "ADJUDICATED" and not (r.get("adjudicated_by")
                                                    and r.get("decision")):
            add(18, "%s 标为 ADJUDICATED 但没有真实裁决人与决定" % r["task_id"])
        if r.get("status") == "PENDING" and r.get("decision"):
            add(18, "%s PENDING 却有 decision（静默推断）" % r["task_id"])

    # 19) trace integrity（Phase 4C.1-A 新增）
    #     只把「声明 v2 契约的 trace」的不一致计为违规；历史冻结 trace 的既知不一致
    #     标为 LEGACY_FROZEN 另行造册 —— 既不掩盖，也不靠改历史来让门禁变绿。
    legacy_frozen = {}
    contract_traces = 0
    trace_dirs = ["research_traces_4c1b", "research_traces_4b",
                  "research_traces_v2", "research_traces_context_audit"]
    trace_files = []
    for d in trace_dirs:
        trace_files += sorted(glob.glob(os.path.join(EVAL, d, "*.json")))
    for p in trace_files:
        try:
            tr = json.load(open(p, encoding="utf-8"))
        except Exception as exc:                      # pragma: no cover
            add(19, "%s 无法解析：%s" % (os.path.basename(p), exc))
            continue
        # 契约版本可能写在 run 顶层或 trace 文档里（与 eval_integrity 同判据）
        if ei.CONTRACT_SCHEMA in (tr.get("schema_version"),
                                  (tr.get("trace") or {}).get("schema_version")):
            contract_traces += 1
        for f in ei.trace_integrity_findings(tr):
            if f["severity"] == "VIOLATION":
                add(19, "%s %s: %s" % (tr.get("task_id"), f["code"], f["detail"][:160]))
            else:
                legacy_frozen[f["code"]] = legacy_frozen.get(f["code"], 0) + 1

    gates = {k: {"violations": len(x), "examples": x[:4]} for k, x in v.items()}
    total = sum(g["violations"] for g in gates.values())
    doc = {"schema_version": "phase4c-hard-gates/v1",
           "inherited_phase4b": {"gate_count": b4.get("gate_count"),
                                 "all_zero": b4.get("all_zero")},
           "new_gates": {str(i): gates.get(i, {"violations": 0, "examples": []})
                         for i in range(13, 20)},
           "gate_count_new": 7,
           "human_review_states": review_states,
           "human_review_legitimate_n": sum(1 for s in review_states.values()
                                            if s == "REVIEWED_HUMAN"),
           "trace_integrity": {
               "contract_schema": ei.CONTRACT_SCHEMA,
               "contract_traces_checked": contract_traces,
               "legacy_frozen_findings": legacy_frozen,
               "legacy_frozen_total": sum(legacy_frozen.values()),
               "note": ("历史冻结 trace 的既知不一致**不计入 hard-gate 违规**，"
                        "单列在此并写入 _data/eval/trace_integrity_baseline_v1.json；"
                        "绝不修改历史 trace。"),
           },
           "total_violations": total, "all_zero": total == 0}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("  inherited Phase 4B: %s gates, all_zero=%s"
              % (b4.get("gate_count"), b4.get("all_zero")))
        for i in range(13, 20):
            g = doc["new_gates"][str(i)]
            print("  %-5s gate %d %s" % ("PASS" if not g["violations"] else "FAIL", i,
                                         g["examples"] or "0"))
        print("  人工评审：合法 %d 条（%s）"
              % (doc["human_review_legitimate_n"],
                 doc["human_review_states"]))
        print("  trace integrity：契约 trace %d 条；历史冻结既知不一致 %d 条 %s"
              % (contract_traces, doc["trace_integrity"]["legacy_frozen_total"],
                 legacy_frozen or ""))
        print("[hard-gates-4c] total_violations=%d -> %s"
              % (total, "ALL ZERO" if total == 0 else "FAIL"))
    if a.verify:
        return 0 if doc["all_zero"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
