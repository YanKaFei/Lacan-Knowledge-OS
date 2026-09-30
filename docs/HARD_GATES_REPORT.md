# HARD_GATES_REPORT.md — §23 硬门禁统一计算

> 生成：`_scripts/_tools/check_hard_gates.py`　·　原始数据：`_data/index/HARD_GATES.json`

**本文件里的每个数字都是现算的，不是从别处手抄的。**每一行的「算法」列写清数据来源；产物一变，重跑一次就能看出门禁有没有被打破。

## 0. 汇总

| 项 | 值 |
|---|---:|
| 门禁数 | **17** |
| 违规总数 | **0** |
| `all_zero` | **True** |
| passage store 内 passage 数 | 249105 |
| passage store content_hash | `1dd3e0704402b09c61cf8cb9` |

## 1. 逐项

| # | 门禁 | 值 | 算法 / 数据来源 |
|---|---|---:|---|
| 1 | `fabricated_passage_ids` | **0** | 扫描 10 个产物收集引用 id，逐个到 passages.jsonl 的真实 id 集合（本项扫了 249105 条）里查 |
| 2 | `broken_passage_references` | **0** | 引用的 id 是否符合 `^passage\.[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+$` |
| 3 | `silent_provenance_upgrade` | **0** | trace_status == COMPLETE 却 trace_missing 非空（0）；或 authority_level == L4 且 canonical（0） |
| 4 | `gold_references_to_nonexistent_passages` | **0** | 45 条 gold 的 evidence 并集（252 条）逐个查真实 id 集合 |
| 5 | `canonical_source_mutation` | **0** | `.lacan-build/atlas` 源文件 sha256 vs `_build_meta.json` 记录 |
| 6 | `source_hash_mutation` | **0** | 同上（含源文件缺失） |
| 7 | `vector_index_corpus_hash_mismatch` | **0** | 按 `corpus_hash` 自己的规则重算 `sha256(passages.jsonl 字节)`，再与 `VECTOR_INDEX_MANIFEST` 和 benchmark manifest 比对 |
| 8 | `automatic_source_link_canonicalization` | **0** | 候选文件 210 条中 `canonical=true` 或 `review_status != candidate` 的条数，加上 `concepts.jsonl` 是否被改动 |
| 9 | `runtime_reference_parity_failure` | **0** | `RUNTIME_PARITY_MANIFEST.hard_gates` + 逐模型 status |
| 10 | `invalid_embedding_dimension` | **0** | `RUNTIME_PARITY_MANIFEST` 逐模型 dims.match |
| 11 | `max_seq_length_mismatch` | **0** | `RUNTIME_PARITY_MANIFEST` 逐模型 ref vs onnx 的 max_seq_length |
| 12 | `NaN_or_Inf_embedding` | **0** | `RUNTIME_GATES.determinism.*.nan_or_inf` 求和 |
| 13 | `zero_norm_embedding` | **0** | `RUNTIME_GATES.determinism.*.zero_norm` 求和 |
| 14 | `model_manifest_hash_mismatch` | **0** | 调 `build_model_manifest.py --verify`，逐文件重算 sha256 |
| 15 | `wheelhouse_hash_mismatch` | **0** | 调 `build_wheelhouse.py --verify`，逐 wheel 重算 sha256 + 重算 wheelhouse_hash |
| 16 | `answerable_unanswerable_metric_contamination` | **0** | 两个分母 query_id 交集 + 不可答记录是否带 answerable 指标 |
| 17 | `passage_outside_evaluation_pool` | **0** | semantic benchmark 所有配置的 top-20 是否都在 `evaluation_pool` 内 |

## 2. 判定规则

任何一项 > 0 即视为**交付失败**（不是「需要注意」）。特别地：

- `fabricated_passage_ids` / `gold_references_to_nonexistent_passages` > 0 → 结论里不能出现任何引用。
- `canonical_source_mutation` / `source_hash_mutation` > 0 → 唯一副本被改动，必须先恢复再谈别的。
- `answerable_unanswerable_metric_contamination` > 0 → 所有 recall/MRR/nDCG 作废（分母被污染）。
- `runtime_reference_parity_failure` > 0 → **不得进入 semantic benchmark**（§11 原文）。
- `automatic_source_link_canonicalization` > 0 → 候选被自动当成结论，这是本项目最严重的越权。

## 3. 复现

```bash
python3 _scripts/_tools/check_hard_gates.py --run      # 全量重算（含 384MB 单次扫描）
python3 _scripts/_tools/check_hard_gates.py --verify   # 只核已有产物
```
