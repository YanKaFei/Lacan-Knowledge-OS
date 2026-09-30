#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_acceptance.py — Phase 4E §49–§55：Remediation Gate v1 的冻结与判定。

两种用法：

    python3 _scripts/_tools/phase4e_acceptance.py --freeze-gate
        # 写出/冻结 _data/phase4e/phase4e_remediation_gate_v1.json（**只在最终验收前**）

    python3 _scripts/_tools/phase4e_acceptance.py --run [--real-run <dir>] ...
        # 建立 4e_acceptance_<ts>_<id>：评估 E1–E17，产出全部验收工件与最终判定

设计纪律（与 4D.7 相同）：
* Gate **先冻结、后验收**；冻结后不得改判据、阈值或证据口径。
* 判定只有两个值：`PHASE_4E_COMPLETE` / `PHASE_4E_BLOCKED`。
* 任一 E 判据 FAIL → `PHASE_4E_BLOCKED`，且 **CCR-0001 不得 RESOLVED**。
* 只消费**已有工件**（不重跑 14 题、不改历史 run）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
P4E = os.path.join(VAULT, "_data", "phase4e")
GATE = os.path.join(P4E, "phase4e_remediation_gate_v1.json")
FREEZE_DIR = os.path.join(VAULT, "_data", "core_freeze")
LIVE_FREEZE = os.path.join(FREEZE_DIR, "scholarly_core_freeze_v1.json")
PARENT_FREEZE = os.path.join(FREEZE_DIR, "history",
                             "scholarly_core_freeze_v1.4d2-workspace-registered.json")
PRODUCT_BOUNDARY_KEYS = ("scholarly_api_core_hash", "scholarly_api_objects_hash",
                         "scholarly_api_policy_hash")

GATE_ID = "Phase 4E Remediation Gate v1"
CRITERIA = [
    ("E1", "CCR-0001 root cause identified（根因有据、含 9 问与 D2 对照）",
     "PHASE4E_CCR0001_ROOT_CAUSE.md + _data/phase4e/root_cause.json"),
    ("E2", "completion provider != synthesis adapter 边界已恢复（llm 分支经 make_adapter）",
     "test_phase4e_ccr0001_wiring（test_03 复现转绿）+ adapter_contract.json"),
    ("E3", "synthesis prompt hash unchanged（SYSTEM_CONTRACT）",
     "freeze 比对：synthesis_prompt_hash 与父冻结一致"),
    ("E4", "judge prompt hash unchanged（JUDGE_SYSTEM）",
     "freeze 比对：judge_prompt_hash 与父冻结一致"),
    ("E5", "scholarly semantic components drift = 0",
     "freeze 比对：仅 scholarly_api_core_hash 变化（38/39 不变）"),
    ("E6", "real-provider smoke succeeds（1 题走完整 pipeline）",
     "test_phase4e_real_provider_smoke + real_provider_metrics.json"),
    ("E7", "14/14 real-provider regression completes（attempted, provider_attempts 记录, sealed）",
     "seal.json: provider_success == 14/14 且 tasks_attempted == 14"),
    ("E8", "Gate13/19/20/21 new violations = 0",
     "gate_results.json（Gate20/21 在新 run 上重算）+ 冻结审计复算"),
    ("E9", "abstention leakage = 0",
     "metrics.abstention_findings == [] 且 rt-J01/J02/J03 全部 ABSTAINED"),
    ("E10", "unsupported final claims = 0 / rejected claims in final = 0",
     "Gate21 by_code: D_SUBSTANTIVE_CLAIM_WITHOUT_EVIDENCE == 0 且 "
     "D_REJECTED_CLAIM_IN_FINAL == 0"),
    ("E11", "provider failure returns PROVIDER_UNAVAILABLE / proper error",
     "test_phase4e_ccr0001_wiring test_04/05 + product delta 的 provider 失败检查"),
    ("E12", "mock fallback on real-provider failure = 0",
     "test_phase4e_ccr0001_wiring test_05/06 + product delta 的 no-fallback 检查"),
    ("E13", "product UI/MCP real-provider path succeeds",
     "test_phase4e_product_real_provider_path + product delta 的 UI E2E"),
    ("E14", "human spot review FAIL = 0（6 题，含 rt-D01/I02/H02/C03/J02/G01）",
     "human_spot_review.jsonl"),
    ("E15", "full regression failed=[] skipped=[]（含新增 4E 套件）",
     "regression.json（exit=0，failed=[], skipped=[]）"),
    ("E16", "core freeze / freeze lineage valid",
     "core_freeze --verify + freeze_lineage --verify（5 段，语义变化 0）"),
    ("E17", "secrets leakage = 0（工件/日志/导出）",
     "secret_audit.json：API key / Bearer / sk- 形态出现次数 = 0"),
]


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    with open(p, "rb") as f:
        return sha_bytes(f.read())


