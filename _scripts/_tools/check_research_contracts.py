#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_research_contracts.py — Phase 4C.1-B §21：契约编译的**产物级门禁**

不跑检索（快），只做三件事：
  1. 对 14 个已人工评审任务编译 contract（用 `make_plan`），断言 10 类契约都能编译；
  2. 断言**硬规则**确实会拦：缺 lane / 缺 required op / 缺 relation evidence /
     缺历时端点 / metadata 不可用 / EXPECTED_ZERO=0 判 PASS（用内存构造的反例）；
  3. 断言 gold_v2 与三个人工裁决一致（rt-J01 / rt-H02 / rt-G01）。

`--verify` → 有任一条不成立则非零退出。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_contract as rc          # noqa: E402
import evidence_sufficiency_v21 as v21  # noqa: E402
from research_answer import make_plan   # noqa: E402


def jl(p):
    try:
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except Exception:
        return []


def jd(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def public(t):
    return {k: t[k] for k in ("task_id", "question", "language", "task_type",
                              "required_capabilities", "split")}


def _ev(pid, text):
    return {"passage_id": pid, "text": text, "authority_level": "L1",
            "seminar_id": "seminar." + pid.split(".")[1], "trace_status": "COMPLETE"}


def _compile(tt, q, *, lang="zh", entities=(), evidence=(), executed=("resolve_entity",),
             caps=()):
    plan = {"planned_operations": ["resolve_entity", "find_concept_evidence",
                                   "search_passages", "get_context"],
            "task_type": tt, "salient_terms": [], "question_language": lang,
            "entities": [{"term": t, "status": "RESOLVED", "entities": [e],
                          "context_required": False} for t, e in entities],
            "required_capabilities": list(caps), "anchor_pool": []}
    return rc.compile_research_contract(
        {"task_id": "gate", "question": q, "language": lang, "task_type": tt,
         "required_capabilities": list(caps)},
        plan, {"evidence": list(evidence)}, executed_tools=list(executed))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    problems = []
    stats = {}

    # 1) 14 个任务全部可编译
    tasks = {r["task_id"]: r for r in jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))}
    spec = {r["task_id"]: r for r in
            jl(os.path.join(EVAL, "scholarly_regression_v1.jsonl"))}
    compiled = 0
    types = set()
    for tid in sorted(spec):
        t = tasks.get(tid)
        if not t:
            problems.append("回归规格里的任务不在 v1 任务集：%s" % tid)
            continue
        c = rc.compile_research_contract(public(t), make_plan(public(t)),
                                         {"evidence": []})
        types.add(c["contract_type"])
        audit = rc.validate_contract(c)
        if audit["state_ceiling"] not in ("SUPPORTED", "PARTIALLY_SUPPORTED",
                                          "INSUFFICIENT_EVIDENCE"):
            problems.append("%s state_ceiling 非法：%s" % (tid, audit["state_ceiling"]))
        compiled += 1
    stats["tasks_compiled"] = compiled
    stats["contract_types_seen"] = sorted(types)
    if compiled != 14:
        problems.append("只编译了 %d/14 个任务" % compiled)

    # 2) 十类契约都能编译（含未在 14 题里出现的类型）
    for tt in rc.CONTRACTS:
        try:
            c = _compile(tt, "测试问题", entities=[("x", "concept.desir")])
            if c["contract_type"] != rc.CONTRACTS[tt].__name__:
                problems.append("%s 编译出的 contract_type 不符：%s" % (tt, c["contract_type"]))
        except Exception as exc:                              # pragma: no cover
            problems.append("%s 编译失败：%s" % (tt, exc))
    stats["contract_classes"] = len(rc.CONTRACTS)

    # 3) 硬规则反例（内存构造，不依赖任何具体任务）
    checks = []

    c = _compile("concept_relation", "desire 与 demand 什么关系？",
                 entities=[("desire", "concept.desir"), ("demand", "concept.demande")],
                 evidence=[_ev("passage.S05.unknown.P0001", "le désir ...")],
                 executed=("resolve_entity", "compare_concepts", "get_context"))
    codes = [v["code"] for v in rc.validate_contract(c)["violated_rules"]]
    checks.append(("missing_lane_blocks_supported", "MISSING_REQUIRED_LANE" in codes,
                   codes))

    c = _compile("translation_terminology", "「快感」译名如何？", executed=("resolve_entity",))
    codes = [v["code"] for v in rc.validate_contract(c)["violated_rules"]]
    checks.append(("missing_operation_blocks_supported",
                   "MISSING_REQUIRED_OPERATION" in codes, codes))

    c = _compile("philosophy_to_lacan", "黑格尔如何进入拉康的欲望理论？",
                 entities=[("désir", "concept.desir")],
                 evidence=[_ev("passage.S05.unknown.P0001", "le désir ...")],
                 executed=("resolve_entity", "compare_concepts", "get_context"))
    codes = [v["code"] for v in rc.validate_contract(c)["violated_rules"]]
    checks.append(("relation_evidence_missing_blocks", "RELATION_EVIDENCE_MISSING" in codes,
                   codes))

    c = _compile("diachronic_development", "Seminar VII 到 Seminar XX 的 jouissance",
                 entities=[("jouissance", "concept.jouissance")],
                 evidence=[_ev("passage.S20.unknown.P0001", "la jouissance ...")],
                 executed=("resolve_entity", "trace_concept", "get_context"))
    audit = rc.validate_contract(c)
    checks.append(("diachronic_endpoint_missing_blocks",
                   audit["state_ceiling"] == "INSUFFICIENT_EVIDENCE",
                   [v["code"] for v in audit["violated_rules"]]))

    c = _compile("topology_matheme", "Que exprime la formule $ ◊ a ?", lang="fr",
                 entities=[("fantasme", "concept.fantasme")],
                 evidence=[_ev("passage.S14.unknown.P0066",
                               "le poinçon est divisé par la barre verticale, c'est le "
                               "sujet barré à ce rapport de si et seulement si avec le petit(a).")],
                 executed=("resolve_entity", "find_concept_evidence", "get_context",
                           "search_passages"))
    codes = [v["code"] for v in rc.validate_contract(c)["violated_rules"]]
    checks.append(("formalism_retrieval_not_structural",
                   "RETRIEVED_FORMALISM_MISSING" in codes
                   and "CORPUS_FORMALISM_MISSING" not in codes, codes))

    c = _compile("insufficient_unanswerable", "1953 年 11 月 18 日的确切日期是哪天？")
    audit = rc.validate_contract(c)
    checks.append(("metadata_unavailable_is_structural",
                   audit["state_ceiling"] == "INSUFFICIENT_EVIDENCE",
                   [v["code"] for v in audit["violated_rules"]]))

    c = _compile("translation_terminology", "「原乐」这个译名在语料里如何？")
    z = [x for x in c["expected_zero_lanes"] if x["term"] == "原乐"]
    checks.append(("expected_zero_lane_passes",
                   bool(z) and z[0]["result"] == "PASS" and z[0]["observed_hits"] == 0,
                   z))

    # 4) v2.1：契约上限 + 无解释升格被禁止
    v2 = {"engine": "evidence_sufficiency/v2", "final_state": "SUPPORTED",
          "reasons": ["证据量、多分量一致性、session 多样性、约束满足四项均达标。"],
          "signals": {"component_agreement": None, "constraint_satisfaction": None,
                      "independent_families_executed": [], "passage_count": 3,
                      "distinct_session_count": 2}}
    c = _compile("concept_relation", "desire 与 demand 什么关系？",
                 entities=[("desire", "concept.desir"), ("demand", "concept.demande")],
                 evidence=[_ev("passage.S05.unknown.P0001", "le désir ...")],
                 executed=("resolve_entity", "compare_concepts", "get_context"))
    out = v21.evaluate_v21(v2, c)
    checks.append(("v21_caps_supported_and_explains",
                   out["final_state"] != "SUPPORTED" and out["transition"] is not None
                   and bool(out["transition_reason"]),
                   {"final": out["final_state"], "transition": out["transition"]}))
    checks.append(("v21_drops_template_reason",
                   any("四项均达标" in d for d in out["dropped_reasons"]),
                   out["dropped_reasons"]))

    # 5) gold_v2 与人工裁决一致
    g2 = {r["task_id"]: r for r in
          jl(os.path.join(EVAL, "gold_v2", "research_tasks_v2.jsonl"))}
    want = {"rt-J01": "PARTIALLY_SUPPORTED", "rt-H02": "SUPPORTED",
            "rt-G01": "UNDETERMINED_PENDING_RELATION_RETRIEVAL"}
    for tid, w in want.items():
        got = (g2.get(tid) or {}).get("answerability")
        checks.append(("gold_v2_%s_%s" % (tid, w), got == w, got))
    man = jd(os.path.join(EVAL, "gold_v2", "MANIFEST.json"), {}) or {}
    import eval_integrity as ei
    checks.append(("gold_v2_v1_untouched",
                   man.get("v1_sha256") == ei.sha256_file(
                       os.path.join(EVAL, "research_tasks_v1.jsonl")),
                   man.get("v1_sha256", "")[:16]))
    checks.append(("needs_manual_review_not_auto_guessed",
                   len(man.get("counts", {}).get("needs_manual_review_tasks") or []) >= 1,
                   man.get("counts", {}).get("needs_manual_review_tasks")))

    failed = [c for c in checks if not c[1]]
    stats["hard_rule_checks"] = len(checks)
    stats["hard_rule_failures"] = [c[0] for c in failed]
    for name, ok, ev in checks:
        if not ok:
            problems.append("硬规则检查失败：%s（evidence=%s）"
                            % (name, json.dumps(ev, ensure_ascii=False)[:160]))

    if not a.quiet:
        print("契约编译：%d/14 任务；契约类 %d 类；硬规则检查 %d 项"
              % (compiled, len(rc.CONTRACTS), len(checks)))
        for name, ok, _detail in checks:
            print("  %-5s %s" % ("PASS" if ok else "FAIL", name))
        if problems:
            print("[research-contracts] %d 个问题" % len(problems))
    if a.verify:
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
