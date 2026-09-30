# EVIDENCE_BUNDLE.md — Evidence Bundle schema

> 版本 `1.0.0`
> 总纲：`RETRIEVAL_ARCHITECTURE.md`　·　融合：`HYBRID_RETRIEVAL.md`　·　溯源：`SOURCE_PROVENANCE.md`

---

## 0. 状态：✅ **已实现**（schema `evidence-bundle/v1`）

> | 项 | 状态 | 证据 |
> |---|---|---|
> | Bundle 生成器 | ✅ **已实现** | `_scripts/_tools/hybrid_retrieve.py` → `retrieve()` |
> | Bundle 硬校验器 | ✅ **已实现** | 同上 `validate_bundle()` / `_validate_bundle_impl()` |
> | schema 版本 | ✅ | 实测 `bundle["schema"] == "evidence-bundle/v1"` |
> | 上游组件 | ✅ alias / lexical / graph / RRF / diversity 已接 | **Vector 仍缺**（占位） |
> | 专项测试 | ✅ | `test_phase3_retrieval.py`（26 项，实测 OK） |
>
> 实测一次真实调用（`retrieve("大他者", top_k=5, explain=True)`）：
>
> ```
> validate_bundle(bundle)  ->  []          # 无问题
> warnings                 ->  ["VECTOR_COMPONENT_ABSENT: ..."]
> evidence                 ->  5 条
> ```
>
> ⚠️ **本文档的 schema 章节（§2/§3）已按实现的实际字段重写**；
> 早期草稿版本的字段名与实现有差异，差异点已在 §3.4 逐条列出。

---

## 1. 设计目标

Evidence Bundle 是一次检索的**完整交付物**。它必须能回答三个问题：

| 问题 | 由什么回答 |
|---|---|
| 「你找到了什么证据？」 | `evidence[]` —— 每条都带原文与 stable `passage_id` |
| 「为什么是这些？」 | 每条 evidence 的 `lexical_rank` / `vector_rank` / `graph_reason` / `fusion_rank` / `why_retrieved` |
| 「这些证据够不够、可不可信？」 | `coverage` + `warnings` + 每条 evidence 的 `provenance_status` / `canonical_status` |

**核心纪律**：

> 任何一个 `passage_id` 都必须通过 **canonical store validator**。
> 禁止生成不存在的 ID。

这条不是「尽量做到」，而是**结构性要求**：Bundle 的构造过程必须先查 canonical store，
拿不到记录就**不放进 evidence**（而不是放进去再补元数据）。
`lacan_search.exact_passage()` 已经在 API 层体现这条（不存在 → `None`，不编造）。

---

## 2. Bundle 级字段（**照实际实现**）

实测 `retrieve()` 返回的顶层键共 **16 个**（`explain=True` 时 **17 个**）：

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `schema` | str | 常量 | `"evidence-bundle/v1"` |
| `query` | str | 调用方 | 用户原始查询，**原样保留** |
| `intent` | str | `QueryPlan.intent` | 见 `QUERY_MODEL.md §3` |
| `language` | str \| None | `QueryPlan.language` | |
| `entities` | list | `QueryPlan.entities` | 含 `matched_alias` |
| `ambiguous_entities` | list | `QueryPlan` | 歧义须透传（见 §2.1） |
| `periods` | list | `QueryPlan.periods` | |
| `filters` | dict | `QueryPlan.filters` | 实际生效的过滤条件 |
| `evidence` | list[Evidence] | 见 §3 | 检索结果 |
| `coverage` | dict | `coverage_of()` | 见 §4 |
| `warnings` | list[str] | 见 §5 | 显式告警 |
| `components` | dict | 各路命中数 | 见 §2.2 |
| `fusion` | dict | RRF 元信息 | `{"method":"rrf","k":60,"note":...}` |
| `diversity` | dict | `diversify()` | `{"kept":N,"dropped":[...],"session_limit":3}` |
| `explain` | dict \| None | 仅 `explain=True` | 调试轨迹，见 `HYBRID_RETRIEVAL.md §5.4` |
| `from_llm_fallback` | bool | `QueryPlan` | 透传：本次解析是否走了 LLM 兜底 |
| `router` | dict | 路由元信息 | 实现额外提供 |

### 2.1 `components`：各路的实际命中数（实测）

