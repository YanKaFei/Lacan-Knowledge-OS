#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embedding_provider.py — §7 EmbeddingProvider 抽象 + §12 Full Corpus Gate

接口（核心检索链只依赖这个抽象，不依赖任何供应商）
────────────────────────────────────────────────────
    embed_documents(texts) -> list[list[float]]
    embed_queries(texts)   -> list[list[float]]
    metadata()             -> dict（§7 要求的 10 个字段）

已登记的 provider
─────────────────
1. **ONNX 本地模型**（`OnnxTransformersProvider`）—— 本机两个真实 multilingual 模型：

   | key | 模型 | 维度 | 架构 | ONNX |
   |---|---|---|---|---|
   | `minilm` | `paraphrase-multilingual-MiniLM-L12-v2` | 384 | BertModel | 470 MB |
   | `mpnet`  | `paraphrase-multilingual-mpnet-base-v2` | 768 | XLMRobertaModel | 1.11 GB |

   两者都是 mean-token pooling + L2、含 CJK 分词（SentencePiece unigram）。

   **运行时状态（Phase 3B.1 §8 实测，会随环境变化，以运行时探测为准）**：
   `.venv-embedding/` 里 numpy 2.0.2 / onnxruntime 1.19.2 / tokenizers 0.22.2
   均已可用，两个 session 都能创建。所以**本 provider 现在是可执行的**。

   但它仍然**如实探测**：`available` 由 `import onnxruntime` 与 ONNX 文件是否存在
   在**运行时**共同决定，不是硬编码常量。缺运行时/缺模型时 `metadata()` 会给出
   `blocked_reason`，而不是静默返回空向量。

   **max length 不硬编码**：从模型目录的 `config.json` / `tokenizer_config.json`
   实际读出（§9 要求），声明值与生效值都写进 metadata。

2. **`HashingProvider`（纯 Python，无依赖）** —— 字符 n-gram 哈希 + 带符号随机投影。
   ⚠️ **它不是神经语义模型**，只是让向量管线（索引/检索/融合/评测）能在无依赖条件下
   被端到端验证。它的跨语言能力**先天为零**（中文字符与法文字母不共享 n-gram），
   因此 **ZH→FR 的 gate 必须留给真实模型**，不能用它的分数下结论。

设计纪律
────────
* `metadata()` 必须如实说明 `available` / `blocked_reason` ——
  让「这个 provider 跑不了」是**可查询的事实**，而不是静默返回空向量。
* 任何 provider 都不得改动 canonical corpus；embedding 只作用在 derived 文本上。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))

# 本机模型位置（Phase 2 已确认存在）
MODEL_ROOTS = {
    "minilm": os.path.expanduser("<HOME>"),
    "mpnet": os.path.expanduser("<HOME>"),
}

# ONNX 模型登记表（元数据来自实际读 config.json，不是抄宣传）
ONNX_REGISTRY = {
    "minilm": {
        "provider": "onnx-local",
        "model": "paraphrase-multilingual-MiniLM-L12-v2",
        "model_revision": "local-snapshot-2026-08-27",
        "dimensions": 384,
        "max_input_declared": 512,
        "normalization": "mean-pooling + L2 normalize",
        "pooling": "mean_tokens",
        "architecture": "BertModel",
        "multilingual_capability": "multilingual (含 CJK，SentencePiece unigram)",
        "runtime_required": "onnxruntime",
        "device": "cpu",
        "onnx_bytes": 470301610,
        "languages_declared": ["zh", "fr", "en", "mul"],
    },
    "mpnet": {
        "provider": "onnx-local",
        "model": "paraphrase-multilingual-mpnet-base-v2",
        "model_revision": "local-snapshot-2026-08-28",
        "dimensions": 768,
        "max_input_declared": 514,
        "normalization": "mean-pooling + L2 normalize",
        "pooling": "mean_tokens",
        "architecture": "XLMRobertaModel",
        "multilingual_capability": "multilingual (XLM-R 底座，含 CJK)",
        "runtime_required": "onnxruntime",
        "device": "cpu",
        "onnx_bytes": 1110068629,
        "languages_declared": ["zh", "fr", "en", "mul"],
    },
}


def _read_json(path):
    """→ (data, error)。**不吞异常**：文件存在但读不了是缺陷，必须能被看见。

    第一版这里 `except Exception: return {}`，结果一个 NameError 被静默吃掉，
    表现为「读不到长度契约」而不是「代码有 bug」。因此改为显式返回错误。
    """
    if not os.path.isfile(path):
        return {}, "文件不存在"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return {}, "%s: %s" % (type(e).__name__, e)


