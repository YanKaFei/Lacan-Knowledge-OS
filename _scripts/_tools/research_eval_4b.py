#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_eval_4b.py — Phase 4B §21/§25/§26/§29/§30：研究质量评测

它评的是**研究质量**，不是检索指标
────────────────────────────────────
Phase 4A 评「能不能取到证据」；Phase 4B 评「研究做得好不好」：

  Evidence Validity · Citation Entailment(术语级代理) · Claim Coverage ·
  Unsupported Claim Rate · Source Layer Accuracy · Evidence Sufficiency Accuracy ·
  Entity Resolution Accuracy · Diachronic Coverage · Research Efficiency ·
  Research Completion

§22：**不合成单一总分**。所有分指标都在 `metrics` 里并列，dashboard 只做展示。

评测时的两条纪律
────────────────
* **Gold 不进入 Agent**（§6）：送进 Agent 的只有 `public_view(task)`；
  `gold_isolation` 会把实际字段列表写进结果与 trace，可复核。
* **评测过程只读**（§33）：`record_gaps=False`，不写 canonical、不写缺口队列；
  要产出 gap 候选请单独跑 `--propose-gaps`。

用法
────
    python3 research_eval_4b.py --split dev        # 开发集
    python3 research_eval_4b.py --split holdout    # 盲测集（只在开发集定稿后跑）
    python3 research_eval_4b.py --budget-check     # 预算耗尽行为测试
    python3 research_eval_4b.py --propose-gaps     # 从实跑结果写 gap **候选**
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
TASKS = os.path.join(EVAL, "research_tasks_v1.jsonl")
TRACES = os.path.join(EVAL, "research_traces_4b")
RESULTS = os.path.join(EVAL, "research_eval_results_v1.json")
# Phase 4C：v2 引擎的新结果 —— **绝不覆盖** Phase 4B 的 v1 结果文件
OUT_V4C = os.path.join(EVAL, "research_eval_results.v4c.json")
TRACES_4C = os.path.join(EVAL, "research_traces_4c")
HUMAN = os.path.join(EVAL, "research_human_review.jsonl")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_answer as ans        # noqa: E402
import ontology_gaps as ogq          # noqa: E402

PUBLIC_FIELDS = ("task_id", "question", "language", "task_type",
                 "required_capabilities", "split")

FAILURE_TAXONOMY = (
    "ENTITY_RESOLUTION_FAILURE", "TERMINOLOGY_MAPPING_FAILURE", "RETRIEVAL_MISS",
    "RANKING_FAILURE", "CONTEXT_INSUFFICIENT", "ONTOLOGY_GAP", "SOURCE_GAP",
    "EVIDENCE_SUFFICIENCY_ERROR", "CITATION_ERROR", "SYNTHESIS_OVERCLAIM",
    "BUDGET_EXHAUSTION",
)

DIA_TYPES = ("diachronic_development",)
LANE_TYPES = ("concept_relation", "translation_terminology")


