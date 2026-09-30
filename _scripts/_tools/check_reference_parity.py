#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_reference_parity.py — Phase 3B.1 §11 Reference Parity Test

§11 原文要求：用「可信参考实现」在 20–30 条文本上生成参考向量，与本机 ONNX
结果比对维度 / 余弦 / 数值差。

本机的现实约束（实测，不是推测）
────────────────────────────────
* `huggingface.co` **不可达**（DNS 只返回不可达的 IPv6；`hf-mirror.com` 302/308
  跳回 huggingface.co，同样不可达）→ 不能从 HF 取上游权重。
* `pypi.org` **可达** → 可以装 PyTorch + sentence-transformers。
* `modelscope.cn` **可达**（HTTP 200 实测）→ 上游官方权重从这里取，
  见 `fetch_reference_model.py` 与 `REFERENCE_MODEL_MANIFEST.json`。

于是参考实现 = **sentence-transformers + 上游官方 `model.safetensors`**，
不是「我自己再实现一遍」。两侧不共享任何编码代码：

    参考侧  .lacan-build/reference-venv  →  sentence_transformers.SentenceTransformer.encode()
    被测侧  .venv-embedding             →  embedding_provider.OnnxTransformersProvider

fixture 的挑法（**刻意压着截断边界**）
────────────────────────────────────
从 6,000 条 benchmark corpus 里确定性地取候选，先只 tokenize 拿到 token 长度，
再按**长度分桶 × 语言**各取若干条 —— 这样 128/512 的截断契约差异一定会被暴露，
而不是全挑短句让 parity 轻松通过。

用法
────
    python3 check_reference_parity.py --run                 # 两个模型全跑
    python3 check_reference_parity.py --run --models minilm
    python3 check_reference_parity.py --verify              # 只校验已有产物
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
BUILD = os.path.expanduser("<HOME>")

ONNX_PY = os.path.join(VAULT, ".venv-embedding", "bin", "python")
REF_PY = os.path.join(BUILD, "reference-venv", "bin", "python")
REF_MODELS = os.path.join(BUILD, "reference-models")
WORKER = os.path.join(HERE, "_parity_worker.py")

PASSAGES = os.path.join(VAULT, "_data", "passage_store", "passages.jsonl")
BENCH = os.path.join(VAULT, "_data", "index", "vector", "vector_benchmark_corpus.jsonl")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")

FIXTURE_OUT = os.path.join(VECDIR, "embedding_reference_fixture.json")
VECTORS_OUT = os.path.join(VECDIR, "embedding_reference_vectors.json")
MANIFEST_OUT = os.path.join(VECDIR, "RUNTIME_PARITY_MANIFEST.json")
REPORT_OUT = os.path.join(VAULT, "RUNTIME_PARITY_REPORT.md")

SCHEMA = "runtime-parity/v1"

# ── fixture 设计：长度分桶 × 语言。桶边界压着 ST 的 128 上限。───────────────
BUCKETS = [
    ("tiny", 1, 15),
    ("short", 16, 63),
    ("near_limit", 64, 127),
    ("over_limit", 128, 10**9),   # ← 必须存在：否则截断契约的差异测不出来
]
PER_BUCKET_LANG = 4              # 4 桶 × 2 语言 × 4 = 32 条语料；§11 要求 20–30，
                                 # 因此下面再砍到 26（保留 over_limit 全部）
TARGET_TOTAL = 26

# 查询侧：中文 5 条 + 法文 5 条（跨语言方向的关键输入）
QUERIES = [
    ("q_zh_01", "zh", "大他者是怎么被定义的"),
    ("q_zh_02", "zh", "享乐与欲望的区别"),
    ("q_zh_03", "zh", "象征界与语言的关系"),
    ("q_zh_04", "zh", "圣状的作用是什么"),
    ("q_zh_05", "zh", "对象a是什么"),
    ("q_fr_01", "fr", "Comment se définit le grand Autre ?"),
    ("q_fr_02", "fr", "la différence entre la jouissance et le désir"),
    ("q_fr_03", "fr", "le symbolique et le langage"),
    ("q_fr_04", "fr", "la fonction du sinthome"),
    ("q_fr_05", "fr", "qu'est-ce que l'objet petit a"),
]

