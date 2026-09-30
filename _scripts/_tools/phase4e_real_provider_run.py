#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_real_provider_run.py — Phase 4E §21–§31：真实 provider 14 题回归。

它做的是**产品路径**：`scholarly_api.core.research()`（= MCP `lacan.research` 的同一个入口），
`provider="llm"`，逐题跑冻结任务集里的 14 题，并：

* 记录 §16 要求的身份（request / contract / evidence / synthesis payload / final answer hash）；
* 记录 §30 的 claim 指标（generated / validated / repaired / rejected）；
* 对**新 run 的结果**重算 Gate 20 与 Gate 21（同一冻结函数，Δ=0 才算通过）；
* 做 §28 的弃权控制检查（rt-J01/J02/J03：不得有实质补答）；
* 做 §42 的 D2 结构对照（诊断用，不做逐字比对）；
* §48 封存（seal.json：manifest/metrics/results/claims hash + provider_success）。

纪律：
* **只对 provider transient 错误**重试（timeout / rate limit / connection），≤2 次并全部记账；
  答案质量类失败（validation/citation/abstention）**绝不**重试到过关（§46/§47）。
* 不覆盖 D2（`4c1d2_llm_20260924T190203Z_50de1609`）；本 run 是新目录。
* 不落盘任何凭据；跑完自查（§68）。

用法：
    python3 _scripts/_tools/phase4e_real_provider_run.py --limit 1     # 冒烟
    python3 _scripts/_tools/phase4e_real_provider_run.py               # 14/14
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
for p in (TOOLS, os.path.join(TOOLS, "lacan_mcp"), VAULT):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_integrity as ei                       # noqa: E402
from scholarly_api import core                    # noqa: E402

OUT_ROOT = os.path.join(VAULT, "_data", "phase4e")
FROZEN_TASKS = os.path.join(VAULT, "_data", "eval", "gold_v2", "research_tasks_v2.jsonl")
D2_RUN = os.path.join(VAULT, "_data", "eval", "runs",
                      "4c1d2_llm_20260924T190203Z_50de1609")
MARKER = "CCR-0001_REMEDIATION_VERIFICATION"
PHASE = "Phase 4E"
TRANSIENT = ("PROVIDER_TIMEOUT", "PROVIDER_RATE_LIMITED", "PROVIDER_CONNECTION_FAILED")
MAX_RETRIES = 2

