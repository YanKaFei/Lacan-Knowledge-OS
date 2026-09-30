# MCP Tool Contracts — Lacanian Knowledge OS（Phase 4A）

> ⚠️ **本文件由 `_scripts/_tools/render_contracts.py` 从 `schemas.py` 渲染生成。**
> 不要手改：`--check` 会在文档与代码分叉时报错。改契约请改 `schemas.py`。
>
> 生成命令：`python3 _scripts/_tools/render_contracts.py`

## 这一层是什么（§1）

MCP 在这里是 **Knowledge Access Layer（知识访问层）**，**不是 Answer Generator**：
它返回**结构化证据**（passage + 出处 + 权威层级 + 覆盖度 + 告警 + 证据状态），
由调用它的 LLM 去组织答案。所以：

* 每个 tool 的输出都含同一套 **8 段 schema**（§6）；
* 每个 tool 都**只读**（§2/§21）：没有任何写入型参数；
* 「证据够不够」由**结构性**信号判定（§7–§10），**禁止** cosine 阈值；
* `evidence_state` 判的是「知识库是否支持这次研究操作」，**不判理论对错**（§10）。

## 共享输出 schema（§6）

所有 tool 的返回都是这 8 段（顺序固定，缺一不可）：

`request`  `resolution`  `retrieval`  `evidence`  `coverage`  `provenance`  `warnings`  `evidence_state`

| 段 | 含义 |
|---|---|
| `request` | 原样回显请求参数（含补全后的默认值），便于 research trace 复现 |
| `resolution` | 实体解析结果：entities / ambiguous / collisions / unresolved_terms（来自 entity_resolution + lacanian_semantic_guard） |
| `retrieval` | 检索层元数据：route / vector_enabled / lanes / component_counts / component_ranks 摘要（来自 query_routing_policy + Phase 3 组件） |
| `evidence` | 证据条目数组。**每条必须带真实 passage_id**，外加 seminar/session/language/text/why_retrieved/component_contribution/provenance |
| `coverage` | 覆盖度：evidence_n / session_n / seminar_n / period_n / language_mix / term_coverage |
| `provenance` | 溯源汇总：trace_status 分布、SOURCE_TRACE_INCOMPLETE 计数、witness/corpus_source 分布 |
| `warnings` | 结构化告警数组：每条 {code, message, severity, action}；**不得吞掉** SOURCE_TRACE_INCOMPLETE / ENTITY_COLLISION / AMBIGUOUS_ENTITY |
| `evidence_state` | Evidence Sufficiency 的结论：SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE / CONFLICTING_EVIDENCE，附带 signals 与 reasons（**不是** 0–1 confidence） |

## Tool 一览（10 个，§4「克制」）

| # | tool | 职责一句话 | 每概念 lane | 实体约束 | 历时分组 |
|---|---|---|---|---|---|
| 1 | `search_passages` | 通用证据检索 | 按 route 决定 | False | False |
| 2 | `get_passage` | 取单个 Passage | 0 | False | False |
| 3 | `get_context` | 取本地上下文 | 0 | False | False |
| 4 | `resolve_entity` | 实体解析（含歧义与碰撞） | 0 | True | False |
| 5 | `get_concept` | 取概念卡 | 0 | True | False |
| 6 | `find_concept_evidence` | 实体约束的证据检索 | 1 | True | False |
| 7 | `trace_concept` | 历时证据组织 | 按 period 分组 | True | True |
| 8 | `compare_concepts` | 两概念对比（独立 lane） | 每概念一条 | True | False |
| 9 | `trace_source` | 溯源链追溯 | 0 | False | False |
| 10 | `terminology_lookup` | 受控术语映射查询 | 0 | True | False |

> 责任矩阵的作用（§5）：三个「看起来都像检索」的 tool （`search_passages` / `find_concept_evidence` / `trace_concept`）
> 必须**职责不同**，不能互为别名。上表就是它们的区别，并由 `test_phase4a_mcp.py` 断言。

## 1. `search_passages`

**通用证据检索**

**用途（purpose）**：把研究问题交给 Phase 3 已验证的检索链。**不重新实现检索**：内部调用 query_routing_policy + Phase 3 组件（Exact/Entity/Alias/Lexical/Terminology Bridge X/Metadata/MiniLM vector）。

