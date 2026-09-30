# RUNTIME_GATES_REPORT.md — §9 Tokenizer Gate + §13 Runtime Determinism Gate

> 生成：`_scripts/_tools/check_runtime_gates.py`　·　原始数据：`_data/index/vector/RUNTIME_GATES.json`

## 0. 结论

| 模型 | §9 Tokenizer | §13 重复推理逐位相同 | batch 不变 | 线程不变 | NaN/Inf | 零范数 |
|---|---|---|---|---|---|---|
| `minilm` | PASS | PASS | PASS（top-k 一致） | PASS（top-k 一致） | 0 | 0 |
| `mpnet` | PASS | PASS | PASS（top-k 一致） | PASS（top-k 一致） | 0 | 0 |

## 1. §9 Tokenizer Gate 逐项

### `minilm`

- 生效截断长度 `effective_max_length` = **128**（来自 `sentence_bert_config.json`）
- 模型 vocab size（`config.json.vocab_size`，即 embedding 矩阵行数）= **250037**
- tokenizer 词表大小（`get_vocab_size(with_added_tokens=True)`）= 250002
- 边界文本 token 长度：`[2, 2, 3, 6, 5, 13, 19, 10, 18, 128, 128]`

| 检查 | 结果 |
|---|---|
| `repeat_same_process` | ✅ |
| `repeat_new_process` | ✅ |
| `no_padding` | ✅ |
| `mask_equals_token_count` | ✅ |
| `truncation_length` | ✅ |
| `bos_eos_present` | ✅ |
| `bos_unique` | ✅ |
| `ids_within_vocab` | ✅ |
| `ids_within_tokenizer_vocab` | ✅ |
| `empty_ok` | ✅ |
| `no_none_ids` | ✅ |
| `fixed_length_padding_invariant` | ✅ |

### `mpnet`

- 生效截断长度 `effective_max_length` = **128**（来自 `sentence_bert_config.json`）
- 模型 vocab size（`config.json.vocab_size`，即 embedding 矩阵行数）= **250002**
- tokenizer 词表大小（`get_vocab_size(with_added_tokens=True)`）= 250002
- 边界文本 token 长度：`[2, 2, 3, 6, 5, 13, 19, 10, 18, 128, 128]`

| 检查 | 结果 |
|---|---|
| `repeat_same_process` | ✅ |
| `repeat_new_process` | ✅ |
| `no_padding` | ✅ |
| `mask_equals_token_count` | ✅ |
| `truncation_length` | ✅ |
| `bos_eos_present` | ✅ |
| `bos_unique` | ✅ |
| `ids_within_vocab` | ✅ |
| `ids_within_tokenizer_vocab` | ✅ |
| `empty_ok` | ✅ |
| `no_none_ids` | ✅ |
| `fixed_length_padding_invariant` | ✅ |

### 1.1 定长固定文本探针（§9 原文要求）

同一段固定文本，三路编码，向量必须**完全相同**：

| 模型 | 文本 token 数 | A 单条 | B 与长文本同批 | C 手动补到 生效长度 | A–B cos | A–C cos | A–B 最大差 | 补位是否全被 mask |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `minilm` | 19 | 19 | 128 | 128 | 1.000000039 | 1.000000039 | 6.706e-08 | ✅ |
| `mpnet` | 19 | 19 | 128 | 128 | 0.999999957 | 0.999999957 | 4.657e-08 | ✅ |

**`attention_mask` 求和必须等于真实 token 数**：这一条就是 padding 泄漏的探针。旧版 provider 因为 `tokenizers.encode_batch` 会按批内最长自动补齐，用 `len(ids)` 反推 mask，导致 mask 全是 1、`<pad>` 被当成真实 token（见 `OFFLINE_RUNTIME_GUIDE.md §5.2`）。

## 2. §13 Runtime Determinism Gate 逐项

### `minilm`（17 条文本）

- 重复推理**逐位相同**：✅
- L2 范数区间：[0.999999948, 1.000000107]；NaN/Inf = 0；零范数 = 0

| 变化 | 最大分量差 | 最大 (1-cos) | top-5 名次一致 |
|---|---:|---:|---|
| batch_1 | 2.682e-07 | 1.078e-07 | ✅ |
| batch_4 | 6.706e-08 | 2.139e-07 | ✅ |
| batch_8 | 5.215e-08 | 2.139e-07 | ✅ |
| threads_4 | 0.000e+00 | 2.139e-07 | ✅ |

### `mpnet`（17 条文本）

- 重复推理**逐位相同**：✅
- L2 范数区间：[0.999999936, 1.000000054]；NaN/Inf = 0；零范数 = 0

| 变化 | 最大分量差 | 最大 (1-cos) | top-5 名次一致 |
|---|---:|---:|---|
| batch_1 | 9.499e-08 | 9.169e-08 | ✅ |
| batch_4 | 6.065e-08 | 1.280e-07 | ✅ |
| batch_8 | 2.980e-08 | 1.280e-07 | ✅ |
| threads_4 | 0.000e+00 | 1.280e-07 | ✅ |

**这里没有假设「批大小/线程数不影响结果」。** 表格里的数字是**实测**的：多线程会改变浮点归约顺序，所以分量差通常非 0；关键是**名次是否一致** —— 检索只依赖名次，所以这才是决定性的判定。

因此本项目的生产 embedding **默认单线程**（`intra_op_num_threads=1`），把那点不确定性直接消掉；需要吞吐时才调大，并且必须重跑本 gate。