```jsonc
{"alias": 1, "lexical": 50, "graph": 0, "vector": 0,
 "vector_status": {"implemented": false,
                   "reason": "vector backend 尚未实现（见 VECTOR_INDEX.md 状态标注）"}}
```

**这是「哪些组件真的参与了」的机械证据**：

* `graph: 0` —— 因为关系数据只有 1 条主库边（`RETRIEVAL_ARCHITECTURE.md §6.3.1`）；
* `vector: 0` + `vector_status.implemented=false` —— 向量未实现，
  **组件自己说出来**，而不是给出一个看起来完整的答案；
* 同时会在 `warnings` 里出现 `VECTOR_COMPONENT_ABSENT`。

> 这与 `SOURCE_PROVENANCE.md` 的 `SOURCE_TRACE_INCOMPLETE` 是同一条纪律的两种应用：
> **缺什么就说什么。**

### 2.2 ⚠️ 必须同时带上的两个「负数」字段

| 字段 | 说明 |
|---|---|
| `ambiguous_entities` | `QueryPlan` 里已存在。**必须透传** —— 若查询命中了歧义别名（如 `l'autre` 折叠到大他者），Bundle 里要能看见，否则调用方会把「本库没有小他者」误读成「查到了」 |
| `from_llm_fallback` | `QueryPlan` 里已存在。**必须透传** —— 让人知道这次解析是否用了模型兜底 |

> 这两个字段的存在理由相同：**把不确定性往外传，而不是在管道里抹掉。**

---

## 3. Evidence 级字段（**照实际实现**）

实测 `bundle["evidence"][i]` 的键共 **19 个**：

```
alias_rank · canonical_status · fusion_rank · graph_rank · graph_reason
language · lexical_rank · passage_id · provenance_status · rerank_score
seminar_id · session_id · source_authority · text · text_role
textual_realization · vector_rank · why_retrieved · witness_id
```

按用途分三组：**身份与溯源**（§3.1）、**检索证据**（§3.2）、
**实现特有的三个字段**（§3.3）。

### 3.1 身份与溯源（全部来自 canonical store，禁止推导）

| 字段 | 来源（passage 记录字段） | 说明 |
|---|---|---|
| `passage_id` | `id` | ★ 必须过 validator |
| `seminar_id` | `seminar_id` | 如 `seminar.S01` |
| `session_id` | `session_id` | 如 `session.S01.unknown.L01` |
| `witness_id` | `witness_id` | 具体文本版本（Phase 3 §0 三层结构里的中间层） |
| `language` | `language` | `fr` / `zh` |
| `text` | `raw_text` | ★ **canonical 原文**，不做任何改写 |
| `source_authority` | `authority_level` | `L1` / `L2` |
| `text_role` | `text_role` | `transcription` / `translation` / `edition` |
| `canonical_status` | `canonical` + `status` | 实测全库 `canonical=false`、`status=recovered` |
| `provenance_status` | `trace_status` + `trace_missing` | `COMPLETE` / `SOURCE_TRACE_INCOMPLETE` |

**实测取值形态**（`_data/passage_store/passages.jsonl` 首条）：

```
id                      passage.S01.unknown.L01.P0001
seminar_id              seminar.S01
session_id              session.S01.unknown.L01
witness_id              witness.zh.translation-project
language                zh
text_role               translation
authority_level         L2
canonical               False
status                  recovered
trace_status            SOURCE_TRACE_INCOMPLETE
trace_missing           ["upstream_original_file"]
```

> `canonical_status` 与 `provenance_status` **不是装饰**。
> 中译全库 `SOURCE_TRACE_INCOMPLETE`（上游源目录已消失），
> 法语全库 `COMPLETE`（第二跳可达）—— 实测 82,578 / 166,527。
> Bundle 必须让使用者一眼看出「这条证据能不能闭合到原文」。

### 3.2 检索证据（回答「为什么被检索出来」）

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `alias_rank` | int \| null | alias 组件 | 未命中记 `null` |
| `lexical_rank` | int \| null | `lacan_search` | 未命中记 `null` |
| `graph_rank` | int \| null | graph 扩展 | 未命中记 `null` |
| `vector_rank` | int \| null | 向量层（未实现） | 现恒为 `null` |
| `fusion_rank` | int | RRF 输出名次 | |
| `rerank_score` | float \| null | rerank（无独立 reranker） | 现恒为 `null` |
| `graph_reason` | str \| null | graph 扩展 | 形如 `gaze --formalized_as--> objet-a` |
| `why_retrieved` | list[str] | 各路自述 | 如 `["lexical_zh"]` |

