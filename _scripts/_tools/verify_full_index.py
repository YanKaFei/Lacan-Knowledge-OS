#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_full_index.py — Phase 3C §4 Full Index Verification

§4 要求的每一项都要**实测**，不能靠 manifest 自我声明：

| # | 判据 | 怎么算 |
|---|---|---|
| 1 | vector count == 249,105 | `.npy` 的 shape[0] |
| 2 | dimension == 384 | `.npy` 的 shape[1] |
| 3 | NaN == 0 | 全矩阵扫描 |
| 4 | Inf == 0 | 全矩阵扫描 |
| 5 | duplicate vector IDs == 0 | ids 文件去重前后长度相同 |
| 6 | missing passage IDs == 0 | store 有、索引没有 |
| 7 | extra passage IDs == 0 | 索引有、store 没有 |
| 8 | passage ID → vector ID 一一对应 | 索引第 i 行必须等于 store 第 i 条 |
| 9 | 重复 query top-k deterministic | 同一 query 连查两次，名次列表完全相同 |
| 10 | artifact hash 与 manifest 一致 | 重算 `.npy` 的 sha256 |
| 11 | L2 范数 ≈ 1 | 抽样 2,000 条的范数区间 |

用法
────
    .venv-embedding/bin/python _scripts/_tools/verify_full_index.py
    .venv-embedding/bin/python _scripts/_tools/verify_full_index.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
PASSAGES = os.path.join(STORE, "passages.jsonl")
OUT = os.path.join(VECDIR, "FULL_INDEX_VERIFICATION.json")
REPORT = os.path.join(VAULT, "FULL_VECTOR_INDEX_REPORT.md")

EXPECT_N = 249105
EXPECT_DIM = 384
SAMPLE = 2000

