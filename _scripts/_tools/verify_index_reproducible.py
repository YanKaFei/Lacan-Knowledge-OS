#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_index_reproducible.py — Phase 3C §24 第 2 条「Vector index 可从 canonical corpus 重建」

判据必须是**真的重建一次再比**，不能靠「配置固定所以应该一样」。

做法
────
1. 第二次独立构建写到**另一组产物**（`--out-suffix _rebuild`），不覆盖第一次；
2. 比对两份 manifest 的 `index_artifact_hash` 与 `ids_sha256`；
3. 比对 corpus_hash / model_hash / runtime_hash / build_config_hash / dimensions；
4. 逐条比对 ids 列表（顺序也必须是同一个）。

任一项不同 → `passed = false`，Phase 3 不得关闭。

用法
────
    # 先做第二次构建（约 1 小时）
    .venv-embedding/bin/python _scripts/_tools/build_full_vector_index.py --build --out-suffix _rebuild
    # 再比对
    python3 _scripts/_tools/verify_index_reproducible.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
OUT = os.path.join(VECDIR, "FULL_INDEX_REPRODUCIBILITY.json")

PRIMARY = os.path.join(VECDIR, "FULL_INDEX_MANIFEST.minilm.json")
REBUILD = os.path.join(VECDIR, "FULL_INDEX_MANIFEST_rebuild.minilm.json")
IDS_A = os.path.join(VECDIR, "full_index_minilm.ids.txt")
IDS_B = os.path.join(VECDIR, "full_index_minilm_rebuild.ids.txt")


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    checks = {}

    def add(name, passed, detail):
        checks[name] = {"passed": bool(passed), "detail": detail}

    if not (os.path.isfile(PRIMARY) and os.path.isfile(REBUILD)):
        doc = {"schema_version": "index-reproducibility/v1", "passed": False,
               "reason": "缺一次独立重建的 manifest —— 先跑 "
                         "`build_full_vector_index.py --build --out-suffix _rebuild`",
               "checks": {}}
        json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps(doc, ensure_ascii=False, indent=1)[:600])
        return 2

    A = json.load(open(PRIMARY, encoding="utf-8"))
    B = json.load(open(REBUILD, encoding="utf-8"))

    for key in ("index_artifact_hash", "corpus_hash", "model_hash", "runtime_hash",
                "build_config_hash", "dimensions", "passage_count", "index_version"):
        add("same__%s" % key, A.get(key) == B.get(key),
            {"primary": A.get(key), "rebuild": B.get(key)})

    add("same__ids_sha256",
        A["artifacts"]["ids_sha256"] == B["artifacts"]["ids_sha256"],
        {"primary": A["artifacts"]["ids_sha256"][:24],
         "rebuild": B["artifacts"]["ids_sha256"][:24]})

    # ids 逐条比对（顺序也要一致）
    if os.path.isfile(IDS_A) and os.path.isfile(IDS_B):
        with open(IDS_A, encoding="utf-8") as f:
            ia = [l.rstrip("\n") for l in f if l.strip()]
        with open(IDS_B, encoding="utf-8") as f:
            ib = [l.rstrip("\n") for l in f if l.strip()]
        same = ia == ib
        add("same__ids_list_in_order", same,
            {"primary_n": len(ia), "rebuild_n": len(ib),
             "first_diff": next((i for i in range(min(len(ia), len(ib)))
                                 if ia[i] != ib[i]), None)})
    else:
        add("same__ids_list_in_order", False, {"error": "缺 ids 文件"})

    passed = all(c["passed"] for c in checks.values())
    doc = {
        "schema_version": "index-reproducibility/v1",
        "purpose": ("§24 第 2 条：从 canonical corpus **真的重建一次**，"
                    "逐项比对两份产物。不是「配置固定所以应该一样」。"),
        "primary_manifest": os.path.relpath(PRIMARY, VAULT),
        "rebuild_manifest": os.path.relpath(REBUILD, VAULT),
        "checks": checks,
        "passed": passed,
        "failed": [k for k, v in checks.items() if not v["passed"]],
        "primary_build_seconds": A.get("build_seconds"),
        "rebuild_build_seconds": B.get("build_seconds"),
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for k, v in checks.items():
            print("  %-34s %s" % (k, "PASS" if v["passed"] else "**FAIL**"))
        print("[reproducible] passed = %s" % passed)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
