#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5a_timing.py — §38：把完整回归的耗时**真实落盘**（不估算）。

数据来源（全部是已落盘的真实工件，本工具不重新计时、不推算）：

    _data/phase5a/regression.json        run_regression 的记录（wall clock / suite_timing）
    <run_dir>/logs/suite_timing.tsv      逐套件 TSV（若存在，作为交叉核对）

输出 `_data/phase5a/regression_timing.json`：
    total_wall_clock_s / suites_n / checks_n / failed / skipped / exit_code
    top_slow_suites / median_s / p95_s / p95_meaningful / buckets / retry_count

**数据不足时如实写 UNKNOWN**，绝不估算。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
P5A = os.path.join(VAULT, "_data", "phase5a")


def jd(p, d=None):
    if not os.path.isfile(p):
        return d
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def percentile(vals, q):
    """线性插值分位（样本 < 4 时返回 None —— 分位数没有意义，不硬算）。"""
    if not vals:
        return None
    if len(vals) < 4:
        return None
    xs = sorted(vals)
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return round(xs[lo] * (1 - frac) + xs[hi] * frac, 3)


def timing_classify(sec):
    if sec < 1.5:
        return "interactive-fast"
    if sec < 30:
        return "interactive-wait"
    if sec < 300:
        return "provider-bound"
    return "batch"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--regression", default=os.path.join(P5A, "regression.json"))
    ap.add_argument("--out", default=os.path.join(P5A, "regression_timing.json"))
    ap.add_argument("--label", default="Phase 5A acceptance regression")
    a = ap.parse_args(argv)

    reg = jd(a.regression)
    if not reg:
        print("缺回归记录：%s" % os.path.relpath(a.regression, VAULT))
        return 2
    timing = reg.get("suite_timing") or []
    durs = [float(t.get("duration") or 0) for t in timing]
    buckets = {}
    for t in timing:
        b = t.get("class") or timing_classify(float(t.get("duration") or 0))
        buckets[b] = buckets.get(b, 0) + 1

    tsv = os.path.join(VAULT, reg.get("out_dir") or "", "logs", "suite_timing.tsv")
    tsv_rows = None
    if os.path.isfile(tsv):
        tsv_rows = sum(1 for ln in open(tsv, encoding="utf-8") if ln.strip()) - 1

    rec = {
        "schema_version": "phase5a-regression-timing/v1",
        "label": a.label,
        "source_regression": os.path.relpath(a.regression, VAULT),
        "source_run_dir": reg.get("out_dir"),
        "total_wall_clock_s": reg.get("wall_clock_seconds"),
        "suites_n": reg.get("suites"),
        "checks_n": reg.get("checks"),
        "failed": reg.get("failed") or [],
        "skipped": reg.get("skipped") or [],
        "exit_code": reg.get("exit_code"),
        "head_before": reg.get("head_before"),
        "head_after": reg.get("head_after"),
        "recorded_at": reg.get("recorded_at"),
        "suites_with_timing_n": len(timing),
        "suite_seconds_sum": round(sum(durs), 1) if durs else None,
        "top_slow_suites": [
            {"suite": t.get("suite_name"), "seconds": t.get("duration"),
             "class": t.get("class"), "status": t.get("status")}
            for t in timing[:12]],
        "median_s": None if not durs else round(sorted(durs)[len(durs) // 2], 3),
        "p95_s": percentile(durs, 0.95),
        "p95_meaningful": len(durs) >= 4,
        "buckets": buckets,
        "retry_count": sum(int(t.get("retry_count") or 0) for t in timing),
        "retry_note": ("run_all_tests.sh 的逐套件驱动不做重试；"
                       "浏览器 settle 重试由 product_acceptance 的 Runner 记录，"
                       "不在本回归里"),
        "tsv_rows_n": tsv_rows,
        "notes": [
            "只测量 + 分类，不设拍脑袋阈值；机器高负载只解释「为什么慢」，不当产品缺陷。",
            "wall clock 来自 run_regression 的真实计时（不是各套件之和 —— "
            "后者不含进程启动与 shell 开销）。",
            "样本 < 4 时 p95 无意义，如实置 null。",
        ],
    }
    if not durs:
        rec["median_s"] = "UNKNOWN"
        rec["retry_count"] = "UNKNOWN"
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print("timing -> %s" % os.path.relpath(a.out, VAULT))
    print("  wall_clock=%ss | suites=%s checks=%s failed=%s skipped=%s"
          % (rec["total_wall_clock_s"], rec["suites_n"], rec["checks_n"],
             rec["failed"], rec["skipped"]))
    print("  median=%ss p95=%ss（meaningful=%s）| buckets=%s | retries=%s"
          % (rec["median_s"], rec["p95_s"], rec["p95_meaningful"],
             rec["buckets"], rec["retry_count"]))
    for t in rec["top_slow_suites"][:5]:
        print("  %-52s %8.1fs %s" % (t["suite"], t["seconds"] or 0, t["class"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
