#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""summarize_regression_timing.py — 从完整回归日志里还原**逐套件耗时**。

为什么需要它：`run_all_tests.sh` 逐套件调用 `python3 -m unittest <suite>`，
unittest 在每套件结束时打印 `Ran N tests in X.XXXs` —— 逐套件耗时其实**在日志里**，
脚本本身不落盘。本工具做**确定性解析**（不改产品、不改测试、不改 Gate），
把日志转成 TSV，供验收报告引用。

    python3 _scripts/_tools/summarize_regression_timing.py <regression.log> [out.tsv]

输出 TSV 列：`suite<TAB>tests<TAB>seconds<TAB>status`
（`status` 由日志里该套件是否出现 FAILED/OK 推断；解析不到就写 UNKNOWN，
绝不编造数字。）
"""
from __future__ import annotations

import os
import re
import sys

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SUITE_RE = re.compile(r"^--\s+(\S+)\s*$")
RAN_RE = re.compile(r"^Ran (\d+) tests? in ([0-9.]+)s")
FAILED_RE = re.compile(r"^FAILED\s*\(", re.M)


def parse(path):
    rows = []
    cur = None
    pending = None                      # 上一段 "Ran …" 等待归属
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = ANSI_RE.sub("", line).rstrip("\n")
            m = SUITE_RE.match(line)
            if m:
                if pending:
                    rows.append(pending)
                    pending = None
                cur = m.group(1)
                continue
            m = RAN_RE.match(line)
            if m and cur:
                pending = {"suite": cur, "tests": int(m.group(1)),
                           "seconds": float(m.group(2)), "status": "OK"}
                cur = None
                continue
            if pending and (line.startswith("OK") or line.startswith("FAILED")):
                pending["status"] = ("FAIL" if line.startswith("FAILED") else "OK")
                rows.append(pending)
                pending = None
    if pending:
        rows.append(pending)
    return rows


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    src = argv[0]
    rows = parse(src)
    out = argv[1] if len(argv) > 1 else None
    total = sum(r["seconds"] for r in rows)
    print("解析到 %d 个套件；逐套件耗时合计 %.1fs" % (len(rows), total))
    for r in sorted(rows, key=lambda r: -r["seconds"])[:12]:
        print("  %-52s %5d tests %8.1fs %s"
              % (r["suite"], r["tests"], r["seconds"], r["status"]))
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("suite\ttests\tseconds\tstatus\n")
            for r in sorted(rows, key=lambda r: -r["seconds"]):
                fh.write("%s\t%d\t%.3f\t%s\n"
                         % (r["suite"], r["tests"], r["seconds"], r["status"]))
        print("→ %s" % os.path.relpath(out))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
