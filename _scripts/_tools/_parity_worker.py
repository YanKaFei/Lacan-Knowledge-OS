#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_parity_worker.py — §11 reference parity 的**单侧执行器**

同一个 fixture 文本，用两种**互相独立**的路径编码：

    --impl reference   sentence-transformers（PyTorch + 上游 model.safetensors）
                       在 .lacan-build/reference-venv 里跑 —— 这是"可信参考实现"
    --impl onnx        本 vault 的 OnnxTransformersProvider（onnxruntime + tokenizers）
                       在 .venv-embedding 里跑 —— 这是被测对象

两侧分别写成 JSON，由 check_reference_parity.py 比对。
**两侧不共享任何编码代码**：参考侧完全走 sentence-transformers，
被测侧走 embedding_provider.py。这才叫"独立实现比对"。

用法（由 check_reference_parity.py 调用，一般不单独跑）：
    python _parity_worker.py --impl reference --model minilm \
        --model-dir <dir> --input fixture.json --output out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def run_onnx(model, texts, batch_size):
    sys.path.insert(0, HERE)
    import embedding_provider as ep
    p = ep.OnnxTransformersProvider(model)
    if not p.available:
        raise SystemExit("ONNX provider 不可用: %s" % p.blocked_reason)
    t0 = time.time()
    vecs = p.embed_documents(texts, batch_size=batch_size)
    dt = time.time() - t0
    import numpy as np
    import onnxruntime
    import tokenizers
    return {
        "impl": "onnx",
        "model": model,
        "model_dir": p.root,
        "onnx_path": p.onnx_path,
        "max_seq_length": p.length_contract["effective_max_length"],
        "length_contract": p.length_contract,
        "dims": len(vecs[0]) if vecs else None,
        "vectors": vecs,
        "batch_size": batch_size,
        "seconds": dt,
        "env": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "onnxruntime": onnxruntime.__version__,
            "tokenizers": tokenizers.__version__,
        },
    }


def run_reference(model, texts, batch_size, model_dir):
    # 完全离线：本地目录 + 环境变量禁止联网
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import numpy as np
    import torch
    import transformers
    import sentence_transformers
    from sentence_transformers import SentenceTransformer

    if not model_dir or not os.path.isdir(model_dir):
        raise SystemExit("参考模型目录不存在: %s" % model_dir)
    st = SentenceTransformer(model_dir, device="cpu")
    st.eval()
    max_seq = getattr(st, "max_seq_length", None)
    t0 = time.time()
    with torch.no_grad():
        arr = st.encode(
            list(texts),
            batch_size=batch_size or len(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    dt = time.time() - t0
    arr = np.asarray(arr, dtype="float64")
    return {
        "impl": "reference",
        "model": model,
        "model_dir": model_dir,
        "max_seq_length": int(max_seq) if max_seq is not None else None,
        "dims": int(arr.shape[1]) if arr.ndim == 2 else None,
        "vectors": arr.tolist(),
        "batch_size": batch_size or len(texts),
        "seconds": dt,
        "env": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "sentence_transformers": sentence_transformers.__version__,
        },
    }


def tokenize_only(model, texts):
    """只跑 tokenizer（不建 ONNX session）—— fixture 选样阶段用，省掉 470MB/1.1GB 加载。

    ★ 两个都必须显式做，否则长度是错的：
      * `no_padding()`  —— tokenizer.json 自带 padding 配置，encode_batch 会按批内最长补齐，
                           `len(ids)` 会变成"批内最长"而不是这条文本的真实长度。
      * `no_truncation()` —— 先拿**真实** token 数，才能判断哪些文本真的超过 128。
    """
    from tokenizers import Tokenizer
    root = os.path.expanduser("<HOME>" % model)
    sys.path.insert(0, HERE)
    import embedding_provider as ep
    lc = ep.model_length_contract(root)
    tok = Tokenizer.from_file(os.path.join(root, "tokenizer.json"))
    tok.no_padding()
    tok.no_truncation()
    enc = tok.encode_batch(list(texts))
    eff = lc["effective_max_length"]
    return {
        "impl": "tokenize-only",
        "model": model,
        "model_dir": root,
        "max_seq_length": eff,
        "length_contract": lc,
        "dims": None,
        "token_lengths": [len(e.ids) for e in enc],
        "token_lengths_after_truncation": [min(len(e.ids), eff) for e in enc],
        "padding_disabled": True,
        "truncation_disabled": True,
        "batch_size": len(texts),
        "seconds": 0.0,
        "env": {"python": sys.version.split()[0]},
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", required=True,
                    choices=["onnx", "reference", "tokenize-only"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch-size", type=int, default=0)
    a = ap.parse_args(argv)

    texts = json.load(open(a.input, encoding="utf-8"))["texts"]
    if a.impl == "onnx":
        out = run_onnx(a.model, texts, a.batch_size or None)
    elif a.impl == "tokenize-only":
        out = tokenize_only(a.model, texts)
    else:
        out = run_reference(a.model, texts, a.batch_size or None, a.model_dir)
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
        f.write("\n")
    print("%s/%s batch=%s dims=%s %.1fs" % (
        a.impl, a.model, out["batch_size"], out["dims"], out["seconds"]))


if __name__ == "__main__":
    main()