THRESHOLDS = {
    "dimension_match": "完全相同（否则 invalid_embedding_dimension）",
    "min_cosine": 0.99999,
    "max_abs_component_diff": 1e-4,
    "l2_norm_tolerance": 1e-5,
    "top5_neighbor_set_jaccard": 1.0,
}


# ───────────────────────────────────────────────────────────── 工具

def load(path):
    return json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else None


def resolve_anchor(name):
    """锚点写的是文件名，可能落在 vault 根或 _data/index/vector/ 下。"""
    for d in (VAULT, VECDIR, HERE):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return os.path.join(VAULT, name)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_texts(texts):
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def load_benchmark_ids():
    ids = []
    with open(BENCH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            ids.append((d["passage_id"], d["language"]))
    return ids


def load_texts(wanted_ids):
    """流式读 passages.jsonl，只留想要的 id（384MB 不整体载入）。"""
    want = set(wanted_ids)
    out = {}
    with open(PASSAGES, encoding="utf-8") as f:
        for line in f:
            if not want:
                break
            d = json.loads(line)
            pid = d["id"]
            if pid in want:
                out[pid] = {"text": d["normalized_text"],
                            "language": d["language"],
                            "raw_text": d.get("raw_text"),
                            "session_id": d.get("session_id"),
                            "seminar_id": d.get("seminar_id")}
                want.discard(pid)
    return out


def run_worker(py, impl, model, texts, model_dir=None, batch_size=0):
    with tempfile.TemporaryDirectory() as td:
        fin = os.path.join(td, "in.json")
        fout = os.path.join(td, "out.json")
        with open(fin, "w", encoding="utf-8") as f:
            json.dump({"texts": texts}, f, ensure_ascii=False)
        cmd = [py, WORKER, "--impl", impl, "--model", model,
               "--input", fin, "--output", fout]
        if model_dir:
            cmd += ["--model-dir", model_dir]
        if batch_size:
            cmd += ["--batch-size", str(batch_size)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            return None, (p.stdout + p.stderr)[-3000:]
        return json.load(open(fout, encoding="utf-8")), None


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def topk_neighbors(vectors, k):
    """fixture 内部的 top-k 近邻集合（排除自身）。"""
    n = len(vectors)
    out = []
    for i in range(n):
        scored = [(cosine(vectors[i], vectors[j]), j) for j in range(n) if j != i]
        scored.sort(key=lambda x: (-x[0], x[1]))
        out.append(set(j for _, j in scored[:k]))
    return out


# ───────────────────────────────────────────────────────────── fixture

def build_fixture(models):
    """两阶段：先 tokenize 候选拿长度 → 再按 桶×语言 选。

    返回 (lengths, chosen, texts)
    """
    bids = load_benchmark_ids()
    # 确定性候选：按 passage_id 排序后等距抽样，避免受 jsonl 物理顺序影响
    fr = sorted([i for i, l in bids if l == "fr"])
    zh = sorted([i for i, l in bids if l == "zh"])
    cand = []
    for pool, lang in ((fr, "fr"), (zh, "zh")):
        step = max(1, len(pool) // 120)
        cand += [(pid, lang) for pid in pool[::step][:120]]
    texts = load_texts([pid for pid, _ in cand])
    cand = [(pid, lang) for pid, lang in cand if pid in texts]
    print("[fixture] 候选 %d 条（fr %d / zh %d）" % (
        len(cand), sum(1 for _, l in cand if l == "fr"),
        sum(1 for _, l in cand if l == "zh")))

    # ── 阶段 A：用被测侧 tokenizer 拿 token 长度（顺带就是 §9 的证据）
    probe = models[0]
    lengths = {}
    for lang in ("fr", "zh"):
        sub = [pid for pid, l in cand if l == lang]
        r, err = run_worker(ONNX_PY, "tokenize-only", probe,
                            [texts[p]["text"] for p in sub])
        if err:
            raise SystemExit("tokenize 探测失败: %s" % err)
        for pid, L in zip(sub, r["token_lengths"]):
            lengths[pid] = L

    # ── 阶段 B：按 桶×语言 选（桶内按 token 长度排序后等距取，避免全挑极端）
    chosen = []
    for _bname, lo, hi in BUCKETS:
        for lang in ("fr", "zh"):
            pool = sorted([pid for pid, l in cand
                           if l == lang and lo <= lengths[pid] <= hi
                           and pid not in chosen],
                          key=lambda p: (lengths[p], p))
            if not pool:
                continue
            step = max(1, len(pool) // PER_BUCKET_LANG)
            chosen += pool[::step][:PER_BUCKET_LANG]
    chosen = sorted(set(chosen))
    print("[fixture] 桶×语言 选出 %d 条" % len(chosen))
    return lengths, chosen, texts


def bucket_of(n):
    for b, lo, hi in BUCKETS:
        if lo <= n <= hi:
            return b
    return None


def finalize_fixture(lengths, chosen, texts):
    """把候选裁到 §11 的 20–30：**强制保留 over_limit 桶**，两语言交替补齐。"""
    must = [p for p in chosen if bucket_of(lengths[p]) == "over_limit"]
    rest = [p for p in chosen if p not in must]
    fr = sorted([p for p in rest if texts[p]["language"] == "fr"],
                key=lambda p: (lengths[p], p))
    zh = sorted([p for p in rest if texts[p]["language"] == "zh"],
                key=lambda p: (lengths[p], p))
    picked = list(must)
    i = 0
    while len(picked) < TARGET_TOTAL and (fr or zh):
        if i % 2 == 0 and fr:
            picked.append(fr.pop(0))
        elif zh:
            picked.append(zh.pop(0))
        elif fr:
            picked.append(fr.pop(0))
        i += 1
    picked = sorted(set(picked))
    return picked[:TARGET_TOTAL], must


# ───────────────────────────────────────────────────────────── run

def cmd_run(models, batch_size=0):
    lengths, chosen, texts = build_fixture(models)
    picked, over_limit = finalize_fixture(lengths, chosen, texts)

    items = []
    for pid in picked:
        L = lengths[pid]
        items.append({"item_id": pid, "kind": "passage", "language": texts[pid]["language"],
                      "text": texts[pid]["text"], "token_length": L,
                      "length_bucket": bucket_of(L),
                      "seminar_id": texts[pid]["seminar_id"],
                      "session_id": texts[pid]["session_id"]})
    for qid, lang, q in QUERIES:
        items.append({"item_id": qid, "kind": "query", "language": lang, "text": q,
                      "token_length": None, "length_bucket": None,
                      "seminar_id": None, "session_id": None})
    all_texts = [it["text"] for it in items]

    pl = [i["token_length"] for i in items if i["kind"] == "passage"]
    fixture = {
        "schema_version": SCHEMA,
        "purpose": "§11 reference parity fixture：语料（含 >128 token 的越界桶）+ 10 条查询",
        # §11 要求 manifest 记 (model / revision / tokenizer hash / pooling / normalization)。
        # 放在这里而不是只放在比对的 manifest 里 —— 这样 fixture 自己是**自描述**的，
        # 单独拿走也不会不知道它是对着哪个模型/哪份 tokenizer 生成的。
        "model_identity": model_identity(models),
        "selection": {
            "source": os.path.relpath(BENCH, VAULT),
            "candidate_count": 240,
            "buckets": [{"name": b, "min_tokens": lo, "max_tokens": hi} for b, lo, hi in BUCKETS],
            "forced_bucket": "over_limit",
            "forced_bucket_items": sorted(over_limit),
            "rule": ("从 benchmark corpus 按 id 排序等距取 240 候选 → tokenize 得 token 长度 "
                     "→ 按 (长度桶 × 语言) 桶内等距选取 → **强制保留 over_limit 桶** "
                     "→ fr/zh 交替补足 26 条。刻意压住 ST 的 128 token 截断边界，"
                     "让截断契约差异必然暴露。"),
            "deterministic": True,
        },
        "passage_items": len(pl),
        "query_items": len(items) - len(pl),
        "total_items": len(items),
        "items": items,
        "texts_sha256": sha256_texts(all_texts),
    }
    fixture["passage_token_length"] = {
        "min": min(pl), "max": max(pl),
        "count_over_128": sum(1 for x in pl if x > 128),
        "count_over_512": sum(1 for x in pl if x > 512),
        "by_bucket": {b: sum(1 for i in items if i["length_bucket"] == b)
                      for b, _, _ in BUCKETS},
    }
    os.makedirs(VECDIR, exist_ok=True)
    with open(FIXTURE_OUT, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("[fixture] %d 条（语料 %d / 查询 %d），token 长度 %s" % (
        len(items), fixture["passage_items"], fixture["query_items"],
        json.dumps(fixture["passage_token_length"]["by_bucket"])))

    # ── 两侧分别编码
    results = {}
    for model in models:
        print("[parity] %s ..." % model)
        ref, err = run_worker(REF_PY, "reference", model, all_texts,
                              model_dir=os.path.join(REF_MODELS, model),
                              batch_size=batch_size)
        if err:
            results[model] = {"status": "REFERENCE_FAILED", "error": err}
            print("  ✗ 参考实现失败: %s" % err[-500:])
            continue
        onnx, err2 = run_worker(ONNX_PY, "onnx", model, all_texts, batch_size=batch_size)
        if err2:
            results[model] = {"status": "ONNX_FAILED", "error": err2}
            print("  ✗ 被测侧失败: %s" % err2[-500:])
            continue
        results[model] = compare(model, fixture, ref, onnx)
        print("  %s  dims %s  min_cos %.9f  max_abs_diff %.3e  top5_jaccard %.4f" % (
            results[model]["status"], results[model]["dims"]["match"],
            results[model]["cosine"]["min"], results[model]["component_diff"]["max_abs"],
            results[model]["neighbor_agreement"]["top5_jaccard_min"]))

    man = build_manifest(fixture, results)
    with open(MANIFEST_OUT, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
        f.write("\n")

    out = {"schema_version": SCHEMA, "fixture_sha256": fixture["texts_sha256"],
           "models": {k: {kk: vv for kk, vv in v.items()
                          if kk not in ("reference", "onnx")}
                     for k, v in results.items()}}
    for k, v in results.items():
        if "reference" in v:
            out["models"][k]["reference_env"] = v["reference"]["env"]
            out["models"][k]["onnx_env"] = v["onnx"]["env"]
            out["models"][k]["reference_vectors"] = v["reference"]["vectors"]
            out["models"][k]["onnx_vectors"] = v["onnx"]["vectors"]
    with open(VECTORS_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
        f.write("\n")
    print("[manifest] %s" % MANIFEST_OUT)
    print("[vectors ] %s (%.1f MB)" % (VECTORS_OUT, os.path.getsize(VECTORS_OUT) / 1e6))
    write_report(fixture, results, man)
    return man


def compare(model, fixture, ref, onnx):
    rv, ov = ref["vectors"], onnx["vectors"]
    n = len(rv)
    cos = [cosine(rv[i], ov[i]) for i in range(n)]
    maxdiff = 0.0
    for i in range(n):
        for a, b in zip(rv[i], ov[i]):
            d = abs(a - b)
            if d > maxdiff:
                maxdiff = d
    # L2 范数（两侧都应 ≈1）
    def norms(vs):
        return [sum(x * x for x in v) ** 0.5 for v in vs]
    rn, on = norms(rv), norms(ov)
    # fixture 内部 top-5 近邻集合一致性（排名层面的证据）
    rk, ok = topk_neighbors(rv, 5), topk_neighbors(ov, 5)
    jac = []
    for i in range(n):
        inter = len(rk[i] & ok[i])
        union = len(rk[i] | ok[i])
        jac.append(inter / union if union else 1.0)
    per_item = []
    for i, it in enumerate(fixture["items"]):
        per_item.append({
            "item_id": it["item_id"], "kind": it["kind"], "language": it["language"],
            "token_length": it["token_length"], "length_bucket": it["length_bucket"],
            "cosine": cos[i], "max_abs_component_diff": max(
                abs(a - b) for a, b in zip(rv[i], ov[i])),
            "top5_jaccard": jac[i],
        })
    worst = sorted(per_item, key=lambda x: x["cosine"])[:8]
    problems = []
    if ref["dims"] != onnx["dims"]:
        problems.append("invalid_embedding_dimension")
    if not (min(cos) >= THRESHOLDS["min_cosine"]):
        problems.append("runtime_reference_parity_failure")
    if maxdiff > THRESHOLDS["max_abs_component_diff"]:
        problems.append("runtime_reference_parity_failure(max_abs_diff)")
    if any(abs(x - 1.0) > THRESHOLDS["l2_norm_tolerance"] for x in on):
        problems.append("l2_norm_out_of_tolerance")
    if min(jac) < THRESHOLDS["top5_neighbor_set_jaccard"]:
        problems.append("runtime_reference_parity_failure(top5_neighbors)")
    if ref["max_seq_length"] != onnx["max_seq_length"]:
        problems.append("length_contract_mismatch")
    return {
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "dims": {"reference": ref["dims"], "onnx": onnx["dims"],
                 "match": ref["dims"] == onnx["dims"]},
        "max_seq_length": {"reference": ref["max_seq_length"], "onnx": onnx["max_seq_length"]},
        "length_contract": onnx.get("length_contract"),
        "item_count": n,
        "cosine": {"min": min(cos), "mean": sum(cos) / n, "max": max(cos)},
        "component_diff": {"max_abs": maxdiff,
                           "threshold": THRESHOLDS["max_abs_component_diff"]},
        "l2_norm": {"reference_min": min(rn), "reference_max": max(rn),
                    "onnx_min": min(on), "onnx_max": max(on)},
        "neighbor_agreement": {"top5_jaccard_min": min(jac),
                               "top5_jaccard_mean": sum(jac) / n},
        "worst_items": worst,
        "per_item": per_item,
        "reference": {"env": ref["env"], "vectors": ref["vectors"],
                      "batch_size": ref["batch_size"], "seconds": ref["seconds"],
                      "model_dir": ref["model_dir"]},
        "onnx": {"env": onnx["env"], "vectors": onnx["vectors"],
                 "batch_size": onnx["batch_size"], "seconds": onnx["seconds"],
                 "onnx_path": onnx["onnx_path"]},
    }


def model_identity(models):
    """从 MODEL_MANIFEST.json + REFERENCE_MODEL_MANIFEST.json 组装每个模型的**身份指纹**。"""
    mm = load(os.path.join(VAULT, "MODEL_MANIFEST.json")) or {}
    rm = load(os.path.join(VECDIR, "REFERENCE_MODEL_MANIFEST.json")) or {}
    out = {}
    for key in models:
        m = (mm.get("models") or {}).get(key) or {}
        files = m.get("files") or {}
        up = ((rm.get("models") or {}).get(key) or {})
        h = lambda rel: (files.get(rel) or {}).get("sha256")   # noqa: E731
        out[key] = {
            "model": m.get("model"),
            "architecture": m.get("architecture"),
            "revision": ({"source": "local-snapshot",
                          "onnx_sha256": h("onnx/model.onnx")}),
            "tokenizer_sha256": h("tokenizer.json"),
            "tokenizer_config_sha256": h("tokenizer_config.json"),
            "sentencepiece_sha256": h("sentencepiece.bpe.model"),
            "config_sha256": h("config.json"),
            "sentence_bert_config_sha256": h("sentence_bert_config.json"),
            "pooling": m.get("pooling"),
            "pooling_config_sha256": h("1_Pooling/config.json"),
            "normalization": m.get("length_contract", {}).get("rule") and "L2 normalize" or "L2 normalize",
            "dimensions": m.get("dimension"),
            "effective_max_length": m.get("effective_max_length"),
            "length_contract": m.get("length_contract"),
            "upstream": {
                "repo": up.get("repo"),
                "revision": up.get("revision"),
                "model_safetensors_sha256": ((up.get("files") or {}).get("model.safetensors") or {}).get("sha256"),
                "local_files_match_upstream": (up.get("summary") or {}).get("local_files_differing") == [],
                "source": (rm.get("source") or {}).get("modelscope"),
            },
        }
    return out


def build_manifest(fixture, results):
    model_manifest = os.path.join(VAULT, "MODEL_MANIFEST.json")
    ref_manifest = os.path.join(VECDIR, "REFERENCE_MODEL_MANIFEST.json")
    return {
        "schema_version": SCHEMA,
        "fixture": {
            "path": os.path.relpath(FIXTURE_OUT, VAULT),
            "texts_sha256": fixture["texts_sha256"],
            "total_items": fixture["total_items"],
            "passage_items": fixture["passage_items"],
            "query_items": fixture["query_items"],
            "passage_token_length": fixture["passage_token_length"],
        },
        "thresholds": THRESHOLDS,
        "model_identity": fixture.get("model_identity"),
        "reference_environment": {
            k: (v.get("reference", {}) or {}).get("env")
            for k, v in results.items() if "reference" in v},
        "onnx_environment": {
            k: (v.get("onnx", {}) or {}).get("env")
            for k, v in results.items() if "onnx" in v},
        "anchors": {
            "MODEL_MANIFEST.json": sha256_file(model_manifest) if os.path.isfile(model_manifest) else None,
            "REFERENCE_MODEL_MANIFEST.json": sha256_file(ref_manifest) if os.path.isfile(ref_manifest) else None,
        },
        "hard_gates": {
            "runtime_reference_parity_failure": sum(
                1 for r in results.values() if "runtime_reference_parity_failure" in
                " ".join(r.get("problems", []))),
            "invalid_embedding_dimension": sum(
                1 for r in results.values() if "invalid_embedding_dimension" in r.get("problems", [])),
            "max_seq_length_mismatch": sum(
                1 for r in results.values() if "length_contract_mismatch" in r.get("problems", [])),
        },
        "models": {k: {"status": v.get("status"),
                       "problems": v.get("problems", []),
                       "cosine_min": v.get("cosine", {}).get("min"),
                       "max_abs_component_diff": v.get("component_diff", {}).get("max_abs"),
                       "top5_jaccard_min": v.get("neighbor_agreement", {}).get("top5_jaccard_min"),
                       "dims": v.get("dims"),
                       "max_seq_length": v.get("max_seq_length")}
                   for k, v in results.items()},
        "overall_status": ("PASS" if results and all(
            v.get("status") == "PASS" for v in results.values()) else "FAIL"),
    }


def write_report(fixture, results, man):
    L = []
    A = L.append
    A("# RUNTIME_PARITY_REPORT.md — Phase 3B.1 §11 Reference Parity Test\n")
    A("> 目的：证明**本机 ONNX 管线**与**可信参考实现**在同一批文本上给出同一批向量。")
    A("> 两侧不共享任何编码代码。产物：`%s` / `%s` / `%s`。\n" % (
        os.path.basename(FIXTURE_OUT), os.path.basename(VECTORS_OUT),
        os.path.basename(MANIFEST_OUT)))
    A("## 0. 结论\n")
    A("| 模型 | 状态 | 维度 | min cosine | max 分量差 | top-5 邻居 Jaccard | 参考 max_seq_length | ONNX max_seq_length |")
    A("|---|---|---|---|---|---|---|---|")
    for k, v in results.items():
        if v.get("status") in ("REFERENCE_FAILED", "ONNX_FAILED"):
            A("| `%s` | **%s** | – | – | – | – | – | – |" % (k, v["status"]))
            continue
        A("| `%s` | **%s** | %s | %.9f | %.3e | %.4f | %s | %s |" % (
            k, v["status"], v["dims"]["onnx"], v["cosine"]["min"],
            v["component_diff"]["max_abs"], v["neighbor_agreement"]["top5_jaccard_min"],
            v["max_seq_length"]["reference"], v["max_seq_length"]["onnx"]))
    A("")
    for k, v in results.items():
        if v.get("problems"):
            A("`%s` problems: %s\n" % (k, v["problems"]))

    A("## 1. 参考实现是什么（以及为什么只能是它）\n")
    A("§11 要「可信参考实现」。本机的可达性实测决定了唯一可行方案：\n")
    A("| 端点 | 结果 |")
    A("|---|---|")
    A("| `huggingface.co` | ✗ 不可达（DNS 只返回不可达 IPv6） |")
    A("| `hf-mirror.com` | ✗ 308/302 跳回 huggingface.co |")
    A("| `pypi.org` | ✓ 200 |")
    A("| `www.modelscope.cn` | ✓ 200 |")
    A("")
    A("因此参考实现 = **PyTorch + sentence-transformers（PyPI）** × "
      "**上游官方 `model.safetensors`（ModelScope）**，装在 "
      "`.lacan-build/reference-venv/`，权重在 `.lacan-build/reference-models/<key>/`。\n")
    A("**关键点：这不是「我自己再实现一遍」。** 参考侧调的是 "
      "`SentenceTransformer(model_dir).encode(...)`，与被测侧 "
      "`OnnxTransformersProvider` 没有任何共享代码。\n")
    A("本地 `models/<key>/` 与上游同名文件的 sha256 比对见 "
      "`REFERENCE_MODEL_MANIFEST.json`：**共有文件全部逐位一致**"
      "（`model.safetensors` 本地本来没有，是本次新取的）。\n")

    A("## 2. Fixture\n")
    A("- 语料 %d 条 + 查询 %d 条 = **%d 条**（§11 要求 20–30 条文本）" % (
        fixture["passage_items"], fixture["query_items"], fixture["total_items"]))
    A("- 语料 token 长度：min %s / max %s；**>128 token 的有 %s 条**，>512 的 %s 条" % (
        fixture["passage_token_length"]["min"], fixture["passage_token_length"]["max"],
        fixture["passage_token_length"]["count_over_128"],
        fixture["passage_token_length"]["count_over_512"]))
    A("- 长度桶分布：`%s`" % json.dumps(fixture["passage_token_length"]["by_bucket"],
                                        ensure_ascii=False))
    A("- `texts_sha256 = %s`" % fixture["texts_sha256"])
    A("")
    A("**为什么这样挑**：如果只挑短句，128 与 512 两种截断契约给出完全一样的结果，"
      "parity 会在无意中放过一个真实差异。所以 fixture 强制保留 `over_limit` 桶。\n")

    A("## 3. ★ 本次 parity **确实揪出的一个真实差异**\n")
    A("模型目录里三处长度声明**互相不一致**（实测）：\n")
    A("| 来源 | 字段 | minilm | mpnet | 含义 |")
    A("|---|---|---|---|---|")
    A("| `config.json` | `max_position_embeddings` | 512 | 514 | transformer 骨架的位置编码上限 |")
    A("| `tokenizer_config.json` | `model_max_length` | 512 | 512 | tokenizer 的声明上限 |")
    A("| `sentence_bert_config.json` | `max_seq_length` | **128** | **128** | **sentence-transformers 实际用的截断长度** |")
    A("")
    A("第一版 provider 只读前两者 → 取 512 → **与参考实现在 >128 token 的文本上必然分叉**。")
    A("已改为以 `sentence_bert_config.json` 为参考契约（`reference_max_length`），"
      "且 `effective_max_length` 默认等于它，**不做静默分叉**。\n")

    A("## 3.5 模型 / tokenizer 身份指纹（§11 要求记录）\n")
    A("| 模型 | 维度 | tokenizer sha256 | sentencepiece sha256 | onnx sha256 | pooling | effective max len | 上游仓库 | 本地=上游 |")
    A("|---|---:|---|---|---|---|---:|---|---|")
    for k, v in (man.get("model_identity") or {}).items():
        A("| `%s` | %s | `%s` | `%s` | `%s` | %s | %s | `%s` | %s |" % (
            k, v["dimensions"], str(v["tokenizer_sha256"])[:16],
            str(v["sentencepiece_sha256"])[:16], str(v["revision"]["onnx_sha256"])[:16],
            v["pooling"], v["effective_max_length"],
            (v.get("upstream") or {}).get("repo"),
            "✅" if (v.get("upstream") or {}).get("local_files_match_upstream") else "—"))
    A("")
    A("## 4. 逐条结果（最差的 8 条）\n")
    for k, v in results.items():
        if "worst_items" not in v:
            continue
        A("### `%s`\n" % k)
        A("| item | kind | lang | tokens | bucket | cosine | max Δ分量 | top5 Jaccard |")
        A("|---|---|---|---|---|---|---|---|")
        for w in v["worst_items"]:
            A("| `%s` | %s | %s | %s | %s | %.9f | %.3e | %.3f |" % (
                w["item_id"], w["kind"], w["language"], w["token_length"],
                w["length_bucket"] or "-", w["cosine"],
                w["max_abs_component_diff"], w["top5_jaccard"]))
        A("")
        A("环境：参考 `%s`；被测 `%s`" % (
            json.dumps(v["reference"]["env"], ensure_ascii=False),
            json.dumps(v["onnx"]["env"], ensure_ascii=False)))
        A("")

    A("## 5. 判定\n")
    A("- overall_status = **%s**" % man["overall_status"])
    A("- 硬门禁计数：`%s`" % json.dumps(man["hard_gates"], ensure_ascii=False))
    A("- 阈值：`%s`" % json.dumps(THRESHOLDS, ensure_ascii=False))
    A("")
    A("## 6. §11 未覆盖的部分（不冒充）\n")
    A("- 本测试证明的是「**同一份权重 + 同一份 tokenizer，两种独立实现给出同一向量**」。")
    A("  它**不能**证明 ONNX 权重与 HF 上的 checkpoint 一致 —— 那个 checkpoint 在")
    A("  本机拿不到（`huggingface.co` 不可达）。能证明的是：本地 `models/` 里的")
    A("  config/tokenizer/pooling 配置与 **ModelScope 上游**逐位一致，且比对用的")
    A("  `model.safetensors` 就是**上游那一份**（sha256 记录在案）。")
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report  ] %s" % REPORT_OUT)


def cmd_verify():
    problems = []
    for p in (FIXTURE_OUT, VECTORS_OUT, MANIFEST_OUT):
        if not os.path.isfile(p):
            problems.append("缺产物: %s" % os.path.basename(p))
    if problems:
        return {"status": "FAIL", "problems": problems}
    man = json.load(open(MANIFEST_OUT, encoding="utf-8"))
    fix = json.load(open(FIXTURE_OUT, encoding="utf-8"))
    # ★ 锚点新鲜度：记录时引用的上游文件现在还是不是同一份？
    #   manifest 一旦重新生成（例如 MODEL_MANIFEST 升到 v2），旧锚点就**过期**了，
    #   这意味着「这份 parity 结论绑定的是哪个模型」变得不可验证 —— 必须报出来。
    for name, rec in (man.get("anchors") or {}).items():
        pth = resolve_anchor(name)
        if rec is None:
            problems.append("锚点 %s 未记录" % name)
        elif not os.path.isfile(pth):
            problems.append("锚点文件缺失: %s" % name)
        elif sha256_file(pth) != rec:
            problems.append("锚点过期: %s 已变更（需要重跑 --run）" % name)
    if sha256_texts([i["text"] for i in fix["items"]]) != man["fixture"]["texts_sha256"]:
        problems.append("fixture texts_sha256 与 manifest 不符")
    if man["overall_status"] != "PASS":
        problems.append("overall_status=%s" % man["overall_status"])
    for k, v in man["models"].items():
        if v["status"] != "PASS":
            problems.append("%s status=%s" % (k, v["status"]))
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "overall_status": man["overall_status"], "models": man["models"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--models", default="minilm,mpnet")
    ap.add_argument("--batch-size", type=int, default=0)
    a = ap.parse_args(argv)
    if a.verify:
        r = cmd_verify()
        print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
        return 0 if r["status"] == "PASS" else 1
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    man = cmd_run(models, batch_size=a.batch_size)
    return 0 if man["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
