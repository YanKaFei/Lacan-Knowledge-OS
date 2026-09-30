#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_synthesis_4c1c.py — Phase 4C.1-C §27/§28/§29：**不可变 run** + synthesis diagnostic

Run Immutability（§27，B3 事故的教训）
────────────────────────────────────
每次 evaluation / synthesis run 都写进**独立、带时间戳的目录**：

    _data/eval/runs/4c1c_<YYYYmmddTHHMMSSZ>_<8hex>/

规则：
  * 目录已存在 → **拒绝写入**（`SystemExit`），没有 `--force-overwrite`；
  * `--new-run` 只是**新建**一个 run（换新的 id），不是覆盖旧的；
  * run manifest 钉住：run_id / phase / created_at / git HEAD / 引擎哈希 / 任务清单。

本脚本对 **14 个 human-reviewed 任务** 重新生成 synthesis candidate，并标记：

    marker = DIAGNOSTIC
    human_validated = false
    NOT_HUMAN_VALIDATED

产物：
  * `_data/eval/runs/<run_id>/run_manifest.json`
  * `_data/eval/runs/<run_id>/synthesis_results.json`
  * `_data/eval/runs/<run_id>/metrics.json`
  * `_data/eval/research_synthesis_results.4c1c.json`（聚合指针 + 逐题摘要）

用法：
    python3 run_synthesis_4c1c.py [--all] [--adapter mock|llm] [--run-id ID] [--new-run]
                                  [--quiet]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
RUNS_DIR = os.path.join(EVAL, "runs")
AGG = os.path.join(EVAL, "research_synthesis_results.4c1c.json")
PHASE = "4C.1-C"
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_answer as ans               # noqa: E402
import synthesis_contract as sc             # noqa: E402
import synthesis_claims as scl              # noqa: E402
import synthesis_render as sr               # noqa: E402
import synthesis_adapters as sad            # noqa: E402
import eval_integrity as ei                 # noqa: E402

ENGINE_FILES = ("synthesis_contract.py", "synthesis_claims.py", "synthesis_render.py",
                "synthesis_adapters.py", "research_execution.py", "research_contract.py",
                "research_answer.py")


# ── run immutability（§27）
def new_run_dir(phase="4c1c", run_id=None, base=RUNS_DIR):
    """新建 run 目录；**已存在即拒绝**（没有 force-overwrite）。"""
    rid = run_id or "%s_%s_%s" % (phase, time.strftime("%Y%m%dT%H%M%SZ"),
                                  uuid.uuid4().hex[:8])
    d = os.path.join(base, rid)
    if os.path.exists(d):
        raise SystemExit("拒绝覆盖：run 目录已存在 %s\n"
                         "（如需新一轮请用 --new-run 生成新的 run id；"
                         "本工具**不提供** force-overwrite）" % d)
    os.makedirs(d, exist_ok=False)
    return rid, d


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def engine_hashes():
    out = {}
    for fn in ENGINE_FILES:
        p = os.path.join(HERE, fn)
        if os.path.isfile(p):
            out[fn] = _sha(p)
    return out


def git_head():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=VAULT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return None


# ── 任务
def reviewed_tasks():
    ids = [json.loads(l)["task_id"]
           for l in open(os.path.join(EVAL, "research_human_review.jsonl"),
                         encoding="utf-8") if l.strip()]
    return ids


def all_tasks():
    return [json.loads(l)["task_id"]
            for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"),
                          encoding="utf-8") if l.strip()]


def task_defs(ids):
    d = {json.loads(l)["task_id"]: json.loads(l)
         for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"),
                       encoding="utf-8") if l.strip()}
    return [d[i] for i in ids if i in d]


def public_view(t):
    return {k: t[k] for k in ("task_id", "question", "language", "task_type",
                              "required_capabilities", "split")}


