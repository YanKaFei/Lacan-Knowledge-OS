#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_regression.py — Phase 4E §44：全量回归并把结果记成 `_data/phase4e/regression.json`。

复用 4D.7 的 `product_acceptance.run_regression()`（不修改它）：它跑
`bash _scripts/run_all_tests.sh`（完整模式），抓 exit / suites / checks /
failed / skipped / 墙钟 / 逐套件耗时，并写回归日志。

用法：
    python3 _scripts/_tools/phase4e_regression.py [--out-dir _data/phase4e/regression_<ts>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tests"))

import product_acceptance as PA                      # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E full regression record")
    ap.add_argument("--out-dir", default=None)
    # 默认仍是 Phase 4E 的固定记录位（保持 4E 复现路径不变）；
    # Phase 5A 等后续阶段必须显式 --record，避免把上一阶段的回归记录覆盖掉。
    ap.add_argument("--record", default=os.path.join(VAULT, "_data", "phase4e",
                                                     "regression.json"))
    # 后续阶段（Phase 5A 等）复用本工具时，如实标注这是哪一阶段的回归
    ap.add_argument("--phase", default="Phase 4E")
    ap.add_argument("--purpose", default=("CCR-0001 remediation verification"
                                          "（含新增 4E 套件与 4E 工件完整性校验）"))
    a = ap.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = a.out_dir or os.path.join(VAULT, "_data", "phase4e", "regression_%s" % stamp)
    os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)

    rec = PA.run_regression(out_dir)
    rec["phase"] = a.phase
    rec["purpose"] = a.purpose
    rec["out_dir"] = os.path.relpath(out_dir, VAULT)
    # ① 记录位（可由 --record 指定）
    dst = a.record if os.path.isabs(a.record) else os.path.join(VAULT, a.record)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    # ② 本次 run 的 out_dir 里再存一份（run 工件自证，不依赖全局记录位）
    with open(os.path.join(out_dir, "regression.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print("regression: exit=%s suites=%s checks=%s failed=%s skipped=%s（%.0fs）"
          % (rec.get("exit_code"), rec.get("suites"), rec.get("checks"),
             rec.get("failed") or [], rec.get("skipped") or [],
             rec.get("wall_clock_seconds") or 0))
    print("-> %s" % os.path.relpath(dst, VAULT))
    return 0 if (rec.get("exit_code") == 0 and not rec.get("failed")
                 and not rec.get("skipped")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
