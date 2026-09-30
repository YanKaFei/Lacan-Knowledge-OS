#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_full_vector_index.py — Phase 3C §3 Full-Corpus MiniLM Vector Index

必须用 `.venv-embedding/bin/python` 跑。

    .venv-embedding/bin/python _scripts/_tools/build_full_vector_index.py --build
    .venv-embedding/bin/python _scripts/_tools/build_full_vector_index.py --verify

设计纪律
────────
* **前置门**：`--build` 之前先跑 `prebuild_integrity_gate.py`；不过就不动工。
* **不改 canonical store**：只读 `passages.jsonl`，产物全部写在 `_data/index/vector/`。
* **derived artifact**：`.npy`（383 MB）与 ids 文本文件都**不入 Git**；
  入 Git 的是 `FULL_INDEX_MANIFEST.minilm.json`（小、可 diff、含 13 个必需字段）。
* **可续跑**：写 memmap + `progress` 边车。40 分钟的任务中断一次不该从零开始。
  续跑要求顺序完全一致 —— 顺序就是 `passages.jsonl` 的行序（确定性的），
  并且记录已完成的前缀 hash，续跑时校验。
* **确定性**：固定 batch、固定线程数（4，实测与 1 线程 top-k 完全一致）、
  固定 chunk；`index_artifact_hash` 是对最终 `.npy` 的 sha256。
* **不做 ANN**：`index_type = flat-float32-memmap`。这是**精确**检索（暴力余弦），
  在 249,105×384 上一次 matmul 约几十毫秒，不需要 ANN，也就没有近似召回损失。

13 个必需字段（§3）
───────────────────
corpus_hash · passage_count · language_counts · embedding_model · model_hash ·
runtime_hash · dimensions · normalization · index_type · index_version ·
build_config_hash · created_from · index_artifact_hash
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
PASSAGES = os.path.join(STORE, "passages.jsonl")

MODEL_KEY = "minilm"
INDEX_VERSION = "full-minilm-flat-v1"
CHUNK = 2048
BATCH = 16
THREADS = 4
EMB_OUT = os.path.join(VECDIR, "full_index_minilm.npy")
IDS_OUT = os.path.join(VECDIR, "full_index_minilm.ids.txt")
PROGRESS = os.path.join(VECDIR, "full_index_minilm.progress.json")
MANIFEST_OUT = os.path.join(VECDIR, "FULL_INDEX_MANIFEST.minilm.json")
GATE = os.path.join(VECDIR, "PREBUILD_INTEGRITY_GATE.json")

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


