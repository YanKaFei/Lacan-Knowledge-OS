#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase3_completion.py — Phase 3C §24 Phase 3 Completion Gate（22 条）

§24 原文：**Phase 3 可以关闭，不要求「Vector 在所有 query 上都优于 lexical」。
要求的是最终 Retrieval System 成立。** 满足 22 条后允许声明
`PHASE 3 RETRIEVAL LAYER = COMPLETE`，**即使 raw embedding contrastive 仍不是 10/10** ——
因为我们验证的是最终 Retrieval System，而不是要求通用 embedding 模型本身
成为 Lacanian theorist。

本脚本把 22 条逐条变成**可执行判据**，产出：
    _data/index/PHASE3_COMPLETION_GATE.json
    PHASE3C_FINDINGS.md

它**只报事实**：`CLOSABLE` 或者 `NOT_CLOSABLE`（附未通过的条目）。
不通过时**不得**声明 Phase 3 完成。

用法
────
    python3 _scripts/_tools/check_phase3_completion.py              # 算并写报告
    python3 _scripts/_tools/check_phase3_completion.py --verify     # 只核结论
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
IDX = os.path.join(VAULT, "_data", "index")
VECDIR = os.path.join(IDX, "vector")
REPORTS = os.path.join(VAULT, "_index", "Reports")
OUT_JSON = os.path.join(IDX, "PHASE3_COMPLETION_GATE.json")
FINDINGS = os.path.join(VAULT, "PHASE3C_FINDINGS.md")

sys.path.insert(0, HERE)


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None


def jl(p):
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def txt(p):
    return open(p, encoding="utf-8").read() if os.path.isfile(p) else ""


