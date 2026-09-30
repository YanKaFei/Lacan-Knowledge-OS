#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_corpus_acceptance.py — demo 语料（阶段 2）的**可重复验收**。

它回答的问题是：**一个下载了引擎、没有任何语料的人，能不能跑通一次完整研究？**
并且把"能跑"这件事变成机器可核的记录，而不是文档里的说法。

流程（全部在临时目录里，不碰当前 vault）：

    ① 从本仓库生成公开版（allow-list + 消毒 + verify）        → <out>/engine
    ② 在副本里跑 `tools/build_demo_corpus.py .`（全流水线）    → 段落库/索引/本体层/冻结/谱系
    ③ 打 demo 语料包 `tools/pack-corpus.py --kind demo`        → corpus-demo-v1.tar.gz + manifest
    ④ 把**干净的**公开版装进另一个副本，用 fetch-corpus 安装包 → 接收端还原
    ⑤ 逐项核验：ensure_corpus / core_freeze / freeze_lineage / 本体校验器 / 索引校验
    ⑥ 真跑一次研究（MCP lacan.research，mock provider）        → 必须是 VALIDATED*，且有真实引文
    ⑦ 核验**诚实边界**：档案 unreviewed-corpus、状态 CORPUS_HUMAN_REVIEW_NOT_AVAILABLE、
       包里不含参考语料的人工验收工件、包是 pack_kind=demo

退出码：0 = 全部通过；1 = 有断言失败（报告里逐条给出）。

用法：
    python3 _scripts/_tools/demo_corpus_acceptance.py                  # 全流程
    python3 _scripts/_tools/demo_corpus_acceptance.py --keep           # 保留临时目录
    python3 _scripts/_tools/demo_corpus_acceptance.py --out /tmp/demo-acc
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
QUESTION = "Comment la suggestion agit-elle dans l'hystérie ?"
REFERENCE_ACCEPTANCE_FILES = (
    "_data/eval/research_human_review.jsonl",
    "_data/eval/research_human_review_round2.jsonl",
    "_data/eval/human_adjudication_queue.jsonl",
    "_data/eval/scholarly_readiness_gate_v1.json",
    "_data/eval/gold_v2/research_tasks_v2.jsonl",
    "_data/eval/phase4c1d2_frozen_identity.json",
)