**不要用它来做（not_for）**：不要用它做「某概念的历时演变」（用 trace_concept）或「某概念的全部支持证据」（用 find_concept_evidence）。

**责任范围**：scope=通用 · entity_constrained=False · diachronic_grouping=False · lanes=按 route 决定

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 |  | 研究问题或检索串（自然语言可） |
| `language` | enum(zh\|fr\|en\|mul\|any) | 否 | `any` | 限定证据语言 |
| `seminar` | string | 否 |  | 研讨班约束，如 seminar.S11 或 S11 |
| `period` | string | 否 |  | 时期约束，如 1964-1965；分期表来自 seminars.jsonl 的 year_from/year_to（**不是** query_router —— 它没有分期表） |
| `entities` | array | 否 |  | 额外指定的 entity_id（补充自动解析结果） |
| `top_k` | integer 1..50 | 否 | `10` | 返回证据条数上限 |
| `retrieval_mode` | enum(auto\|lexical\|vector\|hybrid\|exact) | 否 | `auto` | 强制检索路径。auto=交给 routing policy 决定（默认，也是唯一推荐的用法） |
| `include_context` | boolean | 否 | `false` | 是否为 top evidence 附上前后文引用 |
| `explain` | boolean | 否 | `false` | 是否返回 component ranks 明细 |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 2. `get_passage`

**取单个 Passage**

**用途（purpose）**：按 stable ID 取 canonical passage 及其 witness / provenance / 邻居可用性。

**不要用它来做（not_for）**：不要用它检索；也不要用它猜 ID —— 不存在必须返回 PASSAGE_NOT_FOUND。

**责任范围**：scope=单 passage · entity_constrained=False · diachronic_grouping=False · lanes=0

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `passage_id` | string | 是 |  | passage.S… 形式 stable ID |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 3. `get_context`

**取本地上下文**

**用途（purpose）**：按 store 原顺序取前后 before/after 条**真实** passage。**不做 LLM 总结** —— 只返回原文与顺序。

**不要用它来做（not_for）**：不要用它跨 session 拼证据（那会破坏顺序语义）。

**责任范围**：scope=单 passage 邻域 · entity_constrained=False · diachronic_grouping=False · lanes=0

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `passage_id` | string | 是 |  | 中心 passage 的 stable ID |
| `before` | integer 0..20 | 否 | `3` | 向前取几条（沿 store 原序） |
| `after` | integer 0..20 | 否 | `3` | 向后取几条（沿 store 原序） |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 4. `resolve_entity`

**实体解析（含歧义与碰撞）**

**用途（purpose）**：把词映射到 concept entity。状态只能是 RESOLVED / AMBIGUOUS / UNRESOLVED / ENTITY_COLLISION，**不静默解析**。

**不要用它来做（not_for）**：不要用它取证据（用 find_concept_evidence）。

**责任范围**：scope=解析 · entity_constrained=True · diachronic_grouping=False · lanes=0

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `term` | string | 是 |  | 待解析的词或短语（如 objet a / l'Autre / 凝视） |
| `language` | enum(zh\|fr\|en\|any) | 否 | `any` | 限定解析语言（一般留 any） |
| `context` | string | 否 |  | 可选上下文，用于在歧义时给出来源线索 |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 5. `get_concept`

**取概念卡**

**用途（purpose）**：返回 canonical name / aliases / 语言 / status / period / 链接的 passage / relations / source links / ontology gaps。**不自动生成概念定义**；没有 reviewed definition 就明说没有。

**不要用它来做（not_for）**：不要用它找证据（用 find_concept_evidence）。

**责任范围**：scope=实体元数据 · entity_constrained=True · diachronic_grouping=False · lanes=0

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `entity_id` | string | 是 |  | concept.* 形式 entity id |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 6. `find_concept_evidence`

**实体约束的证据检索**

**用途（purpose）**：先解析实体，再**在该实体范围内**取支持证据；可选 seminar / period / language / top_k。

**不要用它来做（not_for）**：不要用它做通用检索（用 search_passages）；也不要用它做历时组织（用 trace_concept）。

