#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_synthesis_4c1d.py — Phase 4C.1-D §30/§37/§38：不可变 run + 真实 LLM 诊断 + Gate 21

四种模式（互不覆盖，各自写进独立 run 目录）：

    --mode calibration   entailment 校准集（离线，确定性 + 可选 judge）
    --mode adversarial   §33/§34/§35 对抗测试（scripted provider，离线）
    --mode mock          MOCK_VALIDATION：用 C 的确定性 mock 走完整 D 流水线
    --mode llm           REAL_LLM_DIAGNOSTIC：真实 provider 生成 claims + 真实 judge

Run 目录（§37 不可变）：

    _data/eval/runs/4c1d_<mode>_<ts>_<8hex>/
        run_manifest.json      provider / model / temperature / prompt_hash /
                               input_hash / raw_output_hash / validated_output_hash /
                               validator_version / 成本 telemetry
        results.json           逐题（含 atoms / entailment / repair / reject / answer）
        metrics.json

聚合指针：`_data/eval/research_synthesis_results.4c1d.json`

Provider 未配置时：`llm` 模式 **拒绝运行**（`SKIPPED_PROVIDER_UNAVAILABLE`），
不是 PASS 也不是 FAIL；CI 只跑 calibration / adversarial / mock。
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
AGG = os.path.join(EVAL, "research_synthesis_results.4c1d.json")
PHASE = "4C.1-D"
VALIDATOR_VERSION = "entailment-validator/1"

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_answer as ans               # noqa: E402
import synthesis_contract as sc             # noqa: E402
import synthesis_claims as scl              # noqa: E402
import synthesis_render as sr               # noqa: E402
import synthesis_adapters as sad            # noqa: E402
import synthesis_entailment as se           # noqa: E402
import synthesis_validation as sv           # noqa: E402
import eval_integrity as ei                 # noqa: E402

ENGINE_FILES = ("synthesis_contract.py", "synthesis_claims.py", "synthesis_render.py",
                "synthesis_adapters.py", "synthesis_entailment.py",
                "synthesis_validation.py", "run_synthesis_4c1d.py",
                "research_execution.py", "research_contract.py", "research_answer.py")
CALIBRATION = os.path.join(EVAL, "claim_entailment_calibration_v1.jsonl")


def _sha_text(t):
    return hashlib.sha256(str(t).encode("utf-8")).hexdigest()


def _sha_file(p):
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
            out[fn] = _sha_file(p)
    return out


def git_head():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=VAULT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return None


def new_run_dir(mode, base=RUNS_DIR, run_id=None, prefix="4c1d"):
    rid = run_id or "%s_%s_%s_%s" % (prefix, mode, time.strftime("%Y%m%dT%H%M%SZ"),
                                     uuid.uuid4().hex[:8])
    d = os.path.join(base, rid)
    if os.path.exists(d):
        raise SystemExit("拒绝覆盖：run 目录已存在 %s\n"
                         "（新一轮请用 --new-run；本工具不提供 force-overwrite）" % d)
    os.makedirs(d, exist_ok=False)
    return rid, d


# ── 任务
def reviewed_tasks():
    return [json.loads(l)["task_id"]
            for l in open(os.path.join(EVAL, "research_human_review.jsonl"),
                          encoding="utf-8") if l.strip()]


def task_defs(ids):
    d = {json.loads(l)["task_id"]: json.loads(l)
         for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"),
                       encoding="utf-8") if l.strip()}
    return [d[i] for i in ids if i in d]


def public_view(t):
    return {k: t[k] for k in ("task_id", "question", "language", "task_type",
                              "required_capabilities", "split")}