def model_length_contract(root):
    """从模型目录**实际读出**长度契约（§9：不得硬编码 max length）。

    ★ 三个来源**并不一致**（实测 minilm）：

      | 来源 | 字段 | 值 |
      |---|---|---|
      | `config.json` | `max_position_embeddings` | 512 |
      | `tokenizer_config.json` | `model_max_length` | 512 |
      | `sentence_bert_config.json` | `max_seq_length` | **128** |

    `sentence_bert_config.json` 才是 **sentence-transformers 参考实现的长度契约**
    （ST 的 `Transformer` 模块读它，`encode()` 按它 truncate）。前两者只是
    transformer 骨架的位置编码上限。

    这一点是做 §11 reference parity 时才发现的：只读 config.json 会得到 512，
    与参考实现的 128 不一致 —— **对超过 128 token 的文本，向量会与参考实现对不上**。

    返回：
      max_position_embeddings / model_max_length / sentence_transformers_max_seq_length
      reference_max_length  —— 参考实现的契约（有 ST 配置就用它，否则退到 min(上两者)）
      effective_max_length  —— 本 provider 默认使用的长度（默认 = reference，避免静默分叉）
      read_errors           —— 读失败不会被吞掉
    """
    cfg, e1 = _read_json(os.path.join(root, "config.json"))
    tcfg, e2 = _read_json(os.path.join(root, "tokenizer_config.json"))
    scfg, e3 = _read_json(os.path.join(root, "sentence_bert_config.json"))
    mpe = cfg.get("max_position_embeddings")
    mml = tcfg.get("model_max_length")
    stl = scfg.get("max_seq_length")
    # HF 用 1e30 之类哨兵表示"无限制"，不是真长度
    if isinstance(mml, (int, float)) and mml > 10**6:
        mml = None
    cands = [v for v in (mpe, mml) if isinstance(v, int) and v > 0]
    backbone_cap = min(cands) if cands else None
    ref = stl if isinstance(stl, int) and stl > 0 else backbone_cap
    errs = []
    for name, e in (("config.json", e1), ("tokenizer_config.json", e2),
                    ("sentence_bert_config.json", e3)):
        if e and e != "文件不存在":
            errs.append("%s: %s" % (name, e))
    return {
        "max_position_embeddings": mpe,
        "model_max_length": mml,
        "sentence_transformers_max_seq_length": stl,
        "backbone_max_length": backbone_cap,
        "reference_max_length": ref,
        "effective_max_length": ref,
        "rule": ("reference_max_length = sentence_bert_config.max_seq_length（参考实现契约）；"
                 "无该文件时退到 min(max_position_embeddings, model_max_length)。"
                 "effective 默认等于 reference，**不做静默分叉**。"),
        "sources": {
            "config.json": os.path.join(root, "config.json"),
            "tokenizer_config.json": os.path.join(root, "tokenizer_config.json"),
            "sentence_bert_config.json": os.path.join(root, "sentence_bert_config.json"),
        },
        "read_errors": errs,
    }


def runtime_available():
    """检查 ONNX 运行时是否可用（运行时探测，不是硬编码结论）。"""
    try:
        import onnxruntime  # noqa: F401
        return True, None
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


class EmbeddingProvider:
    """Provider 抽象基类。"""

    def embed_documents(self, texts):
        raise NotImplementedError

    def embed_queries(self, texts):
        raise NotImplementedError

    def metadata(self):
        raise NotImplementedError


