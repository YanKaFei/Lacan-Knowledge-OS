# OFFLINE_RUNTIME_GUIDE.md — 离线 Embedding 运行时的重建与校验

> 适用：本机（macOS 26.2 / arm64 / CPython 3.9.6）。
> 目标：**在断网或网络不可靠的情况下**，把两个真实 multilingual ONNX 模型的运行时
> 一次装出来，并且每一步都能校验。
>
> 相关产物：`RUNTIME_TARGET.json` · `embedding-runtime-requirements.in` ·
> `embedding-runtime-requirements.lock` · `WHEELHOUSE_MANIFEST.json` ·
> `RUNTIME_INSTALLED.json` · `MODEL_MANIFEST.json` ·
> `_data/index/vector/REFERENCE_MODEL_MANIFEST.json` ·
> `_data/index/vector/RUNTIME_PARITY_MANIFEST.json`

---

## 0. 三十秒版

```bash
cd <HOME>

# ① 建 wheelhouse（联网时做一次；之后可永久离线）
.venv-embedding/bin/python _scripts/_tools/build_wheelhouse.py --build --force

# ② 证明离线装得出来（干净 venv + --no-index）
python3 _scripts/_tools/build_wheelhouse.py --offline-test

# ③ 校验 wheelhouse / 模型 hash / 参考权重 / parity
python3 _scripts/_tools/build_wheelhouse.py --verify
python3 _scripts/_tools/build_model_manifest.py --verify
python3 _scripts/_tools/fetch_reference_model.py --verify
python3 _scripts/_tools/check_reference_parity.py --verify
```

全绿即运行时可用且可追溯。

---

## 1. 本机真实平台事实（不要按操作系统的名字猜）

`RUNTIME_TARGET.json` 里的值都由**命令实测**得到，原始命令记录在
`probe_commands` 字段。

| 项 | 实测值 |
|---|---|
| OS / 版本 | Darwin / macOS **26.2** |
| machine / processor | **arm64** / arm |
| Python | **3.9.6** CPython，`cache_tag = cpython-39` |
| 解释器二进制 | **universal2**（`lipo -archs` = `x86_64 arm64`），实际以 **arm64** 运行 |
| `sysconfig.get_platform()` | **`macosx-10.9-universal2`** |
| `HOST_GNU_TYPE` | `x86_64-apple-darwin`（**构建机**是 x86_64，别被它带偏） |
| 解释器支持的 wheel tag 数 | **957** |
| 其中 `_arm64` / `_universal2` 平台数 | **40** |
| 最高平台 tag | `macosx_26_0_arm64` |

### 1.1 这一节为什么重要

`sysconfig.get_platform()` 报的是 `macosx-10.9-universal2`，
而机器是 arm64 / macOS 26.2，`HOST_GNU_TYPE` 又说是 x86_64。
**三个信号互相矛盾** —— 任何一个单独拿去选 wheel 都可能选错。

所以正确的做法只有一个：**问解释器自己支持哪些 tag**。
`build_wheelhouse.py` 就是这么做平台的：

```python
from pip._internal.utils.compatibility_tags import get_supported
# 取所有 platform，去重，只保留 arm64 / universal2
```

它**不写死任何平台名**。`--print-tags` 可以直接看推导结果。

---

## 2. 依赖从哪来（不是猜的）

`embedding-runtime-requirements.in` 的来源是 **AST 扫描 + 运行时验证**：

```
numpy          ← embedding_provider.OnnxTransformersProvider._ensure()
onnxruntime    ← 同上
tokenizers     ← 同上
```

传递依赖**一个都不手写**，全部交给 pip 解析后冻结进
`embedding-runtime-requirements.lock`（34 个包，含 `coloredlogs` / `flatbuffers` /
`protobuf` / `sympy` / `huggingface-hub` / `httpx` / …）。

⚠️ 反面教材：如果只写 `onnxruntime` 而漏掉 `coloredlogs`，
`import onnxruntime` 会在运行期直接失败 —— 这正是「不许猜依赖」的理由。

---

## 3. wheelhouse：怎么建、怎么证

### 3.1 建

```bash
.venv-embedding/bin/python _scripts/_tools/build_wheelhouse.py --build --force
```

- `--only-binary=:all:` —— **任何包没有本平台 wheel 就直接失败**，
  绝不静默退回 sdist（退回 sdist 就等于放弃「离线 wheelhouse」这个保证）。
  失败时返回 `RUNTIME_WHEEL_INCOMPATIBLE`，本机实测**没有出现**。
