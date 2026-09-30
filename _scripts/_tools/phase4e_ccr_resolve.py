#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_ccr_resolve.py — Phase 4E §54：把 CCR-0001 标记为 RESOLVED（仅在 E1–E17 全 PASS 后）。"""
import argparse, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = "<REPO>"
CCR = os.path.join(VAULT, "_core_change_requests", "requests", "CCR-0001.json")
OUT = os.path.join(VAULT, "_data", "phase4e", "ccr_resolution.json")
P4E = os.path.join(VAULT, "_data", "phase4e")

ap = argparse.ArgumentParser()
ap.add_argument("--acc-run", required=True)
ap.add_argument("--real-run", required=True)
ap.add_argument("--delta-run", required=True)
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()

d = json.load(open(CCR, encoding="utf-8"))
fin = json.load(open(os.path.join(P4E, a.acc_run, "final_decision.json"), encoding="utf-8"))
if fin.get("decision") != "PHASE_4E_COMPLETE":
    print("FAIL 验收未通过（%s）—— 不得 RESOLVED" % fin.get("decision")); sys.exit(1)

note = ("Phase 4E 修复并验证：根因是产品门面（scholarly_api/core.py）把低层 completion "
        "provider 当成 synthesis adapter 使用；修复 = 改经既有工厂 "
        "synthesis_adapters.make_adapter()，真 provider 被包进 ScholarlySynthesisAdapter"
        "（与 4C.1-D/D2 结构一致，engine 逐字节未改）。验证：14/14 真实 provider 回归"
        "（Gate20=0 / Gate21=0 / 弃权 3/3 / 无泄漏）、6 题 agent-mediated spot review "
        "(FAIL=0)、产品 delta 验证（A/D/F + 四格式 + Project + Obsidian）、全量回归 "
        "failed=[] skipped=[]、冻结谱系第 5 段（语义变化 0）。")
d.update({"status": "RESOLVED", "resolution_phase": "Phase 4E", "triage_note": note,
          "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          "verification": {"acceptance_run": a.acc_run, "real_provider_run": a.real_run,
                           "product_delta_run": a.delta_run,
                           "gate": "Phase 4E Remediation Gate v1（E1–E17 全 PASS）",
                           "freeze": "scholarly_core_freeze_v1 + lineage 第 5 段（ccr=CCR-0001）"}})
if a.apply:
    with open(CCR, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2); f.write("\n")
    r = subprocess.run([sys.executable, os.path.join(VAULT, "_scripts", "_tools",
                                                     "check_core_change_requests.py"),
                        "--verify"], capture_output=True, text=True, cwd=VAULT)
    print(r.stdout.strip()[-200:] or r.stderr.strip()[-200:])
    assert r.returncode == 0, "CCR 校验失败"
doc = {"schema_version": "phase4e-ccr-resolution/v1", "ccr": "CCR-0001",
       "status": "RESOLVED", "resolution_phase": "Phase 4E",
       "acceptance_run": a.acc_run, "real_provider_run": a.real_run,
       "product_delta_run": a.delta_run, "summary": note,
       "root_cause": "completion provider 被当成 synthesis adapter（产品边界 wiring 缺陷）",
       "fix_summary": "llm/mock 分支改经 make_adapter（reuse 既有 adapter）+ 错误翻译/子分类/脱敏",
       "semantic_impact": "runtime_wiring_changed=true / scholarly_semantics_changed=false",
       "new_freeze_identity": "scholarly_core_freeze_v1 + lineage segment 5（phase=4E）"}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True); f.write("\n")
print("-> %s" % os.path.relpath(OUT, VAULT))