**实测 rank 保真度**（这是本项目的硬要求）：

```
passage.S21.unknown.L10.P0099 | lexical_rank=1  fusion_rank=1
passage.S10.unknown.L23.P0105 | lexical_rank=2  fusion_rank=2
passage.S26.unknown.L10.P0028 | lexical_rank=4  fusion_rank=3
```

第 3 条 `lexical_rank=4` 而 `fusion_rank=3` —— 因为 lexical rank 3 的那条
被 diversity 当作 near-duplicate 丢掉了。**名次如实反映「进来时排第几」，
不是「最终排第几」**，这正是可审计所需。

⚠️ **但 `explain` 轨迹里的同类字段全是 `null`**（见 `HYBRID_RETRIEVAL.md §5.4`）——
最终 evidence 正确，调试视图有缺陷。

**为什么 rank 未命中用 `null` 而不是 0**：

* `0` 会被误读成「第 0 名」或「得分 0」；
* `null` 明确表示**这一路没有检索到它** —— 与 §「单路缺失不惩罚」的融合规则一致
  （见 `HYBRID_RETRIEVAL.md §3.1`）。

**`why_retrieved` 是 list 而不是 str**：一个候选可能被多路同时命中，
这本身就是**强相关信号**，必须能表达多条。

现有实现的字段来源（`lacan_search._row_to_hit`）：

```python
d["passage_id"] = d.pop("id")
d["text"]       = row["raw_text"]
d["rank"]       = rank
d["score"]      = score
d["why_retrieved"] = why      # "lexical_zh" / "lexical_fr" / "exact_id"
```

即：**Bundle 的 evidence 级字段在 lexical 层已经基本齐备**，
缺的是 vector/graph/fusion 那几项（因为那几层未实现）。

---

### 3.3 `textual_realization`：实现特有的字段

实测 evidence 里有一个字段不在早期设计草案中：**`textual_realization`**。
它的值等于 `witness_id`（如 `witness.zh.translation-project`）。

它表达 Phase 3 §0 三层结构（CorpusSource → Witness → **PassageRealization**）
里的**最底层**：该 Passage 在这一 witness 中的**具体实现**。

| 层 | bundle 里的字段 | 实测值 |
|---|---|---|
| CorpusSource | （未直接暴露） | `corpus-source.staferla` … |
| Witness | `witness_id` | `witness.zh.translation-project` |
| **PassageRealization** | **`textual_realization`** | 同 `witness_id` |

**它回答「这段证据具体来自哪一份文本实现」**，而不只是「来自哪个渠道」。
详见 `WITNESS_MODEL.md` 与 `PHASE3_FINDINGS.md §0`。

### 3.4 与早期设计草案的差异（逐条）

本文档 §2/§3 的早期版本是**设计草案**；实现落地后的差异：

| 项 | 草案 | 实现 | 评价 |
|---|---|---|---|
| 顶层字段数 | 7 | **17** | 实现更丰富（+`components`/`fusion`/`diversity`/`explain`/`schema`/`language`/`periods`/`from_llm_fallback`/`router`） |
| `from_llm_fallback` | 顶层字段 | ✅ **已透传**（修复后实测在 bundle 里） | 缺口已闭合 |
| `router` | 未列 | ✅ **新增** | 实现额外提供了路由元信息 |
| `alias_rank` | 未列 | **有** | 实现更全 |
| `graph_rank` | 未列 | **有** | 实现更全 |
| `textual_realization` | 未列 | **有** | 实现更全 |
| evidence 字段数 | 16 | **19** | 实现是草案的超集 |

> **`from_llm_fallback` 曾未透传**（本文档上一版记录过），
> **现已修复** —— 实测 bundle 顶层含该字段。
> 实现还额外提供了 `router` 键（路由元信息），是草案没有的。
>
> **撰写期间该字段被补上**，说明这一条反馈已被采纳。

---

## 4. `coverage`（**照实际实现**）

实测 `bundle["coverage"]` 有 **5 个键**：