def build_checks():
    C = []

    def add(n, req, fn, evidence):
        C.append({"n": n, "requirement": req, "fn": fn, "evidence": evidence})

    # 1 full index built + verified
    def c1():
        m = load(os.path.join(VECDIR, "FULL_INDEX_MANIFEST.minilm.json"))
        v = load(os.path.join(VECDIR, "FULL_INDEX_VERIFICATION.json"))
        return bool(m and m.get("passage_count") == 249105 and m.get("dimensions") == 384
                    and v and v.get("passed")), {
            "manifest": "FULL_INDEX_MANIFEST.minilm.json",
            "verification": (v or {}).get("passed"),
            "failed_checks": (v or {}).get("failed")}
    add(1, "MiniLM 249,105 Passage full index 建成并通过完整性验证", c1,
        "FULL_INDEX_MANIFEST.minilm.json · FULL_INDEX_VERIFICATION.json")

    # 2 reproducible from canonical corpus
    def c2():
        r = load(os.path.join(VECDIR, "FULL_INDEX_REPRODUCIBILITY.json"))
        return bool(r and r.get("passed")), (r or {})
    add(2, "Vector index 可从 canonical corpus 重建", c2,
        "FULL_INDEX_REPRODUCIBILITY.json（第二次独立构建的 artifact hash 比对）")

    # 3 Terminology Bridge formal
    def c3():
        rows = jl(os.path.join(VAULT, "_data", "terminology_bridge.jsonl"))
        need = ("term_id", "source_form", "source_language", "target_form",
                "target_language", "entity_id", "relation_type", "status",
                "review_status", "source", "notes")
        ok = bool(rows) and all(all(k in r for k in need) for r in rows)
        eq = [r for r in rows if r["relation_type"] == "equivalent"]
        df = [r for r in rows if r["relation_type"] == "distinct_from"]
        return ok and bool(eq) and bool(df), {
            "rows": len(rows), "equivalent": len(eq), "distinct_from": len(df),
            "api": "terminology_bridge.py", "doc": "TERMINOLOGY_BRIDGE.md"}
    add(3, "Terminology Bridge X 成为正式可审计组件", c3,
        "_data/terminology_bridge.jsonl · terminology_bridge.py · TERMINOLOGY_BRIDGE.md")

    # 4 routing policy actually runs
    def c4():
        r = load(os.path.join(VECDIR, "ROUTING_COVERAGE.json"))
        return bool(r and r.get("queries_routed", 0) >= 40 and
                    r.get("distinct_routes_used", 0) >= 3), (r or {})
    add(4, "Query Routing Policy 实际运行", c4,
        "_data/index/vector/ROUTING_COVERAGE.json · QUERY_ROUTING_POLICY.md")

    # 5 vector can be disabled per class
    def c5():
        d = load(os.path.join(VECDIR, "full_corpus_results.json"))
        if not d:
            return False, {}
        m = list(d["models"].values())[0]
        return m["vector_disabled_queries"] > 0, {
            "vector_disabled_queries": m["vector_disabled_queries"],
            "multi_lane_queries": m["multi_lane_queries"]}
    add(5, "Vector 可以按 query class 禁用", c5,
        "full_corpus_results.json.vector_disabled_queries > 0")

    # 6 full-corpus benchmark run
    def c6():
        d = load(os.path.join(VECDIR, "full_corpus_results.json"))
        return bool(d and "249,105" in (d.get("scale") or "")
                    and d.get("answerable_n") == 40), {
            "scale": (d or {}).get("scale"), "answerable_n": (d or {}).get("answerable_n")}
    add(6, "full-corpus benchmark 已运行", c6, "FULL_CORPUS_RETRIEVAL_RESULTS.md")

    # 7 ZH->FR real results
    def c7():
        d = load(os.path.join(VECDIR, "full_corpus_results.json"))
        if not d:
            return False, {}
        m = list(d["models"].values())[0]
        z = (m.get("by_class") or {}).get("zh_to_fr")
        return bool(z and z.get("n", 0) > 0 and
                    z.get("E+L+V+X", {}).get("hit@20") is not None), (z or {})
    add(7, "ZH→FR retrieval 有真实结果", c7,
        "full_corpus_results.json.by_class.zh_to_fr")

    # 8 X/V attribution explicit
    def c8():
        a = load(os.path.join(VECDIR, "full_corpus_ablation.json")) or {}
        t = txt(os.path.join(VAULT, "FULL_CORPUS_ABLATION.md"))
        has_numbers = "X`（术语桥）" in t and "`V`（向量）" in t
        has_verdict = ("principal cross-language mechanism" in t
                       or "边际大于" in t or "两者边际相同" in t)
        return bool(has_numbers and has_verdict), {
            "report": "FULL_CORPUS_ABLATION.md", "attribution_section": has_numbers,
            "verdict_stated": has_verdict}
    add(8, "cross-language improvement 的 X / V attribution 已明确", c8,
        "FULL_CORPUS_ABLATION.md §2")

    # 9 raw vs system contrastive separated
    def c9():
        d = load(os.path.join(VECDIR, "contrastive_system_vs_raw.json"))
        return bool(d and "raw_vector_contrastive_pass" in d
                    and "system_contrastive_pass" in d and d.get("n") == 10), {
            "raw": (d or {}).get("raw_vector_contrastive_pass"),
            "system": (d or {}).get("system_contrastive_pass"),
            "n": (d or {}).get("n")}
    add(9, "Raw Vector Contrastive 与 System Contrastive 分开报告", c9,
        "contrastive_system_vs_raw.json · ROUTED_RETRIEVAL_EVALUATION.md")

    # 10 semantic guard reduces confusion (or at least does not harm)
    def c10():
        d = load(os.path.join(VECDIR, "contrastive_system_vs_raw.json"))
        if not d:
            return False, {}
        raw = d["raw_vector_contrastive_pass"]
        sysp = d["system_contrastive_pass"]
        return sysp >= raw, {"raw": raw, "system": sysp, "delta": sysp - raw,
                             "claim": ("reduces_confusion" if sysp > raw
                                       else "no_harm_but_no_gain")}
    add(10, "Semantic Guard 能降低理论概念混淆（至少不造成损害）", c10,
        "contrastive_system_vs_raw.json（system ≥ raw）")

    # 11 exact/source not degraded
    def c11():
        d = load(os.path.join(VECDIR, "full_corpus_results.json"))
        if not d:
            return False, {"error": "缺 full_corpus_results.json"}
        m = list(d["models"].values())[0]
        out = {}
        ok = True
        for cls in ("exact_quotation", "exact_source_lookup"):
            z = (m.get("by_class") or {}).get(cls)
            if not z:
                out[cls] = {"status": "no_samples_in_gold",
                            "note": "该 query class 在本 gold 集里没有样本"}
                continue
            routed = z.get("ROUTED", {}).get("hit@20")
            forced = z.get("E+L+V+X", {}).get("hit@20")
            out[cls] = {"n": z["n"], "ROUTED": routed, "forced_E_L_V_X": forced,
                        "degraded": (routed is not None and forced is not None
                                     and routed < forced - 1e-9)}
            if routed is not None and forced is not None and routed < forced - 1e-9:
                ok = False
        # 结构性证据：这些 class 的 route 本身就把向量关掉了（候选上限 0）
        import query_routing_policy as rp
        out["structural_guarantee"] = {
            r: {"vector_enabled": rp.ROUTING_TABLE[r]["vector_enabled"],
                "vector_candidate_limit": rp.ROUTING_TABLE[r]["vector_candidate_limit"]}
            for r in ("EXACT_QUOTATION", "EXACT_SOURCE_LOOKUP")}
        if not all(v["vector_enabled"] is False and v["vector_candidate_limit"] == 0
                   for v in out["structural_guarantee"].values()):
            ok = False
        return ok, out
    add(11, "exact/source retrieval 不因 vector 强制介入而明显退化", c11,
        "full_corpus_results.json.by_class（ROUTED 关闭向量后不得低于强制 E+L+V+X）")

    # 12 ROUTED vs static real numbers
    def c12():
        d = load(os.path.join(VECDIR, "full_corpus_results.json"))
        if not d:
            return False, {}
        m = list(d["models"].values())[0]["aggregate"]
        r, s, l = m["ROUTED"]["hit@20"], m["E+L+V+X"]["hit@20"], m["L"]["hit@20"]
        return all(x is not None for x in (r, s, l)), {
            "ROUTED": r, "STATIC_E_L_V_X": s, "L": l,
            "delta_vs_static": None if None in (r, s) else r - s,
            "delta_vs_L": None if None in (r, l) else r - l}
    add(12, "ROUTED retrieval 与静态 pipeline 有真实对比数字", c12,
        "FULL_CORPUS_ABLATION.md §0")

    # 13 answerable/unanswerable isolated
    def c13():
        d = load(os.path.join(VECDIR, "full_corpus_results.json"))
        h = load(os.path.join(IDX, "HARD_GATES.json"))
        ok = bool(d and d.get("answerable_n") == 40 and d.get("unanswerable_n") == 5)
        gate = (h or {}).get("gates", {}).get(
            "answerable_unanswerable_metric_contamination")
        return ok and gate == 0, {"answerable_n": (d or {}).get("answerable_n"),
                                  "unanswerable_n": (d or {}).get("unanswerable_n"),
                                  "contamination_gate": gate}
    add(13, "answerable / unanswerable 指标继续隔离", c13,
        "full_corpus_results.json · HARD_GATES.json")

    # 14 source linking candidate only
    def c14():
        r = load(os.path.join(VECDIR, "source_linking_fullcorpus.json"))
        rows = jl(os.path.join(VAULT, "concept_source_link_candidates_fullcorpus.jsonl"))
        ok = bool(r and rows) and all(x["review_status"] == "candidate"
                                      and x["canonical"] is False for x in rows)
        return ok and r["hard_gates"]["automatic_source_link_canonicalization"] == 0, {
            "candidates": len(rows),
            "canonicalization_gate": (r or {}).get("hard_gates", {}).get(
                "automatic_source_link_canonicalization")}
    add(14, "source linking 自动结果仍只为 candidate", c14,
        "concept_source_link_candidates_fullcorpus.jsonl · SOURCE_LINKING_FULL_CORPUS_REPORT.md")

    # 15-19 hard gates
    HG = {
        15: ("fabricated_passage_ids", "fabricated passage IDs = 0"),
        16: ("broken_passage_references", "broken references = 0"),
        17: ("canonical_source_mutation", "source mutation = 0"),
        18: ("silent_provenance_upgrade", "silent provenance upgrade = 0"),
        19: ("vector_index_corpus_hash_mismatch", "vector/corpus hash mismatch = 0"),
    }
    for n, (key, req) in HG.items():
        def mk(k):
            def f():
                h = load(os.path.join(IDX, "HARD_GATES.json"))
                v = (h or {}).get("gates", {}).get(k)
                return v == 0, {"gate": k, "value": v}
            return f
        add(n, req, mk(key), "HARD_GATES_REPORT.md（17 项现算）")

    # 20 validator 0 error
    def c20():
        p = os.path.join(REPORTS, "validation-report.json")
        r = load(p)
        if not r:
            return False, {}
        # ⚠️ 校验报告把计数放在 `summary` 里，不是在顶层。
        #    第一版读顶层 `errors` → 读到 null → 静默判 False。
        s = r.get("summary") or {}
        errs = s.get("errors")
        rel_errs = s.get("relation_errors", 0)
        return (errs == 0 and rel_errs == 0), {
            "summary.errors": errs, "summary.relation_errors": rel_errs,
            "summary.warnings": s.get("warnings"),
            "files_scanned": s.get("files_scanned"),
            "broken_wikilinks": s.get("broken_wikilinks"),
            "duplicate_ids": s.get("duplicate_ids"),
            "filename_id_mismatches": s.get("filename_id_mismatches"),
            "field_path_note": "计数在 summary 里（第一版读顶层 errors 读到 null）"}
    add(20, "validator 0 error", c20, "_index/Reports/validation-report.json")

    # 21 tests all green
    def c21():
        t = load(os.path.join(IDX, "TEST_RUN.json"))
        if not t:
            return False, {"note": "缺 TEST_RUN.json —— 需跑一次 ./_scripts/run_all_tests.sh 记录结果"}
        return t.get("exit_code") == 0 and t.get("failed_suites") == [], {
            "exit_code": t.get("exit_code"), "suites": t.get("suites"),
            "failed_suites": t.get("failed_suites"), "recorded_at": t.get("recorded_at")}
    add(21, "tests 全绿", c21, "_data/index/TEST_RUN.json")

    # 22 full deterministic suite passed
    def c22():
        t = load(os.path.join(IDX, "DETERMINISTIC_SUITE_RUN.json"))
        if not t:
            return False, {"note": "缺 DETERMINISTIC_SUITE_RUN.json —— 需完整跑一次 test_phase2_deterministic"}
        return (t.get("exit_code") == 0 and t.get("complete") is True), {
            "exit_code": t.get("exit_code"), "complete": t.get("complete"),
            "ran_tests": t.get("ran_tests"), "seconds": t.get("seconds")}
    add(22, "最终一次完整 deterministic suite 通过", c22,
        "_data/index/DETERMINISTIC_SUITE_RUN.json")
    return C