# ── provider
def load_dsh_key():
    """从 DSH 凭据库取 DEEPSEEK_API_KEY（**不打印、不落盘**），仅注入本进程环境。

    只有在显式需要真实 provider 时调用；CI/单元测试不会走到这里。
    """
    if os.environ.get("DSH_SYNTHESIS_API_KEY"):
        return True
    import re
    p = os.path.expanduser("~/.dsh/.credentials.yaml")
    if not os.path.isfile(p):
        return False
    for line in open(p, encoding="utf-8"):
        m = re.match(r"\s*DEEPSEEK_API_KEY:\s*(\S+)\s*$", line)
        if m:
            os.environ["DSH_SYNTHESIS_API_KEY"] = m.group(1)
            os.environ.setdefault("DSH_SYNTHESIS_BASE_URL",
                                  "https://api.deepseek.com/v1")
            os.environ.setdefault("DSH_SYNTHESIS_MODEL", "deepseek-flash")
            return True
    return False


def build_provider(kind, temperature=0.0):
    if kind in ("deepseek", "openai_compatible", "auto"):
        load_dsh_key()
        return sad.OpenAICompatibleProvider(timeout=60)
    if kind == "none":
        return None
    raise SystemExit("未知 provider：%s" % kind)


# ── mode：calibration
def run_calibration(judge=None, quiet=False):
    cases = [json.loads(l) for l in open(CALIBRATION, encoding="utf-8") if l.strip()]
    out = []
    for c in cases:
        contract = c["contract"]
        atom = dict(c["atom"])
        pre = se.deterministic_precheck(atom, contract)
        # 校准要按 **claim 级** 判定（先原子化）：partial 类案例正是「部分原子被蕴含」
        wrapper = {"claim_id": c["case_id"], "claim_type": atom.get("claim_type"),
                   "claim_text": atom.get("atom_text"),
                   "epistemic_status": atom.get("epistemic_status"),
                   "evidence_ids": atom.get("evidence_ids") or [],
                   "corpus_scan_ref": atom.get("corpus_scan_ref")}
        cverdict = se.validate_claim(wrapper, contract, judge=judge,
                                     question=c.get("question"))
        verdict = {"status": cverdict["status"], "strength": cverdict["strength"],
                   "llm_judgment": next((a["llm_judgment"] for a in cverdict["atoms"]
                                         if a["llm_judgment"]), None),
                   "reason": next((a["reason"] for a in cverdict["atoms"]
                                   if a["reason"]), None),
                   "atoms": cverdict["atoms"]}
        expected = c["expected_status"]
        got = verdict["status"]
        # `requires_judge=True` 的样例在 judge 关闭时**记 SKIPPED**（不计入准确率），
        # 而不是当成 mismatch —— 否则会把「离线跑不动」误报成「validator 错」
        skipped = bool(c.get("requires_judge")) and not (judge and judge.enabled)
        ok = (got == expected) if not skipped else None
        out.append({"case_id": c["case_id"], "category": c["category"],
                    "skipped_requires_judge": skipped,
                    "expected_status": expected, "expected_strength":
                        c.get("expected_strength"), "got_status": got,
                    "got_strength": verdict["strength"], "ok": ok,
                    "deterministic_signal": pre.get("signal"),
                    "used_llm": bool(verdict.get("llm_judgment")),
                    "reason": verdict.get("reason")})
        if not quiet:
            print("  %-8s %-22s exp=%-20s got=%-20s %s"
                  % (c["case_id"], c["category"], expected, got,
                     "OK" if ok else "MISMATCH"))
    scored = [x for x in out if x["ok"] is not None]
    n_ok = len([x for x in scored if x["ok"]])
    by_cat = {}
    for x in scored:
        d = by_cat.setdefault(x["category"], {"n": 0, "ok": 0})
        d["n"] += 1
        d["ok"] += 1 if x["ok"] else 0
    return {"cases": out, "n": len(out), "scored_n": len(scored),
            "skipped_n": len(out) - len(scored), "ok": n_ok,
            "accuracy": round(n_ok / len(scored), 4) if scored else None,
            "by_category": by_cat,
            "judge_enabled": bool(judge and judge.enabled)}


