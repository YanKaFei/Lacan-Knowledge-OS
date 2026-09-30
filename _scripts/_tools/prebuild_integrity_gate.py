#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prebuild_integrity_gate.py — Phase 3C §2 Pre-build Integrity Gate

**全量 embedding 之前的最后一道门。任何一项不通过就停，不开始构建。**

判据（全部来自实测，不接受自我声明）
────────────────────────────────────
| # | 判据 | 数据来源 |
|---|---|---|
| 1 | canonical passage count == 249,105 | `_build_meta.json` + 一次真实计数 |
| 2 | zh == 82,578 | 同上 |
| 3 | fr == 166,527 | 同上 |
| 4 | source hash 未改变 | atlas 源文件 sha256 vs `_build_meta.source_files` |
| 5 | model manifest hash 未改变 | `build_model_manifest.py --verify` |
| 6 | runtime parity 仍通过 | `check_reference_parity.py --verify` |
| 7 | MiniLM reference cosine ≥ 冻结阈值 | `RUNTIME_PARITY_MANIFEST.thresholds.min_cosine` |
| 8 | embedding dimension == 384 | ONNX 输出维度 |

为什么这些必须**先**过：全量构建要跑约 40–60 分钟。如果语料被换过、
模型文件被换过、或 parity 已经不成立，那 40–60 分钟产出的是一个**来源不明**的
383 MB 二进制 —— 而且它看起来一切正常。所以门必须在前面。

用法
────
    python3 _scripts/_tools/prebuild_integrity_gate.py            # 跑并打印
    python3 _scripts/_tools/prebuild_integrity_gate.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
ATLAS = os.path.expanduser("<HOME>")
OUT = os.path.join(VECDIR, "PREBUILD_INTEGRITY_GATE.json")

EXPECT_TOTAL = 249105
EXPECT_ZH = 82578
EXPECT_FR = 166527
MODEL_KEY = "minilm"
EXPECT_DIM = 384


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def count_passages():
    """真实数一遍 passages.jsonl —— 不信任何缓存里的数字。"""
    total = 0
    by_lang = {}
    p = os.path.join(STORE, "passages.jsonl")
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            total += 1
            lang = json.loads(line).get("language")
            by_lang[lang] = by_lang.get(lang, 0) + 1
    return total, by_lang


