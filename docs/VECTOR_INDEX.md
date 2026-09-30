# VECTOR_INDEX.md — 向量检索（设计与状态）

> ⚠️⚠️ **本文件描述的是设计。截至撰写时，向量检索后端尚未实现、未实测。** ⚠️⚠️
>
> | 项 | 状态 |
> |---|---|
> | Adapter 接口 | ⚠️ **未实现**（本文档即其规范） |
> | 向量库 | ⚠️ **未建**（`find . -iname "*.lance" -o -iname "*.onnx"` 返回空） |
> | Embedding 模型 | ⚠️ **未选型**（`_scripts/requirements.txt` 无任何向量/模型依赖声明） |
> | 评测数字 | ⚠️ **无**。本文档**不含任何实测分数**，因为一次都没跑过 |
> | 代表性子集 | ⚠️ **未抽取** |
>
> **实现后必须回填**（本文档末尾 §7 列了清单）：
> 实际模型名与版本、维度、归一化方式、子集规模与抽样方法、
> 四个方向的实测 Recall@k / MRR、构建耗时与索引体积、以及
> `INDEX_MANIFEST.json` 里的向量段落。
>
> **在此之前，任何引用本文档的表述都不得声称向量检索已可用。**

---

## 0. 为什么单独立一份「设计」文档

Phase 1 的 `ARCHITECTURE.md §8` 已把向量检索列为混合检索的一路，
Phase 2 把 Passage 层冻结完成。现在到 Phase 3，向量这一路**还没有写**，
但它的**接口必须先定下来**，理由：

1. **接口是契约**。上游（Query Router）与下游（Fusion）都要知道
   「一个向量后端需要提供什么」，否则实现时会把模型细节泄漏到调用方，
   之后换模型就要改调用方。
2. **未实现的组件必须可见**。把它写成「已完成」会污染整个检索层的可信度 ——
   这与本项目「宁可标 SOURCE_TRACE_INCOMPLETE 也不给看似完整的答案」是同一条纪律。
3. **模型选型需要证据，不能凭直觉**。见 §3：先用代表性子集测方向，
   再决定是否值得全量。

---

## 1. Adapter 接口（规范，未实现）

向量后端必须以 **adapter** 形式接入，调用方只依赖下面三个方法，
**不依赖任何具体模型或库**。

```python
class VectorAdapter:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量编码文档侧文本。

        要求：
        * 返回长度必须等于输入长度（调用方核验，不等即报错）
        * 向量维度必须与 model_metadata()['dimensions'] 一致
        * 必须确定：同一输入两次 → 同一向量（浮点逐位或严格容差内）
        * 必须支持批大小控制，且分批不改变结果
        """

    def embed_query(self, text: str) -> list[float]:
        """编码查询侧文本。

        ★ 为什么与 embed_documents 分开：
        多数检索模型对「查询」与「文档」使用不同的前缀/指令模板
        （asymmetric encoding）。若共用一个方法，会把查询当文档编码，
        实测上会显著掉分 —— 接口层先把这条分开，避免实现时踩。
        """

    def model_metadata(self) -> dict:
        """模型自述元数据。**必填字段见下表** —— 缺任何一个都视为不合格。"""
```

### 1.1 `model_metadata()` 必填字段

| 字段 | 说明 | 为什么必须 |
|---|---|---|
| `model` | 模型标识 | 换模型必须能在 manifest 里看见 |
| `version` | 模型版本 / 权重版本 | 同名字不同版本结果不同，必须可区分 |
| `dimensions` | 向量维度 | 建库与查询必须一致；不一致会让检索静默失效 |
| `normalization` | 归一化方式（如 L2 / none） | 决定内积还是余弦；弄错会整体偏序 |
| `language_capability` | 支持语言（如 `[zh, fr, en]` 或 `multilingual`） | 本项目必须做**跨语言**检索（zh→fr），单语模型直接不合格 |
| `max_tokens` | 单条最大长度 | Passage 有长有短，超长会被截断，必须知道截断点 |
| `build_config` | 抽取子集规模 / 批大小 / 随机种子等 | §13 索引可重建的前提 |

> **注意**：这里刻意**不写具体模型名**。选型需要 §3 的实测证据，
> 现在写任何模型名都是编造。