# ── mode：adversarial
def run_adversarial(quiet=False):
    """§33/§34/§35：三类对抗测试（scripted provider，确定性、离线）。"""
    import synthesis_adversarial as adv
    results = []
    for case in adv.CASES:
        r = adv.run_case(case)
        results.append(r)
        if not quiet:
            print("  %-26s %-10s detected=%-5s %s"
                  % (case["case_id"], case["kind"], r["detected"],
                     r.get("detected_by") or r.get("note") or ""))
    n_det = len([r for r in results if r["detected"]])
    return {"cases": results, "n": len(results), "detected_n": n_det,
            "detection_rate": round(n_det / len(results), 4) if results else None,
            "by_kind": {k: {"n": len([r for r in results if r["kind"] == k]),
                            "detected": len([r for r in results
                                             if r["kind"] == k and r["detected"]])}
                        for k in {c["kind"] for c in results}}}


# ── mode：mock / llm（14 题全流程）
def run_tasks(mode, provider=None, judge=None, quiet=False, ids=None, limit=0):
    task_ids = ids or reviewed_tasks()
    if limit:
        task_ids = task_ids[:limit]
    tasks = task_defs(task_ids)
    synth = (sad.MockSynthesisAdapter() if mode == "mock"
             else sad.ScholarlySynthesisAdapter(provider=provider))
    rows = []
    costs = {"provider_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "judge_tokens": 0, "repair_tokens": 0, "latency_s": 0.0}
    for t in tasks:
        run = ans.run_task(public_view(t), record_gaps=False)
        contract = sc.build_synthesis_input_contract(run)
        t0 = time.time()
        retries = 0
        attempts = []
        while True:
            try:
                # D 阶段用 **strict=False**：整份响应不再一票否决，
                # 逐条清洗 / C 验证 / entailment / repair / reject 由 D 流水线负责
                draft = (synth.synthesize(t["question"], contract, strict=False)
                         if mode == "llm" else synth.synthesize(t["question"], contract))
                attempts.append({"attempt_n": retries + 1, "result": "OK",
                                 "error": None})
                break
            except Exception as exc:                    # provider 抖动 → 重试 1 次
                if retries >= 2:
                    draft = {"ok": False, "failure_mode": "LLM_PROVIDER_FAILURE",
                             "detail": str(exc)[:160], "claims": [], "usage": {}}
                    attempts.append({"attempt_n": retries + 1, "result": "FAILED",
                                     "error": str(exc)[:160], "backoff_s": 0})
                    break
                retries += 1
                time.sleep(5 * (2 ** (retries - 1)))
        synth_latency = time.time() - t0
        row = {"task_id": t["task_id"], "question": t["question"],
               "task_type": t["task_type"], "mode": mode,
               "answer_permission": contract.get("answer_permission"),
               "contract_status": contract.get("status"),
               "synthesis_ok": bool(draft.get("ok")),
               "failure_mode": draft.get("failure_mode"),
               "failure_detail": draft.get("detail") if not draft.get("ok") else None,
               "synthesis_latency_s": round(synth_latency, 2),
               "provider_retries": retries,
               "provider_attempts": attempts,
               "marker": "DIAGNOSTIC", "human_validated": False,
               "validation_note": "NOT_HUMAN_VALIDATED",
               "input_contract": contract, "marker_mode":
                   ("MOCK_VALIDATION" if mode == "mock" else "REAL_LLM_DIAGNOSTIC")}
        if draft.get("ok"):
            pipe = sv.run_validation_pipeline(run, contract, draft, judge=judge,
                                              question=t["question"])
            row.update({
                "generated_claims": pipe["generated_claims"],
                "prevalidation_dropped": pipe["prevalidation_dropped"],
                "quote_fixes": pipe["quote_fixes"],
                "c_dropped": pipe["c_dropped"],
                "entailment": pipe["entailment"], "validated_claims":
                    pipe["validated_claims"], "answer": pipe["answer"],
                "markdown": pipe["markdown"], "answer_state": pipe["answer_state"],
                "c_validation_failures": pipe["c_validation"]["violations"],
            })
            costs["provider_calls"] += 1 if mode == "llm" else 0
            u = (draft.get("usage") or {})
            costs["input_tokens"] += int(u.get("input_tokens") or 0)
            costs["output_tokens"] += int(u.get("output_tokens") or 0)
            costs["latency_s"] += float(u.get("latency_s") or 0)
        else:
            row.update({"generated_claims": 0, "validated_claims": [],
                        "entailment": {"results": [], "repaired": [], "rejected": []},
                        "answer": None, "markdown": None,
                        "answer_state": "VALIDATION_FAILED"})
        rows.append(row)
        # durable per-task progress（只用于可观测性，不参与最终 READY 判定）
        try:
            with open(os.path.join(run_dir, "progress.jsonl"), "a",
                      encoding="utf-8") as pf:
                pf.write(json.dumps({"task_id": row["task_id"],
                                     "answer_permission": row.get("answer_permission"),
                                     "generated_claims": row.get("generated_claims"),
                                     "validated_claims": len(row.get("validated_claims") or []),
                                     "answer_state": row.get("answer_state"),
                                     "failure_mode": row.get("failure_mode"),
                                     "provider_attempts": row.get("provider_attempts")},
                                    ensure_ascii=False) + "\n")
                pf.flush()
        except Exception:
            pass
        if not quiet:
            print("  %-7s %-20s gen=%-3s valid=%-3s rej=%-2s state=%s"
                  % (t["task_id"], row.get("answer_permission"),
                     row.get("generated_claims", 0),
                     len(row.get("validated_claims") or []),
                     len((row.get("entailment") or {}).get("rejected") or []),
                     row.get("answer_state")), flush=True)
    if judge is not None:
        costs["judge_tokens"] = judge.usage.get("input_tokens", 0) + \
            judge.usage.get("output_tokens", 0)
        costs["latency_s"] += float(judge.usage.get("latency_s") or 0)
        costs["judge_calls"] = judge.calls
    return rows, costs


def _write(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="mock",
                    choices=("calibration", "adversarial", "mock", "llm"))
    ap.add_argument("--provider", default="auto",
                    help="auto|deepseek|openai_compatible|none")
    ap.add_argument("--judge", default="auto", help="auto|on|off")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--new-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--run-prefix", default="4c1d",
                    help="run 目录前缀（D2 用 4c1d2）")
    a = ap.parse_args(argv)
    if a.check:
        return check_run()

    provider = build_provider(a.provider if a.provider != "auto" else "deepseek")
    provider_ok = bool(provider and provider.available)
    if a.mode == "llm" and not provider_ok:
        print("SKIPPED_PROVIDER_UNAVAILABLE：未配置 provider（DSH_SYNTHESIS_API_KEY），"
              "拒绝用真实 LLM 模式出结果")
        return 3
    judge_on = (a.judge == "on") or (a.judge == "auto" and provider_ok)
    judge = se.EntailmentJudge(provider=provider if judge_on else None,
                              enabled=judge_on) if a.mode in ("calibration", "llm") \
        else None

    rid = a.run_id
    if rid and os.path.exists(os.path.join(RUNS_DIR, rid)):
        if not a.new_run:
            raise SystemExit("拒绝覆盖：run 已存在 %s（要新建请加 --new-run）" % rid)
        rid = None
    rid, run_dir = new_run_dir(a.mode, run_id=rid, prefix=a.run_prefix)
    t0 = time.time()
    payload = {}
    if a.mode == "calibration":
        payload["calibration"] = run_calibration(judge=judge, quiet=a.quiet)
    elif a.mode == "adversarial":
        payload["adversarial"] = run_adversarial(quiet=a.quiet)
    else:
        rows, costs = run_tasks(a.mode, provider=provider, judge=judge,
                                quiet=a.quiet, limit=a.limit)
        payload["rows"] = rows
        payload["costs"] = costs
        payload["metrics"] = sv.entailment_metrics(rows)
        payload["gate21"] = {"violations": ei.synthesis_entailment_findings(
            {"rows": rows})}
    manifest = {
        "schema_version": "synthesis-run-manifest/v1",
        "run_id": rid, "phase": PHASE, "mode": a.mode,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - t0, 1),
        "git_head": git_head(), "engine_hashes": engine_hashes(),
        "validator_version": VALIDATOR_VERSION,
        "provider": (getattr(provider, "name", None) if provider else None),
        "model": (getattr(provider, "model", None) if provider else None),
        "temperature": 0.0,
        "judge_enabled": bool(judge and judge.enabled),
        "provider_available": provider_ok,
        "adapter": ("mock" if a.mode == "mock" else "llm"),
        "marker": ("MOCK_VALIDATION" if a.mode == "mock" else
                   ("REAL_LLM_DIAGNOSTIC" if a.mode == "llm" else "DIAGNOSTIC")),
        "human_validated": False, "immutable": True,
        "note": ("DIAGNOSTIC：不是 human-validated；第二轮人工评审在 4C.1-E。"
                 "真实 LLM 只做 evidence → structured claims，不得自行检索/补知识。"),
    }
    _write(os.path.join(run_dir, "run_manifest.json"), manifest)
    _write(os.path.join(run_dir, "results.json"),
           {"schema_version": "synthesis-entailment-results/v1", "run_id": rid,
            "phase": PHASE, "mode": a.mode, "marker": manifest["marker"],
            "human_validated": False, **payload})
    if "metrics" in payload:
        _write(os.path.join(run_dir, "metrics.json"), payload["metrics"])
    agg = {
        "schema_version": "research-synthesis-results-4c1d/v1",
        "marker": manifest["marker"], "phase": PHASE, "mode": a.mode,
        "human_validated": False, "run_id": rid,
        "run_dir": os.path.relpath(run_dir, VAULT),
        "created_at": manifest["created_at"], "seconds": manifest["seconds"],
        "provider": manifest["provider"], "model": manifest["model"],
        "judge_enabled": manifest["judge_enabled"],
        "metrics": payload.get("metrics"),
        "gate21_violations": (payload.get("gate21") or {}).get("violations"),
        "calibration": (payload.get("calibration") or {}).get("accuracy"),
        "adversarial": (payload.get("adversarial") or {}).get("detection_rate"),
        "rows": [{k: v for k, v in r.items()
                  if k not in ("input_contract", "answer", "markdown",
                               "validated_claims", "entailment",
                               "c_validation_failures")}
                 for r in (payload.get("rows") or [])],
    }
    # 本阶段所有 run 的索引（一个 run 目录一个真值；aggregate 只指向**最新**一个）
    runs_index = []
    for d in sorted(os.listdir(RUNS_DIR)):
        if not d.startswith("4c1d_"):
            continue
        mp = os.path.join(RUNS_DIR, d, "run_manifest.json")
        rp = os.path.join(RUNS_DIR, d, "results.json")
        if not (os.path.isfile(mp) and os.path.isfile(rp)):
            continue
        man = json.load(open(mp, encoding="utf-8"))
        res = json.load(open(rp, encoding="utf-8"))
        g21 = ei.synthesis_entailment_findings(res) if res.get("rows") else []
        runs_index.append({
            "run_id": man.get("run_id"), "mode": man.get("mode"),
            "marker": man.get("marker"),
            "created_at": man.get("created_at"),
            "provider": man.get("provider"), "model": man.get("model"),
            "judge_enabled": man.get("judge_enabled"),
            "engine_hashes_ok": all(engine_hashes().get(k) == v for k, v in
                                    (man.get("engine_hashes") or {}).items()),
            "stale_engine": bool(man.get("stale_engine")),
            "stale_reason": man.get("stale_reason"),
            "gate21_violations": len(g21),
            "metrics": (res.get("metrics") or None),
            "calibration_accuracy": (res.get("calibration") or {}).get("accuracy"),
            "adversarial_detection_rate":
                (res.get("adversarial") or {}).get("detection_rate"),
        })
    agg["runs_index"] = runs_index
    _write(AGG, agg)
    if not a.quiet:
        print("\n-> %s" % os.path.relpath(run_dir, VAULT))
        print("-> %s" % os.path.relpath(AGG, VAULT))
        if payload.get("metrics"):
            m = payload["metrics"]
            for k in ("generated_claims", "validated_claims", "repaired_claims",
                      "rejected_claims", "claim_validation_rate",
                      "direct_entailment_rate", "NOT_ENTAILED_generated",
                      "source_role_violations_in_final"):
                print("  %-34s %s" % (k, m.get(k)))
    return 0


