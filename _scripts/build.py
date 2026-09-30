#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — 构建编排入口（Phase 2）

把整条派生链按**固定顺序**跑一遍：

    1. inventory_corpus.py    只读盘点源语料 → _data/corpus_inventory.{json,csv} + corpus_report.md
    2. audit_recoverable_corpus.py  → _data/recoverable_corpus.json
    3. build_passage_store.py  → _data/passage_store/{passages,witnesses,translations,alignments,claims}.jsonl
                                 + _index/passage_store.sqlite
    4. render_vault.py         → 02_Lacan_Seminars/**（Seminar / Session / Passage heading）
    5. validate_vault.py       → _index/Reports/validation-report.{md,json}
    6. make_index.py           → _index/Views/*.md

用法
────
    python3 _scripts/build.py              # 默认：确定性（重跑无 diff）
    python3 _scripts/build.py --stamp      # 刷新 generated_at 为真实时间
    python3 _scripts/build.py --skip-slow  # 跳过需要重扫 1.2GB 的 inventory
    python3 _scripts/build.py --only 3,4   # 只跑指定步骤（调试用）

退出码：0 全部成功；非 0 表示某步失败（并打印是哪一步）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(VAULT, "_scripts")
TOOLS = os.path.join(SCRIPTS, "_tools")

# (编号, 名称, 脚本相对路径, 是否耗时)
STEPS = [
    (1, "inventory",            os.path.join(SCRIPTS, "inventory_corpus.py"), True),
    (2, "recoverable-audit",    os.path.join(TOOLS, "audit_recoverable_corpus.py"), False),
    (3, "passage-store",        os.path.join(TOOLS, "build_passage_store.py"), False),
    (4, "concepts-claims-align", os.path.join(TOOLS, "seed_concepts_and_claims.py"), False),
    (5, "render-vault",         os.path.join(TOOLS, "render_vault.py"), False),
    (6, "validate",             os.path.join(TOOLS, "validate_vault.py"), False),
    (7, "index-views",          os.path.join(TOOLS, "make_index.py"), False),
]


def main():
    ap = argparse.ArgumentParser(description="Lacan OS 派生链构建（确定性）")
    ap.add_argument("--stamp", action="store_true",
                    help="刷新 generated_at 为真实时间（默认内容推导）")
    ap.add_argument("--skip-slow", action="store_true",
                    help="跳过需要重扫源语料的步骤（inventory，约 1-2 分钟）")
    ap.add_argument("--only", default="", help="只跑指定步骤，如 3,4")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    failed = []

    for num, name, script, slow in STEPS:
        if wanted and str(num) not in wanted:
            continue
        if args.skip_slow and slow:
            if not args.quiet:
                print(f"[{num}/{len(STEPS)}] {name:18s} SKIP (--skip-slow)")
            continue
        if not os.path.isfile(script):
            # 尚未实现的步骤：显式跳过而不是假装成功
            if not args.quiet:
                print(f"[{num}/{len(STEPS)}] {name:18s} SKIP (未实现: "
                      f"{os.path.relpath(script, VAULT)})")
            continue

        cmd = [sys.executable, script]
        if args.stamp:
            cmd.append("--stamp")
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=VAULT)
        if r.returncode != 0:
            print(f"[{num}/{len(STEPS)}] {name:18s} FAILED (exit {r.returncode})",
                  file=sys.stderr)
            print(r.stdout[-1500:], file=sys.stderr)
            print(r.stderr[-1500:], file=sys.stderr)
            failed.append((num, name))
        elif not args.quiet:
            print(f"[{num}/{len(STEPS)}] {name:18s} OK")

    if failed:
        print(f"\n构建失败: {failed}", file=sys.stderr)
        return 1
    if not args.quiet:
        mode = "stamped" if args.stamp else "deterministic"
        print(f"\n构建完成（{mode}）。重跑应当无 git diff。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
