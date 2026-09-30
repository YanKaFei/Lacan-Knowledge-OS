#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_research_agent.py — Phase 4A §16/§17：Research Agent 的机器可算指标

为什么这些指标能被客观核对
──────────────────────────
「答案写得好不好」不可核对；但下面这些**都能**：

| 指标（§17） | 怎么算 |
|---|---|
| `classifier_accuracy` | `query_type` 是否等于数据集里的期望 |
| `tool_selection_correctness` | 主工具是否是期望的那个（从 trace 里读） |
| `passage_validity` | 返回的 `passage_id` 是否**全部**存在于 canonical store |
| `citation_validity` | `citable_passages` 全部可回查 + fabricated 必须 0 |
| `sufficiency_correctness` | `evidence_state.state` 是否落在允许集合内 |
| `gap_detection_recall` | 期望的缺口 code 是否出现在 resolution/ontology_gaps |
| `constraint_honesty` | 期号约束是否被**真的满足或如实否定** |
| `retry_behavior` | 需要第二步的问题里，trace 是否真的出现第二步 |
| `budget_compliance` | 每次 `tool_calls` ≤ 预算上限（默认 12） |
| `no_fabrication` | 全量 fabricated = 0（硬指标） |

**禁止**把这些数字事后调参到好看（§30）：这里只跑、只报。

产物
────
    _data/eval/research_eval_results.json     # 指标 + 每问明细
    _data/eval/research_traces/trace-*.json   # 抽样 trace（§18 的可核查证据）

用法
────
    python3 _scripts/_tools/eval_research_agent.py [--save-traces N] [--json]
