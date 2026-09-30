# EMBEDDING_PROVIDER.md — §7 EmbeddingProvider 抽象

> ⚠️ **本文件记录的是 Phase 3B 当时的状态，运行时阻断后来已在 Phase 3B.1 解除。**
> 文中「onnxruntime 装不上 / PyPI 不可达 / 向量路径不可执行」等描述**已过期**。
> 最新事实与证据请看：
> * `PHASE3B1_FINDINGS.md` —— 运行时恢复、§11 parity、§9/§13 gate
> * `PHASE3B2_FINDINGS.md` —— 语义评测与六配置消融（含**更正**：方向 B 的
>   scored 召回≈0，旧的「margin 为正」数字**作废**）
> * `OFFLINE_RUNTIME_GUIDE.md` —— 离线重建与校验


> 实现：`_scripts/_tools/embedding_provider.py`
> **核心检索链只依赖本抽象，不依赖任何供应商。**

---

## 1. 接口

```python
class EmbeddingProvider:
    def embed_documents(self, texts) -> list[list[float]]
    def embed_queries(self, texts)   -> list[list[float]]
    def metadata(self)               -> dict
```

`embed_documents` 与 `embed_queries` 分开 —— 某些模型对两侧用不同前缀
（如 `query:` / `passage:`），接口必须容纳这一点。

## 2. `metadata()` 字段（§7 要求 10 项）

| 字段 | 说明 |
|---|---|
| `provider` | 供应商标识（`onnx-local` / `builtin-hashing`） |
| `model` | 模型名 |
| `model_revision` | 版本/快照标识 |
| `dimensions` | 向量维度 |
| `max_input` | 最大输入长度 |
| `normalization` | 归一化方式（pooling + L2） |
| `multilingual_capability` | 多语言能力（**如实描述，不夸大**） |
| `runtime` | 运行时（`onnxruntime` / `python-stdlib`） |
| `device` | 设备（cpu） |
| `available` | **能否实际执行** |

额外两个审计字段：`blocked_reason`、`embeddings_computed`。

**为什么 `available` / `blocked_reason` 是必需的**：Provider 不可用时若静默返回
空向量，下游会把「模型没跑」误读成「相似度为 0」。让失败**可查询**是硬要求。

## 3. 已登记的 provider

### 3.1 ONNX 本地模型（真实模型存在，运行时缺失）

| 目录 | 模型 | 维度 | 架构 | max_input | ONNX |
|---|---|---|---|---|---|
| `models/minilm` | `paraphrase-multilingual-MiniLM-L12-v2` | 384 | BertModel | 512 | 470 MB |
| `models/mpnet` | `paraphrase-multilingual-mpnet-base-v2` | 768 | XLMRobertaModel | 514 | 1.11 GB |

* 元数据全部由**实读 `config.json` / `1_Pooling/config.json` / `tokenizer_config.json`** 得到
* 两者都是 **mean_tokens pooling + L2**、multilingual、含 CJK（SentencePiece unigram）
* **当前 `available = false`** —— `onnxruntime` / `numpy` / `tokenizers` 未安装，
  且本机离线（PyPI 不可达）。`blocked_reason` 写明原因。

```
$ python3 _scripts/_tools/embedding_provider.py --registry
```

### 3.2 `builtin-hashing`（纯 Python，非神经）

字符 2–4gram 哈希 + 带符号随机投影 + L2，仅用 Python 标准库。

**用途与限度（必须一起读）**：

* ✅ 让「向量索引 → 检索 → RRF 融合 → 评测」这条链在无依赖环境下**端到端可验证**
* ❌ **不是语义模型**：`metadata()["is_neural"] = false`
* ❌ **无跨语言能力**：中文字符与法文字母不共享 n-gram。实测中文 vs 法文余弦 **0.0389**
* ❌ 因此它的 `ZH→FR = 0` **不能**用来否定真实 multilingual 模型

## 4. 工厂与失败模式

```python
get_provider("onnx:mpnet")        # 真实模型（当前不可执行）
get_provider("builtin-hashing")   # 退化 provider
registry_status()                 # 全表含 available / blocked_reason
```

不可用时 `embed_*` 抛 `RuntimeError`（**不返回空向量**）。

## 5. 契约测试

`test_phase3b_contracts.py::test_06_provider_contract` 断言：

1. 三个方法都存在
2. `metadata()` 含全部 §7 要求的 10 个字段
3. `builtin-hashing` 必须声明 `is_neural: false`
4. 每个 ONNX provider 都必须有 `blocked_reason` 字段；不可用时必须非空

`test_07` 断言非神经 provider 的跨语言相似度 < 0.2（如实特性，不是缺陷）。

## 6. 待运行时可用后要做什么

1. 跑 `onnx:minilm` 与 `onnx:mpnet` 两个候选
2. 用**同一** adjudicated gold / benchmark corpus / top-k / preprocessing 比较
   （§11 的比较表）
3. 特别测 §9 的四方向：A ZH→ZH · **B ZH→FR（最重要 gate）** · C FR→FR · D paraphrase
4. 跑 `lacan_contrastive_eval.jsonl`（§10）—— 若某模型持续把 hard negative 排在
   positive 之前，**不得**选为 production model
5. 全部通过后才允许考虑 full-corpus embedding（§12 gate）
