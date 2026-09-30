# RETRIEVAL_ARCHITECTURE.md — Phase 3 检索架构总纲

> 版本 `1.0.0`　·　范围：Retrieval & Evidence Assembly
> 前置：`ARCHITECTURE.md`（§8 已定接口）· `PASSAGE_MODEL.md` · `WITNESS_MODEL.md` · `SOURCE_PROVENANCE.md`
> 实测发现与阶段记录：`PHASE3_FINDINGS.md`
>
> ⚠️ **时点说明**：Phase 3 的代码在本文档撰写期间仍在并行推进
> （`hybrid_retrieve.py` / `eval_retrieval.py` / `INDEX_MANIFEST.json` 都是撰写中途落地的）。
> 本文档已按**撰写完成时**的实际状态同步；若与代码不符，以代码为准。

---

## 0. 目标不是「做向量数据库」

本阶段的验收标准**不是**「有没有向量库」，而是：

> 给定一个拉康研究问题，系统能**可靠地找到证据**，并产出**可解释、可追溯**的
> Evidence Bundle —— 每一条结果都能回答「为什么被检索出来」，
> 且每个 `passage_id` 都指向 canonical store 里真实存在的一段。

这条标准决定了几件事：

| 因为 | 所以 |
|---|---|
| 结果必须可追溯 | 每个 component 的 **rank 必须保留**在输出里（不能只给一个融合分数） |
| 不允许编造 | `passage_id` 必须过 canonical store validator；查不到就返回空 |
| 检索质量排序在准确性之后 | 先保证「不编造、不改 canonical」，再谈召回率 |
| 拉康概念有历史分期 | Query 必须能表达 period / seminar 约束，而不是只做关键词匹配 |

---

## 1. 组件链（当前状态）

```
                        Query
                          │
                          ▼
              ┌───────────────────────┐
              │ §5 Query Router       │  ✅ 已实现  query_router.py
              │  deterministic first  │     纯规则，不调用模型
              └───────────┬───────────┘
                          │ QueryPlan
        ┌─────────────────┼─────────────────┬──────────────────┐
        ▼                 ▼                 ▼                  ▼
  ┌───────────┐   ┌─────────────┐   ┌─────────────┐   ┌──────────────┐
  │ §4 Exact  │   │ §3 Lexical  │   │ Vector      │   │ §8 Graph     │
  │   Alias   │   │   FTS5      │   │  ⚠️ 未实现   │   │ ✅ 已实现     │
  │ ✅已实现   │   │ ✅已实现     │   │  (占位接口)  │   │ 但数据极少    │
  │alias_index│   │lacan_search │   │             │   │ (见 §6.3)    │
  └─────┬─────┘   └──────┬──────┘   └──────┬──────┘   └──────┬───────┘
        │                │                 │                  │
        └────────────────┴────────┬────────┴──────────────────┘
                                  ▼
                        ┌───────────────────────────┐
                        │ Union → Dedup → RRF →     │  ✅ 已实现
                        │ Diversity                 │  hybrid_retrieve.py
                        └─────────┬─────────────────┘
                                  ▼
                        ┌───────────────────────────┐
                        │ Evidence Bundle           │  ✅ 已实现
                        │ (evidence-bundle/v1)      │  + validate_bundle()
                        └───────────────────────────┘
```

**当前状态**：`Query Router → Alias / Lexical / Graph → RRF → Diversity → Bundle`
**主链已跑通**；唯一缺的是 **Vector**（`hybrid_retrieve.vector_component()` 是占位，
`INDEX_MANIFEST.json` 里 `embedding: null` 明示未实现）。

实测一次完整调用（`hybrid_retrieve.retrieve("大他者", top_k=5, explain=True)`）：

```
components : {"alias": 1, "lexical": 50, "graph": 0, "vector": 0,
              "vector_status": {"implemented": false, "reason": "..."}}
fusion     : {"method": "rrf", "k": 60, "note": "只用名次，不用原始分数"}
diversity  : {"kept": 5, "dropped": [{"reason": "near_duplicate", ...}], "session_limit": 3}
warnings   : ["VECTOR_COMPONENT_ABSENT: vector backend 尚未实现…"]
validate_bundle(bundle) -> []          ← 无问题
```