# ── metrics（§29）
def compute_metrics(rows):
    def _n(pred, seq):
        return len([x for x in seq if pred(x)])

    claims = [c for r in rows for c in (r.get("claims") or [])]
    groups = [g for r in rows for g in ((r.get("answer") or {}).get("citations") or [])]
    passages = [p for g in groups for p in (g.get("passages") or [])]
    quotes = [c.get("quotation") for c in claims if c.get("quotation")]
    claim_viol = [v for r in rows
                  for v in ((r.get("validation") or {}).get("claim_violations") or [])]
    ans_viol = [v for r in rows
                for v in ((r.get("validation") or {}).get("answer_violations") or [])]
    allowed = [r for r in rows if r.get("synthesis_allowed")]
    return {
        "tasks_n": len(rows),
        "synthesis_allowed_n": len(allowed),
        "full_synthesis_n": _n(lambda r: r.get("answer_permission") == "FULL_SYNTHESIS",
                               rows),
        "qualified_synthesis_n": _n(
            lambda r: r.get("answer_permission") == "QUALIFIED_SYNTHESIS", rows),
        "abstention_n": _n(lambda r: r.get("answer_permission") == "ABSTAIN", rows),
        "blocked_n": _n(lambda r: r.get("answer_permission") == "BLOCKED", rows),
        "synthesis_failed_n": _n(lambda r: r.get("failure_mode"), rows),
        "claims_total": len(claims),
        "claims_with_evidence": _n(lambda c: c.get("evidence_ids"), claims),
        # §17/§29 的硬目标口径：**substantive** claim 没有 evidence = 违规。
        # `CORPUS_ABSENCE` / `LIMITATION` 本来就不该有 evidence（它们由 corpus_scan_ref 支撑），
        # 单独记账，不得混进 hard target。
        "substantive_claims_n": _n(
            lambda c: c.get("claim_type") in scl.SUBSTANTIVE_CLAIM_TYPES, claims),
        "claims_without_evidence": _n(
            lambda c: c.get("claim_type") in scl.SUBSTANTIVE_CLAIM_TYPES
            and not c.get("evidence_ids"), claims),
        "absence_or_limitation_claims": _n(
            lambda c: c.get("claim_type") in scl.ABSENCE_CLAIM_TYPES, claims),
        "absence_claims_with_corpus_scan_ref": _n(
            lambda c: c.get("claim_type") in scl.ABSENCE_CLAIM_TYPES
            and c.get("corpus_scan_ref"), claims),
        "eligible_citations": _n(
            lambda p: p.get("citation_eligibility") == "ELIGIBLE", passages),
        "qualified_citations": _n(
            lambda p: p.get("citation_eligibility") == "QUALIFIED", passages),
        "ineligible_citations_used": _n(
            lambda p: p.get("citation_eligibility") == "INELIGIBLE", passages),
        "direct_quotes_total": len(quotes),
        "quotes_with_exact_span": _n(
            lambda q: q.get("kind") == "CORPUS_QUOTE" and q.get("exact_span"), quotes),
        "quotes_paraphrase": _n(lambda q: q.get("kind") == "PARAPHRASE", quotes),
        "quotes_model_translation": _n(
            lambda q: q.get("kind") == "MODEL_TRANSLATION", quotes),
        "source_role_violations": _n(lambda v: v.get("code") == "SOURCE_ROLE_VIOLATION",
                                     claim_viol + ans_viol),
        "abstention_contract_violations": _n(
            lambda v: v.get("code") == "ABSTENTION_CONTRACT_VIOLATION",
            claim_viol + ans_viol),
        "claim_violations": len(claim_viol),
        "answer_violations": len(ans_viol),
        "schema_valid_n": _n(lambda r: not (r.get("validation") or {}).get(
            "claim_violations") and not (r.get("validation") or {}).get(
            "answer_violations"), rows),
        "schema_valid_rate": (round(_n(lambda r: not (r.get("validation") or {}).get(
            "claim_violations") and not (r.get("validation") or {}).get(
            "answer_violations"), rows) / len(rows), 4) if rows else None),
        "trace_leaks_n": _n(lambda r: (r.get("validation") or {}).get("trace_leaks"),
                            rows),
        "hard_targets": {
            "claims_without_evidence": 0,
            "ineligible_citations_used": 0,
            "source_role_violations": 0,
            "abstention_contract_violations": 0,
        },
    }


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="对全部 27 任务跑（默认只跑 14 个 human-reviewed 任务）")
    ap.add_argument("--adapter", default="mock", choices=("mock", "llm"))
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--new-run", action="store_true",
                    help="显式新建一轮 run（生成新的 run id；**不是**覆盖旧的）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="只校验当前 run（不写任何文件）：manifest 钉住、指标可复算、Gate 20 = 0")
    a = ap.parse_args(argv)
    if a.check:
        return check_run()

    ids = all_tasks() if a.all else reviewed_tasks()
    tasks = task_defs(ids)
    rid = a.run_id
    if rid and os.path.exists(os.path.join(RUNS_DIR, rid)):
        if not a.new_run:
            raise SystemExit("拒绝覆盖：run 已存在 %s（要新建请加 --new-run）" % rid)
        rid = None
    rid, run_dir = new_run_dir(run_id=rid)
    adapter = sad.make_adapter(a.adapter)
    if a.adapter == "llm" and not getattr(adapter.provider, "available", False):
        raise SystemExit("provider 不可用（未配置 API key）：拒绝用 llm adapter 出结果")

    t0 = time.time()
    rows = []
    for t in tasks:
        run = ans.run_task(public_view(t), record_gaps=False)
        contract = sc.build_synthesis_input_contract(run)
        out = adapter.synthesize(t["question"], contract)
        row = {
            "task_id": t["task_id"], "question": t["question"],
            "task_type": t["task_type"], "language": t.get("language"),
            "evidence_state": contract.get("evidence_state"),
            "execution_state": contract.get("execution_state"),
            "answer_permission": contract.get("answer_permission"),
            "permission_reasons": contract.get("permission_reasons"),
            "contract_status": contract.get("status"),
            "synthesis_allowed": bool(out["ok"]),
            "template": (contract.get("synthesis_template") or {}).get("template"),
            "failure_mode": out.get("failure_mode"),
            "failure_detail": out.get("detail"),
            "abstained": contract.get("answer_permission") == "ABSTAIN",
            "blocked": contract.get("answer_permission") == "BLOCKED",
            "warnings": contract.get("warnings") or [],
            "marker": "DIAGNOSTIC", "phase": PHASE, "human_validated": False,
            "validation_note": "NOT_HUMAN_VALIDATED",
            "input_contract": contract,
            "claims": out.get("claims") or [],
            "answer": None, "markdown": None,
            "validation": {"claim_violations": [], "answer_violations": [],
                           "trace_leaks": []},
        }
        if out["ok"]:
            crep = scl.validate_claims(out["claims"], contract)
            answer = sr.build_answer(contract, out["claims"], out.get("sections") or {},
                                     out.get("abstention"))
            arep = sr.validate_answer(answer, contract)
            row["answer"] = answer
            row["markdown"] = sr.render_markdown(answer)
            row["validation"] = {
                "claim_violations": crep["violations"],
                "claim_failure_counts": crep["failure_counts"],
                "answer_violations": arep["violations"],
                "answer_failure_counts": arep["failure_counts"],
                "trace_leaks": sr.trace_leaks(answer),
                "claim_metrics": crep["metrics"],
                "answer_metrics": sr.answer_metrics(answer),
            }
        rows.append(row)
        if not a.quiet:
            print("  %-7s %-20s tpl=%-22s claims=%-2d %s" % (
                t["task_id"], row["answer_permission"], row["template"],
                len(row["claims"]),
                ("FAILED:" + str(row["failure_mode"])) if row["failure_mode"] else ""))

    metrics = compute_metrics(rows)
    manifest = {
        "schema_version": "synthesis-run-manifest/v1",
        "run_id": rid, "phase": PHASE, "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - t0, 1),
        "git_head": git_head(), "engine_hashes": engine_hashes(),
        "adapter": a.adapter,
        "provider": getattr(adapter, "provider", None).name
        if getattr(adapter, "provider", None) else None,
        "provider_deterministic": bool(getattr(getattr(adapter, "provider", None),
                                               "deterministic", True)),
        "llm_called": a.adapter == "llm",
        "task_set": "all" if a.all else "human_reviewed_14",
        "task_ids": [t["task_id"] for t in tasks],
        "marker": "DIAGNOSTIC", "human_validated": False,
        "immutable": True,
        "note": ("DIAGNOSTIC synthesis run：**不是** human-validated，"
                 "不得当作 scholarly evaluation；第二轮人工评审在 4C.1-E。"),
    }
    _write(os.path.join(run_dir, "run_manifest.json"), manifest)
    _write(os.path.join(run_dir, "synthesis_results.json"),
           {"schema_version": "synthesis-results/v1", "run_id": rid, "phase": PHASE,
            "marker": "DIAGNOSTIC", "human_validated": False, "rows": rows})
    _write(os.path.join(run_dir, "metrics.json"), metrics)
    agg = {
        "schema_version": "research-synthesis-results-4c1c/v1",
        "marker": "DIAGNOSTIC", "phase": PHASE, "human_validated": False,
        "run_id": rid, "run_dir": os.path.relpath(run_dir, VAULT),
        "created_at": manifest["created_at"], "seconds": manifest["seconds"],
        "adapter": a.adapter, "task_set": manifest["task_set"],
        "metrics": metrics,
        "rows": [{k: v for k, v in r.items()
                  if k not in ("input_contract", "answer", "markdown", "claims")}
                 for r in rows],
        "disclaimer": ("DIAGNOSTIC 4C.1-C：synthesis candidate 只用于验证 "
                       "Input Contract / Claim Schema / Citation Binding / Abstention / "
                       "Output Schema 闭环；**NOT_HUMAN_VALIDATED**。"),
    }
    _write(AGG, agg)
    if not a.quiet:
        print("\nsynthesis 指标（§29）：")
        for k in ("tasks_n", "synthesis_allowed_n", "full_synthesis_n",
                  "qualified_synthesis_n", "abstention_n", "blocked_n",
                  "claims_total", "claims_with_evidence", "claims_without_evidence",
                  "eligible_citations", "ineligible_citations_used",
                  "direct_quotes_total", "quotes_with_exact_span",
                  "source_role_violations", "abstention_contract_violations",
                  "schema_valid_rate"):
            print("  %-36s %s" % (k, metrics.get(k)))
        print("-> %s" % os.path.relpath(run_dir, VAULT))
        print("-> %s" % os.path.relpath(AGG, VAULT))
    return 0