| 字段 | 实测样例 | 说明 |
|---|---|---|
| `seminars` | `["seminar.S02","seminar.S10","seminar.S15","seminar.S21","seminar.S26"]` | 结果覆盖的期号 |
| `sessions` | `["session.S02.unknown.L20", ...]` | 覆盖的课次 |
| `periods` | `["1953-1955","1959-1963","1967-1971","1972-1973","1976-1981"]` | 覆盖的分期 |
| `languages` | `["zh"]` | 覆盖的语言 |
| `authority_levels` | `["L2"]` | 覆盖的权威层 |

**这五个维度正好对应「证据是否分散」的五个可检查面**：
期号（是否只砸在一期）、课次（是否只砸在一课）、分期（历时覆盖）、
语言（跨语言是否真拿到两语）、权威层（是否只有二手、没有原文）。

### 4.1 与早期设计草案的差异

草案曾列 `languages_present` / `languages_queried` / `witnesses_present` /
`components_used` / `components_failed` / `trace_status_distribution` /
`canonical_distribution` —— 这些字段名**实现里都不存在**。

实现用的替代方案更简洁：

| 草案想要的信息 | 实现里从哪看 |
|---|---|
| `components_used` / `components_failed` | **`bundle["components"]`**（各路命中数 + `vector_status`），
以及 `bundle["warnings"]` 里的 `VECTOR_COMPONENT_ABSENT` |
| `canonical_distribution` | 每条 evidence 的 `canonical_status` 字段 |
| `trace_status_distribution` | 每条 evidence 的 `provenance_status` 字段 |
| `witnesses_present` | 🟡 **无对应字段** —— 建议补（否则看不出证据是否只来自单一 witness） |

> **「组件是否可用」这件事的实现方式比草案更好**：
> 草案想用一个 `components_failed` 数组，实现则用
> `components`（含 `vector_status.implemented=false` + `reason`）
> **加上** `warnings` 双重表达 —— 既有结构化字段，又有人可读告警。

---

## 5. `warnings`

### 5.1 实测已产出的 warning

```
["VECTOR_COMPONENT_ABSENT: vector backend 尚未实现（见 VECTOR_INDEX.md 状态标注）"]
```

这是**当前唯一实际产出的 warning**，来自 `vector_component()` 在
后端缺失时的自述。它示范了本项目要的行为：
**组件缺席时自己说出来，而不是给出看起来完整的答案。**

### 5.2 建议补充的 warning（未实现）

| warning | 触发条件 | 为什么需要 |
|---|---|---|
| `AMBIGUOUS_ENTITY_NOT_RESOLVED` | `ambiguous_entities` 非空 | 让「候选冲突」可见 |
| `CASE_VARIANT_REQUESTED` | 某 entity 的 `match_type == "case_variant"` | **不能只看 `ambiguous_entities`** —— 见 §7.2 |
| `SOURCE_TRACE_INCOMPLETE_PRESENT` | 有条目 `provenance_status == SOURCE_TRACE_INCOMPLETE` | 实测全库 82,578 条中译都是 INCOMPLETE，用户必须知道 |
| `LOW_COVERAGE` | `coverage` 只覆盖 1 个 seminar 或只 1 个语言 | 防止「看起来相关其实只有一个证据」 |
| `NO_EVIDENCE` | `evidence` 为空 | 「检索不到」本身是必须交付的信息 |
| `LLM_FALLBACK_USED` | `QueryPlan.from_llm_fallback` 为真 | 审计解析来源（且该字段当前**未透传**，见 §3.4） |
| `QUERY_CONSTRAINT_UNPARSED` | 查询含期号写法但 `seminars` 为空 | 见下 |

### 5.3 `QUERY_CONSTRAINT_UNPARSED` 的必要性

实测 `研讨班 11`（中文 + 阿拉伯数字、无「期」字）与
`研讨班XI里的objet a` 仍**解析失败**（`QUERY_MODEL.md §5.1`）。

若不告警，调用方会把「约束没被解析」误读成「全库都没有」——
这是两类完全不同的结论。**静默的约束丢失比检索不到更危险。**

**`NO_EVIDENCE` 时绝不能返回看似完整的空 bundle 而不告警。**

---

## 6. 与 canonical store validator 的接口

Bundle 构造**必须**依赖 canonical store 的校验能力。现有能力（`_scripts/_tools/validate_vault.py:306`）：

