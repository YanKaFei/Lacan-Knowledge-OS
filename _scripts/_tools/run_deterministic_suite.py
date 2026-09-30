#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_deterministic_suite.py — Phase 3C §21 完整跑一次 test_phase2_deterministic

§21 原文：
> 此前 `test_phase2_deterministic` 有 5 项因每项执行完整 build、总耗时较长而未完整运行。
> 在 Phase 3 最终关闭前：**至少完整执行一次整个 deterministic suite**。
> 不要每次开发循环都运行完整长测试。但**最终 gate 不允许只用单元级替代**。

所以这个脚本**不做任何替代**：它就把整个套件跑完，记录退出码与耗时，
落 `_data/index/DETERMINISTIC_SUITE_RUN.json`。

耗时来源（**实测**，不是估计）：完整 `build.py` 约 **66 秒**，
套件里 7 个测试合计实测 **约 8 分钟**（487 秒）。
（旧注释里写的「每次 17 分钟 / 整个 100 分钟」是错的 —— 那是冷缓存的第一次构建数字，
后续构建走 Passage Store 的约定快速路径。）

用法
────
    python3 _scripts/_tools/run_deterministic_suite.py          # 跑（约 100 分钟）
    python3 _scripts/_tools/run_deterministic_suite.py --verify  # 只核记录
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TESTS = os.path.join(VAULT, "_scripts", "_tests")
OUT = os.path.join(VAULT, "_data", "index", "DETERMINISTIC_SUITE_RUN.json")
SUITE = "test_phase2_deterministic"


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)

    if a.verify:
        if not os.path.isfile(OUT):
            print(json.dumps({"status": "FAIL",
                              "problems": ["缺 DETERMINISTIC_SUITE_RUN.json"]},
                             ensure_ascii=False, indent=1))
            return 1
        d = json.load(open(OUT, encoding="utf-8"))
        ok = d.get("exit_code") == 0 and d.get("complete") is True
        print(json.dumps({"status": "PASS" if ok else "FAIL",
                          "exit_code": d.get("exit_code"),
                          "complete": d.get("complete"),
                          "ran_tests": d.get("ran_tests"),
                          "seconds": d.get("seconds")},
                         ensure_ascii=False, indent=1))
        return 0 if ok else 1

    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "unittest", "-v", SUITE],
                       cwd=TESTS, capture_output=True, text=True)
    dt = time.time() - t0
    tail = (r.stderr or "")[-4000:]
    ran = None
    for line in (r.stderr or "").splitlines():
        if line.startswith("Ran ") and " test" in line:
            try:
                ran = int(line.split()[1])
            except Exception:
                pass
    expected = 7
    doc = {
        "schema_version": "deterministic-suite-run/v1",
        "purpose": ("§21：Phase 3 关闭前**完整**跑一次 deterministic suite，"
                    "不允许只用单元级替代。"),
        "suite": SUITE,
        "exit_code": r.returncode,
        "complete": (ran is not None and ran >= expected and r.returncode == 0),
        "ran_tests": ran,
        "expected_tests": expected,
        "seconds": dt,
        "minutes": dt / 60,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "why_slow": ("该套件有 7 个测试各自调用一次 build.py，实测整套约 8 分钟。"
                     "⚠️ 默认 build 走 Passage Store 快速路径（源未变则不重写 373MB），"
                     "所以它证明的是「已提交状态跑一次默认 build 无 diff」；"
                     "真实重派生证据见 _data/index/FULL_REDERIVATION.json。"),
        "stderr_tail": tail,
        "note": ("`complete` 要求：跑到 ≥7 个测试且退出码为 0。"
                 "只跑了一部分不算通过。"),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[deterministic] exit=%s ran=%s complete=%s %.1f min" % (
        r.returncode, ran, doc["complete"], dt / 60))
    print(tail[-1500:])
    return 0 if doc["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
