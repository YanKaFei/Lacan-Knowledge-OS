# SOURCE_PROVENANCE.md — 来源可追溯性

> 版本 `1.0.0`　·　核心目标：**任何 AI 结论最终可以追溯到具体 Source / Seminar / Session / Passage**

---

## 1. 唯一不可妥协的目标

系统的验收标准不是「能回答问题」，而是：

> 给出的每一个实质判断，都能沿一条**可机械验证**的链，
> 走到一个具体的 Passage，再走到一个具体的文件与版本。

不能走通时，系统必须**明说走不通**，而不是给一个看起来完整的答案。

---

## 2. 完整溯源链

```
Level 6  AI Answer / Synthesis
            │  claim
Level 5  Claim（判断本身）
            │  relation + evidence.passage_id
Level 4  Passage（最小证据单元，带稳定 ID）
            │  structure_path / session_id
Level 3  Session（课次，带日期）
            │  seminar
Level 2  Document / Seminar（一个逻辑文献）
            │  edition / translator / publisher
Level 1  Edition（具体版本：瑟伊版 / 英译 / 中译）
            │  source_hash / source_path
Level 0  Original Source（原始文件字节，sha256 锚定）
```

链上任一环缺失 → **`SOURCE_TRACE_INCOMPLETE`**。

---

## 3. `trace_status` 三值

| 值 | 含义 | 使用条件 |
|---|---|---|
| `COMPLETE` | 七级链完整可验证 | 每一跳都能解析到真实存在的实体 |
| `SOURCE_TRACE_INCOMPLETE` | 链有断口 | **任何**一环缺失；必须在正文写明缺哪一环 |
| `NOT_APPLICABLE` | 本就不需要溯源 | 仅限元数据类节点（如 `source`、`person` 的身份信息） |

**硬规则**：`type: synthesis`（L4）节点必须显式声明 `trace_status`，且
`sources` 与 `passages` 不得同时为空。

---

## 4. 断链必须明示，不得伪装

这是本文件最重要的一条。系统禁止把无法验证的 AI 内容伪装成来源事实。

### 4.1 禁止的写法

```markdown
❌ 拉康在第十一期研讨班中指出，对象 a 是欲望的原因。[1]
   （[1] 指向一个不存在的 passage，或指向整本书而不是具体段落）
```

### 4.2 要求的写法

```markdown
✅ 拉康在第十一期研讨班中指出，对象 a 是欲望的原因。
   [passage.S11.1964-02-12.P007]

✅ 关于「对象 a 在 S20 之后被重新表述」这一说法，
   本库 SOURCE_TRACE_INCOMPLETE —— 缺 passage；
   S20 的中英对照本尚未做结构解析，无法定位到具体课次。
   （此句为推论，authority_level: L4）

❌ 不得写： 「拉康大概说过……」
```

### 4.3 三种诚实的失败表述

| 情况 | 标准表述 |
|---|---|
| 库内完全没有 | 「库中无直接出处」 |
| 有文本但未解析到 Passage 级 | 「`SOURCE_TRACE_INCOMPLETE`：定位到 Document 级，未到 Passage 级」 |
| 只有二手转述 | 「二手转述（L2），未找到拉康本人原文对应段落」 |

---

## 5. 权威分层与溯源的组合

两套东西必须**同时**标注，且不可互相替代：

| `authority_level` | 说「这话有多权威」 |
| `trace_status` | 说「这话能不能查证」 |

四种组合的实际含义：

| 组合 | 含义 | 处理 |
|---|---|---|
| L1 + COMPLETE | 拉康原文且可精确定位 | 可直接引用为事实 |
| L1 + INCOMPLETE | 拉康原文但只到 Document 级 | 可引用，但必须声明页码未定 |
| L4 + COMPLETE | AI 综合但有完整证据链 | 可引用，但必须标明是 AI 综合，且**永不 canonical** |
| L4 + INCOMPLETE | AI 综合且无法充分查证 | **必须显著标注不可作为事实依据** |

---

## 6. `source_hash` 作为防篡改锚点

每个节点的 `source_hash` 是该知识所依据源文件的 sha256。
inventory 已为全部 143 个文件算好 sha256。

用途：

1. **检测源文件漂移**：源文件被替换/重新 OCR 后，hash 不匹配 → 提示
   依赖该文件的知识需要复核。
2. **防止张冠李戴**：证明「这段话确实来自这个文件」而不是「来自某个同名文件」。
3. **支持重复检测**：实测 4 组 sha256 完全相同的文件
   （如三份 S23 中英对照 PDF 字节相同），可安全地合并 `document` 层引用。

### 6.1 实测的重复/分卷情况（inventory 结果）

**4 组字节级重复（sha256 相同）**

| 组 | 文件数 | 内容 |
|---|---|---|
| `dup.sha256.bc01560e95a4` | 3 | S23 圣状中英对照（三个文件名，同一内容） |
| `dup.sha256.a982c4276d5c` | 2 | S20 Encore 中英对照 |
| `dup.sha256.2546e8b44621` | 2 | *La psychose ordinaire. La Convention d'Antibes*（Miller） |
| `dup.sha256.552c58562207` | 2 | Chris Coffman, *Trans-Afrmative Žižeks*（英文原版 + 中译名版本） |