| 检查 | 错误码 |
|---|---|
| 计数守恒（zh 82,578 / fr 166,527 / 合 249,105） | `PASSAGE_COUNT_MISMATCH` / `PASSAGE_ZH_COUNT` / `PASSAGE_FR_COUNT` |
| ID 唯一 | `PASSAGE_DUPLICATE_ID` |
| ID 命中 `id-namespaces.json` 的 pattern | `PASSAGE_ID_PATTERN` |
| 溯源自洽（INCOMPLETE 必须写明缺哪一环） | `PASSAGE_TRACE_INCONSISTENT` |
| 无损（文本变了必须有 `normalization_operations`） | `PASSAGE_LOSSY_NORMALIZATION` |
| `passage_witnesses` 引用完整 | `PASSAGE_WITNESS_DANGLING` |
| `recovered` translation 不得 canonical | `RECOVERED_TRANSLATION_CANONICAL` |

### 6.1 实际实现的校验入口

`hybrid_retrieve.validate_bundle(bundle)` → 返回问题列表（空列表 = 通过）。
内部 `_validate_bundle_impl()` 会取 `passage_meta` 的全部 ID 作为 `store_ids`，
逐条校验 evidence。

**实测**：`validate_bundle(retrieve("大他者", top_k=5))` → `[]`。

| 行为 | 实现 |
|---|---|
| 命中 → 只从 canonical 记录取字段 | ✅ Bundle 构造走 `passage_meta` / store |
| 未命中 → **记为问题，不是静默通过** | ✅ `FABRICATED_PASSAGE_ID` |
| 只读 | ✅ 不写任何 store |

### 6.2 与 `lacan_search` 的分工

`lacan_search.exact_passage(pid)` 在 ID 不存在时返回 **`None`**（API 层不编造）；
`validate_bundle` 则在 **bundle 层**把「编造 ID」升级为**显式问题码**。
两层各司其职：前者防「取到不存在的段」，后者防「bundle 里混进不存在的引用」。

> ⚠️ **实测到一次瞬态假阳性**：当 `lexical.sqlite` 正在被并行重建时，
> `validate_bundle` 可能因取到不完整的 `store_ids` 而把**真实存在**的 ID
> 报成 `FABRICATED_PASSAGE_ID`。
> 这是**并发/重建期的瞬态**，不是逻辑 bug（DB 可用后同一 bundle 校验返回 `[]`）。
> 若要更稳，可在校验前加一次「store 完整性检查」（计数守恒）。
> 这一点已记入 `RETRIEVAL_EVALUATION.md §3` 的门禁讨论。

---

## 7. 完整样例（**示意**，字段来源真实、取值需实现后回填）

### 7.0 真实输出（`retrieve("大他者", top_k=2)`，实测原样）

实现已存在，因此下面是**程序真实输出**（`text` 截断到 56 字），不是手写示意：

```jsonc
{
  "schema": "evidence-bundle/v1",
  "query": "大他者",
  "intent": "concept_lookup",
  "language": "zh",
  "components": {
    "alias": 1, "lexical": 50, "graph": 0, "vector": 0,
    "vector_status": {"implemented": false,
                      "reason": "vector backend 尚未实现（见 VECTOR_INDEX.md 状态标注）"}
  },
  "fusion": {"method": "rrf", "k": 60,
             "note": "只用名次，不用原始分数（避开不可比 score space）"},
  "diversity": {"kept": 2, "session_limit": 3},
  "warnings": ["VECTOR_COMPONENT_ABSENT: ..."],
  "evidence": [{
    "passage_id": "passage.S21.unknown.L10.P0099",
    "seminar_id": "seminar.S21",
    "session_id": "session.S21.unknown.L10",
    "witness_id": "witness.zh.translation-project",
    "textual_realization": "witness.zh.translation-project",
    "language": "zh",
    "source_authority": "L2",
    "text_role": "translation",
    "canonical_status": false,
    "provenance_status": "SOURCE_TRACE_INCOMPLETE",
    "alias_rank": null, "lexical_rank": 1, "graph_rank": null,
    "vector_rank": null, "fusion_rank": 1, "rerank_score": null,
    "graph_reason": null,
    "text": "> 作为大他者本身的大他者，带大写 A 的大他者……"
  }]
}
```

> 顶层键数随实现演进：曾为 14/15，**现为 16/17**
> （新增 `from_llm_fallback` 与 `router`；带 `explain=True` 时多 `explain`）。
> 实测当前顶层键见 §2。

### 7.1 手写示意（含歧义用例）

下面这个 bundle 是**按 schema 手写的示意**，
`passage_id` 形态、`entities` / `ambiguous_entities` 取值均取自**真实**
`query_router.route("signifiant 是什么")` 的返回。