def _write(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)



def check_run():
    """`--check`：校验聚合指针 → run 目录 → manifest 钉住 → 指标可复算 → Gate 20。

    **只读**：不写任何文件，也不新建 run。
    """
    if not os.path.isfile(AGG):
        print("FAIL 尚无 4C.1-C synthesis run（%s）" % os.path.relpath(AGG, VAULT))
        return 1
    agg = json.load(open(AGG, encoding="utf-8"))
    run_dir = os.path.join(VAULT, agg.get("run_dir") or "")
    man_p = os.path.join(run_dir, "run_manifest.json")
    res_p = os.path.join(run_dir, "synthesis_results.json")
    problems = []
    if not os.path.isfile(man_p) or not os.path.isfile(res_p):
        print("FAIL run 目录缺 manifest/results：%s" % run_dir)
        return 1
    man = json.load(open(man_p, encoding="utf-8"))
    res = json.load(open(res_p, encoding="utf-8"))
    if man.get("run_id") != agg.get("run_id"):
        problems.append("run_id 与 manifest 不一致")
    if man.get("phase") != PHASE:
        problems.append("phase=%s" % man.get("phase"))
    if not man.get("immutable") or man.get("human_validated"):
        problems.append("manifest 的 immutable/human_validated 标记不对")
    live = engine_hashes()
    for k, v in (man.get("engine_hashes") or {}).items():
        if live.get(k) != v:
            problems.append("engine hash 漂移：%s（manifest 钉住的 run 已被引擎改动失效）" % k)
    recomputed = compute_metrics(res.get("rows") or [])
    if json.dumps(recomputed, sort_keys=True) != json.dumps(agg.get("metrics") or {},
                                                            sort_keys=True):
        problems.append("metrics 与 rows 不可复算一致")
    findings = ei.synthesis_run_findings(res)
    if findings:
        problems.append("Gate 20 违规 %d 条：%s" % (len(findings),
                                                   findings[:2]))
    if problems:
        print("FAIL 4C.1-C run 校验未通过：")
        for p in problems:
            print("  - %s" % p)
        return 1
    print("4C.1-C run 校验通过：run_id=%s（%d 题；Gate 20 = 0；manifest 哈希一致）"
          % (agg.get("run_id"), len(res.get("rows") or [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
