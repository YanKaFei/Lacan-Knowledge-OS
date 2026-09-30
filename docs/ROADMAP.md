# ROADMAP.md — 路线图

> 版本 `1.0.0`　·　原则：**先让溯源成立，再让检索变强**

---

## 0. 优先级判据

当多个目标冲突时，按此顺序取舍：

1. **准确性** —— 宁可说「不知道」，不可给错答案
2. **来源可追溯性** —— 没有出处的结论没有价值
3. **长期可维护性** —— 字段封闭、结构稳定、可重建
4. **Obsidian 可读性** —— 人必须能读能改
5. **Agent 可调用性** —— 统一服务接口
6. **检索质量** —— 混合检索与重排

即：**检索质量排在最后**。一个检索很准但来源不明的系统，
在拉康研究里是负资产——因为读者无法判断某句话是拉康说的、
米勒说的、还是模型编的。

---

## 当前进度（截至 Phase 3B.2，**不要从这里往下读成「已完成」**）

> 本路线图是最初的计划编号；实际执行把「检索层」拆成了 Phase 3 / 3A / 3B / 3B.1 / 3B.2。
> 权威结论在 findings 文件里，**本表只做指针**。

| 阶段 | 状态 | 权威文件 |
|---|---|---|
| Phase 1 Inventory + 架构 + Vault | ✅ | `PHASE1_FINDINGS.md` |
| Phase 2 语料整合与 Passage 规范化 | ✅ | `PHASE2_FINDINGS.md` · `DELIVERY_EVIDENCE_PHASE2.md` |
| Phase 3 / 3A 检索与证据装配 | ⚠️ | `PHASE3_FINDINGS.md` · `RETRIEVAL_EVALUATION.md` |
| Phase 3B 语义检索与 gold 评测 | ⚠️ **部分**（被运行时阻断，后来解除） | `PHASE3B_FINDINGS.md`（顶部有过期横幅） |
| **Phase 3B.1 离线运行时恢复** | ✅ **运行时部分 ACCEPTED** | `PHASE3B1_FINDINGS.md` · `OFFLINE_RUNTIME_GUIDE.md` |
| **Phase 3B.2 语义评测与消融** | ⚠️ **PARTIAL** | `PHASE3B2_FINDINGS.md` · `SEMANTIC_BENCHMARK_RESULTS.md` |
| **全量向量索引（§21 门禁）** | ❌ **未构建** | `VECTOR_INDEX_MANIFEST.json`（`status = NOT_BUILT`） |
| Phase 4 混合检索（路线图口径） | ⛔ **未开始** | —— |

**为什么 3B.2 是 PARTIAL（三条硬缺口，不是谦虚）**：

1. 方向 C（FR→FR）与 D（FR→ZH）在 gold 上 **n = 0** —— 没有样本，不是测得 0；
2. 方向 B（ZH→FR）的 **scored** Recall@20 只有 minilm 0/8、mpnet 1/8，
   定量原因见 `CROSSLANG_DIAGNOSTIC.md`（语义 margin 仅 +0.04）；
3. Contrastive 只有 **4/10** 通过，且未过的正是拉康最需要区分的那几组术语。

因此**不进入下一阶段**。`VECTOR_INDEX_MANIFEST.status` 保持 `NOT_BUILT`。

---

## Phase 1 — Inventory + Architecture + Vault Scaffold ✅ 本轮

| 交付物 | 状态 |
|---|---|
| 环境勘察与既有资产复用评估 | ✅ |
| 只读语料 inventory 引擎 | ✅ `_scripts/inventory_corpus.py` |
| `corpus_inventory.json` / `.csv` / `corpus_report.md` | ✅ 143 文件 / 1.198 GiB |
| Obsidian vault scaffold（16 主目录 + 4 下划线目录） | ✅ |
| JSON Schema（knowledge / relation / id-namespaces） | ✅ |
| 七份架构文档 | ✅ |
| 代表性测试数据（fixtures） | ✅ |
| 自动化测试（ID 唯一 / YAML schema / broken wikilink / invalid relation / source trace / duplicate entity / orphan concept） | ✅ |
| inventory 引擎测试 | ✅ 21 项 |

**本阶段明确未做**：批量转换、embedding、抓站、OCR、结构解析。
这些是 Phase 2 起的任务，且架构已为它们留好落位。

