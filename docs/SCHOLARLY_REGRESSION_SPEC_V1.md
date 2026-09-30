# Scholarly Regression Spec V1 — Phase 4C.1-A §12

> 机器可读规格：`_data/eval/scholarly_regression_v1.jsonl`（14 行，每行一个已人工评审任务）
> 生成脚本：`_scripts/_tools/build_scholarly_regression_v1.py`（`--check` 可复现）
> 依赖的冻结基线：`research_human_review.jsonl`（14 条评分）、`human_adjudication_queue.jsonl`（3 条裁决）、
> `human_review_baseline_v1.json`（逐任务钉住的快照）、`evaluation_truth_adjudicated_v1.json`（三个裁决题的 gold_v2 规范）

## 0. 为什么不能只存 `expected_state`

Phase 4C 人工评审证明：**只给 expected_state 不足以防回归**。系统可以在
「缺 lane / 缺端点 / 缺关系证据 / 缺 formalism / 缺 metadata」的条件下照样输出 `SUPPORTED`
（`rt-B01`、`rt-C03`、`rt-G01`、`rt-H02` 全是这样）。因此每条回归规格必须同时固定：

```
required_entities / required_operations / required_lanes / required_constraints
required_endpoints / expected_zero_lanes / relation_evidence_required
source_layers_required / seminar_constraints / period_constraints
formalism_required / metadata_required / terminology_lanes
supported_forbidden_conditions / abstention_contract
lane_semantics（每条 lane 的 expectation / observed_hits / result）
human_review_baseline（14 条人工评分，逐字内嵌）
human_adjudication（3 条裁决，逐字内嵌）
gold_v2_spec / gold_v2_target_answerability（裁决题）
spec_basis（每条手写要求的依据 = 人工评审的 issue code）
```

**手写部分只有 `spec_basis` 指向的那些要求**；其余字段全部从冻结产物机械推导，
`--check` 保证可复现（同样的输入 → 同样的 14 行）。

## 1. 总览

| task | task_type | gold v1 | gold_v2 目标 | lanes | 约束 | 禁止条件 | 人工六维（tc/ha/dp/au/oc/cl） |
|---|---|---|---|---|---|---|---|
| `rt-A01` | concept_definition | SUPPORTED | — | 2 | 1 | 1 | 2/2/3/2/4/3 |
| `rt-B01` | concept_relation | SUPPORTED | — | 3 | 2 | 1 | 1/N/A/1/1/1/2 |
| `rt-C03` | diachronic_development | SUPPORTED | — | 2 | 2 | 1 | 1/1/1/1/1/2 |
| `rt-D01` | seminar_specific | SUPPORTED | — | 2 | 2 | 1 | 3/N/A/5/3/5/3 |
| `rt-E01` | case_research | SUPPORTED | — | 1 | 2 | 1 | 1/N/A/1/1/1/2 |
| `rt-F01` | freud_to_lacan | SUPPORTED | — | 2 | 2 | 1 | 1/1/1/1/1/2 |
| `rt-G01` | philosophy_to_lacan | SUPPORTED | **UNDETERMINED_PENDING_RELATION_RETRIEVAL** | 4 | 3 | 1 | 1/1/1/1/4/2 |
| `rt-G02` | philosophy_to_lacan | SUPPORTED | — | 2 | 4 | 2 | 1/2/1/1/1/2 |
| `rt-H02` | topology_matheme | SUPPORTED | **SUPPORTED**（仅 answerability 标签） | 3 | 2 | 2 | 1/N/A/2/1/4/2 |
| `rt-I02` | translation_terminology | SUPPORTED | — | 3 | 2 | 1 | 1/N/A/2/1/1/2 |
| `rt-I03` | translation_terminology | SUPPORTED | — | 0 | 6 | 2 | 1/N/A/1/1/1/2 |
| `rt-J01` | insufficient_unanswerable | INSUFFICIENT_EVIDENCE | **PARTIALLY_SUPPORTED** | 3 | 4 | 2 | 3/N/A/4/3/5/3 |
| `rt-J02` | insufficient_unanswerable | INSUFFICIENT_EVIDENCE | — | 1 | 0 | 1 | 3/4/4/3/5/3 |
| `rt-J03` | insufficient_unanswerable | INSUFFICIENT_EVIDENCE | — | 0 | 5 | 2 | 4/4/4/3/5/3 |