def check_run():
    """只读校验当前 4C.1-D run（manifest 钉住 + 指标可复算 + Gate 21 = 0）。"""
    if not os.path.isfile(AGG):
        print("FAIL 尚无 4C.1-D run")
        return 1
    agg = json.load(open(AGG, encoding="utf-8"))
    run_dir = os.path.join(VAULT, agg.get("run_dir") or "")
    man_p = os.path.join(run_dir, "run_manifest.json")
    res_p = os.path.join(run_dir, "results.json")
    problems = []
    if not os.path.isfile(man_p) or not os.path.isfile(res_p):
        print("FAIL run 目录缺 manifest/results：%s" % run_dir)
        return 1
    man = json.load(open(man_p, encoding="utf-8"))
    res = json.load(open(res_p, encoding="utf-8"))
    if man.get("run_id") != agg.get("run_id"):
        problems.append("run_id 不一致")
    if not man.get("immutable") or man.get("human_validated"):
        problems.append("immutable/human_validated 标记不对")
    live = engine_hashes()
    for k, v in (man.get("engine_hashes") or {}).items():
        if live.get(k) != v:
            problems.append("engine hash 漂移：%s" % k)
    if res.get("rows"):
        m = sv.entailment_metrics(res["rows"])
        if json.dumps(m, sort_keys=True) != json.dumps(agg.get("metrics") or {},
                                                       sort_keys=True):
            problems.append("metrics 与 rows 不可复算一致")
    if agg.get("gate21_violations"):
        problems.append("Gate 21 违规 %s" % agg["gate21_violations"])
    # 现场扫描 runs 目录（不要相信旧的 runs_index 快照）
    live_runs = []
    for d in sorted(os.listdir(RUNS_DIR)):
        mp = os.path.join(RUNS_DIR, d, "run_manifest.json")
        rp = os.path.join(RUNS_DIR, d, "results.json")
        if not (os.path.isfile(mp) and os.path.isfile(rp)) or not d.startswith("4c1d"):
            continue
        man = json.load(open(mp, encoding="utf-8"))
        ok = all(engine_hashes().get(k) == v for k, v in
                 (man.get("engine_hashes") or {}).items())
        live_runs.append({"run_id": man.get("run_id"), "mode": man.get("mode"),
                          "engine_hashes_ok": ok,
                          "stale_engine": bool(man.get("stale_engine"))})
    for r in live_runs:
        if not r.get("engine_hashes_ok") and not r.get("stale_engine"):
            problems.append("run %s 的引擎哈希已漂移（需重跑该 run）" % r.get("run_id"))
    if problems:
        print("FAIL 4C.1-D run 校验未通过：")
        for p in problems:
            print("  - %s" % p)
        return 1
    print("4C.1-D run 校验通过：mode=%s run_id=%s（Gate 21 = 0；manifest 哈希一致）"
          % (agg.get("mode"), agg.get("run_id")))
    for r in live_runs:
        print("   run %-42s mode=%-11s gate21=%-2s calib=%-7s adv=%-5s hash_ok=%s"
              % (r.get("run_id"), r.get("mode"), r.get("gate21_violations"),
                 r.get("calibration_accuracy"), r.get("adversarial_detection_rate"),
                 r.get("engine_hashes_ok")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