def sha256_lines(seq):
    h = hashlib.sha256()
    for s in seq:
        h.update(s.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def runtime_hash():
    """运行时指纹：锁文件 + wheelhouse + 三个包的版本，一起哈希。"""
    import numpy as np
    import onnxruntime
    import tokenizers
    payload = {
        "lock_sha256": sha256_file(os.path.join(VAULT, "embedding-runtime-requirements.lock")),
        "wheelhouse_hash": json.load(open(os.path.join(VAULT, "WHEELHOUSE_MANIFEST.json"),
                                          encoding="utf-8"))["wheelhouse_hash"],
        "numpy": np.__version__,
        "onnxruntime": onnxruntime.__version__,
        "tokenizers": tokenizers.__version__,
        "python": sys.version.split()[0],
        "threads": THREADS,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), payload


def build_config_hash():
    payload = {"chunk": CHUNK, "batch": BATCH, "threads": THREADS,
               "model": MODEL_KEY, "index_version": INDEX_VERSION,
               "normalization": "mean-token pooling + L2 normalize",
               "index_type": "flat-float32-memmap",
               "order": "passages.jsonl line order"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), payload


def iter_passages():
    """按 `passages.jsonl` 行序产出 (id, language, normalized_text)。"""
    with open(PASSAGES, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            yield d["id"], d.get("language"), (d.get("normalized_text") or "")


def out_paths(suffix=""):
    s = suffix or ""
    return (EMB_OUT.replace(".npy", "%s.npy" % s),
            IDS_OUT.replace(".ids.txt", "%s.ids.txt" % s),
            PROGRESS.replace(".progress.json", "%s.progress.json" % s),
            MANIFEST_OUT.replace(".minilm.json", "%s.minilm.json" % s))


def cmd_build(force=False, suffix=""):
    emb_out, ids_out, progress, manifest_out = out_paths(suffix)
    if suffix:
        print("[build] 输出后缀 %r → %s" % (suffix, os.path.basename(emb_out)))
    import numpy as np
    import embedding_provider as ep

    # ── 前置门
    if not os.path.isfile(GATE):
        raise SystemExit("缺 PREBUILD_INTEGRITY_GATE.json —— 先跑 prebuild_integrity_gate.py")
    gate = json.load(open(GATE, encoding="utf-8"))
    if not gate.get("passed"):
        raise SystemExit("§2 前置门未通过（%s）—— 停止 full build" % gate.get("failed"))

    prov = ep.OnnxTransformersProvider(MODEL_KEY, intra_op_num_threads=THREADS)
    if not prov.available:
        raise SystemExit("provider 不可用: %s" % prov.blocked_reason)
    dims = ep.ONNX_REGISTRY[MODEL_KEY]["dimensions"]
    prov._ensure()

    meta = json.load(open(os.path.join(STORE, "_build_meta.json"), encoding="utf-8"))
    total = meta["counts"]["passages"]

    if force:
        for p in (emb_out, ids_out, progress):
            if os.path.exists(p):
                os.remove(p)

    done = 0
    prefix_ids = []
    if os.path.isfile(progress) and os.path.isfile(emb_out) and os.path.isfile(ids_out):
        pr = json.load(open(progress, encoding="utf-8"))
        done = pr.get("done", 0)
        prefix_ids = pr.get("ids", [])
        print("[build] 续跑：已完成 %d / %d" % (done, total))

    mat = np.lib.format.open_memmap(emb_out, mode="r+" if done else "w+",
                                    dtype="float32", shape=(total, dims))
    ids_f = open(ids_out, "a" if done else "w", encoding="utf-8")

    it = iter_passages()
    # 跳过已完成的前缀，并**校验**它确实对得上（顺序变了就停）
    for i in range(done):
        pid, _, _ = next(it)
        if pid != prefix_ids[i]:
            raise SystemExit("顺序不一致：第 %d 条 id 是 %s，progress 记录的是 %s —— "
                             "passage store 变了，不能续跑（删掉 progress 重来）"
                             % (i, pid, prefix_ids[i]))

    t0 = time.time()
    buf_ids, buf_txt = [], []
    written = done
    langs = {}

    def flush():
        nonlocal buf_ids, buf_txt, written
        if not buf_txt:
            return
        vecs = prov.embed_documents(buf_txt, batch_size=BATCH)
        arr = np.asarray(vecs, dtype="float32")
        if arr.shape != (len(buf_txt), dims):
            raise SystemExit("维度异常：%s" % (arr.shape,))
        mat[written:written + len(buf_txt)] = arr
        for pid in buf_ids:
            ids_f.write(pid + "\n")
        written += len(buf_txt)
        mat.flush()
        ids_f.flush()
        json.dump({"done": written, "ids": prefix_ids + buf_ids},
                  open(progress, "w", encoding="utf-8"))
        prefix_ids.extend(buf_ids)
        buf_ids, buf_txt = [], []
        el = time.time() - t0
        rate = el / max(1, written - done)
        print("[build] %6d / %d (%.1f%%)  %.1f 段/s  ETA %.1f min" % (
            written, total, 100.0 * written / total,
            (written - done) / max(el, 1e-9), rate * (total - written) / 60), flush=True)

    for pid, lang, text in it:
        langs[lang] = langs.get(lang, 0) + 1
        buf_ids.append(pid)
        buf_txt.append(text)
        if len(buf_txt) >= CHUNK:
            flush()
        if written + len(buf_txt) >= total:
            break
    flush()
    ids_f.close()
    del mat

    dt = time.time() - t0
    rh, rh_payload = runtime_hash()
    bh, bh_payload = build_config_hash()
    manifest = {
        "schema_version": "full-vector-index/v1",
        "corpus_hash": sha256_file(PASSAGES),
        "passage_count": written,
        "language_counts": langs,
        "embedding_model": ep.ONNX_REGISTRY[MODEL_KEY]["model"],
        "model_hash": json.load(open(os.path.join(VAULT, "MODEL_MANIFEST.json"),
                                     encoding="utf-8"))["models"][MODEL_KEY]["files"]["onnx/model.onnx"]["sha256"],
        "runtime_hash": rh,
        "runtime_hash_payload": rh_payload,
        "dimensions": dims,
        "normalization": "mean-token pooling + L2 normalize",
        "index_type": "flat-float32-memmap",
        "index_version": INDEX_VERSION,
        "build_config_hash": bh,
        "build_config": bh_payload,
        "created_from": {
            "passages": os.path.relpath(PASSAGES, VAULT),
            "store_content_hash": meta.get("content_hash"),
            "store_generated_at": meta.get("generated_at"),
            "store_stamp_mode": meta.get("stamp_mode"),
            "prebuild_gate": os.path.relpath(GATE, VAULT),
        },
        "index_artifact_hash": sha256_file(emb_out),
        "artifacts": {
            "vectors": os.path.relpath(emb_out, VAULT),
            "vectors_bytes": os.path.getsize(emb_out),
            "ids": os.path.relpath(ids_out, VAULT),
            "ids_sha256": sha256_file(ids_out),
            "ids_lines": written,
        },
        "determinism": {
            "order": "passages.jsonl line order",
            "chunk": CHUNK, "batch": BATCH, "threads": THREADS,
            "threads_note": ("§13 实测：threads=1 与 threads=4 的 top-k 完全一致，"
                             "4 线程快 3.8–4.2×"),
        },
        "build_seconds": dt,
        "exact_search": True,
        "ann": None,
        "ann_note": ("未使用 ANN —— 精确暴力余弦在 249,105×384 上一次 matmul 即可，"
                     "没有近似召回损失。"),
        "not_in_git": [os.path.relpath(emb_out, VAULT), os.path.relpath(ids_out, VAULT),
                       os.path.relpath(progress, VAULT)],
    }
    json.dump(manifest, open(manifest_out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[build] 完成：%d 条 × %d 维，%.1f min，%.1f MB" % (
        written, dims, dt / 60, os.path.getsize(emb_out) / 1e6))
    print("[build] manifest -> %s" % manifest_out)
    print("[build] index_artifact_hash = %s" % manifest["index_artifact_hash"][:24])
    return manifest


def load_index(with_ids=True):
    """给其它工具用的读取接口（只读，不改产物）。"""
    import numpy as np
    man = json.load(open(MANIFEST_OUT, encoding="utf-8"))
    mat = np.load(EMB_OUT, mmap_mode="r")
    ids = None
    if with_ids:
        with open(IDS_OUT, encoding="utf-8") as f:
            ids = [l.rstrip("\n") for l in f]
    return mat, ids, man


def cmd_verify():
    problems = []
    if not os.path.isfile(MANIFEST_OUT):
        return {"status": "FAIL", "problems": ["缺 FULL_INDEX_MANIFEST.minilm.json"]}
    man = json.load(open(MANIFEST_OUT, encoding="utf-8"))
    need = ("corpus_hash", "passage_count", "language_counts", "embedding_model",
            "model_hash", "runtime_hash", "dimensions", "normalization",
            "index_type", "index_version", "build_config_hash", "created_from",
            "index_artifact_hash")
    for k in need:
        if k not in man or man[k] in (None, "", {}):
            problems.append("manifest 缺必需字段 %s" % k)
    # artifact 是否还在、是否被改过
    if os.path.isfile(EMB_OUT):
        if sha256_file(EMB_OUT) != man["index_artifact_hash"]:
            problems.append("index_artifact_hash 与 .npy 不符 —— 索引被改过")
    else:
        problems.append("缺向量文件（大产物不入 Git，需在本机重建）")
    if os.path.isfile(IDS_OUT):
        if os.path.getsize(IDS_OUT) and sha256_file(IDS_OUT) != man["artifacts"]["ids_sha256"]:
            problems.append("ids 文件 sha256 不符")
    else:
        problems.append("缺 ids 文件")
    if os.path.isfile(PASSAGES) and \
            sha256_file(PASSAGES) != man["corpus_hash"]:
        problems.append("corpus_hash 不符 —— canonical store 变了，索引过期")
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "passage_count": man.get("passage_count"),
            "dimensions": man.get("dimensions"),
            "index_version": man.get("index_version")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out-suffix", default="", help="写到另一组产物（用于可重建性验证）")
    a = ap.parse_args(argv)
    if a.build:
        cmd_build(force=a.force, suffix=a.out_suffix)
        return 0
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