def load_tasks():
    with open(TASKS, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def public_view(task):
    """§6：只给 Agent 这些字段。gold 一律不出现。"""
    return {k: task[k] for k in PUBLIC_FIELDS if k in task}


COMPARE_MARKERS = ("区别", "差异", "对比", "比较", "区分", "关系",
                   "différence", "difference", "vs", "versus", "distinction")


def _needs_lanes(task):
    """该任务是否**要求**并置比较（因而必须有独立 lane）。"""
    tt = task.get("task_type")
    if tt == "concept_relation":
        return True
    q = (task.get("question") or "").lower()
    if tt == "translation_terminology" and len(task.get("expected_entities") or []) >= 2:
        return any(mk in q for mk in COMPARE_MARKERS)
    return False


def _lane_recall(task, seen, k):
    """每个 lane 的**完整命中集**上的召回（分母是 lane 集大小，不是抽样 gold）。"""
    sets = task.get("lane_eval_sets") or {}
    if not sets:
        return None
    vals = []
    for _lane, ids in sets.items():
        ids = set(ids)
        if not ids:
            continue
        denom = min(k, len(ids))
        if denom <= 0:
            continue
        vals.append(len(ids & seen) / denom)
    return round(sum(vals) / len(vals), 4) if vals else None


def evaluate(task, run):
    """把一次研究跑的结果对照 gold 评估。→ row dict（全部指标都在）。"""
    pack = run["evidence_pack"]
    an = run["answer"] or {"claims": [], "sections": {}}
    chk = run["answer_check"] or {"metrics": {}, "issues": []}
    m = chk["metrics"]
    gold = set(task.get("gold_evidence") or [])
    accept = set(task.get("acceptable_evidence") or [])
    cited = {p for c in an["claims"] for p in c["citations"]}
    seen = set(run["trace"]["passages_seen"])
    resolved = {e for x in (run["plan"]["entities"] or [])
                for e in (x.get("entities") or [])}
    periods_seen = {e.get("period") for e in pack["evidence"] if e.get("period")}
    routes = set(run["trace"]["retrieval_routes"])
    lane_tags = {e.get("lane") for e in pack["evidence"] if e.get("lane")}
    rel = (pack.get("evidence_state", {}).get("signals") or {}).get("relevance_rate")

    gold_hit = len(gold & cited)
    gold_seen = len(gold & seen)
    row = {
        "task_id": task["task_id"], "split": task["split"],
        "task_type": task["task_type"], "language": task["language"],
        "question": task["question"],
        # ── 证据/引用类
        "evidence_validity": m.get("evidence_validity"),
        "citation_anchor_support_rate": m.get("citation_anchor_support_rate"),
        "citation_term_cluster_rate": m.get("citation_term_cluster_rate"),
        "claim_coverage": (len([c for c in an["claims"] if c["citations"]])
                           / len(an["claims"])) if an["claims"] else None,
        "unsupported_claim_rate": m.get("unsupported_claim_rate"),
        "fabricated_citations": m.get("fabricated_citations"),
        "source_layer_confusions": m.get("source_layer_confusions"),
        "provenance_upgrades": m.get("provenance_upgrades"),
        # ── 检索/研究有效性
        # ⚠️ `gold_evidence` 是**分层抽样**（每期≤3）的参考样本，**不是召回分母**：
        #    抽样取的是 store 里最早命中的那几条，而检索返回的是排序靠前的段落，
        #    两者交集天然接近 0（实测 D01：gold 9 条全在 S11，agent 也在 S11 取到 12 条，
        #    交集仍为 0）。把它当召回率会得出「检索全错」的假结论。
        #    真正可用的检索指标是下面的 **lane_recall**（对每个 lane 的完整命中集算）。
        "gold_sample_n": len(gold), "gold_sample_seen": gold_seen,
        "gold_sample_cited": gold_hit,
        "lane_eval_sets": {k: len(v) for k, v in
                           (task.get("lane_eval_sets") or {}).items()},
        "lane_hits": {k: len(set(v) & seen) for k, v in
                      (task.get("lane_eval_sets") or {}).items()},
        "lane_recall": _lane_recall(task, seen, len(pack["evidence"])),
        "acceptable_n": len(accept),
        "acceptable_cited": len(accept & cited),
        "evidence_n": pack["evidence_n"],
        "useful_evidence_n": len(cited & (gold | accept)),
        # ── 能力类
        "entities_expected": task.get("expected_entities") or [],
        "entities_resolved": sorted(resolved),
        # 只对**问题本身蕴含的**实体计分；desirable_entities 是「理想情况下还会找到」
        # 的实体，不计入准确率（第一版把 E01 的 forclusion 也算进去，属于不公平的期望）。
        "entity_resolution_ok": bool(set(task.get("expected_entities") or [])
                                     <= resolved) if task.get("expected_entities")
        else True,
        "desirable_entities": task.get("desirable_entities") or [],
        "desirable_hit": sorted(set(task.get("desirable_entities") or []) & resolved),
        "periods_expected": task.get("expected_periods") or [],
        "periods_seen": sorted(p for p in periods_seen if p),
        "period_coverage_ok": (len(set(task.get("expected_periods") or [])
                                   & periods_seen)
                               / len(set(task["expected_periods"])))
        if task.get("expected_periods") else None,
        "distinct_periods": len(periods_seen),
        "distinct_seminars": len({e.get("seminar_id") for e in pack["evidence"]}),
        "lanes": len(routes), "routes": sorted(routes),
        # §16：lane 看的是**证据的 lane 标记 / 解析出的实体数**，
        # 不是「用了几个不同 route」——第一版把 route 数当 lane 数，恒为 0。
        "lane_tags": sorted(t for t in lane_tags if t),
        # 「对比题」的判据必须是**真的要求并置比较**，不是「期望实体 ≥2」：
        # 历时题（C01）与哲学来源题（G02）也会有 2 个期望实体，但它们不是对比题
        # （第一版用实体数当判据，把这两题误判成 lane 失败）。
        "separate_lanes_required": _needs_lanes(task),
        "separate_lanes_ok": (len(lane_tags) >= 2 or len(resolved) >= 2)
        if _needs_lanes(task) else None,
        "relevance_rate": rel,
        "term_counts": run["plan"].get("term_counts"),
        "calibration": run["trace"].get("calibration"),
        # ── 状态与预算
        "answerability": task["answerability"],
        "state": pack["evidence_state"]["state"],
        "tool_calls": run["budget"]["used"]["tool_calls"],
        "context_expansions": run["budget"]["used"]["context_expansions"],
        "retries": run["budget"]["used"]["retries"],
        "budget_exceeded": run["budget"]["exceeded"],
        "multi_step": run["budget"]["used"]["tool_calls"] >= 3,
        "research_completion": bool(an["sections"].get("brief_answer"))
        and any(c["citations"] for c in an["claims"]),
        "ontology_gap_codes": pack.get("ontology_gap_codes") or [],
        "source_trace_incomplete_n": pack["evidence_state"]["signals"].get(
            "source_trace_incomplete_n", 0),
        "warnings": [w["code"] for w in pack.get("warnings") or []],
        "issues": chk["issues"],
        "seconds": run["seconds"],
        "gold_isolation": run["gold_isolation"],
    }
    # ── sufficiency 校准（§13）：false SUPPORTED 是最高风险
    want, got = task["answerability"], row["state"]
    if want == "SUPPORTED":
        row["sufficiency_ok"] = got in ("SUPPORTED", "PARTIALLY_SUPPORTED")
        row["false_insufficient"] = got == "INSUFFICIENT_EVIDENCE"
    else:
        row["sufficiency_ok"] = got != "SUPPORTED"
        row["false_supported"] = got == "SUPPORTED"
    row.setdefault("false_supported", False)
    row.setdefault("false_insufficient", False)
    row["failure_classes"] = classify(task, row)
    return row


def classify(task, row):
    """§26：把每个问题尽量定位到层。"""
    out = []
    if not row["entity_resolution_ok"]:
        out.append("ENTITY_RESOLUTION_FAILURE")
    if row["false_supported"]:
        out.append("EVIDENCE_SUFFICIENCY_ERROR")
    if row["false_insufficient"]:
        out.append("EVIDENCE_SUFFICIENCY_ERROR")
    if row["fabricated_citations"]:
        out.append("CITATION_ERROR")
    if row["provenance_upgrades"] or row["source_layer_confusions"]:
        out.append("CITATION_ERROR")
    if row["answerability"] != "INSUFFICIENT_EVIDENCE" and row["lane_recall"] is not None:
        if row["lane_recall"] == 0:
            out.append("RETRIEVAL_MISS")
        elif row["lane_recall"] < 0.05:
            out.append("RANKING_FAILURE")
    ENTITY_LEVEL_GAPS = {"COUNTERPART_ENTITY_MISSING", "BOTH_ENTITIES_MISSING",
                         "UNRESOLVED_ENTITY", "AMBIGUOUS_ENTITY", "ENTITY_COLLISION"}
    if ENTITY_LEVEL_GAPS & set(row["ontology_gap_codes"]):
        out.append("ONTOLOGY_GAP")
    if row["source_trace_incomplete_n"]:
        out.append("SOURCE_GAP")
    # 只有「证据多但一条上下文都没补」才算上下文不足
    if row["context_expansions"] == 0 and row["evidence_n"] > 5 \
            and row["task_type"] in ("concept_definition", "case_research",
                                     "diachronic_development"):
        out.append("CONTEXT_INSUFFICIENT")
    if row["budget_exceeded"]:
        out.append("BUDGET_EXHAUSTION")
    if row["task_type"] == "seminar_specific" and "CONSTRAINT_RETURNED_NOTHING" \
            in row["warnings"]:
        out.append("TERMINOLOGY_MAPPING_FAILURE")
    if row["unsupported_claim_rate"] and row["unsupported_claim_rate"] > 0:
        out.append("SYNTHESIS_OVERCLAIM")
    return out


def aggregate(rows):
    """§22：分指标并列，**不合成单一总分**。"""
    n = len(rows)

    def mean(key, keep=lambda v: v is not None):
        vals = [r[key] for r in rows if keep(r.get(key))]
        return round(sum(vals) / len(vals), 4) if vals else None

    def rate(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(1 for v in vals if v) / len(vals), 4) if vals else None

    metrics = {
        "n_tasks": n,
        # Evidence Validity
        "evidence_validity": mean("evidence_validity"),
        "fabricated_citations_total": sum(r["fabricated_citations"] or 0 for r in rows),
        # Citation Entailment（两个术语级代理 + 明说局限）
        "citation_anchor_support_rate": mean("citation_anchor_support_rate"),
        "citation_term_cluster_rate": mean("citation_term_cluster_rate"),
        "entailment_is_term_level_proxy": True,
        # Claim Coverage / Unsupported
        "claim_coverage": mean("claim_coverage"),
        "unsupported_claim_rate": mean("unsupported_claim_rate"),
        "unsupported_claims_total": sum(
            len([i for i in (r["issues"] or []) if i.get("kind") == "UNSUPPORTED_CLAIM"])
            for r in rows),
        "unsupported_claim_tasks": [r["task_id"] for r in rows
                                    if any(i.get("kind") == "UNSUPPORTED_CLAIM"
                                           for i in (r["issues"] or []))],
        # Source Layer
        "source_layer_confusions_total": sum(r["source_layer_confusions"] or 0
                                             for r in rows),
        "provenance_upgrades_total": sum(r["provenance_upgrades"] or 0 for r in rows),
        # Sufficiency 校准
        "sufficiency_accuracy": rate("sufficiency_ok"),
        "false_supported": [r["task_id"] for r in rows if r["false_supported"]],
        "false_insufficient": [r["task_id"] for r in rows if r["false_insufficient"]],
        "states_reached": sorted({r["state"] for r in rows}),
        "tasks_downgraded_by_calibration": [
            r["task_id"] for r in rows
            if (r.get("calibration") or {}).get("reasons")],
        "tasks_with_calibration_signals": [r["task_id"] for r in rows
                                           if r.get("calibration")],
        "relevance_rate_mean": mean("relevance_rate"),
        # Entity / 时期 / lane
        "entity_resolution_accuracy": rate("entity_resolution_ok"),
        "period_coverage_mean": mean("period_coverage_ok"),
        "diachronic_tasks": [r["task_id"] for r in rows
                             if r["task_type"] in DIA_TYPES],
        "diachronic_period_coverage": mean(
            "period_coverage_ok",
            keep=lambda v: v is not None),
        "separate_lanes_required_n": len([r for r in rows
                                          if r.get("separate_lanes_required")]),
        "separate_lanes_accuracy": rate("separate_lanes_ok"),
        # 效率 / 完成度
        "tool_calls_total": sum(r["tool_calls"] for r in rows),
        "tool_calls_mean": round(sum(r["tool_calls"] for r in rows) / n, 2) if n else None,
        "useful_evidence_mean": mean("useful_evidence_n"),
        "research_completion_rate": rate("research_completion"),
        "multi_step_rate": rate("multi_step"),
        "lane_recall_mean": mean("lane_recall"),
        "gold_sample_recall_note": ("gold_evidence 是分层抽样参考，**不作为召回分母**；"
                                    "检索有效性看 lane_recall_mean。"),
        # 失败分类
        "failure_counts": _count_failures(rows),
        "tasks_with_failures": [r["task_id"] for r in rows if r["failure_classes"]],
    }
    return metrics


def _count_failures(rows):
    from collections import Counter
    c = Counter()
    for r in rows:
        for f in r["failure_classes"]:
            c[f] += 1
    return dict(c)


def run_split(tasks, budget=None, save=True, tag="dev", quiet=False):
    rows, t0 = [], time.time()
    os.makedirs(TRACES, exist_ok=True)
    for t in tasks:
        pub = public_view(t)
        run = ans.run_task(pub, budget=budget, record_gaps=False)
        row = evaluate(t, run)
        rows.append(row)
        if save:
            with open(os.path.join(TRACES, "%s.json" % t["task_id"]), "w",
                      encoding="utf-8") as f:
                json.dump({"task_id": t["task_id"], "public_task": pub,
                           "gold_withheld": {k: t[k] for k in t if k not in PUBLIC_FIELDS},
                           "plan": run["plan"], "evidence_pack": run["evidence_pack"],
                           "answer": run["answer"], "answer_check": run["answer_check"],
                           "trace": run["trace"], "budget": run["budget"],
                           "evaluation": row}, f, ensure_ascii=False, indent=1)
                f.write("\n")
        if not quiet:
            print("  %-10s %-24s state=%-21s n=%-3d lane_recall=%-6s calls=%-2d %s"
                  % (t["task_id"], t["task_type"], row["state"], row["evidence_n"],
                     row["lane_recall"], row["tool_calls"],
                     ",".join(row["failure_classes"]) or ""))
    return rows, round(time.time() - t0, 1)


def budget_check(tasks, quiet=False):
    """§20：预算必须真的阻止无限 research，且耗尽时不得编答案。"""
    out = []
    for t in tasks:
        pub = public_view(t)
        run = ans.run_task(pub, budget={"max_tool_calls": 2, "max_passages": 5,
                                        "max_context_expansions": 0,
                                        "max_retries": 0},
                           record_gaps=False)
        row = evaluate(t, run)
        an = run["answer"] or {"sections": {}, "claims": []}
        limited = any("预算" in x for x in (run["evidence_pack"]["limitations"] or []))
        out.append({
            "task_id": t["task_id"],
            "tool_calls": run["budget"]["used"]["tool_calls"],
            "budget_exceeded": run["budget"]["exceeded"],
            "state": row["state"],
            "limitation_reported": limited or bool(run["budget"]["exceeded"]),
            "answer_is_hedged": row["state"] in ("PARTIALLY_SUPPORTED",
                                                 "INSUFFICIENT_EVIDENCE"),
            "fabricated": row["fabricated_citations"],
            "claims": len(an["claims"]),
            "unsupported_claim_rate": row["unsupported_claim_rate"],
        })
        if not quiet:
            print("  %-10s calls=%d exceeded=%s state=%-21s hedged=%s fabricated=%s"
                  % (t["task_id"], out[-1]["tool_calls"], out[-1]["budget_exceeded"],
                     out[-1]["state"], out[-1]["answer_is_hedged"],
                     out[-1]["fabricated"]))
    ok = all(o["tool_calls"] <= 2 and o["answer_is_hedged"] and o["fabricated"] == 0
             and o["limitation_reported"] for o in out)
    return {"checks": out, "all_passed": ok,
            "rule": "预算耗尽必须表现为 PARTIALLY/INSUFFICIENT + 明确的限制说明，且不得编造引用"}


def propose_gaps(tasks, budget=None):
    """§28：从实跑结果写 **candidate** gap（不自动修任何东西）。"""
    added = []
    import knowledge_api as api
    for t in tasks:
        run = ans.run_task(public_view(t), budget=budget, record_gaps=False)
        pack = run["evidence_pack"]
        for term in (pack.get("unresolved_terms") or []):
            term = str(term)
            # 写候选前先确认它**现在仍然**解析不出来 —— 否则会往队列里灌
            # 「其实早已能解析」的假缺口（Phase 4A.1 的 repair --check 会因此失败）。
            st = api.resolve_entity(term)["resolution"]["resolution_status"]
            if st != "UNRESOLVED":
                continue
            got = ogq.propose("missing_entity", term, term=term,
                              detected_by="research_eval_4b",
                              detail="Phase 4B 研究实跑中未能解析的研究用词")
            if got:
                added.append(got["issue_id"])
        for code in (pack.get("ontology_gap_codes") or []):
            if code in ("COUNTERPART_ENTITY_MISSING", "BOTH_ENTITIES_MISSING"):
                got = ogq.propose("missing_entity", "%s|%s" % (t["task_id"], code),
                                  term=run["question"][:40],
                                  detected_by="research_eval_4b",
                                  detail="研究任务 %s 触发 %s" % (t["task_id"], code))
                if got:
                    added.append(got["issue_id"])
    return sorted(set(added))


def write_human_review(tasks, rows):
    """§23：人工评审**骨架**。没有人工评审者 → NOT_REVIEWED，不伪造评分。"""
    by = {r["task_id"]: r for r in rows}
    with open(HUMAN, "w", encoding="utf-8") as f:
        for t in tasks:
            r = by.get(t["task_id"], {})
            f.write(json.dumps({
                "schema_version": "research-human-review/v1",
                "task_id": t["task_id"], "question": t["question"],
                "task_type": t["task_type"], "split": t["split"],
                "auto_metrics": {k: r.get(k) for k in
                                 ("evidence_validity", "citation_anchor_support_rate",
                                  "citation_term_cluster_rate", "claim_coverage",
                                  "unsupported_claim_rate", "state", "answerability",
                                  "gold_recall_cited", "period_coverage_ok")},
                "human_scores": {k: None for k in
                                 ("theoretical_coherence", "historical_accuracy",
                                  "distinction_preservation", "answer_usefulness",
                                  "overclaiming", "clarity")},
                "review_status": "NOT_REVIEWED",
                "note": ("没有人工作者时**不伪造评分**（§23）：所有 human_scores 为 null。"
                         "这些维度（理论连贯性/史学准确性/区分保持/可用性/过度断言/清晰度）"
                         "无法纯程序判定，必须由人填写。"),
            }, ensure_ascii=False) + "\n")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=("dev", "holdout", "all"))
    ap.add_argument("--v4c", action="store_true",
                    help="用 evidence_sufficiency/v2，结果写 research_eval_results.v4c.json")
    ap.add_argument("--budget-check", action="store_true")
    ap.add_argument("--propose-gaps", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    tasks = load_tasks()

    if a.budget_check:
        sel = [t for t in tasks if t["split"] == "dev"][:3]
        print("预算耗尽行为测试（max_tool_calls=2）：")
        res = budget_check(sel, quiet=a.quiet)
        out = os.path.join(VAULT, "_data", "index", "RESEARCH_4B_BUDGET_CHECK.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print("[budget-check] %s" % ("PASS" if res["all_passed"] else "FAIL"))
        return 0 if res["all_passed"] else 1

    if a.propose_gaps:
        before = len(ogq.read_all())
        ids = propose_gaps(tasks)
        after = len(ogq.read_all())
        print("candidate gap：本次新增 %d 条（重复的已去重跳过），"
              "队列共 %d 条 —— 全部为 candidate，不自动修（§28）"
              % (max(0, after - before), after))
        return 0

    sel = [t for t in tasks if a.split == "all" or t["split"] == a.split]
    print("Phase 4B 研究评测：split=%s，%d 个任务" % (a.split, len(sel)))
    rows, secs = run_split(sel, quiet=a.quiet, tag=a.split)
    metrics = aggregate(rows)
    doc = {
        "schema_version": "research-eval-4b/v1",
        "split": a.split,
        "tasks_n": len(sel),
        "seconds": secs,
        "metrics": metrics,
        "rows": rows,
        "score_policy": ("§22：**不合成单一总分**。所有分指标并列在 metrics 里；"
                         "任何汇总展示都不得隐藏 unsupported claim / citation entailment / "
                         "evidence sufficiency。"),
        "entailment_caveat": ("Citation Entailment 只有**术语级代理**"
                              "（严格子串 + 词袋包含）；真正的语义蕴含需要人工评审。"),
    }
    if a.v4c:
        out = OUT_V4C
    else:
        out = RESULTS if a.split in ("all",) else RESULTS.replace(
            ".json", ".%s.json" % a.split)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if not a.v4c:
        write_human_review(sel, rows)
    print("\n== 分指标（无单一总分）==")
    for k, v in metrics.items():
        if k in ("failure_counts",) and not v:
            v = {}
        print("  %-34s %s" % (k, v))
    print("\nwrote %s" % os.path.relpath(out, VAULT))
    print("traces: %s/*.json" % os.path.relpath(TRACES, VAULT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
