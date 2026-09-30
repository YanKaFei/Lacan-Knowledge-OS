# HYBRID_RETRIEVAL.md — 混合检索与融合

> 版本 `1.0.0`
> 总纲：`RETRIEVAL_ARCHITECTURE.md`　·　向量：`VECTOR_INDEX.md`　·　证据：`EVIDENCE_BUNDLE.md`

---

## 0. 状态

> | 组件 | 状态 | 证据 |
> |---|---|---|
> | Exact / Alias | ✅ 已实现 | `alias_index.py`（666 条别名） |
> | Lexical | ✅ 已实现 | `lacan_search.py`（FTS5，249,105 行） |
> | **Graph** | ✅ **已实现**，但**数据极少** | `hybrid_retrieve.graph_component()`；`relations.jsonl` 仅 **1** 行（§5） |
> | Vector | ⚠️ **未实现** | `INDEX_MANIFEST.json` → `embedding: null`；`vector_component()` 是占位 |
> | **Union / Dedup** | ✅ **已实现** | `hybrid_retrieve.retrieve()` |
> | **RRF 融合** | ✅ **已实现** | `rrf_fuse(components, k=60)` |
> | Rerank | 🟡 字段就位（`rerank_score`），无独立 reranker | 实测该字段为 `null` |
> | `explain` 轨迹 rank | ✅ **已修** | 实测 `ranks: {"lexical": 1}`（见 §5.4） |
> | **Diversity** | ✅ **已实现** | `diversify()`：near-dup / session limit / witness-aware |
> | **Evidence Bundle** | ✅ **已实现** | `retrieve()` + `validate_bundle()`，schema `evidence-bundle/v1` |
>
> **主链已跑通**：`Query Router → Alias / Lexical / Graph → RRF → Diversity → Bundle`。
> 唯一缺的是 **Vector**（占位）。
>
> 实测（`retrieve("大他者", top_k=5, explain=True)`）：
>
> ```jsonc
> components : {"alias": 1, "lexical": 50, "graph": 0, "vector": 0,
>               "vector_status": {"implemented": false, "reason": "..."}}
> fusion     : {"method": "rrf", "k": 60,
>               "note": "只用名次，不用原始分数（避开不可比 score space）"}
> diversity  : {"kept": 5, "dropped": [{"reason": "near_duplicate"}], "session_limit": 3}
> warnings   : ["VECTOR_COMPONENT_ABSENT: ..."]
> validate_bundle(bundle) -> []
> ```
>
> **实现后必须回填**：`k` 取值的对照实验（见 §3.2）、rerank 的实际方案。

---

## 1. 为什么**禁止** `0.5 * BM25 + 0.5 * cosine`

这是本文档最重要的一条。看似最直观的加权求和，实际上是一个**错误做法**。

### 1.1 两个分数不在同一个度量空间

| 组件 | 分数性质 | 量纲 |
|---|---|---|
| BM25 | **无界**，取决于语料统计（文档长度、词频、平均长度、`idf`） | 实数为正，量级随语料与查询词频变化 |
| cosine / 内积 | **有界**（归一化后通常在 `[-1, 1]` 或 `[0, 1]`） | 相似度，量级稳定 |

直接把两者相加，等于**把「BM25 的 12.7 分」和「余弦的 0.83 分」按 0.5 : 0.5 混合**。
这不是「等权重」，而是**让 BM25 单方面主导**（12.7 × 0.5 远大于 0.83 × 0.5）。

### 1.2 「先归一化再加权」也不稳

常见补救是 min-max 或 z-score 归一化后再加权。但它引入新的问题：

| 问题 | 说明 |
|---|---|
| 归一化是**按查询**做的 | 同一段落在不同查询里被归一化成不同分数 → 跨查询不可比 |
| min-max 受**异常值**支配 | 一个极高 BM25 分会把其余全部压到接近 0 |
| 分布随查询类型变化 | 精确术语查询的 BM25 分布与描述性提问完全不同 → **有效权重逐查询漂移** |
| 权重变成隐藏超参 | 表面写 `0.5/0.5`，实际等效权重每次查询都不一样，且**无法审计** |

### 1.3 正确做法：只用**排名**

rank 是**跨组件天然可比的**：第 1 名就是第 1 名，不管原始分数是 12.7 还是 0.83。
这正是 **Reciprocal Rank Fusion（RRF）** 的立足点。

> **纪律**：融合层**只消费 rank，不消费 raw score**。
> raw score 仍然要保留（见 §4），但**不参与融合计算** ——
> 它是审计用的证据，不是融合的输入。

---

## 2. 推荐流程