选 `signifiant` 作样例是有意的：它**真的**触发跨实体歧义
（`concept.le-symbolique` 与 `concept.signifiant` 共用同一写法），
所以这个样例能同时演示「歧义暴露」与「组件不可用告警」两件事。

```jsonc
{
  "query": "signifiant 是什么",
  "intent": "concept_relationship",
  "entities": [
    { "entity_id": "concept.le-symbolique", "matched_alias": "signifiant",
      "exact_case": true, "match_type": "exact", "language": "und" },
    { "entity_id": "concept.signifiant", "matched_alias": "signifiant",
      "exact_case": true, "match_type": "exact", "language": "und" }
  ],
  "ambiguous_entities": [
    { "entity_id": "concept.le-symbolique", "matched_alias": "signifiant",
      "ambiguous_with": ["signifiant"],
      "ambiguity_reason": "折叠后大小写碰撞且写法与该实体规范拼写不同" },
    { "entity_id": "concept.signifiant", "matched_alias": "signifiant",
      "ambiguous_with": ["signifiant"],
      "ambiguity_reason": "折叠后大小写碰撞且写法与该实体规范拼写不同" }
  ],
  "filters": {},
  "from_llm_fallback": false,
  "evidence": [
    {
      "passage_id": "passage.S01.unknown.L01.P0001",
      "seminar_id": "seminar.S01",
      "session_id": "session.S01.unknown.L01",
      "witness_id": "witness.zh.translation-project",
      "language": "zh",
      "text": "[1953 年 11 月与 12 月的各次课程没有可用的速记稿]",
      "source_authority": "L2",
      "text_role": "translation",
      "canonical_status": { "canonical": false, "status": "recovered" },
      "provenance_status": {
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "trace_missing": ["upstream_original_file"]
      },
      "lexical_rank": 1,
      "vector_rank": null,
      "graph_reason": null,
      "fusion_rank": 1,
      "rerank_score": null,
      "why_retrieved": ["lexical_zh"]
    }
  ],
  // 注意：下面这两个字段是**实际实现**的字段名（不是设计草案的 components_used/failed）
  "components": {
    "alias": 1, "lexical": 50, "graph": 0, "vector": 0,
    "vector_status": {"implemented": false, "reason": "..."}
  },
  "coverage": {
    "seminars": ["seminar.S01"],
    "sessions": ["session.S01.unknown.L01"],
    "periods": ["1953-1955"],
    "languages": ["zh"],
    "authority_levels": ["L2"]
  },
  "warnings": [
    "VECTOR_COMPONENT_ABSENT: vector backend 尚未实现（见 VECTOR_INDEX.md 状态标注）"
    // 以下为**建议补充**的 warning（§5.2），当前实现尚未产出：
    // "AMBIGUOUS_ENTITY_NOT_RESOLVED", "CASE_VARIANT_REQUESTED",
    // "SOURCE_TRACE_INCOMPLETE_PRESENT", "LOW_COVERAGE"
  ]
}
```

> 上例的 `passage_id` 与 `text` 取自 `_data/passage_store/passages.jsonl` 首条，
> 用于展示字段形态；**真实检索未必返回这一段**。

### 7.2 一个必须写下来的细微行为：`ambiguity_reason` ≠ 有歧义

实测 `exact_lookup("l'autre")`：

```jsonc
{ "entity_id": "concept.l-autre", "matched_alias": "l'Autre",
  "match_type": "case_variant", "case_sensitive": true,
  "ambiguous_with": [],                       // ← 空
  "ambiguity_reason": "大小写理论词：语料同时使用大小写两种形式…" }
```

即：**`ambiguity_reason` 有值，但 `ambiguous_with` 为空**。

原因：`l'autre` 与 `l'Autre` 都指向**同一个实体** `concept.l-autre`
（本库只收录了大他者，没有凭空造小他者），所以不存在「跨实体碰撞」。
`ambiguity_reason` 在这里是**解释大小写敏感性**的说明文字，
**不是**「存在歧义候选」的信号。

后果（对 Bundle 有直接影响）：

| 事实 | 含义 |
|---|---|
| `route("l'Autre 和 l'autre 有什么区别")` 的 `ambiguous_entities` 为 `[]` | 该查询**不会**触发 `AMBIGUOUS_ENTITY_NOT_RESOLVED` |
| 但 `l'autre` 命中的条目 `match_type == "case_variant"` | 「你要的小他者本库没有」这个信息**只存在于 match_type 里** |