- 版本**由 `.lock` 固定**，解析结果必须等于 `.lock`，
  否则 manifest 记 `lock_consistency.consistent = false`，不悄悄换版本。
- 平台 tag 用上节的方式从解释器推导（40 个）。

### 3.2 关于 index（**必须写清楚，否则就是含糊其辞**）

| 来源 | 实测速度 |
|---|---|
| `pypi.org` / `files.pythonhosted.org` 直连 | **约 4–5 kB/s** |
| `https://pypi.tuna.tsinghua.edu.cn/simple` | **约 1.7 MB/s** |

直连慢约 350 倍（约 40 MB 的 wheelhouse 要跑十几分钟以上，
`torch` 那种几十 MB 的包更不现实）。因此 wheelhouse 默认从清华镜像下载。

**镜像服务的是同一批 wheel**；完整性不靠「信任镜像」，而靠
`WHEELHOUSE_MANIFEST.json` 里**逐个 wheel 的 sha256**：

- `wheelhouse_hash` = 对排序后的 `<filename> <sha256>\n` 串联取 sha256
- `--verify` 会重算每一条并与磁盘文件比对，多一个 / 少一个 / 内容变了都会报出来

### 3.3 证明离线可复现（**这是 §5/§6 的核心证据**）

```bash
python3 _scripts/_tools/build_wheelhouse.py --offline-test
```

它做的事：新建一个**干净 venv** → `pip install --no-index --find-links wheelhouse`
→ 核对每个包版本是否**逐条等于** `.lock` → 真跑一次 `import numpy, onnxruntime, tokenizers`
→ 删掉测试 venv。结果写进 `WHEELHOUSE_MANIFEST.json` 的 `offline_install_test`。

实测结果：

```
status = PASS      packages_installed = 34
version_mismatch_vs_lock = {}
import_check = numpy=2.0.2 onnxruntime=1.19.2 tokenizers=0.22.2
network_used = false   （--no-index）
```

> **修正记录**：Phase 3B 时 PyPI 不可达，3B.1 首轮是从 `pypi.org` 直连装的，
> 当时把 §5/§6 记为 **PARTIAL**。改用镜像重建 wheelhouse 并跑通离线复现后，
> 该 PARTIAL **已撤销** —— 现在装的过程本身就是离线的。

---

## 4. 模型运行时闸门

```bash
.venv-embedding/bin/python -c "
import numpy, onnxruntime, tokenizers
print(numpy.__version__, onnxruntime.__version__, tokenizers.__version__)
print(onnxruntime.get_available_providers())"
```

实测：`2.0.2 1.19.2 0.22.2`，providers 含 `CPUExecutionProvider`。

两个 ONNX session 的**输入签名不同**（实测，不是文档抄来的）：

| 模型 | inputs | 输出 |
|---|---|---|
| `minilm` | `input_ids`, `attention_mask`, **`token_type_ids`** | `last_hidden_state (B,T,384)` |
| `mpnet` | `input_ids`, `attention_mask`（**无** `token_type_ids`） | `last_hidden_state (B,T,768)` |

provider 按 session 声明的输入名逐个构造，遇到未预期输入**显式报错**，
不猜、不静默。

---

## 5. 踩过的两个真实坑（都会让向量悄悄变错）

### 5.1 长度契约：三个文件互相矛盾

| 来源 | 字段 | minilm | mpnet | 含义 |
|---|---|---|---|---|
| `config.json` | `max_position_embeddings` | 512 | 514 | 骨架位置编码上限 |
| `tokenizer_config.json` | `model_max_length` | 512 | 512 | tokenizer 声明上限 |
| **`sentence_bert_config.json`** | **`max_seq_length`** | **128** | **128** | **sentence-transformers 实际用的截断长度** |

只读前两者 → 取 512 → 与参考实现（`SentenceTransformer(...).max_seq_length == 128`）
在超过 128 token 的文本上**必然分叉**。
现在 provider 以 `sentence_bert_config.json` 为契约，`effective_max_length` 默认等于它。

### 5.2 ★ attention mask 的 padding 泄漏（最隐蔽的一个）

`tokenizer.json` **自带 padding 配置**（`pad_id = 1`），
`tokenizers` 0.22.2 的 `encode_batch` **会按批内最长自动补齐**，
即使从来没调用过 `enable_padding()`。

于是 `len(b.ids)` 对批内每条都是同一个数，用
`mask[i, :len(b.ids)] = 1` 造出来的 attention mask **全是 1**，
`<pad>` 位置被当成真实 token 参与 mean-pooling —— **向量全错，而且不报错**。