```
QueryPlan（来自 query_router.py）
      │
      ├──────────────┬──────────────┬──────────────┐
      ▼              ▼              ▼              ▼
 ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
 │ 1 Exact │   │ 2 Lexical│   │ 3 Vector │   │ 4 Graph  │
 │  Alias  │   │   FTS5   │   │  ⚠️未实现 │   │ ✅已实现  │
 │ ✅       │   │ ✅        │   │  (占位)   │   │ 数据仅 1  │
 └────┬────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘
      │             │              │              │
      │  rank 1..n  │  rank 1..n   │  rank 1..n   │  rank 1..n
      └─────────────┴──────┬───────┴──────────────┘
                           ▼
                   ┌───────────────┐
                   │ 5 Union       │  各路结果并集（不丢任何一路的候选）
                   └───────┬───────┘
                           ▼
                   ┌───────────────┐
                   │ 6 Dedup       │  按 passage_id 去重；保留各路 rank
                   └───────┬───────┘
                           ▼
                   ┌───────────────┐
                   │ 7 RRF         │  Σ 1/(k + rank_i)，k=60  ✅已实现
                   └───────┬───────┘
                           ▼
                   ┌───────────────┐
                   │ 8 Rerank      │  可选；对 top-N 做交叉重排
                   └───────┬───────┘
                           ▼
                   ┌───────────────┐
                   │ 9 Diversity   │  防止单一 seminar/language 淹没结果
                   └───────┬───────┘
                           ▼
                  Evidence Bundle（见 EVIDENCE_BUNDLE.md）
```

### 2.1 每一步的职责边界

| 步 | 做什么 | **不**做什么 |
|---|---|---|
| 1 Exact/Alias | 别名精确命中，含歧义暴露 | 不做模糊匹配（模糊是 lexical 的事） |
| 2 Lexical | FTS5 bm25 排序 | 不做跨语言（FTS5 结构性做不到） |
| 3 Vector | 语义相似 | 不做关键词精确匹配 |
| 4 Graph | 关系扩展（邻居实体相关段落） | 不做排序 |
| 5 Union | 并集 | **不排序、不截断**（截断会丢证据） |
| 6 Dedup | 按 `passage_id` 合并 | **不丢**任何一路的 rank（多路命中要能看出） |
| 7 RRF | 只按 rank 融合 | **不使用 raw score**（§1.3） |
| 8 Rerank | 对 top-N 精排 | 不改 rank 证据字段（🟡 仅字段就位，无独立 reranker） |
| 9 Diversity | 结果整形（✅ 已实现） | 不改分数的相对顺序（只做必要的下采样） |

---

## 3. RRF 公式与参数

### 3.1 公式

对每个候选文档 `d`：

```
RRF(d) = Σ         1 / (k + rank_r(d))
        r ∈ R
```

其中：

* `R` = 参与融合的排名列表集合（alias / lexical / vector / graph）
* `rank_r(d)` = 文档 `d` 在列表 `r` 中的名次（**从 1 开始**）
* `k` = 平滑常数

若 `d` 未出现在列表 `r` 中，则该列表**不贡献**（等价于该项为 0），
**不是**按「最后一名 + 1」惩罚 —— 后者会惩罚只被单路命中的正确结果。

### 3.2 参数

| 参数 | 建议值 | 依据 |
|---|---|---|
| `k` | **60** | RRF 原文（Cormack et al. 2009）的常用取值。`k` 越大，头部名次差异被压得越平；`k=60` 在「不信任任何单路的第一名」与「保留头部优势」之间取平衡 |
| 各路 `top-n` | 20（可调） | 参与融合的深度。取太小会丢掉「某路排第 15 但另一路排第 2」的候选 |
| 输出 `top-k` | 10–20 | 交给 rerank / bundle |

⚠️ `k=60` 是**引用惯例**，不是本项目实测调出来的值。
实现后应做一次 `k ∈ {10, 30, 60, 100}` 的对照，并把结果回填到本文档。

### 3.3 为什么 RRF 适合本项目

| 性质 | 对本项目的意义 |
|---|---|
| 只用 rank | 不需要假设任何分数分布，`fr_fts` 的 bm25 与向量的余弦可直接共存 |
| 无需训练 | 没有标注数据也能用（本项目的标注数据还很少） |
| 对单路失效鲁棒 | 某一路返回垃圾时，只要其他路正常，RRF 仍能救回正确结果 |
| 可解释 | 每个候选的贡献可以逐路算出 `1/(k+rank)`，能写进 `why_retrieved` |

---

## 4. 所有 component rank 必须保留