**因此 Bundle 的告警规则不能只看 `ambiguous_entities`**，
还应当检查 `entities[].match_type == "case_variant"`
（或 `case_variant_of` 非空），否则会漏掉「用户要的写法库中没有」这一类情况。
这是实现时必须处理的细节，已记入 §8 测试清单。

---

## 8. 测试现状（已实现）+ 建议补测

**已实现**（`test_phase3_retrieval.py`，26 项，实测 OK）覆盖：

| 测试 | 对应要求 |
|---|---|
| `test_00_bundle_schema` | schema 常量 |
| `test_01_evidence_required_fields` | evidence 必填字段齐备 |
| `test_02_four_dimensions_stay_separate` | 四层（authority / provenance / canonical / text_role）不混 |
| `test_03_no_fabricated_ids_and_validate` | 无编造 ID |
| `test_04_validate_bundle_rejects_fabricated` | 校验器能拒编造 |
| `test_05_validate_bundle_rejects_provenance_tamper` | 能拒 provenance 篡改 |
| `test_06_incomplete_provenance_preserved` | INCOMPLETE 如实保留 |
| `test_07_recovered_translation_status_preserved` | recovered 不被升格 |
| `test_08_retrieval_is_deterministic` | 确定性 |
| `test_09/10_rrf_*` | RRF 只消费名次 |
| `test_23_retrieval_does_not_mutate_canonical_store` | 不改 canonical |
| `test_24/25_cli_*` | CLI search / explain |

**仍建议补测**：

| 测试 | 断言 |
|---|---|
| `test_bundle_passes_through_from_llm_fallback` | `QueryPlan.from_llm_fallback` 必须出现在 bundle 里（**已透传**，建议补测试锁住防回归） |
| `test_bundle_text_equals_raw_text` | `text` 与 store `raw_text` **逐字相同** |
| `test_bundle_never_invents_id` | 构造一个不存在的 ID → **抛错**，不得产出 bundle |
| `test_bundle_text_equals_raw_text` | `text` 与 store 的 `raw_text` **逐字相同**（不许改写/截断） |
| `test_bundle_reports_unavailable_components` | 未实现的路必须出现在 `components.vector_status.implemented=false` **且** `warnings` 里 |
| `test_bundle_warns_on_ambiguous_entity` | `ambiguous_entities` 非空 → 必带 `AMBIGUOUS_ENTITY_NOT_RESOLVED` |
| `test_bundle_flags_case_variant` | `match_type=="case_variant"` 的实体 → 必须显式标注（**不能只看 `ambiguous_entities`**，见 §7.2） |
| `test_bundle_warns_on_trace_incomplete` | 含 INCOMPLETE 条目 → 必带对应 warning |
| `test_bundle_no_evidence_is_warned` | 空 evidence → 必带 `NO_EVIDENCE`，不得静默返回空 |
| `test_bundle_is_deterministic` | 同查询两次 → bundle 逐字相同 |
| `test_bundle_does_not_mutate_store` | 构造 bundle 前后，canonical store 的 mtime/size 不变 |

---

## 9. 复核命令

```bash
cd <HOME>

# 1. 确认 Bundle 生成器**已实现**（在 hybrid_retrieve.py 里）
grep -n "def retrieve\|def validate_bundle" _scripts/_tools/hybrid_retrieve.py

# 2. 确认 Bundle 要用的字段在 lexical 返回里已存在
python3 -c "
import sys; sys.path.insert(0,'_scripts/_tools')
import lacan_search as L
h = L.lexical_search('大他者', language='zh', limit=1)[0]
need = ('passage_id','seminar_id','session_id','language','text',
        'authority_level','text_role','canonical','trace_status',
        'rank','why_retrieved')
print('已有:', [k for k in need if k in h])
print('缺  :', [k for k in need if k not in h])"

# 3. 确认 canonical validator 可用（Bundle 的 ID 门禁）
python3 _scripts/_tools/validate_vault.py --json 2>/dev/null | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(d['passage_store']['errors'])"
```

---

*配套：`RETRIEVAL_ARCHITECTURE.md` · `QUERY_MODEL.md` · `HYBRID_RETRIEVAL.md` ·
`RETRIEVAL_EVALUATION.md`*