### 1.2 Adapter 不得做的事

| 禁止 | 原因 |
|---|---|
| ❌ 修改 canonical `raw_text` | 与 Phase 2 §七 无损摄入原则冲突 |
| ❌ 在 adapter 里做 retrieval 逻辑（排序 / 过滤） | 职责分离；排序属于 fusion 层 |
| ❌ 返回不存在的 `passage_id` | 本层根本不该产生 ID，只产生向量 |
| ❌ 静默降级（模型加载失败就返回零向量） | 会让检索「看起来能跑」但结果全错。必须 fail loud |

---

## 2. 存储形态（候选，未定）

`ARCHITECTURE.md:298` 已定项目方向：**第一版用 LanceDB**
（本地文件、无需服务、既有实践经验）。那是本项目的既有选型记录，
不是本文档新提的方案。

LanceDB 之外**不引入**外部向量服务（与「派生物可重建、无服务依赖」一致）。

候选索引需保留的元数据列（与 lexical 的 `passage_meta` 对齐，便于 fusion 时 join）：

```
passage_id · session_id · seminar_id · language · text_role
authority_level · trace_status · witness_id · corpus_source_id
vector · model_version
```

**关键约束**：向量必须与 `passage_id` 一起存。fusion 阶段靠 `passage_id` 去重，
没有它就无法把「向量命中」与「词法命中」合并。

---

## 3. 为什么先做 5k–20k 代表性子集，不 embed 全 249,105

| 理由 | 说明 |
|---|---|
| **先验证方向，再谈规模** | 若跨语言（zh→fr）根本不 work，全量 embedding 只是把失败放大 249,105 倍 |
| **成本可控** | 全量编码 + 建库 + 调参的时间与存储成本高一个数量级；子集能在一次会话内迭代 |
| **可比较** | 四个方向（§4）各需要人工判定的相关性标签；子集才能逐条评定 |
| **避免锁定** | 一旦全量入库，换模型就要重建，容易产生「为了不重建而将就」的路径依赖 |
| **与 FTS5 对照更公平** | lexical 基线已覆盖全库（249,105）。子集向量先看「能不能打到 FTS 打不到的东西」，而不是先比绝对召回 |

**子集抽样要求**（实现时须记录在 `build_config`）：

| 要求 | 说明 |
|---|---|
| 覆盖两种语言 | zh 与 fr 都要有，否则测不了跨语言方向 |
| 覆盖多个 seminar | 不能只抽一期，否则测不出 seminar 过滤是否有效 |
| 覆盖两种 text_role | transcription 与 translation 都要有 |
| 覆盖 `trace_status` 两种取值 | 否则不知道检索是否会漏掉 INCOMPLETE 的段落 |
| 抽样方法可复现 | 固定随机种子并写进 manifest；不得用「随手挑」 |

---

## 4. 四个必测方向

向量检索的**唯一目的**是补上词法检索打不到的部分。因此必须分方向测，
不能只报一个总体分数。

| # | 方向 | 测什么 | 为什么单列 |
|---|---|---|---|
| 1 | **zh → zh** | 中文查询 → 中文段落 | 与 FTS5 bigram 直接对照，看语义检索是否真有增益 |
| 2 | **zh → fr** | 中文查询 → 法文段落 | **跨语言**。这是 FTS5 结构性做不到的（bigram 与法语词形无交集）。也是中译缺失（`passage` 层面 fr 是 zh 的 2.0166 倍）时的补救路径 |
| 3 | **fr → fr** | 法文查询 → 法文段落 | 与 FTS5 法语归一化对照 |
| 4 | **paraphrase → relevant** | 换一种说法问同一件事 → 原段落 | 语义检索的核心价值：词面不同、意思相同 |

### 4.1 为什么必须包含「跨语言」这一维

实测事实（`_data/passage_store/_build_meta.json`）：

```
by_language: {"fr": 166527, "zh": 82578}
```

法语段数是中文的 **2.0166 倍** —— 也就是说**大量法语段落没有中译**。
`ALIGNMENT_MODEL.md §0` 已明确禁止假设 1:1。
在这个语料形态下，一个「只能用中文查中文」的系统会永久丢掉一半以上语料；
跨语言方向不是加分项，**是可用性前提**。

### 4.2 判定与记录要求