**硬要求**：debug output / Evidence Bundle 里必须能看见
**每一个 component 给这个候选打了第几名**，而不只是一个融合后的总分。

```
passage.S13.unknown.P7999
  fusion_rank   : 3
  rrf_score     : 0.0325
  lexical_rank  : 1        ← 词法第 1 名
  vector_rank   : 7        ← 向量第 7 名
  alias_rank    : —        （未被别名命中）
  graph_reason  : —        （未经图扩展）
  why_retrieved : lexical_fr + vector_semantic
```

为什么必须这样：

| 理由 | 说明 |
|---|---|
| **可追溯** | 用户能问「为什么这条被检索出来」，系统必须答得出 |
| **可调试** | 融合效果差时，能看出是哪一路在拖后腿 |
| **可评测** | 分方向评测（`VECTOR_INDEX.md §4`）需要单路 rank，不能只有融合结果 |
| **防暗箱** | 避免「调权重调到看起来好」这类无法审计的操作（也是 §1 禁止加权求和的延伸） |

`lacan_search._row_to_hit()` 已经在返回里带 `rank` 与 `why_retrieved`
（值形如 `lexical_zh` / `lexical_fr` / `exact_id`）—— **这个设计要一路保留到 Bundle**。

---

## 5. Graph：**已实现，但几乎没有数据**

这一条必须单独说清，因为它影响融合的**实际效果**，不只是进度。

### 5.1 组件已实现

`hybrid_retrieve.graph_component()`（`hybrid_retrieve.py:159`）是**已实现**的：

| 特性 | 实现 |
|---|---|
| 数据源 | SQLite typed relations（**不引 Neo4j**） |
| 只走主库 | 候选库关系是未审核建议，**不作为检索依据** |
| 深度受限 | `max_depth=2` |
| 候选受限 | `DEFAULT_GRAPH_CANDIDATES=40` |
| 可解释 | 每条结果带 `graph_reason`，形如 `gaze --formalized_as--> objet-a` |

### 5.2 但关系数据只有 1 条

实测 `_data/relations/`：

| 文件 | 行数 |
|---|---:|
| `relations.jsonl`（主库，graph 只走这里） | **1** |
| `relations.candidate.jsonl`（候选） | **4** |
| `relations.rejected.jsonl` | 0 |
| **合计** | **5** |

且这唯一的主库关系是 Phase 1 的**测试 fixture**
（`rel.000001: seminar.ST1 --appears_in--> case.schreber`），
**不是**从 249,105 段语料系统抽取出来的真实关系图。

**实测后果**：`components.graph == 0` —— graph 组件每次返回空。

### 5.3 结论

| 判断 | 说明 |
|---|---|
| Graph **算法已就位** | 代码可用、可解释、有限流 |
| Graph **实际不产生扩展** | 只有 1 条边，且还是 fixture |
| 这不是「没写」的问题 | 是**关系数据本身还没有** |
| 因此 Graph-RAG 仍排除在 Phase 3 之外 | 见 `RETRIEVAL_ARCHITECTURE.md §6.3.1` |
| 前置条件 | 需要 relation extraction（从语料抽关系）或人工建立 —— 两者都不在 Phase 3 范围内 |

**流程图中保留 Graph 这一路**，接口完整；但**当前它不贡献任何候选**。

---

## 5.4 `explain` 轨迹的 component rank（**已修**）

「所有 component rank 必须保留」这条要求在**最终 `evidence[]` 里满足**：

```
passage.S21.unknown.L10.P0099 | lexical_rank=1  fusion_rank=1
passage.S10.unknown.L23.P0105 | lexical_rank=2  fusion_rank=2
passage.S26.unknown.L10.P0028 | lexical_rank=4  fusion_rank=3
```

**早期版本的 `explain` 轨迹曾全部为 `null`**（本文档上一版记录过该缺陷）：

```jsonc
// 旧：explain.fusion_order_before_diversity[0].ranks
{ "lexical_rank": null, "graph_rank": null, "vector_rank": null }
```

**该问题已修** —— 现在实测：

```jsonc
// 新：explain.fusion_order_before_diversity[0]
{ "passage_id": "passage.S21.unknown.L10.P0099",
  "rrf": 0.016393,
  "ranks": { "lexical": 1 } }
```

### 5.4.1 仍存在一处键名不一致（轻微）

| 位置 | 键名 |
|---|---|
| `evidence[]` | `lexical_rank` / `graph_rank` / `vector_rank`（带 `_rank` 后缀） |
| `explain[].ranks` | `lexical` / `graph` / `vector`（**不带**后缀） |