"""

from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_agent as ra        # noqa: E402
import knowledge_api as api        # noqa: E402
import citations as cit            # noqa: E402

EVAL = os.path.join(VAULT, "_data", "eval", "research_eval.jsonl")
OUT = os.path.join(VAULT, "_data", "eval", "research_eval_results.json")
TRACES = os.path.join(VAULT, "_data", "eval", "research_traces")
# Phase 4A.1：**版本化**评测集。旧结果文件永不覆盖（§6）。
EVAL_V4A1 = os.path.join(VAULT, "_data", "eval", "research_eval_v4a1.jsonl")
OUT_V4A1 = os.path.join(VAULT, "_data", "eval", "research_eval_results.v4a1.json")
TRACES_V4A1 = os.path.join(VAULT, "_data", "eval", "research_traces_v4a1")


def load_eval(path=EVAL):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _codes(doc):
    out = set()
    for w in doc.get("warnings") or []:
        out.add(w.get("code"))
    return out


def run_one(case, save_trace_dir=None):
    t0 = time.time()
    r = ra.research(case["query"], record_gaps=False, save_trace_dir=save_trace_dir)
    p = r["evidence_pack"]
    st = p["evidence_state"]
    sig = st["signals"]
    tools = [s["tool"] for s in r["research_trace"]["steps"]]
    # pack 自己汇总的缺口 code（覆盖 step1 解析 + 主检索 + 每次重试）
    gap_codes = set(p.get("ontology_gap_codes") or [])
    for g in (p.get("resolution") or {}).get("ontology_gaps") or []:
        gap_codes.add(g.get("code"))
    for g in p.get("ontology_gap_candidates") or []:
        gap_codes.add(g.get("issue_type"))
    gap_codes |= _codes(p)

    known = set()
    all_valid = True
    for e in p["evidence"]:
        known.add(e["passage_id"])
    if known:
        import validate as vd
        all_valid = known <= vd.passage_ids()

    expected_gaps = set(case.get("expected_gap_codes") or [])
    details = {
        "id": case["id"], "category": case["category"], "query": case["query"],
        "seconds": round(time.time() - t0, 2),
        "query_type": p["query_type"],
        "retrieval_route": p["retrieval_route"],
        "query_type_ok": p["query_type"] == case["expected_query_type"],
        "primary_tool": p["primary_tool"],
        "primary_tool_expected": case["expected_primary_tool"],
        "tool_selection_ok": (p["primary_tool"] == case["expected_primary_tool"]
                              or case["expected_primary_tool"] in tools),
        "state": st["state"],
        "state_ok": st["state"] in case["allowed_states"],
        "evidence_n": p["evidence_n"],
        "passage_validity": all_valid,
        "resolved_entities": p["resolved_entities"],
        "entities_ok": set(case["expected_resolved_entities"]) <= set(p["resolved_entities"]),
        "unresolved_terms": p["unresolved_terms"],
        "gap_codes": sorted(gap_codes),
        "gap_detection_ok": expected_gaps <= gap_codes if expected_gaps else True,
        "constraint_satisfaction": sig.get("constraint_satisfaction"),
        "constraint_scoped": sig.get("request_scoped"),
        "families": sig["independent_families_executed"],
        "tool_calls": r["budget"]["used"]["tool_calls"],
        "budget_ok": r["budget"]["used"]["tool_calls"] <= r["budget"]["config"]["max_tool_calls"],
        "steps": tools,
        "second_step": len(tools) > 1,
        "limitations": p["limitations"],
        "reasons": st.get("reasons"),
        "notes": st.get("notes"),
        "citable_n": len(p["citable_passages"]),
        "must_mention_ok": all(m in json.dumps(p, ensure_ascii=False)
                               for m in (case.get("must_mention") or [])),
        "fabricated": 0 if all_valid else 1,
    }
    # ── §17：source trace validity（溯源是否**如实**）
    prov = p.get("provenance") or {}
    incomplete = [e for e in p["evidence"]
                  if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"]
    trace_ok = True
    trace_why = []
    if p["evidence"]:
        if not prov:
            trace_ok, trace_why = False, ["provenance 汇总缺失"]
        if not p.get("source_trace"):
            trace_ok, trace_why = False, trace_why + ["top-1 未取溯源链"]
        # 有 SOURCE_TRACE_INCOMPLETE 证据时，必须在 reasons/warnings 里显式出现
        if incomplete:
            blob = json.dumps([st.get("reasons"), st.get("notes"), p.get("warnings")],
                              ensure_ascii=False)
            if "SOURCE_TRACE_INCOMPLETE" not in blob:
                trace_ok, trace_why = False, trace_why + ["溯源缺口未上报"]
    details["source_trace_validity"] = trace_ok
    details["source_trace_why"] = trace_why
    details["source_trace_incomplete_n"] = len(incomplete)

    # ── §17：unsupported claim rate —— 在一份**参考回答**上实测引用契约。
    # Agent 自己不写答案（§11），所以这里用 `citable_passages` 组装一份
    # 「每条断言都带真实引用」的参考回答，验证：
    #   (1) 该契约可被执行（fabricated=0、每条都有 primary/secondary 层级）
    #   (2) 撤掉引用后 unsupported_claim_rate 会**上升**（指标不是死的）
    # ⚠️ 组装时**不能把 id 写进正文**：`citations` 的启发式是「句子里出现
    #    真实 id 就算有引用」，把 id 当描述写进去会让「未引用」的那份也被判成有引用
    #    （第一版就是这样，uncited 率算出 0.0 —— 指标没错，是探针写错了）。
    top = p["citable_passages"][:3]
    cited = "".join("这表明该处有一种相关表述 [%s]。" % pid for pid in top)
    uncited = "".join("这表明该处有一种相关表述。" for _ in top)
    rep_cited = cit.citation_report(cited) if cited else None
    rep_uncited = cit.citation_report(uncited) if uncited else None
    details["citation_contract_ok"] = bool(
        rep_cited and rep_cited["fabricated"] == [] and rep_cited["valid_n"] > 0)
    details["unsupported_claim_rate_cited"] = (
        (rep_cited or {}).get("unsupported", {}).get("unsupported_claim_rate"))
    details["unsupported_claim_rate_uncited"] = (
        (rep_uncited or {}).get("unsupported", {}).get("unsupported_claim_rate"))
    details["citation_contract_detects_missing"] = bool(
        rep_uncited and rep_cited
        and (rep_uncited["unsupported"]["unsupported_claim_rate"] or 0)
        > (rep_cited["unsupported"]["unsupported_claim_rate"] or 0))

    # ── §17：retry 行为（数据集里标了 expect_retry 的，必须真的重试）
    details["retries_used"] = r["budget"]["used"]["retries"]
    want_retry = bool(case.get("expect_retry"))
    got_retry = details["retries_used"] > 0 or len(tools) > len(
        {"resolve_entity"}) + 1 and any(
        t in tools[2:] for t in ("search_passages", "terminology_lookup"))
    details["retry_expected"] = want_retry
    details["retry_fired"] = bool(got_retry)
    details["retry_ok"] = (got_retry == want_retry)

    # 「第二步」是不是**有意义的**重试（换工具/放宽约束/换查询）
    reruns = [s for s in r["research_trace"]["steps"]
              if s["tool"] in ("search_passages", "terminology_lookup",
                               "compare_concepts", "find_concept_evidence")]
    details["multi_step"] = len(reruns) > 1
    details["trace_path"] = r.get("trace_path")
    return details


def summarize(cases):
    n = len(cases)
    def rate(key):
        return round(sum(1 for c in cases if c[key]) / n, 4) if n else None
    metrics = {
        "n": n,
        "classifier_accuracy": rate("query_type_ok"),
        "tool_selection_correctness": rate("tool_selection_ok"),
        "passage_validity": rate("passage_validity"),
        "sufficiency_correctness": rate("state_ok"),
        "gap_detection_accuracy": rate("gap_detection_ok"),
        "entity_resolution_accuracy": rate("entities_ok"),
        "budget_compliance": rate("budget_ok"),
        "must_mention_accuracy": rate("must_mention_ok"),
        # ── §17 要求的其余三项
        "source_trace_validity": rate("source_trace_validity"),
        "citation_contract_ok": rate("citation_contract_ok"),
        "citation_contract_detects_missing": rate("citation_contract_detects_missing"),
        "retry_behavior_accuracy": rate("retry_ok"),
        "retries_total": sum(c["retries_used"] for c in cases),
        "tool_calls_total": sum(c["tool_calls"] for c in cases),
        "tool_calls_avg": (round(sum(c["tool_calls"] for c in cases) / n, 2)
                           if n else None),
        "unsupported_claim_rate_reference": (
            round(sum(c["unsupported_claim_rate_cited"] or 0.0 for c in cases
                      if c["unsupported_claim_rate_cited"] is not None)
                  / max(1, sum(1 for c in cases
                               if c["unsupported_claim_rate_cited"] is not None)), 4)
            if n else None),
        "unsupported_claim_rate_uncited_reference": (
            round(sum(c["unsupported_claim_rate_uncited"] or 0.0 for c in cases
                      if c["unsupported_claim_rate_uncited"] is not None)
                  / max(1, sum(1 for c in cases
                               if c["unsupported_claim_rate_uncited"] is not None)), 4)
            if n else None),
        # 硬指标：一条编造都不允许
        "no_fabrication": (1.0 if all(c["fabricated"] == 0 for c in cases) else 0.0),
        # 引用有效性 = 可回查的 id 比例（fabricated 必须为 0 才算过）
        "citation_validity": (round(sum(1 for c in cases if c["fabricated"] == 0) / n, 4)
                              if n else None),
        "multi_step_rate": rate("multi_step"),
        "states_reached": sorted({c["state"] for c in cases}),
        "types_reached": sorted({c["query_type"] for c in cases}),
        "max_tool_calls_used": max((c["tool_calls"] for c in cases), default=0),
    }
    return metrics


def main(argv):
    save_n = 3
    eval_path, out_path, traces_dir, layer = EVAL, OUT, TRACES, "ontology.v4a1-base(gold)"
    for i, a in enumerate(argv):
        if a == "--save-traces":
            save_n = int(argv[i + 1])
    if "--v4a1" in argv:
        eval_path, out_path, traces_dir = EVAL_V4A1, OUT_V4A1, TRACES_V4A1
        layer = "ontology.v4a1"
    rows = load_eval(eval_path)
    os.makedirs(traces_dir, exist_ok=True)
    cases = []
    for c in rows:
        cases.append(run_one(c, save_trace_dir=(traces_dir if save_n else None)))
    metrics = summarize(cases)
    doc = {
        "schema_version": "research-eval-results/v1",
        "dataset": os.path.relpath(eval_path, VAULT),
        "ontology_layer": layer,
        "supersedes": ("research_eval_results.json（Phase 4A 的结果文件**不覆盖**）"
                       if "--v4a1" in argv else None),
        "generated_by": "_scripts/_tools/eval_research_agent.py",
        "budget_default": ra.DEFAULT_BUDGET,
        "metrics": metrics,
        "cases": cases,
        "determinism_note": ("指标由程序重算，不手工填；traces 与 case 明细同批产出。"
                            "任何一次重跑都应与本文件一致（语料未变时）。"),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if "--json" in argv:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("research eval: %d 问" % metrics["n"])
        for k in ("classifier_accuracy", "tool_selection_correctness",
                  "passage_validity", "citation_validity", "source_trace_validity",
                  "sufficiency_correctness", "gap_detection_accuracy",
                  "entity_resolution_accuracy", "budget_compliance",
                  "retry_behavior_accuracy", "unsupported_claim_rate_reference",
                  "no_fabrication", "multi_step_rate", "tool_calls_total",
                  "tool_calls_avg"):
            print("  %-30s %s" % (k, metrics[k]))
        print("  states: %s" % metrics["states_reached"])
        print("  types : %s" % metrics["types_reached"])
        bad = [c["id"] for c in cases
               if not (c["query_type_ok"] and c["tool_selection_ok"]
                       and c["state_ok"] and c["gap_detection_ok"]
                       and c["passage_validity"] and c["budget_ok"]
                       and c["must_mention_ok"] and c["source_trace_validity"]
                       and c["citation_contract_ok"] and c["retry_ok"])]
        print("  未达期望的 case：%s" % (bad or "无"))
        print("wrote %s" % os.path.relpath(out_path, VAULT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