# (task_id, 冻结 task_type, 产品 mode, 保真度)
TASK_PLAN = [
    ("rt-A01", "concept_definition", "concept_definition", "exact"),
    ("rt-D01", "seminar_specific", "seminar_specific", "exact"),
    ("rt-B01", "concept_relation", "concept_relation", "exact"),
    ("rt-E01", "case_research", "case_research", "exact"),
    ("rt-I02", "translation_terminology", "translation_terminology", "exact"),
    ("rt-C03", "diachronic_development", "diachronic", "exact"),
    ("rt-F01", "freud_to_lacan", "freud_to_lacan", "exact"),
    ("rt-G02", "philosophy_to_lacan", "philosophy_to_lacan", "exact"),
    ("rt-J02", "insufficient_unanswerable", "scholarly", "product_mode_surrogate"),
    ("rt-J03", "insufficient_unanswerable", "scholarly", "product_mode_surrogate"),
    ("rt-H02", "topology_matheme", "topology_matheme", "exact"),
    ("rt-I03", "translation_terminology", "translation_terminology", "exact"),
    ("rt-J01", "insufficient_unanswerable", "scholarly", "product_mode_surrogate"),
    ("rt-G01", "philosophy_to_lacan", "philosophy_to_lacan", "exact"),
]


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha_obj(obj):
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_tasks():
    out = {}
    with open(FROZEN_TASKS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                out[d["task_id"]] = d
    return out


def d2_rows():
    p = os.path.join(D2_RUN, "results.json")
    if not os.path.isfile(p):
        return {}
    doc = json.load(open(p, encoding="utf-8"))
    return {r.get("task_id"): r for r in doc.get("rows") or []}


def api_key():
    return os.environ.get("DSH_SYNTHESIS_API_KEY") or ""


def secret_findings(blobs):
    """§68：工件里不得出现凭据（含常见形态）。"""
    key = api_key()
    bad = []
    for name, text in blobs.items():
        if key and len(key) >= 8 and key in text:
            bad.append("%s: 出现完整 API key" % name)
        for m in re.finditer(r"sk-[A-Za-z0-9_\-]{12,}", text):
            bad.append("%s: 出现 sk- 形态凭据（%s…）" % (name, m.group(0)[:6]))
        if re.search(r"(?i)authorization\s*[:=]\s*bearer\s+\S{12,}", text):
            bad.append("%s: 出现 Authorization: Bearer" % name)
    return bad


def run_one(task_id, frozen_type, mode, fidelity, task, questions_log):
    """跑一题（产品路径 + 只读审计接收器）。返回 row。"""
    sink = {}
    attempts, retries = 0, []
    t0 = time.time()
    res = None
    while True:
        attempts += 1
        sink = {}
        res = core.research(task["question"],
                            {"provider": "llm", "mode": mode, "judge": True,
                             "language": task.get("language") or "any",
                             "task_id": task_id, "_audit_sink": sink})
        diag = ((res or {}).get("detail") or {}).get("provider_diagnostic")
        if not res.get("error_code") or diag not in TRANSIENT or \
                len(retries) >= MAX_RETRIES:
            break
        retries.append({"attempt": attempts, "diagnostic": diag})
        questions_log.append("    transient %s → retry %d/%d"
                             % (diag, len(retries), MAX_RETRIES))
        time.sleep(5)
    latency = time.time() - t0

    contract = sink.get("input_contract") or {}
    pipeline = sink.get("pipeline") or {}
    answer = pipeline.get("answer") or {}
    synth = sink.get("synthesis") or {}
    row = {
        "task_id": task_id,
        "question": task["question"],
        "task_type": frozen_type,                    # ★ 冻结 task_type（§22）
        "product_mode": mode,
        "task_type_fidelity": fidelity,
        "mode": "llm",
        "marker": MARKER,
        "human_validated": False,
        "provider": synth.get("provider"),
        "model": synth.get("model"),
        "provider_attempts": attempts,
        "provider_retries": len(retries),
        "retry_log": retries,
        "synthesis_latency_s": round(latency, 2),
        "synthesis_ok": bool(synth.get("ok")),
        "input_contract": contract,
        "contract_status": contract.get("status"),
        "answer_permission": answer.get("answer_permission")
                             or contract.get("answer_permission"),
        "answer_state": answer.get("answer_state") or "UNKNOWN",
        "answer": answer,
        "entailment": pipeline.get("entailment") or {},
        "validated_claims": pipeline.get("validated_claims") or [],
        "generated_claims": pipeline.get("generated_claims"),
        "prevalidation_dropped": pipeline.get("prevalidation_dropped") or [],
        "quote_fixes": pipeline.get("quote_fixes") or [],
        "c_dropped": pipeline.get("c_dropped") or [],
        "c_validation_failures": len((pipeline.get("c_validation") or {})
                                     .get("violations") or []),
        "failure_mode": None if not res.get("error_code") else res.get("error_code"),
        "failure_detail": (res.get("message") if res.get("error_code") else None),
        "error_detail": (res.get("detail") if res.get("error_code") else None),
        # §16 identities
        "identities": {
            "task_id": task_id,
            "input_contract_hash": sink.get("input_contract_hash"),
            "evidence_ids": sink.get("evidence_ids"),
            "evidence_packet_hash": sha_obj(sink.get("evidence_ids")),
            "synthesis_payload_hash": synth.get("raw_payload_hash"),
            "synthesis_prompt_identity": "synthesis_adapters.SYSTEM_CONTRACT",
            "raw_completion_bytes_retained": bool(synth.get("raw_completion_bytes_retained")),
            "final_answer_hash": sink.get("final_answer_hash"),
            "judge_enabled": sink.get("judge_enabled"),
            "provider": synth.get("provider"),
            "model": synth.get("model"),
            "usage": synth.get("usage") or {},
        },
        "final_answer": sink.get("final_answer"),
        "markdown_present": bool(pipeline.get("markdown")),
    }
    return row


def abstention_check(row):
    """§28：弃权题不得出现实质补答 / 外部知识泄漏。

    判据只用**冻结契约自己的要求**（`abstention_requirements.must_include`）与
    冻结 Gate 的实质 claim 定义，不用 harness 自己发明的字段期望：

    * ABSTAINED ⇒ 最终答案里没有 `D_SUBSTANTIVE` claim（泄漏）；
    * ABSTAINED ⇒ `abstention` 块非空，且语义字段齐全
      （reason codes / missing_information / available_partial_information /
        required sources —— 两套命名都接受，命名偏差另记为 shape 观察，不算泄漏）；
    * ABSTAINED ⇒ `answer_permission == "ABSTAIN"`。
    """
    if row["task_type"] != "insufficient_unanswerable":
        return []
    out = []
    final = row.get("final_answer") or {}
    answer = row.get("answer") or {}
    claims = final.get("validated_claims") or answer.get("claims") or []
    substantive = [c for c in claims if c.get("claim_type") in ei.D_SUBSTANTIVE]
    if substantive:
        out.append({"code": "ABSTENTION_SUBSTANTIVE_LEAKAGE",
                    "detail": "%s 弃权题出现 %d 条实质 claim"
                              % (row["task_id"], len(substantive))})
    if row["answer_state"] != "ABSTAINED":
        out.append({"code": "ABSTENTION_STATE_UNEXPECTED",
                    "detail": "%s state=%s（冻结类型要求弃权）"
                              % (row["task_id"], row["answer_state"])})
        return out
    ab = final.get("abstention") or answer.get("abstention") or {}
    if not ab:
        out.append({"code": "ABSTENTION_BLOCK_MISSING", "detail": row["task_id"]})
        return out
    semantic = {
        "reason_codes": bool(ab.get("abstention_reason_codes") or ab.get("categories")
                             or ab.get("category")),
        "missing_information": bool(ab.get("missing_information")),
        "available_partial_information": "available_partial_information" in ab,
        "required_sources": bool(ab.get("next_required_sources")
                                 or ab.get("required_sources")),
    }
    missing = [k for k, v in semantic.items() if not v]
    if missing:
        out.append({"code": "ABSTENTION_REQUIRED_FIELDS_MISSING",
                    "detail": "%s 缺 %s" % (row["task_id"], missing)})
    if row.get("answer_permission") not in ("ABSTAIN", "ABSTENTION", None):
        out.append({"code": "ABSTENTION_PERMISSION_UNEXPECTED",
                    "detail": "%s permission=%s" % (row["task_id"],
                                                    row.get("answer_permission"))})
    return out


def abstention_shape_notes(row, contract):
    """命名/shape 偏差只作**观察**记录（冻结 renderer 会原样接受 provider 的 abstention）。"""
    final = row.get("final_answer") or {}
    ab = final.get("abstention") or {}
    req = ((contract or {}).get("abstention_requirements") or {}).get("must_include") or []
    if not ab or not req:
        return []
    return [k for k in req if k not in ab]


def classify_difference(d2, new, gate21_new, gate21_d2):
    """§43：差异分类（诊断用）。只有 PIPELINE_REGRESSION 才算 remediation 失败。"""
    if gate21_new > gate21_d2:
        return "PIPELINE_REGRESSION"
    if not d2:
        return "NO_D2_BASELINE"
    c_d2 = {c.get("passage_id") for c in (d2.get("answer") or {}).get("citations") or []}
    c_new = {c.get("passage_id") for c in (new.get("answer") or {}).get("citations") or []}
    inter = len(c_d2 & c_new)
    union = len(c_d2 | c_new) or 1
    overlap = round(inter / union, 3)
    n_d2 = len(d2.get("validated_claims") or [])
    n_new = len(new.get("validated_claims") or [])
    same_state = d2.get("answer_state") == new.get("answer_state")
    if same_state and overlap >= 0.5:
        return "LLM_STOCHASTIC_VARIATION"
    if overlap < 0.5 and n_new <= max(1, n_d2):
        return "EVIDENCE_SELECTION_VARIATION"
    if n_new < n_d2:
        return "VALIDATOR_INDUCED_NARROWING"
    if not same_state:
        return "SYNTHESIS_VARIATION"
    return "MINOR_VARIATION"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E real-provider 14-task regression")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--out-root", default=OUT_ROOT)
    a = ap.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = a.run_id or "phase4e_real_llm_%s_%s" % (stamp, sha_obj(stamp)[:8])
    run_dir = os.path.join(a.out_root, run_id)
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
    log_path = os.path.join(run_dir, "logs", "run.log")

    def log(msg):
        line = "[%s] %s" % (utcnow(), msg)
        print(line, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    tasks = load_tasks()
    d2 = d2_rows()
    plan = TASK_PLAN[:a.limit] if a.limit else TASK_PLAN
    log("run_id=%s | provider=REAL | purpose=%s | tasks=%d" % (run_id, MARKER, len(plan)))

    # 真实凭据准备（与核心同一机制）；**不发探测性研究调用**（省 provider 配额）
    import run_synthesis_4c1d as rt
    import synthesis_adapters as sad
    if not rt.load_dsh_key():
        log("SKIPPED_PROVIDER_UNAVAILABLE：未配置凭据（DSH_SYNTHESIS_API_KEY / "
            "~/.dsh/.credentials.yaml）")
        return 3
    probe = sad.OpenAICompatibleProvider(timeout=10)
    if not probe.available:
        log("SKIPPED_PROVIDER_UNAVAILABLE：provider.available=False")
        return 3
    log("provider=%s model=%s base=%s" % (probe.name, probe.model, probe.base_url))

    rows = []
    t_start = time.time()
    for task_id, frozen_type, mode, fidelity in plan:
        t = tasks.get(task_id)
        if not t:
            log("!! 冻结任务缺失：%s" % task_id)
            rows.append({"task_id": task_id, "failure_mode": "FROZEN_TASK_MISSING",
                         "answer_state": "UNKNOWN", "validated_claims": []})
            continue
        log("→ %s（%s / mode=%s / %s）" % (task_id, frozen_type, mode, fidelity))
        row = run_one(task_id, frozen_type, mode, fidelity, t, [])
        row["abstention_findings"] = abstention_check(row)
        row["abstention_shape_notes"] = abstention_shape_notes(
            row, row.get("input_contract") or {})
        rows.append(row)
        log("  ← %s | claims=%s | citations=%s | %.0fs | attempts=%d"
            % (row["answer_state"],
               len(row.get("validated_claims") or []),
               len(((row.get("answer") or {}).get("citations")) or []),
               row["synthesis_latency_s"], row["provider_attempts"]))
        # 逐题增量落盘：即使后面中断，已跑完的题也不丢
        with open(os.path.join(run_dir, "task_results.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    doc = {"schema_version": "synthesis-run-results/v1", "phase": PHASE, "run_id": run_id,
           "mode": "llm", "marker": MARKER, "human_validated": False, "rows": rows}
    gate20 = [dict(f, task_id=r.get("task_id"))
              for r in rows for f in ei.synthesis_result_findings(r)]
    gate21_findings = ei.synthesis_entailment_findings(doc)
    gate21_violations = [f for f in gate21_findings if f.get("severity") == "VIOLATION"]
    by_code = {}
    for f in gate21_violations:
        by_code[f["code"]] = by_code.get(f["code"], 0) + 1

    # §30 metrics
    def total(key):
        return sum(int(r.get(key) or 0) for r in rows)
    metrics = {
        "tasks_n": len(rows),
        "provider_success": "%d/%d" % (len([r for r in rows if r.get("synthesis_ok")]),
                                       len(rows)),
        "generated_claims": total("generated_claims"),
        "prevalidation_dropped": sum(len(r.get("prevalidation_dropped") or [])
                                     for r in rows),
        "c_dropped": sum(len(r.get("c_dropped") or []) for r in rows),
        "repaired_claims": sum(len((r.get("entailment") or {}).get("repaired") or [])
                               for r in rows),
        "rejected_claims": sum(len((r.get("entailment") or {}).get("rejected") or [])
                               for r in rows),
        "validated_claims": sum(len(r.get("validated_claims") or []) for r in rows),
        "final_citations": sum(len((r.get("answer") or {}).get("citations") or [])
                               for r in rows),
        "answer_states": {s: len([r for r in rows if r.get("answer_state") == s])
                          for s in sorted({r.get("answer_state") for r in rows})},
        "provider_attempts_total": total("provider_attempts"),
        "provider_retries_total": total("provider_retries"),
        "synthesis_latency_s_total": round(sum(r.get("synthesis_latency_s") or 0
                                               for r in rows), 1),
        "gate20_violations": len(gate20),
        "gate21_violations": len(gate21_violations),
        "gate21_by_code": by_code,
        "abstention_findings": [f for r in rows
                                for f in (r.get("abstention_findings") or [])],
        "abstention_shape_notes": {r["task_id"]: r.get("abstention_shape_notes")
                                   for r in rows
                                   if r.get("abstention_shape_notes")},
    }

    # §42 D2 结构对照（诊断）
    comparison = []
    for r in rows:
        b = d2.get(r["task_id"]) or {}
        cb = {c.get("passage_id") for c in (b.get("answer") or {}).get("citations") or []}
        cn = {c.get("passage_id") for c in (r.get("answer") or {}).get("citations") or []}
        comparison.append({
            "task_id": r["task_id"],
            "d2_answer_state": b.get("answer_state"), "p4e_answer_state": r["answer_state"],
            "d2_task_type": b.get("task_type"), "p4e_task_type": r.get("task_type"),
            "d2_validated_claims": len(b.get("validated_claims") or []),
            "p4e_validated_claims": len(r.get("validated_claims") or []),
            "d2_citations": len(cb), "p4e_citations": len(cn),
            "citation_overlap_jaccard": round(len(cb & cn) / (len(cb | cn) or 1), 3),
            "d2_source_layers": sorted({c.get("source_layer")
                                        for c in (b.get("answer") or {}).get("citations")
                                        or []}),
            "p4e_source_layers": sorted({c.get("source_layer") for c in
                                         ((r.get("final_answer") or {}).get("citations")
                                          or [])} - {None}),
            "p4e_final_citations": len((r.get("final_answer") or {}).get("citations") or []),
            "p4e_provenance_status": sorted({c.get("provenance_status") for c in
                                             ((r.get("final_answer") or {}).get("citations")
                                              or [])} - {None}),
            "d2_abstained": b.get("answer_state") == "ABSTAINED",
            "p4e_abstained": r["answer_state"] == "ABSTAINED",
            "classification": classify_difference(b, r, 0, 0),
        })

    gate_results = {
        "schema_version": "phase4e-gate-results/v1", "run_id": run_id,
        "recomputed_on_this_run": {
            "gate20": {"violations": len(gate20),
                       "findings": [dict(f, task_id=None) for f in gate20][:50]},
            "gate21": {"violations": len(gate21_violations),
                       "by_code": by_code,
                       "findings": gate21_violations[:50]},
        },
        "not_recomputed_on_this_run": {
            "gate13": "human review 记录校验（本次 run 不含人工评审记录）",
            "gate19": "trace 完整性（产品路径 provider=llm 不产出 research-trace；"
                      "改由冻结审计 build_evaluation_integrity_audit.py --check 复算）",
        },
    }

    manifest = {
        "schema_version": "synthesis-run-manifest/v1", "run_id": run_id, "phase": PHASE,
        "mode": "llm", "marker": MARKER, "purpose": MARKER,
        "created_at": utcnow(), "seconds": round(time.time() - t_start, 1),
        "git_head": os.popen("git -C %s rev-parse HEAD" % VAULT).read().strip(),
        "entry_point": "scholarly_api.core.research（= MCP lacan.research 同一入口）",
        "provider": "openai_compatible", "model": os.environ.get("DSH_SYNTHESIS_MODEL"),
        "temperature": 0.0, "judge_enabled": True,
        "core_freeze_hash": sha_file(os.path.join(VAULT, "_data", "core_freeze",
                                                  "scholarly_core_freeze_v1.json")),
        "frozen_tasks": [{"task_id": t, "frozen_task_type": ft, "product_mode": m,
                          "fidelity": f} for t, ft, m, f in TASK_PLAN],
        "human_validated": False, "immutable": True,
        "note": ("CCR-0001 remediation verification：真实 provider 经修复后的 "
                 "provider→adapter→boundary wiring 执行冻结任务集；"
                 "不覆盖 4C.1-D2 run。"),
    }

    results_path = os.path.join(run_dir, "results.json")
    metrics_path = os.path.join(run_dir, "metrics.json")
    manifest_path = os.path.join(run_dir, "run_manifest.json")
    gate_path = os.path.join(run_dir, "gate_results.json")
    cmp_path = os.path.join(run_dir, "d2_comparison.json")
    for p, d in ((results_path, doc), (metrics_path, metrics), (manifest_path, manifest),
                 (gate_path, gate_results), (cmp_path, {"run_id": run_id,
                                                        "note": "诊断用，不做逐字比对",
                                                        "rows": comparison})):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
            f.write("\n")

    blobs = {os.path.basename(p): open(p, encoding="utf-8").read()
             for p in (results_path, metrics_path, manifest_path, gate_path, cmp_path,
                       os.path.join(run_dir, "task_results.jsonl"))}
    secrets = secret_findings(blobs)

    seal = {
        "schema_version": "run-seal/v1", "run_id": run_id, "phase": PHASE, "marker": MARKER,
        "provider_success": metrics["provider_success"],
        "tasks_attempted": len(rows), "tasks_expected": len(plan),
        "gate20_violations": len(gate20), "gate21_violations": len(gate21_violations),
        "abstention_findings": len(metrics["abstention_findings"]),
        "manifest_hash": sha_file(manifest_path), "metrics_hash": sha_file(metrics_path),
        "results_hash": sha_file(results_path), "gate_results_hash": sha_file(gate_path),
        "d2_comparison_hash": sha_file(cmp_path),
        "task_results_hash": sha_file(os.path.join(run_dir, "task_results.jsonl")),
        "structured_claims_hash": sha_obj([{"task_id": r["task_id"],
                                            "claims": (r.get("answer") or {}).get("claims")}
                                           for r in rows]),
        "raw_provider_payloads_hash": sha_obj([r["identities"]["synthesis_payload_hash"]
                                               for r in rows]),
        "human_validated": False, "immutable": True, "sealed_at": utcnow(),
        "secret_leak_findings": secrets,
    }
    seal_path = os.path.join(run_dir, "seal.json")
    with open(seal_path, "w", encoding="utf-8") as f:
        json.dump(seal, f, ensure_ascii=False, indent=1)
        f.write("\n")

    log("sealed: %s" % seal_path)
    log("metrics: %s" % json.dumps(metrics, ensure_ascii=False))
    log("secrets: %s" % (secrets or "none"))
    print("run_id: %s" % run_id)
    print("artifacts: %s" % os.path.relpath(run_dir, VAULT))
    ok = (metrics["gate20_violations"] == 0 and metrics["gate21_violations"] == 0
          and not secrets and len(rows) == len(plan))
    print("verdict: %s" % ("PASS" if ok else "ATTENTION"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