---

## Phase 2 — 结构解析与 Passage 化（下一步的主线）

> 目标：让 `trace_claim` **真正可用**。当前溯源只到 Document 级，
> 到不了 Passage 级——这是与「生产级」之间最大的一道鸿沟。

### R0 语料保全与导入（**最高优先级**）

> 实测结论：语料**没有丢失**。`.lacan-build/atlas/` 保有中译 82,578 段 +
> 法语转录 166,527 段，合计 **249,105 个已带出处、已带课次结构的段落**。
> 但中译的**上游源目录已消失**，该 jsonl 目前是**唯一副本**。
> 因此 R0 的性质从「恢复」变为「保全 + 导入」。

| 任务 | 说明 | 优先级 |
|---|---|---|
| R0.1 | **立即备份 `.lacan-build/atlas/`**（至少 `segments.jsonl` + `french_staferla.jsonl`）。它们是唯一副本，任何误删都不可逆 | 🔴 最高 |
| R0.2 | 把 249,105 段导入 vault：`segments.jsonl`→中译 Passage / `french_staferla.jsonl`→法语 Passage | 🔴 高 |
| R0.3 | 建立 **passage ID 映射表**：`.lacan-build` 段号（`s1-01-0001`）→ 本项目 `passage.S1.<session_date>.P<nnn>`。注意源段号含 `lesson` 但**不含日期**，需从 `seminars.json` 的年份区间 + 课次表补日期；补不出的课次标 `session_date: unknown`，**不得编造日期** | 🔴 高 |
| R0.4 | 导入 `seminars.json`（28 期元数据：罗马数字/法文名/中文名/年份/课数）作为 `seminar.*` 实体 | 🟠 中 |
| R0.5 | 导入 `term_vocab.json` / `term_neighbours.json` / `lacancom.json` 作为术语与书目基础 | 🟠 中 |
| R0.6 | 从 `kotoba-rin/Lacan-Chinese-Translation-Project`（CC-BY 4.0）重新获取中译原文，与 `segments.jsonl` 交叉校验（防止 jsonl 是残缺版本） | 🟡 低（有副本后不再阻塞） |
| R0.7 | 用 `inventory_corpus.py` 对导入后的语料重新盘点，纳入统一 inventory | 🟠 中 |

> ⚠️ **`.lacan-build/staferla/` 另有 S1–S27 的 28 份 `.docx`/`.txt` 原始下载**
> （manifest 记录逐期段落数，如 S1 = 9,779 段）。这与 `french_staferla.jsonl`
> 互为备份，是 R0.1 之外的第二道保险。

> 法语转录的 `provenance` 字段已明确写着
> «Document de travail (transcription STAFERLA) — texte non établi»。
> **导入时必须保留这句话**，并在所有引用中标注「工作转录，非瑟伊版定本」——
> 这正是 SOURCE_PROVENANCE.md §8 引用规范的要求。

### R1 OCR 补齐（解锁 14 个文件）

- 安装 `ocrmypdf` + `tesseract`（`chi_sim` / `fra` / `eng`）
- 优先级：**S7 商务印书馆中译（482 页，唯一 S7 中文底本）** >
  埃文斯辞典（484 页） > 沈志中《精神分析辭彙》（686 页） > 其余
- OCR 产物入 `_data/ocr/`，带原文件 `source_hash` 以便审计

### R2 Document 归并（S1）

- 4 组 sha256 字节级重复 + 5 组分卷 → `document` 实体
- 产出 `work.` / `edition.` ID
- 物理文件不动

### R3 结构解析（S3）★ 核心难点

- 逐本建立解析器（不同版本排版差异大）
- 先做已有法语/中译底本的 S1 / S3 / S20 / S23
- 产出 `seminar.*` / `session.*`，日期必须真实，不确定则标 `unknown`

### R4 Passage 化（S4）

- 稳定 ID + `structure_path`
- **不做固定 token 切分**

### R5 概念两层模型落地

- 建立首批 `concept` + `concept_state`（建议从实测高频术语开始：
  objet a / jouissance / grand Autre / sinthome / Nom-du-Père /
  forclusion / désir / fantasme / réel-symbolique-imaginaire）
- 每个 state 必须绑定真实 Passage