跨任务标记：`relation_evidence_required` = B01 / F01 / G01；`formalism_required` = H02；
`metadata_required` = J03；`expected_zero_lanes` = I03 / J02；`source_layers_required` = F01 / G01；
`followup_required` = G01；`human_adjudication` = J01 / H02 / G01。

## 2. 逐任务回归契约（关键项）

### rt-B01 — 三条独立 lane + 关系证据
```yaml
required_lanes: [lane_besoin, lane_demande, lane_desir]
relation_evidence_required: true
if_missing_lane: SUPPORTED = forbidden
```
依据：`research_planning_lane_execution`、`evidence_sufficiency_false_supported`、
`non_substantive_evidence`、`generic_lexical_occurrence_as_evidence`、`citation_entailment_vs_authenticity`。

### rt-C03 — 历时两端必须真进入检索
```yaml
required_endpoints: [seminar.S07, seminar.S20]
diachronic_claim_required: true
if_endpoint_missing: SUPPORTED = forbidden
```
依据：`diachronic_endpoint_missing`（S07 完全缺席）、`scope_constraint_not_pushed_down`、
`sufficiency_false_supported_diachronic`、`no_substantive_diachronic_claim`、
`sufficiency_explanation_cites_absent_signals`。

### rt-D01 — 本轮唯一 PASS，必须被保护
```yaml
required_lanes: [fr_s11_regard, fr_s11_objet]
required_constraints: [seminar 约束 S11 下推到 retrieval, gaze/regard 定位到 objet a]
```
依据：`citation_support = PASS`、`distinction_preservation = 5`；它证明**把期中约束真正下推**是可行且有效的。

### rt-F01 / rt-G01 — 来源分层
```yaml
source_layers_required: [Freud 原始层(Trieb), Lacan 重读层(pulsion)]      # F01
source_layers_required: [Hegel, Kojève, Lacan 重新使用, Lacan 自身欲望理论]  # G01
supported_forbidden_conditions: [Freud primary 层为 0 时判 SUPPORTED]        # F01
```
依据：`source_layer_separation_not_executed`、`required_capability_is_declarative_only`、
`source_layer_separation_missing`。

### rt-G02 — sujet / moi 区分
```yaml
required_entities: [concept.sujet, concept.moi]
supported_forbidden_conditions:
  - 把 cogito 与 sujet 直接等同
  - 未解析 expected entities 时判 SUPPORTED
```
依据：`core_research_task_not_completed`、`required_distinction_absent`、
`gold_lane_not_measuring_theoretical_task`。

### rt-H02 — formalism 两层区分
```yaml
formalism_required: [◊, "S ◊ a", "(S ◊ a)", poinçon, formule]
seminar_constraints: [seminar.S14]
required_entities: [concept.fantasme, concept.objet-petit-a]
retrieval_formalism_missing: structural_unanswerability = false
supported_forbidden_conditions:
  - 未经全库 formalism 扫描就断言结构性不可答
  - 把 $ ◊ a 翻译成自然语言后当作拉康原话引用
```
依据：`formalism_query_dropped`、`retrieval_miss_misclassified_as_structural_unanswerability`、
`wrong_concept_pair`、`gold_evidence_derivation_defect`、`seminar_constraint_not_enforced`；裁决 `GOLD_CORRECT`。

### rt-I03 — 译名 lane 与「预期为 0」
```yaml
terminology_lanes: [快感, 享受, 原乐]
expected_zero_lanes: ["原乐（ZERO_ATTESTATION：全库 0 段）"]
supported_forbidden_conditions:
  - missing required terminology lane 时判 SUPPORTED
  - 把「原乐」说成语料中已确立的译名
```
依据：`terminology_task_not_executed`、`explicit_translation_terms_ignored`、
`ontology_mapping_confused_with_corpus_attestation`、`empty_lane_semantics_missing`、
`unsupported_state_upgrade`。

### rt-J02 / rt-J03 — 弃权契约
```yaml
# rt-J02
expected_zero_lanes: ["zh_frmi（fMRI 全库 0 段；v1 的 3 条命中是 URL 跨 token 假阳性）"]
abstention_contract: [说明为什么不可答, 不得展示 degenerate passage, citation 应支持「为什么不可答」]
# rt-J03
metadata_required: [日级日期（session_date）, 地点, 在场者]
required_constraints: [触发 METADATA_UNAVAILABLE, 不进普通 topical synthesis,
                       明确指出缺失字段, premise_unverified, editorial note 不得计入 L1 primary]
```
依据：`abstention_rationale_not_surfaced_in_answer`、`degenerate_evidence_presented_as_theoretical_development`、
`gold_lane_normalization_cross_token_false_positive`、`internal_verdict_not_surfaced_in_answer`、
`editorial_note_counted_as_l1_primary`、`structural_unanswerability_not_mapped_to_failure_taxonomy`。