# ------------------------------------------------------------ ① ONNX 本地
class OnnxTransformersProvider(EmbeddingProvider):
    """本机真实 multilingual ONNX 模型。**运行时缺失时明确报缺。**"""

    def __init__(self, key, intra_op_num_threads=1):
        # 默认单线程：ONNX Runtime 多线程会改变浮点归约顺序，
        # 单线程是「同样输入 → 逐位同样输出」的前提。
        # 需要吞吐时可以调大，但**必须**配 §13 的线程不变性测试一起看。
        if key not in ONNX_REGISTRY:
            raise KeyError("未登记的 ONNX provider: %s" % key)
        self.key = key
        self.threads = int(intra_op_num_threads)
        self.root = MODEL_ROOTS[key]
        self.onnx_path = os.path.join(self.root, "onnx", "model.onnx")
        self._meta = dict(ONNX_REGISTRY[key])
        self.length_contract = model_length_contract(self.root)
        ok, err = runtime_available()
        self.available = ok and os.path.isfile(self.onnx_path)
        self.blocked_reason = None
        if not os.path.isfile(self.onnx_path):
            self.blocked_reason = "ONNX 文件缺失: %s" % self.onnx_path
        elif not ok:
            self.blocked_reason = "onnxruntime 不可用（%s）" % err
        elif self.length_contract["effective_max_length"] is None:
            self.available = False
            self.blocked_reason = (
                "无法从 config.json / tokenizer_config.json 读出长度契约 —— "
                "不猜 512，直接报不可用。")
        self._session = None
        self._tok = None
        self._np = None
        self._input_names = None
        self._model_hash = None

    def _ensure(self):
        if not self.available:
            raise RuntimeError("provider 不可用: %s" % self.blocked_reason)
        if self._session is None:
            import numpy as np            # noqa: F401
            import onnxruntime as ort
            from tokenizers import Tokenizer
            so = ort.SessionOptions()
            # 确定性：单线程、关掉内存模式优化带来的图改写不确定性
            so.intra_op_num_threads = self.threads
            so.inter_op_num_threads = 1
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                self.onnx_path, so, providers=["CPUExecutionProvider"])
            self._tok = Tokenizer.from_file(
                os.path.join(self.root, "tokenizer.json"))
            # §9：truncation 由模型契约决定，不由调用方随手切片
            maxlen = self.length_contract["effective_max_length"]
            self._tok.enable_truncation(max_length=maxlen)
            # ★★ 必须显式关掉 padding ★★
            # `tokenizer.json` 自带 padding 配置（pad_id/pad_token），tokenizers 0.22.2
            # 的 `encode_batch` **会按批内最长自动补齐**，即使从没调用 enable_padding()。
            # 后果：`len(b.ids)` 对批内每条都是同一个长度，
            # 于是用 `mask[i, :len(ids)] = 1` 造出来的 attention mask **全是 1**，
            # `<pad>` 位置被当成真实 token 参与 mean-pooling → 向量全错。
            # 实测：批内 18 条真实长度 115/33/13/34/128/…，错误 mask 却全是 128。
            # 因此这里关掉 padding，由 _encode 自己做「批内动态 padding」。
            self._tok.no_padding()
            self._np = np
            self._input_names = [i.name for i in self._session.get_inputs()]
        return self._session

    def encode_lengths(self, texts, max_length=None):
        """暴露 tokenize 结果，供 §9 tokenizer gate 逐项核对。"""
        self._ensure()
        maxlen = max_length or self.length_contract["effective_max_length"]
        batch = self._tok.encode_batch(list(texts))
        return [{"ids": list(b.ids), "attention_mask": list(b.attention_mask),
                 "type_ids": list(b.type_ids), "tokens": list(b.tokens),
                 "truncated_to": maxlen} for b in batch]

    def _encode(self, texts, batch_size=None):
        self._ensure()
        np = self._np
        texts = list(texts)
        if not texts:
            return []
        # 动态 padding 到 *本批* 最长（与 sentence-transformers 默认一致）。
        # batch_size 只影响分批，不改变每条文本的 token 序列（已 enable_truncation）。
        bs = batch_size or len(texts)
        out_vecs = []
        for start in range(0, len(texts), bs):
            chunk = texts[start:start + bs]
            batch = self._tok.encode_batch(chunk)
            maxlen = max(len(b.ids) for b in batch)
            ids = np.zeros((len(batch), maxlen), dtype=np.int64)
            mask = np.zeros((len(batch), maxlen), dtype=np.int64)
            for i, b in enumerate(batch):
                L = len(b.ids)
                if len(b.attention_mask) != L:
                    raise RuntimeError(
                        "tokenizer 返回的 attention_mask 长度与 ids 不一致（%d vs %d）"
                        % (len(b.attention_mask), L))
                # mask 一律取自 b.attention_mask，**不要**用 len(b.ids) 反推：
                # 一旦 padding 没关掉，len(b.ids) 是补齐后的长度，会把 <pad> 算成有效 token。
                ids[i, :L] = b.ids
                mask[i, :L] = b.attention_mask
                real = int(sum(b.attention_mask))
                if real != L:
                    raise RuntimeError(
                        "tokenizer 输出里仍有 padding（真实 %d / 总长 %d）—— "
                        "attention mask 会算错，embedding 不可信。" % (real, L))
            # ⚠️ 输入签名**按模型不同**（实测）：
            #   minilm(BertModel):    input_ids, attention_mask, **token_type_ids**
            #   mpnet(XLMRoberta):    input_ids, attention_mask（无 token_type_ids）
            # 第一版硬编码取前两个输入，对 minilm 会漏 token_type_ids 直接报错。
            # 正确做法：按 session 声明的输入名逐个构造，缺什么补什么。
            inp = {}
            for n in self._input_names:
                if n == "input_ids":
                    inp[n] = ids
                elif n == "attention_mask":
                    inp[n] = mask
                elif n == "token_type_ids":
                    inp[n] = np.zeros_like(ids)
                else:
                    # 未预期输入：显式报错，不猜
                    raise RuntimeError("未预期的 ONNX 输入 %r（模型 %s）" % (n, self.key))
            out = self._session.run(None, inp)[0]        # (B, T, D)
            m = mask[:, :, None].astype("float32")
            vec = (out * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
            norm = np.linalg.norm(vec, axis=1, keepdims=True)
            out_vecs.extend((vec / np.clip(norm, 1e-9, None)).tolist())
        return out_vecs

    def embed_documents(self, texts, batch_size=None):
        return self._encode(texts, batch_size=batch_size)

    def embed_queries(self, texts, batch_size=None):
        return self._encode(texts, batch_size=batch_size)

    def metadata(self):
        m = dict(self._meta)
        m["available"] = self.available
        m["blocked_reason"] = self.blocked_reason
        m["embeddings_computed"] = bool(self.available)
        m["is_neural"] = True
        m["length_contract"] = self.length_contract
        m["max_input"] = self.length_contract["effective_max_length"]
        m["onnx_inputs"] = self._input_names
        m["truncation"] = "tokenizers.enable_truncation(max_length=effective_max_length)"
        m["padding"] = "dynamic: pad to longest sequence in the current batch"
        return m


# ------------------------------------------------------------ ② 纯 Python 哈希
class HashingProvider(EmbeddingProvider):
    """字符 n-gram 哈希 + 带符号随机投影（纯 Python，无依赖）。

    ⚠️ **不是神经语义模型。** 用途仅限：在无 onnxruntime/numpy 的环境里
    把「向量索引 → 检索 → RRF 融合 → 评测」这条链端到端跑通并验证可复现性。

    **它的跨语言能力先天为零**：中文字符与法文字母不共享任何字符 n-gram，
    所以 `ZH→FR` 的召回必然为 0。这个 0 **不能**用来否定真实 multilingual 模型
    —— 真实模型的 gate 必须由 ONNX provider 跑出来。
    """

    def __init__(self, dims=256, ngrams=(2, 3, 4)):
        self.dims = dims
        self.ngrams = ngrams

    @staticmethod
    def _norm(s):
        s = unicodedata.normalize("NFKC", str(s or "")).casefold()
        return " ".join(s.split())

    def _vec(self, text):
        v = [0.0] * self.dims
        t = self._norm(text)
        if not t:
            return v
        for n in self.ngrams:
            for i in range(max(0, len(t) - n + 1)):
                g = t[i:i + n]
                h = hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "big") % self.dims
                sign = 1.0 if h[4] & 1 else -1.0
                v[idx] += sign
        # L2 归一化
        nrm = sum(x * x for x in v) ** 0.5
        if nrm > 0:
            v = [x / nrm for x in v]
        return v

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_queries(self, texts):
        return [self._vec(t) for t in texts]

    def metadata(self):
        return {
            "provider": "builtin-hashing",
            "model": "char-ngram-hash-signed-random-projection",
            "model_revision": "v1",
            "dimensions": self.dims,
            "max_input": None,
            "normalization": "char %s-gram + signed hash + L2" % (self.ngrams,),
            "multilingual_capability": (
                "**无跨语言能力** —— 不同文字的字符 n-gram 不相交。"
                "仅用于管线端到端验证，不得用于 model selection。"),
            "runtime": "python-stdlib",
            "device": "cpu",
            "available": True,
            "blocked_reason": None,
            "is_neural": False,
            "embeddings_computed": True,
        }


# ------------------------------------------------------------ 工厂
def get_provider(name):
    """按名取 provider。`onnx:minilm` / `onnx:mpnet` / `builtin-hashing`。"""
    if name in ("builtin-hashing", "hashing"):
        return HashingProvider()
    if name.startswith("onnx:"):
        return OnnxTransformersProvider(name.split(":", 1)[1])
    raise KeyError("未知 provider: %s" % name)


def registry_status():
    """登记表全貌（含可用性）—— 让「跑不了」成为可查询的事实。"""
    out = []
    for key in ONNX_REGISTRY:
        p = OnnxTransformersProvider(key)
        out.append(p.metadata())
    h = HashingProvider()
    out.append(h.metadata())
    return out


def cosine(a, b):
    """纯 Python 余弦（两个向量都已 L2 归一化时等于点积）。"""
    return sum(x * y for x, y in zip(a, b))


if __name__ == "__main__":
    import json
    if len(sys.argv) > 1 and sys.argv[1] == "--registry":
        print(json.dumps(registry_status(), ensure_ascii=False, indent=2))
    else:
        for m in registry_status():
            print("%-34s available=%-5s dims=%s" % (
                m["model"][:34], m["available"], m["dimensions"]))
