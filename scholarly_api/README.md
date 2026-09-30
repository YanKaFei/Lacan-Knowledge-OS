# `scholarly_api` — Phase 4D.0 稳定访问层

```
PRODUCT LAYER  (UI / MCP / Obsidian / Agent)
      ↓   只允许 import scholarly_api
STABLE SCHOLARLY API          ← 本目录（v1 稳定对象 + 11 个入口 + 读写闸门）
      ↓
FROZEN SCHOLARLY CORE         ← _data/core_freeze/scholarly_core_freeze_v1.json 钉住
      ↓
CORPUS / INDEX / ONTOLOGY
```

## 允许 / 禁止

| | |
|---|---|
| ✅ 允许 | `import scholarly_api`；调用下面 11 个入口；写文件走 `scholarly_api.policy.write_text/write_json` |
| ❌ 禁止 | 产品层 `import` `_scripts/_tools/**` 的任何模块；读 Gate/validator/repair/judge 内部字段；直接写 `_data/**`（除策略允许的分类）；把核心答案改写成不同理论结论 |
| ❌ 禁止 | 核心 `ABSTAIN` 时由 Agent 用自身知识补答；核心报错时静默降级 |

## 入口（v1）

```python
api.research(question, options) -> FinalScholarlyAnswer
api.search_passages(query, filters) -> PassageSearchResult
api.get_passage(passage_id) -> PassageRecord
api.get_context(passage_id, before=3, after=3) -> PassageContext
api.get_concept(concept_id) -> ConceptRecord
api.get_seminar(seminar_id) -> SeminarRecord
api.trace_source(passage_id) -> ProvenanceRecord
api.compare_terms(a, b, options) -> FinalScholarlyAnswer
api.research_concept(concept_id, mode, options) -> FinalScholarlyAnswer
api.research_diachronic(concept, start, end, options) -> FinalScholarlyAnswer
api.research_translation(term, options) -> FinalScholarlyAnswer
```

`options`（`research`）：

```python
{"mode": "scholarly",            # task routing 提示，**不能**绕过 core contract
 "language": "zh" | "fr" | "en" | "any",
 "provider": "mock" | "llm",     # 默认 mock：确定性、不发网络
 "judge": True,                  # 仅 llm provider 生效
 "task_id": "...", "budget": 20}
```

**真实 LLM 必须显式 `provider="llm"`**；凭据不可用时返回
`ApiError{error_code: PROVIDER_UNAVAILABLE}` —— 绝不回退到模型自身知识。

## 稳定对象（16 个 v1 schema，`scholarly_api/schemas/*.json`）

`ResearchRequest` · `ResearchContract` · `ResearchExecutionResult` · `EvidencePacket` ·
`SynthesisInput` · `ValidatedClaim` · `CitationBinding` · `FinalScholarlyAnswer` ·
`AbstentionResult` · `ProvenanceRecord` · `PassageRecord` · `PassageContext` ·
`PassageSearchResult` · `ConceptRecord` · `SeminarRecord` · `ApiError`

契约规则：**加字段 = 新版本**；v1 字段语义不得悄悄更改。所有返回都经
`objects.validate()` 校验；失败会带 `_schema_errors` 便于定位（测试断言不得出现）。

## 从既有核心字段的**机械派生**（不发明语义）

| 派生项 | 规则 |
|---|---|
| `PassageRecord.source_layer` | 核心记录无该字段时：有 `translation_id` 且 `authority_level != L1` → `<auth>_RECOVERED`；`text_role == transcription` → `<auth>_TRANSCRIPTION`；`text_role == edition` → `<auth>_EDITION`；否则 `null`（不猜） |
| `FinalScholarlyAnswer.sections` | 逐字取自核心 `answer.sections` |
| `FinalScholarlyAnswer.source_limitations` | 核心 `limitations`/`source_notes` 中**来源层事实行**；核心内部修复日志行（`已剔除…（NOT_ENTAILED）` 等）不进产品视图（原文仍在 `sections` 内） |
| `ValidatedClaim.entailment_status` | 冻结 D 流水线的 entailment 结果（按 `final_claim_id`/`claim_id` 匹配） |
| `SeminarRecord.sessions` | `_data/passage_store/sessions.jsonl`（canonical，只读） |

## 写入闸门（`scholarly_api.policy`）

| 分类 | 例 | 策略 |
|---|---|---|
| `IMMUTABLE_CORE` | 核心语义代码、冻结件、human review、封存 run、Gold、core freeze | **拒绝写入**（`CoreMutationError`） |
| `REBUILDABLE_MACHINE` | SQLite / 向量索引 / 缓存 / `_index/Reports`、`_index/Views` | 允许重建（须可由 Source of Truth 重建） |
| `CANONICAL_KNOWLEDGE` | ontology、terminology bridge、schema | 需 `review_token` |
| `USER_WORKSPACE` | `Research/` `Projects/` `Notes/` `Saved/` `Annotations/` `Concepts/` `Seminars/` `Exports/` | 自由写 |
| `UNKNOWN` | 其它任何路径 | **拒绝**（保守：先登记分类规则） |

## 核心变更纪律

产品使用中发现核心问题 → 写 `_core_change_requests/` 工单，
**不得**直接 patch core。只有新的 Scholarly Remediation Phase 才能改核心语义。

## 版本

* `scholarly_api.API_VERSION = "scholarly-api/v1"`
* 核心冻结：`_data/core_freeze/scholarly_core_freeze_v1.json`
* 校验命令：`python3 _scripts/_tools/core_freeze.py --verify`