每个方向都必须：

1. 有**人工判定**的相关性标签（不能只用 ground-truth 子串匹配 ——
   语义检索命中的段落往往**不含**查询词，子串匹配会把正确答案判成错的）；
2. 报告 **Recall@5 / @10 / @20**、**MRR@10**、**nDCG@10**
   （定义见 `RETRIEVAL_EVALUATION.md §1`）；
3. 与 lexical 基线**在同一查询集**上对照 —— 否则数字不可比；
4. 保留每条的 `vector_rank`（供 Evidence Bundle 的 `why_retrieved`）。

---

## 5. 与 lexical 的分工（预期，待实测验证）

| 查询类型 | 预期主力 | 说明 |
|---|---|---|
| 精确术语（`objet a` / `大他者`） | lexical + alias | 词面命中，FTS5 已经很好 |
| 换说法 / 描述性提问 | vector | 「欲望为什么永远无法满足」这类没有对应词面 |
| 中文查法文原文 | vector | FTS5 结构性做不到 |
| 精确引文 | lexical（短语匹配） | 已实现，见 `LEXICAL_INDEX.md §4` |

⚠️ **这整张表是预期，不是实测结论。** 实现后必须用 §4 的数字**证实或推翻**它。
推翻是有价值的结果 —— 如果向量在某方向没有增益，就不该为它付出复杂度。

---

## 6. 本阶段（Phase 3）对向量的明确决定

| 决定 | 理由 |
|---|---|
| ✅ **先定接口，不写实现** | 接口是契约，实现需要模型选型证据 |
| ✅ **只做子集，不做全量** | §3 |
| ✅ **四个方向的评测方案先定** | §4；否则实现完不知道算不算成功 |
| ❌ **不引入外部向量服务** | 与「派生索引可重建、无服务依赖」一致 |
| ❌ **不在此阶段替换 lexical** | lexical 是全库、确定性的；向量是补充而非替代 |
| ❌ **不做 Graph-RAG / 多跳** | Phase 3 非目标；见 `RETRIEVAL_ARCHITECTURE.md §6` |

---

## 7. 实现后必须回填的清单

实现向量后端时，以下每一项都要**用实测值替换本文档里的 ⚠️**：

- [ ] §0 顶部状态表：四个 ⚠️ 全部改为实测状态
- [ ] adapter 实现文件路径
- [ ] `model_metadata()` 的**七个必填字段的实际值**（含真实模型名与版本）
- [ ] 选定向量库与索引体积
- [ ] 代表性子集：规模、抽样方法、随机种子、语言/seminar/text_role 分布
- [ ] 四个方向各自的 Recall@5/10/20、MRR@10、nDCG@10
- [ ] 每个方向与 lexical 基线的**同查询集对照**数字
- [ ] §5 的分工表：逐行标注「被证实 / 被推翻」
- [ ] 构建耗时
- [ ] `INDEX_MANIFEST.json` 的向量段落 —— 该 manifest **已存在**（vault 根），
      当前 `embedding: null` + `embedding_note` 明示未实现；
      实现后把 `embedding` 从 `null` 换成真实的 `model` / `dimensions` / `normalization`
      （见 `LEXICAL_INDEX.md §6`）
- [ ] 新增测试：向量层的确定性、不退化为零向量、跨语言方向不回归

---

## 8. 复核命令（验证「确实未实现」）

```bash
cd <HOME>

# 1. 没有任何向量资产
find . \( -iname "*.lance" -o -iname "*.onnx" -o -iname "*embed*" \) -not -path "./.git/*"
# 期望：无输出

# 2. 没有向量依赖声明
grep -niE "lancedb|onnx|sentence-transformers|faiss" _scripts/requirements.txt
# 期望：无输出（或非 0 退出码）

# 3. 没有向量实现文件
ls _scripts/_tools/ | grep -iE "vector|embed"
# 期望：无输出

# 4. 没有向量评测结果
ls _data/index/ | grep -i vector
# 期望：无输出
```

---

*配套：`RETRIEVAL_ARCHITECTURE.md` · `LEXICAL_INDEX.md` · `HYBRID_RETRIEVAL.md` ·
`EVIDENCE_BUNDLE.md` · `RETRIEVAL_EVALUATION.md`*