**Phase 2 验收**：能对一个具体判断跑通完整七级溯源链，
或明确返回 `SOURCE_TRACE_INCOMPLETE`。

---

## Phase 3 — 跨语言对齐与术语体系

- S5：`translation` 实体 + `aligns_with`
- 三语术语表（FR/EN/ZH），处理异译归并
- 术语历史（`get_term_history` 的数据基础）
- 中文分词策略决策（FTS5 需要）

**验收**：任一中译 Passage 都能找到对应原文 Passage；
找不到的显式标记。

---

## Phase 4 — 混合检索

六路合流 + 重排：

1. exact alias
2. SQLite FTS5
3. LanceDB 向量
4. Graph 遍历
5. metadata filter
6. reranker

**验收**：每条结果携带 `passage_id` + `authority_level` + `trace_status`。
**不引入 Neo4j**。

---

## Phase 5 — MCP Server（`lacan-kb-mcp`）

12 个工具（`search_knowledge` / `get_concept` / `get_passage` / `get_source` /
`get_neighbors` / `search_by_period` / `search_seminar` / `compare_concepts` /
`trace_claim` / `get_topology` / `get_case` / `get_term_history`）。

**目标**：DeepSeek Harness 与 Codex 都通过它访问，不再各自扫描全文件。

---

## Phase 6 — 外部来源接入

| 来源 | 方式 |
|---|---|
| lacan.com | **导入** `<HOME>`（616 txt 已抓），不重抓 |
| GitHub repositories | 经人工审核后接入 |
| 其他 Lacanian 网站 | 后续评估 |

**约束**：不自动下载任意 GitHub repo；不无审核接入外部内容。

---

## Phase 7 — 与既有系统合流

在动手前**必须先读** `<HOME>` 的：

- `CLAIM_TRACE_SPEC.md` / `CITATION_RESOLVER.md`（与 SOURCE_PROVENANCE 目标重合）
- `CONCEPT_BOUNDARY_REGISTRY.md`（与概念两层模型重合）
- `ASSOCIATION_GRAPH_SPEC.md`（与 RELATION_MODEL 重合）
- `AGENT_CORE_KNOWN_FAILURES.md` / `ASSOCIATION_KNOWN_FAILURES.md`（已知失败，直接受益）

**目的**：把已验证的设计与失败教训吸收进来，而不是造第二套冲突架构。

---

## 2. 风险登记册

| 风险 | 影响 | 缓解 |
|---|---|---|
| **`.lacan-build/atlas/` 是唯一副本且从未备份** | 中译 82,578 段不可逆丢失 | 🔴 R0.1 立即备份；`.lacan-build/staferla/` 的 28 份原始下载作第二道保险 |
| 源段号不含日期 | Passage ID 的日期维度可能填不出 | R0.3 从 `seminars.json` 年份 + 课次表推导；推导不出的标 `unknown`，禁止编造 |
| OCR 质量差 | 中文古籍/旧版排版误识多 | 抽检 + 保留原文件 hash + 标注 OCR 来源 |
| schema 字段失控 | 长期腐化 | `additionalProperties: false` + CHANGELOG 流程 |
| `related_to` 滥用 | 类型化关系退化为无类型链接 | 校验器监控其占比（>40% 警告） |
| AI 内容混入 canonical | 溯源体系失效 | schema 强制 L4 不得 canonical + 分文件存放 |
| 中文分词不当 | FTS5 检索质量差 | Phase 3 专门决策，不默认照搬英文方案 |
| 与 lacan-v2 设计冲突 | 两套架构并存 | Phase 7 前置阅读，先对齐再实现 |

---

## 3. 长期维护机制

| 机制 | 频率 | 产出 |
|---|---|---|
| `validate_vault.py --strict` | 每次提交 | `_index/Reports/validation-report.md` |
| `inventory_corpus.py` 重跑 | 源语料变动时 | 更新 inventory，检测源漂移 |
| 孤儿概念巡检 | 每月 | `_index/Views/orphans.md` |
| `related_to` 占比巡检 | 每月 | 类型化关系健康度 |
| schema CHANGELOG 复核 | 每次字段变更 | 迁移记录 |

---

*配套：`ARCHITECTURE.md`（§10 非目标）、`INGESTION_PIPELINE.md`（各阶段细节）*