def run(cmd, cwd, timeout=3600):
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return {"cmd": " ".join(os.path.basename(c) if os.path.isabs(c) else c for c in cmd),
            "exit": r.returncode, "secs": round(time.time() - t0, 1),
            "stdout": (r.stdout or "")[-4000:], "stderr": (r.stderr or "")[-2000:]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="demo corpus stage-2 acceptance")
    ap.add_argument("--out", default=None, help="工作目录（缺省：临时目录）")
    ap.add_argument("--keep", action="store_true", help="保留工作目录")
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args(argv)

    out = a.out or tempfile.mkdtemp(prefix="demo-acc-")
    os.makedirs(out, exist_ok=True)
    steps, failures = [], []
    checks = {}

    def record(name, ok, detail):
        steps.append({"step": name, "ok": bool(ok), "detail": detail})
        if not ok:
            failures.append(name)
        print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
        return ok

    print("== demo corpus acceptance ==")
    print("workdir: %s" % out)

    # ── ① 公开版（干净引擎）
    engine = os.path.join(out, "engine")
    r = run([PY, os.path.join(HERE, "build_public_edition.py"), "--out", engine], VAULT)
    verify = {}
    try:
        verify = json.loads(r["stdout"])
    except Exception:                                                       # noqa: BLE001
        verify = {}
    record("① 生成公开版（verify.ok）", r["exit"] == 0 and verify.get("ok") is True,
           {"files": verify.get("files"), "mb": verify.get("mb"),
            "problems": verify.get("problems")})

    # ── ② 构建 demo 语料（全流水线）
    builder = os.path.join(out, "builder")
    shutil.copytree(engine, builder)
    r = run([PY, os.path.join("tools", "build_demo_corpus.py"), "."], builder, timeout=3600)
    record("② 构建 demo 语料（段落库→索引→本体层→冻结/谱系）", r["exit"] == 0,
           {"tail": r["stdout"][-1200:], "stderr": r["stderr"][-400:]})

    # ── ③ 打 demo 包
    packdir = os.path.join(out, "pack")
    r = run([PY, os.path.join("tools", "pack-corpus.py"), "--kind", "demo",
             "--out", packdir], builder)
    pack = os.path.join(packdir, "corpus-demo-v1.tar.gz")
    pman = os.path.join(packdir, "corpus-demo-v1.manifest.json")
    manifest = {}
    if os.path.isfile(pman):
        with io.open(pman, encoding="utf-8") as fh:
            manifest = json.load(fh)
    paths = [f["path"] for f in manifest.get("files") or []]
    no_acceptance = not any(p in REFERENCE_ACCEPTANCE_FILES for p in paths)
    record("③ 打 demo 包（pack_kind=demo、不含参考语料人工验收工件）",
           r["exit"] == 0 and manifest.get("pack_kind") == "demo" and no_acceptance
           and manifest.get("corpus_profile") == "unreviewed-corpus",
           {"files": manifest.get("counts", {}).get("files"),
            "mb": round((manifest.get("pack", {}).get("bytes") or 0) / 1048576, 2),
            "pack_kind": manifest.get("pack_kind"),
            "has_reference_acceptance_files": not no_acceptance})

    # ── ④ 接收端：干净引擎 + 安装包
    install = os.path.join(out, "install")
    shutil.copytree(engine, install)
    r = run([PY, os.path.join("tools", "fetch-corpus.py"), "--pack", pack,
             "--manifest", pman, "--into", ".", "--force"], install)
    record("④ 安装 demo 包（逐文件校验 + --force 覆盖参考元数据）", r["exit"] == 0,
           {"tail": r["stdout"][-600:], "stderr": r["stderr"][-300:]})

    # ── ⑤ 逐项核验
    r = run([PY, os.path.join("tools", "ensure_corpus.py"), "--json"], install)
    try:
        st = json.loads(r["stdout"])
    except Exception:                                                       # noqa: BLE001
        st = {}
    checks["ensure_corpus"] = st
    record("⑤a ensure_corpus：ready + 档案 unreviewed-corpus",
           bool(st.get("ready")) and st.get("corpus_profile") == "unreviewed-corpus"
           and st.get("scholarly_status") == "CORPUS_HUMAN_REVIEW_NOT_AVAILABLE",
           {k: st.get(k) for k in ("ready", "passages", "corpus_profile",
                                   "scholarly_status", "human_review")})

    r = run([PY, os.path.join("_scripts", "_tools", "core_freeze.py"), "--verify"], install)
    ok_freeze = r["exit"] == 0 and "CORPUS_HUMAN_REVIEW_NOT_AVAILABLE" in r["stdout"]
    record("⑤b core_freeze --verify（档案状态如实）", ok_freeze, {"tail": r["stdout"][-300:]})

    r = run([PY, os.path.join("_scripts", "_tools", "freeze_lineage.py"), "--verify"], install)
    ok_lineage = r["exit"] == 0 and "semantic=0" in r["stdout"]
    record("⑤c freeze_lineage --verify（semantic=0）", ok_lineage,
           {"tail": r["stdout"][-300:]})

    r = run([PY, os.path.join("_scripts", "_tools", "validate_ontology_v4a1.py"), "--verify"],
            install)
    ok_onto = r["exit"] == 0 and "0 error" in r["stdout"]
    record("⑤d 本体层校验器（0 error）", ok_onto, {"tail": r["stdout"][-300:]})

    r = run([PY, os.path.join("_scripts", "_tools", "lacan-kb"), "index", "--verify"], install)
    record("⑤e 索引校验（与 canonical corpus 同步）", r["exit"] == 0,
           {"tail": r["stdout"][-200:]})

    # ── ⑥ 真跑一次研究（用接收端 vault 的 MCP 工具）
    probe = os.path.join(install, "_demo_acceptance_probe.py")
    with io.open(probe, "w", encoding="utf-8") as fh:
        fh.write('''import json, sys, os
sys.path.insert(0, os.getcwd())
from mcp_server import tools
q = sys.argv[1]
env = tools.call_tool("lacan.research", {"question": q, "provider": "mock", "language": "fr"},
                      audit=False)
if not env.get("ok"):
    print(json.dumps({"ok": False, "error": env.get("error")}, ensure_ascii=False))
    raise SystemExit(1)
a = env["result"]
print(json.dumps({"ok": True, "answer_state": a.get("answer_state"),
                  "summary": a.get("summary"),
                  "citations": [{"claim_id": c.get("claim_id"),
                                 "passage_id": c.get("passage_id"),
                                 "status": c.get("citation_status"),
                                 "span_len": len(c.get("quoted_span") or "")}
                                for c in a.get("citations") or []],
                  "claims_n": len(a.get("validated_claims") or [])},
                 ensure_ascii=False))
''')
    r = run([PY, probe, QUESTION], install, timeout=1800)
    try:
        ans = json.loads(r["stdout"].strip().splitlines()[-1])
    except Exception:                                                       # noqa: BLE001
        ans = {"ok": False, "raw": r["stdout"][-500:]}
    cites = ans.get("citations") or []
    ok_research = (r["exit"] == 0 and ans.get("ok") is True
                   and str(ans.get("answer_state", "")).startswith("VALIDATED")
                   and len(cites) >= 1
                   and all(c.get("span_len", 0) > 0 for c in cites)
                   and all(str(c.get("passage_id", "")).startswith("passage.") for c in cites))
    checks["research"] = ans
    record("⑥ 真跑研究：VALIDATED* + 真实引文", ok_research,
           {"question": QUESTION, "answer_state": ans.get("answer_state"),
            "summary": ans.get("summary"), "citations": cites})

    # ── ⑦ 诚实边界：产物里不得出现"已人工验收"的说法
    honesty = {"profile_in_freeze": None, "pack_profile": manifest.get("corpus_profile"),
               "reference_acceptance_files_present": [
                   p for p in REFERENCE_ACCEPTANCE_FILES
                   if os.path.isfile(os.path.join(install, p))]}
    fp = os.path.join(install, "_data", "core_freeze", "scholarly_core_freeze_v1.json")
    if os.path.isfile(fp):
        with io.open(fp, encoding="utf-8") as fh:
            man = json.load(fh)
        honesty["profile_in_freeze"] = man.get("corpus_profile")
        honesty["status_in_freeze"] = man.get("scholarly_status")
        honesty["absent_components_n"] = len(man.get("absent_components") or [])
    record("⑦ 诚实边界（无人工验收工件、档案如实、状态非 READY）",
           honesty["profile_in_freeze"] == "unreviewed-corpus"
           and honesty["status_in_freeze"] == "CORPUS_HUMAN_REVIEW_NOT_AVAILABLE"
           and not honesty["reference_acceptance_files_present"],
           honesty)

    report = {
        "schema_version": "demo-corpus-acceptance/v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "question": QUESTION,
        "verdict": "COMPLETE" if not failures else "FAILED",
        "steps_n": len(steps), "failed": failures,
        "steps": steps, "checks": checks,
    }
    dest = a.json_out or os.path.join(VAULT, "_data", "daily_use",
                                      "demo_corpus_acceptance.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with io.open(dest, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print("\nverdict: %s（%d 步，failed=%s）" % (report["verdict"], len(steps), failures))
    print("report → %s" % dest)
    if not a.keep and not a.out:
        shutil.rmtree(out, ignore_errors=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