def run_tool(script, args):
    r = subprocess.run([sys.executable, os.path.join(HERE, script)] + args,
                       capture_output=True, text=True)
    body = r.stdout[r.stdout.find("{"):] if "{" in r.stdout else ""
    try:
        return json.loads(body), r.returncode
    except Exception:
        return None, r.returncode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    checks = {}

    def add(name, passed, detail):
        checks[name] = {"passed": bool(passed), "detail": detail}

    bm = json.load(open(os.path.join(STORE, "_build_meta.json"), encoding="utf-8"))
    declared = bm["counts"]

    total, by_lang = count_passages()
    add("passage_count", total == EXPECT_TOTAL,
        {"actual": total, "expected": EXPECT_TOTAL,
         "declared_in_meta": declared.get("passages")})
    add("language_zh", by_lang.get("zh") == EXPECT_ZH,
        {"actual": by_lang.get("zh"), "expected": EXPECT_ZH})
    add("language_fr", by_lang.get("fr") == EXPECT_FR,
        {"actual": by_lang.get("fr"), "expected": EXPECT_FR})

    mut = []
    for name, rec in (bm.get("source_files") or {}).items():
        p = os.path.join(ATLAS, name)
        if not os.path.isfile(p) or sha256_file(p) != rec.get("sha256"):
            mut.append(name)
    add("source_hash_unchanged", not mut,
        {"atlas": ATLAS, "files_checked": list((bm.get("source_files") or {}).keys()),
         "mutated": mut})

    mm, rc = run_tool("build_model_manifest.py", ["--verify"])
    add("model_manifest_hash_unchanged", bool(mm and mm.get("status") == "PASS"),
        {"verify_status": (mm or {}).get("status"),
         "files_checked": (mm or {}).get("files_checked"),
         "problems": (mm or {}).get("problems")})

    par, rc2 = run_tool("check_reference_parity.py", ["--verify"])
    add("runtime_parity_still_passes",
        bool(par and par.get("status") == "PASS"),
        {"verify_status": (par or {}).get("status"),
         "overall": (par or {}).get("overall_status"),
         "problems": (par or {}).get("problems")})

    pm = json.load(open(os.path.join(VECDIR, "RUNTIME_PARITY_MANIFEST.json"),
                        encoding="utf-8"))
    thr = (pm.get("thresholds") or {}).get("min_cosine")
    cos = ((pm.get("models") or {}).get(MODEL_KEY) or {}).get("cosine_min")
    add("minilm_reference_cosine_above_frozen_threshold",
        cos is not None and thr is not None and cos >= thr,
        {"model": MODEL_KEY, "cosine_min": cos,
         "frozen_threshold": thr,
         "threshold_source": "RUNTIME_PARITY_MANIFEST.thresholds.min_cosine"})

    # dim：从**两个互相独立**的来源取，必须都是 384
    #   ① config.json 声明（embedding_provider.ONNX_REGISTRY 实读而来）
    #   ② RUNTIME_PARITY_MANIFEST 里 ONNX 的**实际输出**维度（sentence-transformers 比对过）
    sys.path.insert(0, HERE)
    import embedding_provider as ep
    meta = ep.ONNX_REGISTRY[MODEL_KEY]
    declared_dim = meta["dimensions"]
    onnx_dim = (((pm.get("models") or {}).get(MODEL_KEY) or {}).get("dims") or {}).get("onnx")
    add("minilm_dimension_384",
        declared_dim == EXPECT_DIM and onnx_dim == EXPECT_DIM,
        {"expected": EXPECT_DIM,
         "config_json_dimension": declared_dim,
         "onnx_actual_output_dimension": onnx_dim,
         "source_1": "embedding_provider.ONNX_REGISTRY（实读 config.json）",
         "source_2": "RUNTIME_PARITY_MANIFEST.models.minilm.dims.onnx（ONNX 实跑输出）"})

    # 运行时可导入性是**门的前置条件**，不是维度问题 —— 必须说清楚，否则会误诊
    try:
        import onnxruntime  # noqa: F401
        add("runtime_importable", True,
            {"interpreter": sys.executable, "note": "onnxruntime 可导入"})
    except Exception as e:
        add("runtime_importable", False,
            {"interpreter": sys.executable,
             "error": "%s: %s" % (type(e).__name__, e),
             "fix": "用 .venv-embedding/bin/python 跑本门（这是运行时门，不是纯静态门）"})

    passed = all(c["passed"] for c in checks.values())
    doc = {
        "schema_version": "prebuild-integrity-gate/v1",
        "purpose": ("Phase 3C §2：全量 embedding 之前的最后一道门。"
                    "任何一项不通过 → **停止 full build**。"),
        "model_to_build": MODEL_KEY,
        "checks": checks,
        "passed": passed,
        "failed": [k for k, v in checks.items() if not v["passed"]],
        "action_on_failure": "STOP_FULL_BUILD",
        "counts_expected": {"total": EXPECT_TOTAL, "zh": EXPECT_ZH, "fr": EXPECT_FR},
        "counts_actual": {"total": total, **by_lang},
    }
    os.makedirs(VECDIR, exist_ok=True)
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for k, v in checks.items():
            print("  %-46s %s" % (k, "PASS" if v["passed"] else "**FAIL**"))
        print("[gate] passed = %s" % passed)
        if not passed:
            print("[gate] FAILED: %s" % doc["failed"])
            print("[gate] → 停止 full build，不产出任何 index artifact。")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