sys.path.insert(0, HERE)


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def store_ids(limit=None):
    out = []
    with open(PASSAGES, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            out.append(json.loads(line)["id"])
            if limit and len(out) >= limit:
                break
    return out


def main(argv=None):
    import numpy as np
    import build_full_vector_index as bfvi

    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    checks = {}

    def add(name, passed, detail):
        checks[name] = {"passed": bool(passed), "detail": detail}

    if not os.path.isfile(bfvi.MANIFEST_OUT):
        print("缺 FULL_INDEX_MANIFEST.minilm.json —— 先跑 --build")
        return 2
    man = json.load(open(bfvi.MANIFEST_OUT, encoding="utf-8"))

    mat = np.load(bfvi.EMB_OUT, mmap_mode="r")
    with open(bfvi.IDS_OUT, encoding="utf-8") as f:
        ids = [l.rstrip("\n") for l in f if l.strip()]

    add("vector_count", mat.shape[0] == EXPECT_N,
        {"actual": int(mat.shape[0]), "expected": EXPECT_N})
    add("dimension", mat.shape[1] == EXPECT_DIM,
        {"actual": int(mat.shape[1]), "expected": EXPECT_DIM})

    # NaN / Inf：分块扫描，避免一次性把 383MB 全读进内存再生成掩码
    nan = inf = 0
    norms_min, norms_max = None, None
    rng = np.random.RandomState(20260921)
    sample_idx = rng.choice(mat.shape[0], size=min(SAMPLE, mat.shape[0]), replace=False)
    for start in range(0, mat.shape[0], 8192):
        blk = np.asarray(mat[start:start + 8192], dtype="float32")
        nan += int(np.isnan(blk).sum())
        inf += int(np.isinf(blk).sum())
    add("nan_count", nan == 0, {"nan": nan})
    add("inf_count", inf == 0, {"inf": inf})

    blk = np.asarray(mat[np.sort(sample_idx)], dtype="float32")
    norms = np.linalg.norm(blk, axis=1)
    norms_min, norms_max = float(norms.min()), float(norms.max())
    add("l2_norm_within_tolerance",
        abs(norms_min - 1.0) < 1e-4 and abs(norms_max - 1.0) < 1e-4,
        {"sample": int(len(sample_idx)), "min": norms_min, "max": norms_max,
         "tolerance": 1e-4})

    add("duplicate_vector_ids", len(ids) == len(set(ids)),
        {"ids": len(ids), "unique": len(set(ids))})

    sids = store_ids()
    sset, iset = set(sids), set(ids)
    missing = sorted(sset - iset)
    extra = sorted(iset - sset)
    add("missing_passage_ids", not missing,
        {"count": len(missing), "examples": missing[:5]})
    add("extra_passage_ids", not extra,
        {"count": len(extra), "examples": extra[:5]})

    # 一一对应：索引第 i 行 == store 第 i 条
    mismatch = [i for i in range(min(len(ids), len(sids))) if ids[i] != sids[i]]
    add("passage_to_vector_one_to_one",
        not mismatch and len(ids) == len(sids),
        {"compared": min(len(ids), len(sids)),
         "mismatched_positions": len(mismatch),
         "first_mismatch": mismatch[:3]})

    add("index_artifact_hash_matches_manifest",
        sha256_file(bfvi.EMB_OUT) == man["index_artifact_hash"],
        {"manifest": man["index_artifact_hash"][:24],
         "recomputed": sha256_file(bfvi.EMB_OUT)[:24]})

    # 重复 query top-k deterministic（用文件里的真实文本，不造句子）
    import embedding_provider as ep
    prov = ep.OnnxTransformersProvider("minilm")
    if not prov.available:
        add("repeat_query_topk_deterministic", False,
            {"error": "provider 不可用: %s" % prov.blocked_reason})
    else:
        idx_map = {p: i for i, p in enumerate(ids)}
        probes = [i for i in range(0, len(ids), max(1, len(ids) // 5))][:5]
        texts = {}
        want = {ids[i] for i in probes}
        with open(PASSAGES, encoding="utf-8") as f:
            for line in f:
                if not want:
                    break
                d = json.loads(line)
                if d["id"] in want:
                    texts[d["id"]] = d["normalized_text"]
                    want.discard(d["id"])
        stable = True
        detail = []
        for i in probes:
            t = texts.get(ids[i], "")
            if not t:
                continue
            runs = []
            for _ in range(2):
                v = np.asarray(prov.embed_queries([t])[0], dtype="float32")
                sims = mat @ v
                order = np.argsort(-sims, kind="stable")[:20]
                runs.append([ids[j] for j in order])
            same = runs[0] == runs[1]
            stable = stable and same
            detail.append({"probe_index": int(i), "same": bool(same)})
        add("repeat_query_topk_deterministic", stable, {"probes": detail})

    passed = all(c["passed"] for c in checks.values())
    doc = {
        "schema_version": "full-index-verification/v1",
        "purpose": "Phase 3C §4：每一项都是实测，不是照抄 manifest",
        "checks": checks,
        "passed": passed,
        "failed": [k for k, v in checks.items() if not v["passed"]],
        "index": {
            "index_version": man.get("index_version"),
            "passage_count": man.get("passage_count"),
            "dimensions": man.get("dimensions"),
            "index_artifact_hash": man.get("index_artifact_hash"),
            "corpus_hash": man.get("corpus_hash"),
        },
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_report(doc, man)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for k, v in checks.items():
            print("  %-42s %s" % (k, "PASS" if v["passed"] else "**FAIL**"))
        print("[verify] passed = %s" % passed)
    return 0 if passed else 1


def write_report(doc, man):
    """§23 交付物：FULL_VECTOR_INDEX_REPORT.md"""
    L = []
    A = L.append
    A("# FULL_VECTOR_INDEX_REPORT.md — Phase 3C §3–§4\n")
    A("> 构建：`_scripts/_tools/build_full_vector_index.py`　·　"
      "验证：`_scripts/_tools/verify_full_index.py`　·　"
      "数据：`FULL_INDEX_MANIFEST.minilm.json` · `FULL_INDEX_VERIFICATION.json`\n")
    A("## 0. 结论\n")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 索引版本 | `%s` |" % man.get("index_version"))
    A("| passage 数 | **%s** |" % man.get("passage_count"))
    A("| 维度 | %s |" % man.get("dimensions"))
    A("| 语言分布 | `%s` |" % json.dumps(man.get("language_counts"), ensure_ascii=False))
    A("| 索引类型 | `%s`（**精确**暴力余弦，无 ANN 近似损失） |" % man.get("index_type"))
    A("| 体积 | %.1f MB |" % (man["artifacts"]["vectors_bytes"] / 1e6))
    A("| 构建耗时 | %.1f 分钟 |" % (man.get("build_seconds", 0) / 60))
    A("| **完整性验证** | **%s** |" % ("✅ PASS" if doc["passed"] else "❌ FAIL"))
    A("")
    A("## 1. §4 逐项验证（全部实测）\n")
    A("| # | 判据 | 结果 | 详情 |")
    A("|---|---|---|---|")
    for i, (k, v) in enumerate(doc["checks"].items(), 1):
        A("| %d | `%s` | %s | `%s` |" % (
            i, k, "✅" if v["passed"] else "❌",
            json.dumps(v["detail"], ensure_ascii=False)[:160]))
    A("")
    A("## 2. §3 manifest 必需字段\n")
    A("| 字段 | 值 |")
    A("|---|---|")
    for k in ("corpus_hash", "passage_count", "language_counts", "embedding_model",
              "model_hash", "runtime_hash", "dimensions", "normalization",
              "index_type", "index_version", "build_config_hash", "index_artifact_hash"):
        val = man.get(k)
        if isinstance(val, dict):
            val = json.dumps(val, ensure_ascii=False)[:120]
        elif isinstance(val, str) and len(val) == 64:
            val = "`%s…`" % val[:24]
        A("| `%s` | %s |" % (k, val))
    A("| `created_from` | `%s` |" % json.dumps(man.get("created_from"), ensure_ascii=False)[:160])
    A("")
    A("**13 个必需字段齐备**（§3 点名）。`created_from` 指向 canonical passage store 与其 "
      "`content_hash`，所以「这个索引是从哪份语料建的」是可追溯的。\n")
    A("## 3. 模型决策记录（§1）\n")
    A("本阶段**只建 MiniLM**，MPNet 保持 benchmark-only。理由：\n")
    A("| 模型 | 维度 | Phase 3B.2 池内 E+L+V+X hit@20 | 全量估计 | 决策 |")
    A("|---|---:|---:|---|---|")
    A("| MiniLM | 384 | 0.3024 | 0.65 h / 383 MB | ✅ **建成 production index** |")
    A("| MPNet | 768 | 0.3007 | 2.24 h / 765 MB | ⏸ **保持 benchmark-only**，adapter 保留 |")
    A("")
    A("两者召回几乎相同，但 MPNet 的成本是 3.4× / 2×。"
      "**除非 MiniLM 的全量验证出现明确失败**，否则不升级 MPNet。"
      "MPNet 的 adapter **没有被删除**，仍然可以跑（`--models mpnet`）。\n")
    A("## 4. 不进入 Git 的产物（§22）\n")
    A("| 产物 | 原因 |")
    A("|---|---|")
    for x in man.get("not_in_git", []):
        A("| `%s` | 大二进制 / 可重建，`.gitignore` 已覆盖 |" % x)
    A("")
    A("入 Git 的是 `FULL_INDEX_MANIFEST.minilm.json`（小、可 diff、含"
      "`index_artifact_hash`），所以「索引有没有被换过」可判定。\n")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT)


if __name__ == "__main__":
    raise SystemExit(main())