**5 组同一本书被切分的分卷（逻辑同一 Document）**

| 作品 | 分卷 |
|---|---|
| *Lacan on Psychosis*（Mills & Downing） | pages 1–104 / 105–207 |
| *Repères pour la psychose ordinaire*（Maleval） | pages 1–117 / 118–233 |
| *Ordinary Psychosis and The Body*（Redmond） | pages 1–87 / 88–173 |
| *La Conversation d'Arcachon* | pages 1–79 / 80–158 |
| *SOUS LA DIRECTION DE JACQUES-ALAIN MILLER* | pages 1–111 / 112–221 |


**架构处置**：`document` 层合并为一个文档实体，记录多个物理文件
（`source_path` 列表）；**物理文件一律不动、不删**。

---

## 7. 多语言版本的溯源要求

实测语料中同一作品存在多语言版本，例如：

- `Incandescent Alphabets…(Annie G. Rogers).pdf`（英文原版）
  + `Incandescent Alphabets…汉化版.pdf`（中译）
- 研讨班 20/23 有「中文版」「中英对照版」并行

**规则**：

1. 同一个 Passage 的多语言版本是**同一个 Passage 的不同 rendition**，
   不是三个独立 Passage。
2. 每个 rendition 记录自己的 `edition` / `translator`，
   通过 `aligns_with` 互指。
3. 引用中译时，**必须同时给出它所对应的原文 Passage ID**；
   找不到对应原文时标 `SOURCE_TRACE_INCOMPLETE`。
4. **禁止**因切分方便而把中译与原文切成互不相关的知识块。

---

## 8. 引用规范（写笔记与 AI 输出共用）

| 底本 | 引用格式 | 例 |
|---|---|---|
| 法文底本（瑟伊版/工作底本，有页码） | `《研讨班 III》p.115` | — |
| 法文工作转录（无页码，有段号） | `transcription 段 88` | 需注明「工作转录，非瑟伊版定本」 |
| 中译语料（段号） | `《研讨班 XVII》第5课 段 0049` | **必须同时给课次与段号**；只有课次无法定位到段（实测 82,578 段分属 531 个(期,课)组合） |
| lacan.com | 仅用于年头、法文书名、英译名、分期 | **不冒充法语原文** |
| 自己的推论 | 必须写明「推论」 | — |

**硬规则**：不得改写、拼接、补页码。引用必须是从语料取回的**原文照抄**。

---

## 9. 断层扫描：当前语料的溯源能力实测

基于 `_data/corpus_inventory.json`：

| 能力 | 现状 | 缺口 |
|---|---|---|
| L0 字节锚定（sha256） | ✅ 143/143 全部完成 | — |
| 文本可解析 | ✅ 109/143 | 14 个需 OCR |
| **已结构化的段落语料（vault 外）** | ✅ `.lacan-build/atlas/`：中译 82,578 段（含课次）+ 法语转录 166,527 段 | ⚠️ **尚未导入 vault**，且中译部分为唯一副本 |
| 结构解析（Document→Session→Passage） | ⚠️ 源语料已有课次级结构，但未映射到本项目 ID | Phase 2 R0.3 建立 ID 映射 |
| Passage 级 ID | ❌ 未开始 | Phase 2 R0.2–R0.3 |
| 跨语言对齐 | ❌ 未开始（中译与法语转录并存，是现成的对齐基础） | Phase 3 |
| Seminar 覆盖（本地原始文件） | ⚠️ 识别出 **7 期**：S1/S2/S3/S4/S5/S20/S23（S7 中译本存在但未解析出期号） | 缺 S6/S8–S19/S21–S22/S24–S27 |
| Seminar 覆盖（`.lacan-build` 语料） | ✅ **S1–S27 全部（28 期）** | — |

**结论**：溯源能力的关键瓶颈**不是语料缺失，而是尚未导入**。
`.lacan-build/atlas/` 里的 249,105 段已经带出处、带课次、带 provenance 声明，
一旦按 R0.2–R0.3 映射进 vault，Level 2→Level 4 的链路即可打通。
在此之前，任何声称「可精确定位到段落」的输出都不成立——
这正是 `SOURCE_TRACE_INCOMPLETE` 存在的意义。

**一个必须保留的证据标记**：法语转录自带的 provenance 声明是
«Document de travail (transcription STAFERLA) — texte non établi ;
les ajouts entre crochets ne sont pas de Jacques Lacan.»
导入时必须原样保留，并在所有引用中标注「工作转录，非瑟伊版定本」。
把它丢掉，就等于把工作转录冒充成了定本。

---

*配套：`ARCHITECTURE.md`（§3 权威分层）、`RELATION_MODEL.md`（证据等级）、
`INGESTION_PIPELINE.md`（如何产出这些字段）*
