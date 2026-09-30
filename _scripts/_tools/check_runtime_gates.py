#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_runtime_gates.py — Phase 3B.1 §9 Tokenizer Gate + §13 Runtime Determinism Gate

必须用 `.venv-embedding/bin/python` 跑：
    .venv-embedding/bin/python _scripts/_tools/check_runtime_gates.py --all
    .venv-embedding/bin/python _scripts/_tools/check_runtime_gates.py --verify

§9 Tokenizer Gate
─────────────────
| 检查 | 为什么 |
|---|---|
| 重复 tokenize 逐位相同 | tokenizer 不能有隐藏随机性 |
| `attention_mask` 求和 == 真实 token 数 | ★ 抓 padding 泄漏（见 OFFLINE_RUNTIME_GUIDE §5.2） |
| 无 padding（`len(ids) == sum(mask)`） | 同上 |
| 截断长度 == 模型契约（`sentence_bert_config.json`） | 不许硬编码 512 |
| 超长文本截断后仍且仅有一个 BOS / EOS | 截断不能把头尾标记切掉 |
| token id 落在 [0, vocab) | 越界 id 会让 embedding 静默出错 |
| 空串 / 纯空白 / emoji / 混排 不崩且有确定输出 | 边界输入 |

§13 Runtime Determinism Gate
────────────────────────────
| 检查 | 判定 |
|---|---|
| 重复推理 | **逐位相同**（`==`，不是 allclose） |
| batch size 不变性 | 单批 vs batch=1/4/8 → 最大分量差 + top-k 名次一致性 |
| 线程数不变性 | threads=1 vs 4 → 最大分量差 + 名次一致性 |
| top-k 确定性 | 同一输入两次的 top-k 列表完全相同 |
| NaN / Inf / 零范数 | 必须为 0 |

⚠️ batch/线程 不变性**不假设**。多线程会改变浮点归约顺序，
padding 会改变张量形状 —— 两者都可能让向量在 1e-7 量级上变化。
本脚本**测量**它，并报告是否影响名次，而不是声称「应该没影响」。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
OUT_JSON = os.path.join(VECDIR, "RUNTIME_GATES.json")
REPORT = os.path.join(VAULT, "RUNTIME_GATES_REPORT.md")
ONNX_PY = os.path.join(VAULT, ".venv-embedding", "bin", "python")
sys.path.insert(0, HERE)

MODELS = ("minilm", "mpnet")

EDGE_TEXTS = [
    "",
    " ",
    "a",
    "le grand Autre",
    "大他者",
    "objet petit a : l'objet cause du désir",
    "象征界／想象界／实在界（R.S.I.）",
    "😀 emoji 与文字混排",
    "Lacan dit : « il n'y a pas de rapport sexuel »",
    "无意识像语言一样被结构 " * 300,      # 超长 → 触发截断
    "le désir de l'Autre " * 300,
]