def jd(p, default=None):
    if not os.path.isfile(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def wr(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def gate_payload():
    return {
        "schema_version": "phase4e-remediation-gate/v1",
        "gate_id": GATE_ID,
        "phase": "Phase 4E — Scholarly Core Remediation: Real Provider Path",
        "ccr": "CCR-0001",
        "frozen": True,
        "frozen_at": utcnow(),
        "frozen_before_final_run": True,
        "git_head": subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout.strip(),
        "parent_core_freeze": {
            "manifest": os.path.relpath(PARENT_FREEZE, VAULT),
            "sha256": sha_file(PARENT_FREEZE) if os.path.isfile(PARENT_FREEZE) else None,
        },
        "criteria": [{"id": i, "requirement": r, "evidence": e, "blocking": True}
                     for i, r, e in CRITERIA],
        "decision_values": ["PHASE_4E_COMPLETE", "PHASE_4E_BLOCKED"],
        "policy": {
            "any_criterion_fail": "PHASE_4E_BLOCKED；CCR-0001 不得 RESOLVED",
            "no_gate_edits_after_freeze": True,
            "no_history_rewrite": "失败的 run 保留，修完新开 run",
            "semantic_change_rule": "只允许产品边界组件变化；学术语义漂移必须为 0",
        },
    }


def freeze_gate():
    if os.path.isfile(GATE):
        cur = jd(GATE)
        payload = gate_payload()
        body = {k: v for k, v in payload.items() if k != "frozen_at"}
        old = {k: v for k, v in cur.items() if k not in ("frozen_at", "gate_hash")}
        if body != old:
            print("FAIL gate 已存在且判据发生变化 —— 冻结后不得修改。"
                  "（如需新版本，请另建 phase4e_remediation_gate_v2.json）")
            return 1
        print("Gate 已冻结且未改动：%s" % GATE)
        return 0
    payload = gate_payload()
    payload["gate_hash"] = sha_bytes(json.dumps(
        {k: v for k, v in payload.items() if k != "gate_hash"},
        ensure_ascii=False, sort_keys=True).encode("utf-8"))
    wr(GATE, payload)
    print("frozen gate -> %s（%d 条判据；gate_hash=%s）"
          % (os.path.relpath(GATE, VAULT), len(payload["criteria"]),
             payload["gate_hash"][:16]))
    return 0


# ── 判定辅助
def freeze_compare():
    live, parent = jd(LIVE_FREEZE, {}), jd(PARENT_FREEZE, {})
    lc, pc = live.get("components") or {}, parent.get("components") or {}
    changed = sorted(k for k in set(lc) | set(pc) if lc.get(k) != pc.get(k))
    semantic = [k for k in changed if k not in PRODUCT_BOUNDARY_KEYS]
    return {"changed": changed, "semantic_changes": semantic,
            "unchanged_n": len([k for k in pc if pc.get(k) == lc.get(k)]),
            "synthesis_prompt_same": lc.get("synthesis_prompt_hash") ==
            pc.get("synthesis_prompt_hash"),
            "judge_prompt_same": lc.get("judge_prompt_hash") ==
            pc.get("judge_prompt_hash"),
            "live": live, "parent": parent}


def suite_ok(name):
    """→ (exit_code:int, tail:str)。**返回数字**返回码，便于判据里直接比 0。

    ⚠️ 实测更正：初版返回 `bool`，而判据写成 `rc == 0` —— `True == 0` 恒假，
    于是 E2/E6/E11/E12/E13 被**误判为 FAIL**（工具缺陷，不是产品缺陷）。
    该次 acceptance run 作为 precursor 保留在 `_data/phase4e/` 下，未做任何改写。
    """
    r = subprocess.run([sys.executable, "-m", "unittest", name],
                       capture_output=True, text=True,
                       cwd=os.path.join(VAULT, "_scripts", "_tests"))
    tail = " ".join((r.stdout + r.stderr).split())[-400:]
    return r.returncode, tail


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E acceptance / gate")
    ap.add_argument("--freeze-gate", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--real-run", default=None, help="4E real-provider run 目录")
    ap.add_argument("--delta-run", default=None, help="product delta 目录")
    ap.add_argument("--regression", default=None, help="regression.json")
    ap.add_argument("--spot-review", default=None, help="human_spot_review.jsonl")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    if a.freeze_gate or not (a.run or a.freeze_gate):
        return freeze_gate() if a.freeze_gate else main(["--help"])
    if a.run:
        return run_acceptance(a)
    return 0


def _latest(prefix):
    if not os.path.isdir(P4E):
        return None
    cands = sorted(d for d in os.listdir(P4E) if d.startswith(prefix))
    return os.path.join(P4E, cands[-1]) if cands else None


def _root_cause_json():
    """§53 root_cause.json：把根因结论写成机器可读的事实（与 .md 同源）。"""
    return {
        "schema_version": "phase4e-root-cause/v1",
        "ccr": "CCR-0001",
        "one_line": ("4D.0/4D.1 的产品门面 scholarly_api/core.py 没有复用仓库既有的 "
                     "synthesis adapter 工厂：llm 分支直接把低层 completion provider "
                     "（只有 complete()）当成 adapter 调 .synthesize()/.provider，"
                     "必然 AttributeError。"),
        "defect_location": "scholarly_api/core.py（provider_kind == 'llm' 分支）",
        "introduced_phase": "4D.0/4D.1（产品边界），非 4C.1 学术语义",
        "answers": {
            "q1_who_creates_provider": [
                "scholarly_api/core.py:412（产品路径，错误）",
                "_scripts/_tools/run_synthesis_4c1d.py:build_provider（D2 runner，正确）",
                "_scripts/_tools/synthesis_adapters.py:make_adapter（既有工厂，未被产品路径使用）"],
            "q2_provider_type": "synthesis_adapters.OpenAICompatibleProvider（SynthesisProvider 子类，只有 complete()）",
            "q3_boundary_expects": "adapter.synthesize(question, contract, strict=False) + adapter.provider",
            "q4_mock_adapter": "MockSynthesisAdapter.synthesize()（本身就是 adapter，正确）",
            "q5_real_provider": "OpenAICompatibleProvider.complete()；实现 synthesize() 的是 ScholarlySynthesisAdapter",
            "q6_wrong_layer": "scholarly_api/core.py 的 llm 分支（把 provider 当 adapter）",
            "q7_introduced_when": ("09-23 已有正确 adapter；09-24 D2 用正确结构通过 14/14 + Gate21=0；"
                                   "09-25 写 core.py 时引入（scholarly_api/ 未被 git 跟踪，"
                                   "用文件时间 + 冻结谱系 4D.1 段定位）"),
            "q8_d2_path": "run_synthesis_4c1d.py:237-238 → ScholarlySynthesisAdapter(provider=OpenAICompatibleProvider)",
            "q9_why_not_reused": ("产品门面重新实现了一遍 provider 构造，没调用 make_adapter；"
                                  "4D.1 MCP 契约测试只覆盖 provider=mock，llm 分支从未端到端执行"),
        },
        "reuse_vs_new": {
            "decision": "reuse existing validated adapter（不新增实现）",
            "evidence": ("D2 run manifest 的 10 个 engine 文件与当前工作树逐字节相同，"
                         "含 synthesis_adapters.py（ScholarlySynthesisAdapter + make_adapter）"
                         "与 synthesis_contract.py（= 冻结 synthesis_boundary_hash）"),
        },
        "frozen_impact": "仅 scholarly_api_core_hash（产品边界）；38/39 组件不变",
        "not_solved_here": ("冻结 task_type `insufficient_unanswerable` 无法从产品 mode 表达"
                            "（既有产品接口限制，与本 CCR 无关；见报告 §11/§26）"),
    }


def _adapter_contract_json():
    """§53 adapter_contract.json：边界契约与修复证据（introspection + AST）。"""
    import ast
    import synthesis_adapters as sad
    src = open(os.path.join(VAULT, "scholarly_api", "core.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    llm_branch = {"uses_make_adapter": False, "raw_completion_provider_assignment": False}
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            t = node.test
            if (isinstance(t.left, ast.Name) and t.left.id == "provider_kind"
                    and getattr(t.comparators[0], "value", None) == "llm"):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                            and sub.func.attr == "make_adapter":
                        llm_branch["uses_make_adapter"] = True
                    if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call) \
                            and isinstance(sub.value.func, ast.Attribute) \
                            and sub.value.func.attr == "OpenAICompatibleProvider":
                        llm_branch["raw_completion_provider_assignment"] = True
    prov = sad.OpenAICompatibleProvider(timeout=1)
    adapter = sad.make_adapter("llm", prov)
    return {
        "schema_version": "phase4e-adapter-contract/v1",
        "boundary": {
            "expects": ["synthesize(question, contract, strict=)", "provider"],
            "completion_provider_protocol": ["complete(system, user, schema)", "available",
                                             "name", "model"],
        },
        "classes": {
            "OpenAICompatibleProvider": {
                "mro": [c.__name__ for c in type(prov).__mro__],
                "has_complete": hasattr(prov, "complete"),
                "has_synthesize": hasattr(prov, "synthesize"),
                "has_provider": hasattr(prov, "provider")},
            "ScholarlySynthesisAdapter": {
                "mro": [c.__name__ for c in type(adapter).__mro__],
                "has_synthesize": hasattr(adapter, "synthesize"),
                "has_provider": getattr(adapter, "provider", None) is prov},
        },
        "factory": {"name": "synthesis_adapters.make_adapter",
                    "mock_returns": type(sad.make_adapter("mock")).__name__,
                    "llm_returns": type(adapter).__name__},
        "core_llm_branch_ast": llm_branch,
        "verdict": ("boundary restored: llm 分支经 make_adapter 得到 "
                    "ScholarlySynthesisAdapter"
                    if llm_branch["uses_make_adapter"]
                    and not llm_branch["raw_completion_provider_assignment"]
                    else "FAIL: llm 分支仍直接把 provider 当 adapter"),
    }


def run_acceptance(a):
    real = a.real_run or _latest("phase4e_real_llm_")
    delta = a.delta_run or _latest("4e_product_delta_")
    regression_path = a.regression or os.path.join(P4E, "regression.json")
    spot_path = a.spot_review or os.path.join(P4E, "human_spot_review.jsonl")
    gate = jd(GATE, {})
    if not gate:
        print("FAIL 缺冻结 Gate：%s（先 --freeze-gate）" % os.path.relpath(GATE, VAULT))
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = a.run_id or "4e_acceptance_%s_%s" % (stamp, sha_bytes(stamp.encode())[:8])
    run_dir = os.path.join(P4E, run_id)
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)

    seal = jd(os.path.join(real or "", "seal.json"), {}) if real else {}
    metrics = jd(os.path.join(real or "", "metrics.json"), {}) if real else {}
    gate_res = jd(os.path.join(real or "", "gate_results.json"), {}) if real else {}
    d2cmp = jd(os.path.join(real or "", "d2_comparison.json"), {}) if real else {}
    delta_dec = jd(os.path.join(delta or "", "final_decision.json"), {}) if delta else {}
    reg = jd(regression_path, {})
    fc = freeze_compare()

    def run_tool(tool, *args):
        r = subprocess.run([sys.executable, os.path.join(HERE, tool), *args],
                           capture_output=True, text=True, cwd=VAULT)
        return r.returncode, (r.stdout + r.stderr)[-300:]

    items = []

    def add(cid, ok, evidence):
        items.append({"id": cid, "status": "PASS" if ok else "FAIL",
                      "requirement": dict((i, r) for i, r, _e in CRITERIA)[cid],
                      "evidence": evidence})

    root_doc = os.path.join(VAULT, "PHASE4E_CCR0001_ROOT_CAUSE.md")
    add("E1", os.path.isfile(root_doc), "PHASE4E_CCR0001_ROOT_CAUSE.md + root_cause.json")
    rc2, msg2 = suite_ok("test_phase4e_ccr0001_wiring")
    ast_ev = _adapter_contract_json()
    add("E2", rc2 == 0 and ast_ev["verdict"].startswith("boundary restored"),
        "test_phase4e_ccr0001_wiring exit=%s；%s" % (rc2, ast_ev["verdict"]))
    add("E3", bool(fc["synthesis_prompt_same"]), "synthesis_prompt_hash 与父冻结一致")
    add("E4", bool(fc["judge_prompt_same"]), "judge_prompt_hash 与父冻结一致")
    add("E5", fc["semantic_changes"] == [],
        "changed=%s semantic=%s unchanged=%d"
        % (fc["changed"], fc["semantic_changes"], fc["unchanged_n"]))
    rc3, msg3 = suite_ok("test_phase4e_real_provider_smoke")
    add("E6", rc3 == 0, "test_phase4e_real_provider_smoke exit=%s %s" % (rc3, msg3[-120:]))
    add("E7", seal.get("provider_success") == "14/14"
        and seal.get("tasks_attempted") == 14,
        "seal: provider_success=%s attempted=%s/14"
        % (seal.get("provider_success"), seal.get("tasks_attempted")))
    rc4, msg4 = run_tool("build_evaluation_integrity_audit.py", "--check")
    add("E8", (gate_res.get("recomputed_on_this_run", {})
               .get("gate20", {}).get("violations") == 0)
        and (gate_res.get("recomputed_on_this_run", {})
             .get("gate21", {}).get("violations") == 0) and rc4 == 0,
        "gate20=%s gate21=%s；冻结审计 --check exit=%s"
        % (gate_res.get("recomputed_on_this_run", {}).get("gate20", {}).get("violations"),
           gate_res.get("recomputed_on_this_run", {}).get("gate21", {}).get("violations"),
           rc4))
    j_states = {r["task_id"]: r.get("answer_state")
                for r in (jd(os.path.join(real or "", "results.json"), {}) or {}).get("rows", [])
                if r.get("task_id") in ("rt-J01", "rt-J02", "rt-J03")}
    add("E9", not metrics.get("abstention_findings", ["x"])
        and all(v == "ABSTAINED" for v in j_states.values()) and len(j_states) == 3,
        "abstention_findings=%s；J 题=%s"
        % (metrics.get("abstention_findings"), j_states))
    by_code = (gate_res.get("recomputed_on_this_run", {})
               .get("gate21", {}).get("by_code") or {})
    add("E10", not by_code.get("D_SUBSTANTIVE_CLAIM_WITHOUT_EVIDENCE")
        and not by_code.get("D_REJECTED_CLAIM_IN_FINAL"),
        "gate21 by_code=%s" % by_code)
    add("E11", rc2 == 0 and delta_dec.get("decision") == "DELTA_PASS",
        "确定性 provider 失败用例 + delta=%s" % delta_dec.get("decision"))
    add("E12", rc2 == 0 and delta_dec.get("decision") == "DELTA_PASS",
        "no-fallback 单元断言 + delta no-fallback")
    rc5, msg5 = suite_ok("test_phase4e_product_real_provider_path")
    add("E13", rc5 == 0 and delta_dec.get("decision") == "DELTA_PASS",
        "MCP 真实路径 exit=%s；delta=%s" % (rc5, delta_dec.get("decision")))
    spot = [json.loads(l) for l in open(spot_path, encoding="utf-8")
            if l.strip()] if os.path.isfile(spot_path) else []
    add("E14", bool(spot) and not [s for s in spot if s.get("verdict") == "FAIL"],
        "spot review %d 题；FAIL=%d"
        % (len(spot), len([s for s in spot if s.get("verdict") == "FAIL"])))
    add("E15", reg.get("exit_code") == 0 and not reg.get("failed")
        and not reg.get("skipped"),
        "regression exit=%s suites=%s failed=%s skipped=%s"
        % (reg.get("exit_code"), reg.get("suites"), reg.get("failed"), reg.get("skipped")))
    rc6, msg6 = run_tool("core_freeze.py", "--verify", "--quiet")
    rc7, msg7 = run_tool("freeze_lineage.py", "--verify")
    segs = (jd(os.path.join(FREEZE_DIR, "freeze_lineage.json"), {}) or {}).get("segments") or []
    add("E16", rc6 == 0 and rc7 == 0 and len(segs) == 5,
        "core_freeze exit=%s；lineage exit=%s 段数=%d" % (rc6, rc7, len(segs)))
    secrets = jd(os.path.join(P4E, "secret_audit.json"), {})
    add("E17", secrets.get("verdict") == "PASS"
        and not seal.get("secret_leak_findings"),
        "secret_audit=%s（files=%s）；run seal findings=%s"
        % (secrets.get("verdict"), secrets.get("files_scanned_n"),
           seal.get("secret_leak_findings")))

    failed = [i["id"] for i in items if i["status"] != "PASS"]
    decision = "PHASE_4E_COMPLETE" if not failed else "PHASE_4E_BLOCKED"
    wr(os.path.join(run_dir, "root_cause.json"), _root_cause_json())
    wr(os.path.join(run_dir, "adapter_contract.json"), ast_ev)
    for name, src_dir in (("real_provider_metrics.json", real),
                          ("task_results.jsonl", real),
                          ("gate_results.json", real),
                          ("d2_comparison.json", real)):
        src = os.path.join(src_dir or "", name)
        if os.path.isfile(src):
            with open(src, encoding="utf-8") as f:
                body = f.read()
            with open(os.path.join(run_dir, name), "w", encoding="utf-8") as f:
                f.write(body)
    if os.path.isfile(spot_path):
        with open(spot_path, encoding="utf-8") as f:
            body = f.read()
        with open(os.path.join(run_dir, "human_spot_review.jsonl"), "w",
                  encoding="utf-8") as f:
            f.write(body)
    wr(os.path.join(run_dir, "regression.json"), reg)
    wr(os.path.join(run_dir, "manifest.json"), {
        "schema_version": "phase4e-acceptance-manifest/v1", "run_id": run_id,
        "created_at": utcnow(), "head": subprocess.run(
            ["git", "-C", VAULT, "rev-parse", "HEAD"], capture_output=True,
            text=True).stdout.strip(),
        "gate_id": gate.get("gate_id"), "gate_hash": gate.get("gate_hash"),
        "gate_file_sha256": sha_file(GATE),
        "real_provider_run": os.path.relpath(real, VAULT) if real else None,
        "product_delta_run": os.path.relpath(delta, VAULT) if delta else None,
        "freeze": {"live_sha256": sha_file(LIVE_FREEZE),
                   "parent_sha256": sha_file(PARENT_FREEZE),
                   "changed": fc["changed"], "semantic_changes": fc["semantic_changes"]},
        "ccr": "CCR-0001", "decision": decision})
    wr(os.path.join(run_dir, "final_decision.json"), {
        "schema_version": "phase4e-final-decision/v1", "run_id": run_id,
        "decision": decision, "items": items, "failed": failed,
        "ccr_0001_status": "RESOLVED" if decision == "PHASE_4E_COMPLETE"
        else "ACCEPTED_FOR_REMEDIATION",
        "next_status": ("REAL_PROVIDER_SCHOLARLY_RESEARCH_READY"
                        if decision == "PHASE_4E_COMPLETE"
                        else "REAL_PROVIDER_SCHOLARLY_RESEARCH_NOT_READY"),
        "finished_at": utcnow()})
    print("\n== Phase 4E acceptance ==")
    for i in items:
        print("  %-4s %s | %s" % (i["id"], i["status"], str(i["evidence"])[:120]))
    print("decision: %s（failed=%s）" % (decision, failed))
    print("artifacts: %s" % os.path.relpath(run_dir, VAULT))
    return 0 if decision == "PHASE_4E_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