---

## 2. 数据地基（实测计数）

所有检索都建立在 Phase 2 已冻结的 canonical store 上。实测（`_data/passage_store/_build_meta.json`）：

| 项 | 计数 | 出处 |
|---|---:|---|
| passages | **249,105** | `counts.passages` |
| ├ zh | 82,578 | `counts.by_language.zh` |
| └ fr | 166,527 | `counts.by_language.fr` |
| sessions | 559 | `counts.sessions` |
| seminars | 28 | `counts.seminars` |
| witnesses | 3 | `counts.witnesses` |
| corpus_sources | 3 | `counts.corpus_sources` |
| passage_realizations | 249,105 | `counts.passage_realizations` |

检索层**只读**这些数据。`test_phase3_lexical.py::test_08_does_not_mutate_canonical_store`
用 mtime + size 锁住「建索引不得修改 canonical store」。

---

## 3. 各组件职责与状态

| 组件 | 文件 | 状态 | 产出 |
|---|---|---|---|
| §5 Query Router | `_scripts/_tools/query_router.py` | ✅ 已实现 | `QueryPlan` |
| §4 Alias Index | `_scripts/_tools/build_alias_index.py` + `alias_index.py` | ✅ 已实现 | `_data/index/alias_index.jsonl`（666 条） |
| §3 Lexical Index | `_scripts/_tools/build_lexical_index.py` + `lacan_search.py` | ✅ 已实现 | `_data/index/lexical.sqlite`（249,105 行 meta） |
| §3 Tokenizer Benchmark | 同上 | ✅ 已实现 | `_data/index/tokenizer_benchmark.json` |
| §2 Vector Index | `hybrid_retrieve.vector_component()`（占位） | ⚠️ **未实现** | `INDEX_MANIFEST.json` → `embedding: null`；设计见 `VECTOR_INDEX.md` |
| §7 Hybrid Fusion (RRF) | `_scripts/_tools/hybrid_retrieve.py` | ✅ **已实现** | `rrf_fuse(components, k=60)` |
| §8 Graph Expansion | 同上 `graph_component()` | ✅ **已实现**（数据极少，见 §6.3） | 用 SQLite typed relations，不引 Neo4j |
| §10 Diversity | 同上 `diversify()` | ✅ **已实现** | near-dup / session limit / witness-aware |
| §9 Evidence Bundle | 同上 `retrieve()` + `validate_bundle()` | ✅ **已实现** | schema `evidence-bundle/v1` |
| §15 Evaluation | `_data/retrieval_eval_spec.jsonl`（120 条规范）+ `build_retrieval_eval.py` / `eval_retrieval.py` | 🟡 脚本就位、**结果未产出** | `retrieval_eval.jsonl` 不存在 |
| §13 Index Manifest | `INDEX_MANIFEST.json`（vault 根） | ✅ **已产出** | 覆盖 lexical / alias 两个索引，`embedding: null` |

---

## 4. 检索的三条硬纪律

### 4.1 不编造 passage_id

`lacan_search.exact_passage()` 在 ID 不存在时返回 `None`；
`lexical_search()` 查不到返回 `[]`。测试锁住：

```
test_phase3_lexical.py::test_09_no_fabricated_results
    lexical_search("zzzqqqxxx不存在的词") == []
    exact_passage("passage.NOT.A.REAL.ID") is None
```

### 4.2 归一化只作用在派生索引上

canonical `raw_text` **一字不改**。检索用的归一化文本在建索引时写进 FTS 表，
查询侧做同样的归一化。这与 Phase 2 §七「无损摄入」同构：
改动发生在派生物里，原件永远保留。

### 4.3 歧义必须显式暴露，禁止自动合并