def run():
    checks = build_checks()
    rows = []
    for c in checks:
        try:
            ok, ev = c["fn"]()
        except Exception as e:
            ok, ev = False, {"error": "%s: %s" % (type(e).__name__, e)}
        rows.append({"n": c["n"], "requirement": c["requirement"],
                     "evidence": c["evidence"], "passed": bool(ok), "detail": ev})
    failed = [r["n"] for r in rows if not r["passed"]]
    doc = {
        "schema_version": "phase3-completion-gate/v1",
        "gate_count": len(rows),
        "passed_count": sum(1 for r in rows if r["passed"]),
        "failed": failed,
        "closable": not failed,
        "declaration_allowed": "PHASE 3 RETRIEVAL LAYER = COMPLETE" if not failed else None,
        "checks": rows,
        "philosophy": ("§24：不要求 Vector 在所有 query 上都优于 lexical；"
                       "要求的是**最终 Retrieval System 成立**。"
                       "raw embedding contrastive 不要求 10/10。"),
    }
    json.dump(doc, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_findings(doc)
    print("[gate] %d/%d passed | closable=%s" % (
        doc["passed_count"], doc["gate_count"], doc["closable"]))
    if failed:
        print("[gate] 未通过：%s" % failed)
    return doc


def write_findings(doc):
    L = []
    A = L.append
    A("# PHASE3C_FINDINGS.md — Phase 3C Full-Corpus Retrieval Validation & Routing\n")
    A("> 生成：`_scripts/_tools/check_phase3_completion.py`　·　"
      "门禁数据：`_data/index/PHASE3_COMPLETION_GATE.json`\n")
    A("## 0. §24 完成门禁：%d / %d\n" % (doc["passed_count"], doc["gate_count"]))
    A("| 项 | 值 |")
    A("|---|---:|")
    A("| 通过 | **%d** |" % doc["passed_count"])
    A("| 未通过 | **%d** |" % len(doc["failed"]))
    A("| `closable` | **%s** |" % doc["closable"])
    A("| 允许的声明 | %s |" % (("`%s`" % doc["declaration_allowed"])
                               if doc["declaration_allowed"] else "**无**（门禁未全过）"))
    A("")
    A("**§24 的立场**：%s\n" % doc["philosophy"])
    A("## 1. 逐条\n")
    A("| # | 要求 | 判定 | 证据 | 详情 |")
    A("|---|---|---|---|---|")
    for r in doc["checks"]:
        A("| %d | %s | %s | %s | `%s` |" % (
            r["n"], r["requirement"], "✅" if r["passed"] else "❌",
            r["evidence"], json.dumps(r["detail"], ensure_ascii=False)[:200]))
    A("")
    A("## 2. 关键数字（来自各专项报告）\n")
    fc = load(os.path.join(VECDIR, "full_corpus_results.json"))
    abl = load(os.path.join(VECDIR, "full_corpus_ablation.json"))
    con = load(os.path.join(VECDIR, "contrastive_system_vs_raw.json"))
    if fc:
        m = list(fc["models"].values())[0]
        a = m["aggregate"]
        A("| 配置 | hit@20 | MRR@10 | nDCG@10 |")
        A("|---|---:|---:|---:|")
        for c in ("L", "V", "E+L", "E+L+V", "E+L+X", "E+L+V+X", "E+L+V+X+M", "ROUTED"):
            x = a.get(c)
            if x:
                A("| `%s` | %.4f | %.4f | %.4f |" % (
                    c, x["hit@20"] or 0, x["mrr@10"] or 0, x["ndcg@10"] or 0))
    if con:
        A("")
        A("| 反例指标 | 值 |")
        A("|---|---:|")
        A("| Raw Vector Contrastive Pass | %s / %s |" % (
            con["raw_vector_contrastive_pass"], con["n"]))
        A("| System Contrastive Pass | %s / %s |" % (
            con["system_contrastive_pass"], con["n"]))
    A("")
    A("## 3. 不进入 Phase 4\n")
    A("本阶段完成后**停止**。Phase 3 可关闭与否由上面的 `closable` 决定；"
      "无论结果如何，**都不进入 Phase 4**。")
    with open(FINDINGS, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % FINDINGS)


def cmd_verify():
    if not os.path.isfile(OUT_JSON):
        return {"status": "FAIL", "problems": ["缺 PHASE3_COMPLETION_GATE.json"]}
    d = load(OUT_JSON)
    problems = []
    if d["closable"] and d["declaration_allowed"] != "PHASE 3 RETRIEVAL LAYER = COMPLETE":
        problems.append("closable=true 但声明文本不对")
    if not d["closable"] and d["declaration_allowed"] is not None:
        problems.append("门禁未过却给出了声明文本 —— §24 被绕过")
    if len(d["checks"]) != 22:
        problems.append("门禁条目数 %d != 22" % len(d["checks"]))
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "closable": d["closable"], "passed_count": d["passed_count"],
            "failed": d["failed"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.run:
        d = run()
        return 0 if d["closable"] else 1
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