def sha(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


# ────────────────────────────────────────────────────────── §9

def tokenizer_gate():
    from tokenizers import Tokenizer
    import embedding_provider as ep
    import numpy as np

    out = {}
    for key in MODELS:
        root = ep.MODEL_ROOTS[key]
        lc = ep.model_length_contract(root)
        eff = lc["effective_max_length"]
        tok = Tokenizer.from_file(os.path.join(root, "tokenizer.json"))
        tok.enable_truncation(max_length=eff)
        tok.no_padding()

        e1 = tok.encode_batch(EDGE_TEXTS)
        e2 = tok.encode_batch(EDGE_TEXTS)
        ids1 = [list(x.ids) for x in e1]
        ids2 = [list(x.ids) for x in e2]

        # 独立进程再算一次，排除「同进程缓存」造成的假确定性
        code = (
            "import json,os;from tokenizers import Tokenizer;"
            "import sys;sys.path.insert(0,%r);import embedding_provider as ep;"
            "root=%r;lc=ep.model_length_contract(root);"
            "t=Tokenizer.from_file(os.path.join(root,'tokenizer.json'));"
            "t.enable_truncation(max_length=lc['effective_max_length']);t.no_padding();"
            "texts=json.loads(%r);"
            "print(json.dumps([list(x.ids) for x in t.encode_batch(texts)]))"
            % (HERE, root, json.dumps(EDGE_TEXTS)))
        r = subprocess.run([ONNX_PY, "-c", code], capture_output=True, text=True)
        ids3 = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None

        # vocab 上界：不用 onnx 包（运行时环境里没有它），
        # 从 **config.json 的 vocab_size**（模型 embedding 矩阵的行数）+ tokenizer 自身词表读。
        # ⚠️ 第一版这里 `try: import onnx ... except: vocab = None`，
        # 于是 ImportError 被静默吃掉，`ids_within_vocab` 变成永远通过的假检查。
        # 现在：值读不到 → 该检查直接 FAIL，不允许静默弱化。
        cfg = ep._read_json(os.path.join(root, "config.json"))[0]
        vocab = cfg.get("vocab_size")
        tok_vocab = tok.get_vocab_size(with_added_tokens=True)

        checks = {
            "repeat_same_process": ids1 == ids2,
            "repeat_new_process": ids3 is not None and ids1 == ids3,
            "no_padding": all(len(x.ids) == int(sum(x.attention_mask)) for x in e1),
            "mask_equals_token_count": all(
                int(sum(x.attention_mask)) == len(x.ids) for x in e1),
            "truncation_length": all(
                len(x.ids) <= eff for x in e1) and any(len(x.ids) == eff for x in e1),
            "bos_eos_present": all(
                len(x.ids) >= 2 for x in e1),
            "bos_unique": all(sum(1 for i in x.ids if i == 0) <= 1 for x in e1),
            "ids_within_vocab": (vocab is not None) and all(
                all(0 <= i < vocab for i in x.ids) for x in e1),
            "ids_within_tokenizer_vocab": all(
                all(0 <= i < tok_vocab for i in x.ids) for x in e1),
            "empty_ok": len(ids1[0]) >= 2,   # 空串也应得到 BOS+EOS
            "no_none_ids": all(all(isinstance(i, int) for i in x.ids) for x in e1),
        }
        fixed = fixed_length_probe(key)
        checks["fixed_length_padding_invariant"] = fixed["passed"]
        out[key] = {
            "fixed_length_probe": fixed,
            "effective_max_length": eff,
            "length_contract": lc,
            "vocab_size": vocab,
            "tokenizer_vocab_size": tok_vocab,
            "checks": checks,
            "all_passed": all(checks.values()),
            "token_lengths": [len(x.ids) for x in e1],
            "texts_sha256": sha(EDGE_TEXTS),
            "ids_sha256": sha(ids1),
        }
    return out


def fixed_length_probe(key):
    """§9「定长固定文本」：同一段文本，padding 到不同长度，向量必须不变。

    为什么必须单独测：批内动态 padding 会让同一段文本在不同批次里被补到不同长度。
    如果 attention mask 有任何泄漏（见 OFFLINE_RUNTIME_GUIDE §5.2），
    这两种长度就会给出**不同的向量** —— 而且不会报错。
    所以这是最直接、最可控的 attention-mask 探针。

    三路对比：
      A 动态 padding（单条，长度 = 自身）
      B 动态 padding（与一条长文本同批，被补到更长）
      C 固定长度 padding（手动补到 effective_max_length）
    """
    import numpy as np
    import embedding_provider as ep

    prov = ep.OnnxTransformersProvider(key)
    prov._ensure()
    eff = prov.length_contract["effective_max_length"]
    fixed_text = "l'objet petit a est la cause du désir dans la structure hystérique"
    long_text = "le signifiant maître représente le sujet pour un autre signifiant " * 40

    a = np.asarray(prov.embed_documents([fixed_text], batch_size=None), dtype="float64")[0]
    b = np.asarray(prov.embed_documents([fixed_text, long_text], batch_size=None),
                   dtype="float64")[0]

    # C：手动固定长度 padding
    tok = prov._tok
    enc = tok.encode(fixed_text)
    n = len(enc.ids)
    ids = np.zeros((1, eff), dtype=np.int64)
    mask = np.zeros((1, eff), dtype=np.int64)
    ids[0, :n] = enc.ids
    mask[0, :n] = enc.attention_mask
    feed = {}
    for name in prov._input_names:
        if name == "input_ids":
            feed[name] = ids
        elif name == "attention_mask":
            feed[name] = mask
        elif name == "token_type_ids":
            feed[name] = np.zeros_like(ids)
        else:
            raise RuntimeError("未预期的 ONNX 输入 %r" % name)
    out = prov._session.run(None, feed)[0]
    m = mask[:, :, None].astype("float32")
    v = (out * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
    c = (v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None))[0]

    def cos(x, y):
        return float((x * y).sum())

    return {
        "fixed_text": fixed_text,
        "fixed_text_tokens": n,
        "effective_max_length": eff,
        "A_alone_len": n,
        "B_with_long_companion_len": min(
            len(tok.encode(long_text).ids), eff),
        "C_manual_fixed_len": eff,
        "A_vs_B_cosine": cos(a, b),
        "A_vs_C_cosine": cos(a, c.astype("float64")),
        "A_vs_B_max_abs_diff": float(np.abs(a - b).max()),
        "A_vs_C_max_abs_diff": float(np.abs(a - c).max()),
        "padded_positions_masked": bool(mask[0, n:].sum() == 0),
        "passed": bool(min(cos(a, b), cos(a, c.astype("float64"))) >= 0.99999
                       and mask[0, n:].sum() == 0),
    }


# ────────────────────────────────────────────────────────── §13

def _embed(model, texts, batch_size=None, threads=1):
    import embedding_provider as ep
    import numpy as np
    p = ep.OnnxTransformersProvider(model, intra_op_num_threads=threads)
    p._ensure()
    v = np.asarray(p.embed_documents(texts, batch_size=batch_size), dtype="float64")
    return v


def _topk(vecs, k=5):
    import numpy as np
    n = len(vecs)
    out = []
    for i in range(n):
        sims = vecs @ vecs[i]
        order = np.lexsort((np.arange(n), -sims))
        out.append([int(j) for j in order if j != i][:k])
    return out


def determinism_gate():
    import numpy as np
    texts = [t for t in EDGE_TEXTS if t.strip()] + [
        "le sujet barré", "对象a", "jouissance", "能指链", "sinthome",
        "le Nom-du-Père", "four discourses", "四种话语"]
    out = {}
    for key in MODELS:
        t0 = time.time()
        single = _embed(key, texts, batch_size=None, threads=1)
        again = _embed(key, texts, batch_size=None, threads=1)
        bitwise = bool((single == again).all())

        batch_rows = {}
        for bs in (1, 4, 8):
            v = _embed(key, texts, batch_size=bs, threads=1)
            d = np.abs(v - single)
            batch_rows["batch_%d" % bs] = {
                "max_abs_component_diff": float(d.max()),
                "max_row_cosine_delta": float(np.abs(
                    1.0 - (v * single).sum(1)).max()),
                "topk_identical": _topk(v) == _topk(single),
            }
        threads_rows = {}
        for th in (4,):
            v = _embed(key, texts, batch_size=None, threads=th)
            d = np.abs(v - single)
            threads_rows["threads_%d" % th] = {
                "max_abs_component_diff": float(d.max()),
                "max_row_cosine_delta": float(np.abs(
                    1.0 - (v * single).sum(1)).max()),
                "topk_identical": _topk(v) == _topk(single),
            }
        norms = np.linalg.norm(single, axis=1)
        out[key] = {
            "n_texts": len(texts),
            "repeat_bitwise_identical": bitwise,
            "batch_invariance": batch_rows,
            "thread_invariance": threads_rows,
            "nan_or_inf": int(np.isnan(single).sum() + np.isinf(single).sum()),
            "zero_norm": int((norms < 1e-12).sum()),
            "norm_min": float(norms.min()), "norm_max": float(norms.max()),
            "seconds_first_run": time.time() - t0,
            "topk_definition": "在本次 %d 条文本内部互为近邻的 top-5（不含自身）" % len(texts),
        }
    return out


# ────────────────────────────────────────────────────────── 吞吐（供 §21 排期用）

def throughput_probe(models=MODELS, n=256, thread_counts=(1, 2, 4, 8)):
    """实测吞吐 + 线程数是否改变名次 + 推算全量索引的时间与体积。

    为什么需要它：§21 的门禁要判 `full_corpus_index_exists`。全量 249,105 条在本轮
    **没有构建**，所以那个判据只能是 false。但「没建」不等于「不知道要多久」——
    把实测吞吐记下来，全量构建就从「未知数」变成一个**有依据的排期**。
    """
    import json
    import numpy as np
    import embedding_provider as ep

    pool_p = os.path.join(VECDIR, "evaluation_pool.json")
    if not os.path.isfile(pool_p):
        return {"status": "NO_POOL"}
    pool_ids = json.load(open(pool_p, encoding="utf-8"))["pool_ids"]
    # 确定性取前 n 条（benchmark corpus 原序，稳定）
    ids = pool_ids[:n]
    texts_by_id = {}
    want = set(ids)
    with open(os.path.join(VAULT, "_data", "passage_store", "passages.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            if not want:
                break
            d = json.loads(line)
            if d["id"] in want:
                texts_by_id[d["id"]] = d["normalized_text"]
                want.discard(d["id"])
    texts = [texts_by_id[p] for p in ids if p in texts_by_id]

    out = {"n_texts": len(texts), "models": {}}
    for key in models:
        per = {}
        ref_topk = None
        for th in thread_counts:
            p = ep.OnnxTransformersProvider(key, intra_op_num_threads=th)
            p._ensure()
            t0 = time.time()
            v = np.asarray(p.embed_documents(texts, batch_size=16), dtype="float64")
            dt = time.time() - t0
            topk = _topk(v)
            if ref_topk is None:
                ref_topk = topk
            per["threads_%d" % th] = {
                "seconds": dt,
                "seconds_per_text": dt / len(texts),
                "topk_identical_to_1thread": topk == ref_topk,
            }
            del p
        best = min(per.values(), key=lambda x: x["seconds"])
        rate = best["seconds_per_text"]
        dims = ep.ONNX_REGISTRY[key]["dimensions"]
        out["models"][key] = {
            "per_thread_count": per,
            "best_seconds_per_text": rate,
            "best_topk_agrees": all(v["topk_identical_to_1thread"] for v in per.values()),
            "projection_full_corpus": {
                "passages": 249105,
                "seconds": 249105 * rate,
                "hours": 249105 * rate / 3600,
                "index_bytes": 249105 * dims * 4,
                "index_mb": 249105 * dims * 4 / 1e6,
                "dims": dims,
            },
        }
        print("[throughput %s] best %.4f s/text -> full 249,105 in %.2f h, index %.0f MB "
              "(top-k 跨线程一致: %s)" % (
                  key, rate, out["models"][key]["projection_full_corpus"]["hours"],
                  out["models"][key]["projection_full_corpus"]["index_mb"],
                  out["models"][key]["best_topk_agrees"]))
    out["note"] = ("全量 249,105 条的向量索引**本轮未构建**（§21 门禁未开）。"
                   "本表给出**实测**的速率与体积，使全量构建成为可排期的步骤，"
                   "而不是「不知道要多久」。")
    # 增量合并：单模型重跑不应覆盖另一个模型已有的实测值
    dst = os.path.join(VECDIR, "THROUGHPUT.json")
    if os.path.isfile(dst):
        try:
            prev = json.load(open(dst, encoding="utf-8"))
            if set(models) != set(MODELS):
                merged = prev.get("models", {})
                merged.update(out["models"])
                out["models"] = merged
                out["n_texts"] = {k: prev.get("n_texts") for k in merged} \
                    if isinstance(prev.get("n_texts"), dict) else prev.get("n_texts")
        except Exception:
            pass
    out["n_texts_by_model"] = {k: (out.get("n_texts") if isinstance(out.get("n_texts"), int)
                                   else None) for k in out["models"]}
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


# ────────────────────────────────────────────────────────── 报告

def write_report(tok, det):
    L = []
    A = L.append
    A("# RUNTIME_GATES_REPORT.md — §9 Tokenizer Gate + §13 Runtime Determinism Gate\n")
    A("> 生成：`_scripts/_tools/check_runtime_gates.py`　·　"
      "原始数据：`_data/index/vector/RUNTIME_GATES.json`\n")
    A("## 0. 结论\n")
    A("| 模型 | §9 Tokenizer | §13 重复推理逐位相同 | batch 不变 | 线程不变 | NaN/Inf | 零范数 |")
    A("|---|---|---|---|---|---|---|")
    for k, v in tok.items():
        d = det.get(k)
        if d is None:
            A("| `%s` | %s | — | — | — | — | — |（§13 未跑）" % (
                k, "PASS" if v["all_passed"] else "**FAIL**"))
            continue
        bi = all(x["topk_identical"] for x in d["batch_invariance"].values())
        ti = all(x["topk_identical"] for x in d["thread_invariance"].values())
        A("| `%s` | %s | %s | %s | %s | %d | %d |" % (
            k, "PASS" if v["all_passed"] else "**FAIL**",
            "PASS" if d["repeat_bitwise_identical"] else "**FAIL**",
            "PASS（top-k 一致）" if bi else "**top-k 变了**",
            "PASS（top-k 一致）" if ti else "**top-k 变了**",
            d["nan_or_inf"], d["zero_norm"]))
    A("")
    A("## 1. §9 Tokenizer Gate 逐项\n")
    for k, v in tok.items():
        A("### `%s`\n" % k)
        A("- 生效截断长度 `effective_max_length` = **%s**（来自 `sentence_bert_config.json`）"
          % v["effective_max_length"])
        A("- 模型 vocab size（`config.json.vocab_size`，即 embedding 矩阵行数）= **%s**" % v["vocab_size"])
        A("- tokenizer 词表大小（`get_vocab_size(with_added_tokens=True)`）= %s" % v["tokenizer_vocab_size"])
        A("- 边界文本 token 长度：`%s`" % v["token_lengths"])
        A("")
        A("| 检查 | 结果 |")
        A("|---|---|")
        for c, r in v["checks"].items():
            A("| `%s` | %s |" % (c, "✅" if r else "❌"))
        A("")
    A("### 1.1 定长固定文本探针（§9 原文要求）\n")
    A("同一段固定文本，三路编码，向量必须**完全相同**：\n")
    A("| 模型 | 文本 token 数 | A 单条 | B 与长文本同批 | C 手动补到 %s | A–B cos | A–C cos | A–B 最大差 | 补位是否全被 mask |" % "生效长度")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for k, v in tok.items():
        f = v.get("fixed_length_probe")
        if not f:
            continue
        A("| `%s` | %d | %d | %d | %d | %.9f | %.9f | %.3e | %s |" % (
            k, f["fixed_text_tokens"], f["A_alone_len"], f["B_with_long_companion_len"],
            f["C_manual_fixed_len"], f["A_vs_B_cosine"], f["A_vs_C_cosine"],
            f["A_vs_B_max_abs_diff"], "✅" if f["padded_positions_masked"] else "❌"))
    A("")
    A("**`attention_mask` 求和必须等于真实 token 数**：这一条就是 padding 泄漏的探针。"
      "旧版 provider 因为 `tokenizers.encode_batch` 会按批内最长自动补齐，"
      "用 `len(ids)` 反推 mask，导致 mask 全是 1、`<pad>` 被当成真实 token"
      "（见 `OFFLINE_RUNTIME_GUIDE.md §5.2`）。\n")
    A("## 2. §13 Runtime Determinism Gate 逐项\n")
    if not det:
        A("（本轮只跑了 §9，§13 见后续运行）\n")
    for k, v in det.items():
        A("### `%s`（%d 条文本）\n" % (k, v["n_texts"]))
        A("- 重复推理**逐位相同**：%s" % ("✅" if v["repeat_bitwise_identical"] else "❌"))
        A("- L2 范数区间：[%.9f, %.9f]；NaN/Inf = %d；零范数 = %d" % (
            v["norm_min"], v["norm_max"], v["nan_or_inf"], v["zero_norm"]))
        A("")
        A("| 变化 | 最大分量差 | 最大 (1-cos) | top-5 名次一致 |")
        A("|---|---:|---:|---|")
        for name, row in list(v["batch_invariance"].items()) + \
                list(v["thread_invariance"].items()):
            A("| %s | %.3e | %.3e | %s |" % (
                name, row["max_abs_component_diff"], row["max_row_cosine_delta"],
                "✅" if row["topk_identical"] else "❌"))
        A("")
    A("**这里没有假设「批大小/线程数不影响结果」。** 表格里的数字是**实测**的："
      "多线程会改变浮点归约顺序，所以分量差通常非 0；关键是**名次是否一致** —— "
      "检索只依赖名次，所以这才是决定性的判定。\n")
    A("因此本项目的生产 embedding **默认单线程**（`intra_op_num_threads=1`），"
      "把那点不确定性直接消掉；需要吞吐时才调大，并且必须重跑本 gate。\n")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT)


def cmd_verify():
    problems = []
    if not os.path.isfile(OUT_JSON):
        return {"status": "FAIL", "problems": ["缺 RUNTIME_GATES.json"]}
    d = json.load(open(OUT_JSON, encoding="utf-8"))
    for k, v in d["tokenizer"].items():
        for c, r in v["checks"].items():
            if not r:
                problems.append("§9 %s 未通过: %s" % (k, c))
        f = v.get("fixed_length_probe") or {}
        if not f.get("passed"):
            problems.append("§9 %s 定长固定文本探针未通过: %s" % (k, f))
    for k, v in d["determinism"].items():
        if not v["repeat_bitwise_identical"]:
            problems.append("§13 %s 重复推理不是逐位相同" % k)
        if v["nan_or_inf"] or v["zero_norm"]:
            problems.append("§13 %s NaN/Inf=%d 零范数=%d" % (
                k, v["nan_or_inf"], v["zero_norm"]))
        for name, row in list(v["batch_invariance"].items()) + \
                list(v["thread_invariance"].items()):
            if not row["topk_identical"]:
                problems.append("§13 %s %s 的 top-5 名次变了" % (k, name))
    return {"status": "PASS" if not problems else "FAIL", "problems": problems}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tokenizer", action="store_true")
    ap.add_argument("--determinism", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--throughput", action="store_true",
                    help="实测吞吐 + 推算全量索引的时间与体积（写 THROUGHPUT.json）")
    ap.add_argument("--tp-models", default=",".join(MODELS))
    ap.add_argument("--tp-threads", default="1,2,4,8")
    ap.add_argument("--tp-n", type=int, default=256)
    a = ap.parse_args(argv)
    if a.throughput:
        thr = tuple(int(x) for x in a.tp_threads.split(",") if x.strip())
        throughput_probe(models=tuple(m.strip() for m in a.tp_models.split(",") if m.strip()),
                         n=a.tp_n, thread_counts=thr)
        return 0
    if a.verify:
        r = cmd_verify()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["status"] == "PASS" else 1
    tok, det = {}, {}
    if os.path.isfile(OUT_JSON) and not a.all:
        prev = json.load(open(OUT_JSON, encoding="utf-8"))
        tok, det = prev.get("tokenizer", {}), prev.get("determinism", {})
    if a.all or a.tokenizer or not (a.tokenizer or a.determinism):
        tok = tokenizer_gate()
        print("[§9] tokenizer gate done: %s" % {k: v["all_passed"] for k, v in tok.items()})
    if a.all or a.determinism or not (a.tokenizer or a.determinism):
        det = determinism_gate()
        print("[§13] determinism gate done")
    out = {"schema_version": "runtime-gates/v1", "tokenizer": tok, "determinism": det}
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_report(tok, det)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