`Autre` / `autre` 大小写携带理论差异（大他者 / 小他者）。
alias 索引折叠后碰撞时**全部返回**并标 `ambiguous_with`，让人看见冲突，
而不是静默选一个。实测 42 条被标 ambiguous，9 组跨实体碰撞待人工复核
（`_data/index/alias_collisions.jsonl`）。

---

## 5. 为什么这样分层（而不是一步到位做向量检索）

| 选择 | 理由 |
|---|---|
| **先做 alias + lexical，再做 vector** | 这两层是**确定性**的：同样的查询必得同样的结果，可被测试锁住。向量检索引入近似最近邻与模型版本，必须先把确定性基线立住，否则出问题分不清是「模型不好」还是「管道有 bug」 |
| **FTS5 而不是外部检索引擎** | Phase 1 已实测本机 SQLite 3.51.0 支持 FTS5；不引入服务依赖，索引是单文件，便于重建与审计 |
| **不引入 Neo4j** | `ARCHITECTURE.md §8` 已定：关系规模（10³–10⁵ 边）未到需要图数据库的程度。JSONL + 内存图 + SQLite 邻接表足够，且更易 diff |
| **Query Router 纯规则** | 用户 §5 硬要求「deterministic first，LLM 只能作可选 fallback」。规则可审计、可测试、零成本、无网络依赖 |
| **先 benchmark 再锁定 tokenizer** | 法语变音/撇号与中文分词都是真坑，凭直觉选会选错（实测第一版选反了，见 `LEXICAL_INDEX.md §3`） |

---

## 6. 本阶段明确的非目标

以下**不做**，且原因不是「来不及」，而是**顺序上不该现在做**：

| 不做 | 原因 |
|---|---|
| ❌ 建问答 Agent | 检索层还没有可交付的 Evidence Bundle，问答 Agent 会直接暴露在无证据生成的风险下 |
| ❌ 接 MCP Server | MCP 是**外部统一接口**，应在 Evidence Bundle schema 冻结之后再做，否则接口会随内部结构反复变 |
| ❌ 建 Codex connector | 同上：接口未定 |
| ❌ 引入 Neo4j | 见 §5；且会引入服务依赖，违背「派生物可重建」 |
| ❌ 自动 canonicalize | Phase 1/2 已定的红线：AI 内容永不自动升格 |
| ❌ 修改原始 corpus | 从 Phase 1 起就是只读。检索层尤其不能为了「提高召回」去改语料 |
| ❌ 全量 embedding 249,105 段 | 见 `VECTOR_INDEX.md §3`：先用 5k–20k 代表性子集验证方向，再谈规模 |

---

## 6.2 已发现的问题（含已修与仍在）

| # | 问题 | 状态 | 证据 |
|---|---|---|---|
| 1 | 中文自然写法 `研讨班 XI` 解析失败 | ✅ **已修** | `query_router.py:116-119` 新增中文+罗马数字分支；实测 `[11]` |
| 2 | 评测规范有 3 个 router 永不产出的 intent | ✅ **已修** | 实测 `spec − router = ∅`（13 类全部可产出） |
| 3 | `translation_terminology` 分支不可达（判定顺序在后） | ✅ **已修** | 该分支已前移到第 1 位；`jouissance 中文怎么译` → `translation_terminology` |
| 4 | `INDEX_MANIFEST.json` 不存在 | ✅ **已修** | 现有 `INDEX_MANIFEST.json`（vault 根），含 corpus_hash 与两个索引条目 |
| 5 | alias 索引的 `language` 对拉丁别名无区分力 | ⚠️ **仍在** | `concept.fr` 60 条中 59 条为 `und`；`concept.en` 68 条全为 `und` |
| 6 | `研讨班 11`（阿拉伯数字、无「期」字）仍失败 | 🔴 **仍在** | `_seminar_from('研讨班 11') == []` |
| 7 | intent 一致率低 | 🟡 **改善但未闭合** | 43/120 → **61/120** |
| 8 | `ambiguous_entities` 漏报 `case_variant` | ⚠️ **仍在** | `route("l'Autre 和 l'autre…")['ambiguous_entities'] == []` |
| 9 | **Graph 组件已实现，但关系数据只有 1 条** | 🔴 **仍在** | `relations.jsonl` = 1 行 → `components.graph == 0` |
| 10 | `explain` 轨迹的 component rank 全为 None | ✅ **已修** | 现实测 `ranks: {"lexical": 1}`；键名与 evidence 不一致（见 §6.3.2） |
| 11 | 单字母别名误命中（`A` → `concept.l-autre`） | 🟡 **仍在** | 使实体数虚增 → 影响 intent |