两处表达同一件事但键名不同，消费方需要写两套取值逻辑。
**建议统一**（未做）—— 属轻微可维护性问题，不影响正确性。

`evidence[].alias_rank` 实测为 `null`（该查询经 alias 命中，但 alias 组件
不产出 passage 级 rank，只产出 entity 级 —— 见 `explain.alias_hits`）。

---

## 6. 测试现状

### 6.1 已实现（`test_phase3_retrieval.py`，26 项，实测 OK）

本层的关键契约**都已有测试覆盖**：

| 测试 | 锁住的契约 |
|---|---|
| `test_00_bundle_schema` | schema 常量 `evidence-bundle/v1` |
| `test_01_evidence_required_fields` | evidence 字段齐备 |
| `test_02_four_dimensions_stay_separate` | 四层语义不混 |
| `test_03_no_fabricated_ids_and_validate` | 无编造 ID |
| `test_04/05_validate_bundle_rejects_*` | 校验器能拒编造 / provenance 篡改 |
| `test_06_incomplete_provenance_preserved` | INCOMPLETE 如实保留 |
| `test_07_recovered_translation_status_preserved` | recovered 不被升格 |
| `test_08_retrieval_is_deterministic` | 确定性 |
| **`test_09_rrf_fusion_is_rank_based`** | **RRF 只用名次** |
| **`test_10_fusion_uses_ranks_not_raw_scores`** | **不用 raw score**（§1.3 的纪律有测试） |
| `test_11_graph_depth_and_limit_respected` | graph 深度/候选受限 |
| `test_12_graph_does_not_use_unreviewed_candidates` | 只走主库关系 |
| `test_13_diversify_collapses_near_duplicates` | 近重复折叠 |
| `test_14_diversify_enforces_session_limit` | session 上限 |
| `test_15_diachronic_prefers_period_coverage` | 历时查询优先 period 覆盖 |
| `test_16_coverage_reports_four_dimensions` | coverage 四维 |
| `test_17/18_vector_*` | 向量接口契约（即便未实现，接口与 adapter 契约有测试） |
| `test_19/20/21_manifest_*` | manifest 与 corpus hash 一致 / CLI 可验 / 大索引不入 git |
| `test_23_retrieval_does_not_mutate_canonical_store` | 不改 canonical store |
| `test_24/25_cli_*` | CLI search / explain |

**实现层也已经落地**，所以 §6 不再列「待实现要求」——
测试文件本身就是契约，以上表格是从测试名反查的覆盖清单。

### 6.2 仍建议补测

| 测试 | 断言 | 为什么 |
|---|---|---|
| `test_explain_trace_carries_component_ranks` | `explain` 的 `ranks` 必须与 `evidence[].*_rank` 一致 | 当前 explain 里全是 `null`（见 §5.4） |
| `test_rrf_k_sensitivity` | 对 `k ∈ {10,30,60,100}` 出对照数字 | §3.2 的 `k=60` 目前是**引用惯例**，未调优 |
| `test_graph_contributes_when_relations_exist` | 造一个有多条关系的数据集，断言 graph 真的贡献候选 | 当前 `graph == 0` 无法区分「算法坏」与「没数据」 |

---

## 7. 复核命令

```bash
cd <HOME>

# 1. 确认融合层**已实现**
grep -n "def rrf_fuse\|def diversify\|def graph_component" _scripts/_tools/hybrid_retrieve.py

# 2. 确认 graph 几乎没有数据（这是设计前提，不是缺陷报告）
#    注意：graph 组件本身是已实现的
for f in _data/relations/*.jsonl; do printf "%-40s %s\n" "$f" "$(wc -l < $f)"; done

# 3. 确认已实现的两路各自可跑
python3 -c "
import sys; sys.path.insert(0,'_scripts/_tools')
import lacan_search as L, alias_index as A
print('lexical:', len(L.lexical_search('大他者', language='zh', limit=5)))
print('alias  :', len(A.exact_lookup('objet a')))"

# 4. 确认返回里已带 rank / why_retrieved（融合层要消费的字段已存在）
python3 -c "
import sys; sys.path.insert(0,'_scripts/_tools')
import lacan_search as L
h = L.lexical_search('大他者', language='zh', limit=1)[0]
print({k: h[k] for k in ('passage_id','rank','score','why_retrieved')})"
```

---

*配套：`RETRIEVAL_ARCHITECTURE.md` · `QUERY_MODEL.md` · `LEXICAL_INDEX.md` ·
`VECTOR_INDEX.md` · `EVIDENCE_BUNDLE.md` · `RETRIEVAL_EVALUATION.md`*