### rt-J01 / rt-G01 — 裁决题
```yaml
# rt-J01（AGENT_CORRECT）
required_lanes: ["zh_moebius（新增：莫比乌斯 / 莫比乌斯带）", fr_moebius, "relation:sujet_barré"]
multilingual_concept_required: true
target_answerability: PARTIALLY_SUPPORTED
# rt-G01（NEEDS_MORE_EVIDENCE）
required_lanes: [fr_hegel, "kojeve（新增）", "maitre-esclave relation（新增）", "desire relation（新增）"]
followup_required: true
target_answerability: UNDETERMINED_PENDING_RELATION_RETRIEVAL
```

## 3. Lane 语义（§A6）：空 lane 不等于失败

| expectation | 0 命中的含义 | result |
|---|---|---|
| `EXPECTED_POSITIVE` | 该 lane 应当有命中 → 0 命中是**检索失败** | `FAIL` |
| `EXPECTED_ZERO` | 0 命中是**正确研究结论**（ZERO_ATTESTATION） | `PASS` |
| `UNKNOWN_EXPECTATION` | 未确定期望 → 0 命中需要复核 | `REVIEW` |

规格里的实例（同一份 `scholarly_regression_v1.jsonl`）：

| task | lane | expectation | observed_hits | result | 含义 |
|---|---|---|---|---|---|
| `rt-I03` | `zh_yuan`（原乐） | `EXPECTED_ZERO` | 0 | **PASS** | 「原乐」在 corpus 中未被实际使用 —— 这正是题目要的结论 |
| `rt-I03` | `zh_kuai`（快感） | `EXPECTED_POSITIVE` | 85 | PASS | 词面命中，但仍需 context validation |
| `rt-I03` | `zh_xiang`（享受） | `EXPECTED_POSITIVE` | 52 | PASS | 不在 alias_index → 不能直接视为 jouissance 翻译 |
| `rt-J02` | `zh_frmi` | `EXPECTED_ZERO` | 0（v2 语义） | PASS | v1 的 3 条命中是 URL 跨 token 假阳性 |
| `rt-C03` | `fr_s07` | `EXPECTED_POSITIVE` | 0 | **FAIL** | 语料有 S07 的 jouissance 段落，检索没取到 |

报告契约（`lane_semantics_v1.json`）：任何 0 命中都必须附 `corpus_scan`
（needle / scope / hits / method），否则 `hit_state` 只能是 `UNKNOWN`；
**禁止**再用统一的 `lane_recall = 0 → FAIL` 覆盖所有 lane。

## 4. 这份规格如何被强制执行

| 机制 | 位置 | 作用 |
|---|---|---|
| Gate 19（trace integrity） | `check_phase4c_hard_gates.py` / `check_trace_integrity.py` | 检测 missing required operations / lanes、无解释的 state transition、reasons 引用 null signals、context expansion 计数不符 |
| 单元测试 | `_scripts/_tests/test_phase4c1_eval_integrity.py::TestScholarlyRegression` | 14/14 覆盖、字段完整性、人工基线逐字内嵌、B01/C03/H02/I03/F01/G01 的专项契约、可复现性、`spec_basis` 有据 |
| 完整性审计 | `build_evaluation_integrity_audit.py` | 汇总 regression 覆盖计数（required_lanes / relation / formalism / metadata / expected_zero / forbidden / baseline / adjudication） |

## 5. 与 v1 gold 的关系（不覆盖）

* 本规格**不修改** `research_tasks_v1.jsonl` 与 `research_tasks_v1.gold_derivation.json`
  （测试 `test_54_v1_gold_is_untouched` 断言任务集里不出现任何裁决痕迹）；
* 三个裁决题的目标 truth 写在 `evaluation_truth_adjudicated_v1.json`
  （`status: SPEC_ONLY_NOT_APPLIED`），真正重建 gold 属 Phase 4C.1-B；
* 历史 benchmark 结果（v1 / v4a1 / v4c）全部保留，新结果必须用新版本号另存。