> #1–#4 都是**文档与实现不一致**或**实现缺口**，已在并行开发中修掉；
> #9–#11 是撰写完成时仍然存在的问题。

## 6.3 两个需要单独说明的问题

### 6.3.1 Graph 组件已实现，但**几乎没有关系数据**

`hybrid_retrieve.graph_component()` 是**已实现**的（用 SQLite typed relations
做受控深度扩展，不引 Neo4j，每条结果带 `graph_reason`）。
但实测 `_data/relations/`：

| 文件 | 行数 |
|---|---:|
| `relations.jsonl`（主库，graph 只走主库） | **1** |
| `relations.candidate.jsonl` | 4 |
| `relations.rejected.jsonl` | 0 |

且这唯一的主库关系是 Phase 1 的**测试 fixture**
（`seminar.ST1 --appears_in--> case.schreber`），不是从 249,105 段语料抽出的真实关系图。

**实测后果**：`components.graph == 0` —— graph 组件每次返回空。

**所以 Graph 的问题不是「算法没写」，而是「关系数据还没有」。**
需要 relation extraction 或人工建立关系，两者都不在 Phase 3 范围内。

### 6.3.2 `explain` 轨迹里的 component rank（**已修**，但键名仍不一致）

`hybrid_retrieve` 的 `evidence[]` **正确保留**了各路名次：

```
passage.S21.unknown.L10.P0099 | lexical_rank=1  fusion_rank=1
passage.S10.unknown.L23.P0105 | lexical_rank=2  fusion_rank=2
passage.S26.unknown.L10.P0028 | lexical_rank=4  fusion_rank=3
```

**早期版本**的 `explain.fusion_order_before_diversity[].ranks` 全是 `null`：

```jsonc
{ "lexical_rank": null, "graph_rank": null, "vector_rank": null }
```

—— 同一条 passage 在 evidence 里 `lexical_rank=1`，在 explain 里却是 `null`。
**该问题已修**，现实测：

```jsonc
{ "passage_id": "passage.S21.unknown.L10.P0099", "rrf": 0.016393,
  "ranks": { "lexical": 1 } }
```

**残留（轻微）**：两处键名不同 —— `evidence[]` 用 `lexical_rank`，
`explain[].ranks` 用 `lexical`。消费方需要写两套取值逻辑，建议统一。

---

## 7. 复核命令

```bash
cd <HOME>

# 权威计数
python3 -c "import json;m=json.load(open('_data/passage_store/_build_meta.json'));print(m['counts'])"

# 三个 Phase 3 测试套件（35 项）
cd _scripts/_tests
python3 -m unittest test_phase3_witness_semantics   # 12
python3 -m unittest test_phase3_alias_index         # 11
python3 -m unittest test_phase3_lexical             # 12

# Query Router 实跑
cd ../_tools && python3 query_router.py "研讨班 XI 里的 objet a"

# alias 统计
python3 -c "import sys;sys.path.insert(0,'.');import alias_index;print(alias_index.stats())"

# 词法检索
python3 -c "import sys;sys.path.insert(0,'.');import lacan_search as L;print(len(L.lexical_search('大他者',language='zh',limit=5)))"
```

---

*配套：`QUERY_MODEL.md` · `LEXICAL_INDEX.md` · `VECTOR_INDEX.md` ·
`HYBRID_RETRIEVAL.md` · `EVIDENCE_BUNDLE.md` · `RETRIEVAL_EVALUATION.md`*