实测（18 条混合长度文本）：

```
真实长度（HF attention_mask 求和）: 115 33 13 34 128 33 32 26 9 9 8 7 6 11 12 9 7 13
错误 mask 求和                   : 128 128 128 ... （全是批内最长）
```

修法：`self._tok.no_padding()`，并且 mask **一律取自 `b.attention_mask`**，
再加一条运行时不变式（`sum(attention_mask) != len(ids)` 直接抛错）。

这个 bug 是 §11 reference parity 揪出来的 —— 单看 embedding 本身完全看不出来。
回归测试：`_tests/test_phase3b1_runtime.py::test_30_attention_mask_has_no_padding_leak`。

---

## 6. 参考实现（§11 parity 的另一半）

### 6.1 为什么参考实现是 sentence-transformers

§11 要「可信参考实现」。本机的可达性实测决定了唯一可行方案：

| 端点 | 结果 |
|---|---|
| `huggingface.co` | ✗ 不可达（DNS 只给不可达的 IPv6） |
| `hf-mirror.com` | ✗ 308/302 跳回 `huggingface.co` |
| `pypi.org` | ✓（但约 4–5 kB/s） |
| 清华 PyPI 镜像 | ✓ 1.7 MB/s |
| **`www.modelscope.cn`** | ✓ 200 |

因此：**PyTorch + sentence-transformers 从 PyPI 镜像装**，
**上游官方 `model.safetensors` 从 ModelScope 取**。

```bash
python3 _scripts/_tools/fetch_reference_model.py --fetch    # 取上游文件 + 逐文件比 hash
```

实测：本地 `models/<key>/` 与上游**同名文件全部逐位一致**
（`config.json` sha256 相同等）。`model.safetensors` 本地本来没有，是本次新取的。

参考环境在 `<HOME>`
（torch 2.8.0 / transformers 4.46.3 / sentence-transformers 3.3.1），
权重在 `<HOME>`。

> **注意**：`<HOME>` 用的是
> **同一套 onnxruntime + tokenizers + mean-pooling 代码**，
> 所以它产出的 LanceDB 向量**不能**当参考实现（那是自己跟自己比）。

### 6.2 跑 parity

```bash
python3 _scripts/_tools/check_reference_parity.py --run       # 两侧分别执行，比数值
python3 _scripts/_tools/check_reference_parity.py --verify
```

fixture 刻意**压住 128 token 的截断边界**（长度分桶 tiny / short / near_limit /
over_limit 各必须有样本），否则截断契约的差异会被无意放过。

---

## 7. 从零重建（完整顺序）

```bash
cd <HOME>

# 1) 隔离运行时环境
/Library/Developer/CommandLineTools/usr/bin/python3 -m venv .venv-embedding
.venv-embedding/bin/python -m pip install --upgrade pip

# 2) wheelhouse（联网一次）→ 离线安装
.venv-embedding/bin/python _scripts/_tools/build_wheelhouse.py --build --force
.venv-embedding/bin/python -m pip install --no-index \
    --find-links wheelhouse -r embedding-runtime-requirements.lock
python3 _scripts/_tools/build_wheelhouse.py --offline-test

# 3) 模型 hash 锚点
.venv-embedding/bin/python _scripts/_tools/build_model_manifest.py --build

# 4) 参考实现（只在需要重跑 parity 时）
/Library/Developer/CommandLineTools/usr/bin/python3 -m venv \
    <HOME>
<HOME> -m pip install \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    torch transformers sentence-transformers sentencepiece safetensors scipy scikit-learn
python3 _scripts/_tools/fetch_reference_model.py --fetch
python3 _scripts/_tools/check_reference_parity.py --run
```

（第 4 步需要联网。若完全断网，前三步仍然可用 —— 两个模型的推理不依赖参考环境。）

---

## 8. 本指南**不**覆盖的东西

- **全量 249,105 条的向量索引**：仍未构建。`VECTOR_INDEX_MANIFEST.status` 保持
  `NOT_BUILT`，直到 §21 的全部门禁通过。本指南只保证**运行时可用**。
- **不保证与 HuggingFace 上的 checkpoint 一致**：`huggingface.co` 不可达，
  拿不到那个 checkpoint。能保证的是本地文件与 **ModelScope 上游**逐位一致，
  且比对用的 `model.safetensors` 就是上游那一份（sha256 在案）。
- **不保证跨机器可移植**：wheelhouse 是按**本机解释器**的 tag 下载的
  （cp39 + arm64/universal2）。换机器要重新 `--build`。