**责任范围**：scope=单实体 · entity_constrained=True · diachronic_grouping=False · lanes=1

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `concept` | string | 是 |  | entity_id（如 concept.jouissance）或可解析的术语 |
| `seminar` | string | 否 |  | 研讨班约束，如 seminar.S11 或 S11 |
| `period` | string | 否 |  | 时期约束（分期表来自 seminars.jsonl） |
| `language` | enum(zh\|fr\|en\|any) | 否 | `any` | 限定证据语言 |
| `top_k` | integer 1..50 | 否 | `15` | 返回证据条数上限 |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 7. `trace_concept`

**历时证据组织**

**用途（purpose）**：按 period → seminar → session 组织某概念的证据，返回覆盖缺口（如 NO_EVIDENCE_FOR_PERIOD）。**不直接生成历史总结。**

**不要用它来做（not_for）**：不要用它做横向对比（用 compare_concepts）。

**责任范围**：scope=单实体 · 历时 · entity_constrained=True · diachronic_grouping=True · lanes=按 period 分组

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `concept` | string | 是 |  | entity_id 或可解析的术语 |
| `language` | enum(zh\|fr\|en\|any) | 否 | `any` | 限定证据语言 |
| `per_period` | integer 1..20 | 否 | `5` | 每个时期最多取几条 |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 8. `compare_concepts`

**两概念对比（独立 lane）**

**用途（purpose）**：对比两个概念。内部**必须**用独立 retrieval lane（§8）：绝不把两个词拼成一个 query 做一次搜索。返回两侧证据、共享上下文、contrastive warnings、覆盖度。**不下理论结论。**

**不要用它来做（not_for）**：不要用它做单概念的证据收集。

**责任范围**：scope=双实体 · entity_constrained=True · diachronic_grouping=False · lanes=每概念一条

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `concept_a` | string | 是 |  | 对比 A 侧（entity_id 或术语） |
| `concept_b` | string | 是 |  | 对比 B 侧（entity_id 或术语） |
| `language` | enum(zh\|fr\|en\|any) | 否 | `any` | 限定两侧证据语言 |
| `top_k` | integer 1..30 | 否 | `10` | **每侧**返回条数上限 |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 9. `trace_source`

**溯源链追溯**

**用途（purpose）**：Passage → PassageRealization → Witness → CorpusSource → source file → sha256 → provenance status。中文 recovered 语料必须继续显式标 SOURCE_TRACE_INCOMPLETE。

**不要用它来做（not_for）**：不要用它取语义证据（用 get_passage / search_passages）。

**责任范围**：scope=溯源 · entity_constrained=False · diachronic_grouping=False · lanes=0

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `passage_id` | string | 是 |  | 要追溯溯源链的 passage ID |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 10. `terminology_lookup`

**受控术语映射查询**

**用途（purpose）**：查 Cross-lingual Terminology Bridge 的受控映射：entity identity / review status / ambiguity / contrastive warnings。**不做普通机器翻译。**

**不要用它来做（not_for）**：不要用它取证据；也不要期待它翻译任意句子。

**责任范围**：scope=术语映射 · entity_constrained=True · diachronic_grouping=False · lanes=0

**输入**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `term` | string | 是 |  | 要查受控映射的术语（不会翻译任意句子） |
| `source_language` | enum(zh\|fr\|en\|any) | 否 | `any` | 限定源语言（一般留 any） |
| `target_language` | enum(zh\|fr\|en\|any) | 否 | `any` | 限定目标语言；any = 全部同 entity 写法 |

**输出**：共享 8 段 schema 全给；`evidence_state` 由 `evidence_sufficiency` 结构性判定。

## 只读保证（§21）

以下词根一旦出现在**任何**参数名里，契约测试直接失败：

`set`, `write`, `update`, `delete`, `remove`, `create`, `canonicalize`, `promote`, `merge`, `fix`, `apply`, `commit`, `save`, `insert`, `patch`, `edit`

唯一会落盘的内容是 `_data/ontology_gap_queue.jsonl`（§22），它由 **Research Agent** 写，且只写 `status: candidate` 的发现记录 —— 不属于 canonical knowledge，MCP tool 本身不写任何文件。

