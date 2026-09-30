# TRANSLATION_MODEL.md — Translation 层（语言角色）

> 版本 `1.0.0`　·　事实来源：`_scripts/_tools/build_passage_store.py`
> （第 198–228 行、第 464–468 行 SQLite 表）、`_data/passage_store/translations.jsonl`、
> `_data/passage_store/_build_meta.json` → `not_canonical`

---

## 1. Translation 是什么，不是什么

### 1.1 它是「语言角色」，不是「译本本身」

Translation 记录的是**一段文本在一个语言里的角色**：它是翻译？是转录？
是原文？并附上它的权威层级与审核状态。

它与 `witness` 的分工（详见 `WITNESS_MODEL.md` §7）：

| | 回答的问题 | 挂在哪 |
|---|---|---|
| **Witness** | 「这是哪一版文本？」（STAFERLA 转录 / 社区中译） | 版本层 |
| **Translation** | 「这段文本在库里扮什么语言角色？」 | 语言角色层，**挂在 witness 之下** |

### 1.2 关系方向

```
witness.fr.staferla ──┐
                      └── trans.fr.staferla      （translations.witness_id → witnesses.id）
witness.zh.translation-project ──┐
                                 └── trans.zh.translation-project
```

实测（`translations.jsonl`，2 条）：

| translation id | `witness_id` | `language` | `text_role` | `authority_level` |
|---|---|---|---|---|
| `trans.fr.staferla` | `witness.fr.staferla` | `fr` | `transcription` | `L1` |
| `trans.zh.translation-project` | `witness.zh.translation-project` | `zh` | `translation` | `L2` |

每条 passage 通过 `translation_id` 指向一个 translation，通过 `witness_id`
指向一个 witness（`PASSAGE_MODEL.md` §6 字段 6/7）。

---

## 2. 完整字段表

`translation` 记录共 **11 个字段**（实测 `translations.jsonl`）：

| # | 字段 | 类型 | 说明 | 实测值（zh / fr） |
|---|---|---|---|---|
| 1 | `id` | string | translation ID | `trans.zh.translation-project` / `trans.fr.staferla` |
| 2 | `witness_id` | string | 所属 witness | `witness.zh.translation-project` / `witness.fr.staferla` |
| 3 | `language` | string | `zh` / `fr` | `zh` / `fr` |
| 4 | `text_role` | string | `translation` / `transcription` | `translation` / `transcription` |
| 5 | `edition` | string | 版本描述 | `Lacan-Chinese-Translation-Project（社区中译）` / `STAFERLA 工作转录` |
| 6 | `translator` | string \| null | 译者 | `multiple (community)` / `null` |
| 7 | `authority_level` | string | L1 / L2 | `L2` / `L1` |
| 8 | `status` | string | 生命周期 | `recovered` / `recovered` |
| 9 | `canonical` | bool | 是否定本 | `false` / `false` |
| 10 | `source_state` | string | 上游状态 | `upstream_missing` / `upstream_present` |
| 11 | `review_status` | string | 审核状态 | `candidate` / `candidate` |

另有两个字段**只在部分记录出现**：

| 字段 | zh | fr | 说明 |
|---|---|---|---|
| `provenance_note` | ✅ | ✅ | 内容不同，见 §4 |
| `generated_by` | ✅ `script:build_passage_store.py` | ✅ 同 | 生成者 |

> 实测两条记录**都有** `provenance_note` 与 `generated_by`，
> 但它们是条件写入（第 212–213、227 行），不属于 §2 表的基础字段集。

---

## 3. 恢复来的中译：`status=recovered`、`canonical=false`、`source_state=upstream_missing`

这是本阶段对中译的**核心立场**。三个字段各说一件事：

| 字段 | 值 | 含义 |
|---|---|---|
| `status` | `recovered` | 这份数据是**从既有产物里恢复**的，不是从权威渠道取得的 |
| `canonical` | `false` | **它不是馆藏定本** |
| `source_state` | `upstream_missing` | 它的**上游源目录已经消失**，无法回溯原始发布 |
| `review_status` | `candidate` | 尚未经人工审核 |

### 3.1 为什么中译特别需要这套标记

实测背景（`WITNESS_MODEL.md` §2、`PASSAGE_MODEL.md` §7）：

- 中译的**上游源目录** `<HOME>` **已消失**。
- 现存副本是 `.lacan-build/atlas/segments.jsonl`（82,578 段），
  **它是那批中译的唯一幸存副本**（已由 `backup_atlas.py` 独立备份，见 `CORPUS_INTEGRATION_REPORT.md`）。
- 因此我们**无法**向用户证明「这 82,578 段逐字等于原项目发布的文本」——
  只能证明「它等于我们手上这份 jsonl」。

这一条直接决定了 `canonical` 必须是 `false`：
**一份无法回溯到上游的恢复副本，不足以成为定本。**

### 3.2 对照：法语转录的 `source_state=upstream_present`

法语转录的上游 `.lacan-build/staferla/`（28 份 `.docx` + `.txt` 原始下载）
**仍然存在**，故 `source_state=upstream_present`。

但它的 `canonical` **同样是 `false`** —— 原因不同：
不是「回不去上游」，而是**它本身就不是定本**（STAFERLA 是工作转录，
`WITNESS_MODEL.md` §4）。**两种不同的理由，同样的结论**，这正是
`canonical` 与 `source_state` 必须分开的原因。

---

## 4. 为什么不得自动覆盖旧翻译

### 4.1 规则

> **不得自动覆盖旧翻译。** 新的译本/修订只能是新增记录，不是原地替换。

### 4.2 覆盖会造成什么

`passages.jsonl` 的每条记录都带 `translation_id`
（实测 249,105 条全部有值）。若将来拿到更好的中译并**覆盖**
`trans.zh.translation-project`：

| 后果 | 说明 |
|---|---|
| 历史引用静默指向他物 | 任何写着 `translation_id: trans.zh.translation-project` 的断言，其含义会**在没有记录变更的情况下改变** |
| 溯源链断而无声 | 没有 diff 能显示「被引文本变了」，因为 ID 没变 |
| 审校记录失效 | `review_status: candidate` 是对**特定文本**的审核；换了文本，审核结论作废 |

这与 `WITNESS_MODEL.md` §5 同一条原则：**witness 与 translation 都 append-only。**

### 4.3 ⚠️ 本阶段的实现局限

`build_passage_store.py` 的 `translations` 是**硬编码字面量**（第 198–228 行），
每次构建重新生成同样两条、id 固定。因此：

- ✅ **不会**发生「自动覆盖」（因为根本没有增量逻辑）
- ❌ 但**也没有**「新增译本」的能力：加第三个 translation 必须改代码
- ❌ `passages.translation_id` 是**单值**，一条 passage 挂不了两个 translation

所以「不得自动覆盖旧翻译」目前是**靠「没有增量写入逻辑」被动满足的**，
不是靠一条主动的防护规则。**如实记录**：这是结构缺失而非设计保证。

---

## 5. 升级为 canonical 需要什么条件

`_build_meta.json` → `not_canonical` 明确写着：

```json
{
  "zh_translation_canonical": false,
  "note": "恢复来的中译 status=recovered；升级为 canonical 需 source linking + 人工审核"
}
```

即**两个**必要条件（缺一不可）：

| # | 条件 | 现状 | 为什么必须 |
|---|---|---|---|
| 1 | **source linking** | ❌ 未达成 | 中译 passage 的 `provenance` 实测 `document_id: null`、`physical_file: null`，`trace_missing: ["logical_document"]`（249,105 条全部如此）。**溯源链断在「逻辑文档」一环**（详见 `PASSAGE_MODEL.md` §7） |
| 2 | **人工审核** | ❌ 未进行 | 全部 `review_status: candidate`。Phase 1 规则：只有人可以把状态写成 `canonical`，且必须填 `reviewed_by` + `reviewed_at`（`KNOWLEDGE_SCHEMA.md` §5） |

### 5.1 source linking 具体要做什么

因为 atlas `.jsonl` 的 sha256 不在 `corpus_inventory.json` 里
（已独立复现，见 `PASSAGE_MODEL.md` §7.1），需要二选一：

- **(a) 把 `.lacan-build/atlas/` 纳入 inventory**，让 `segments.jsonl` 成为一个
  有 `document_id` 的逻辑文档；或
- **(b) 建立显式映射**：atlas 文件 → 它对应的源语料 `document_id`
  （例如 `segments.jsonl` ↔ 已消失的 `研讨班中译/` 目录下的 603 个 md）。

**本阶段未做**（属 Phase 3）。在此之前，`canonical` 必须保持 `false`。

### 5.2 与「L4 永不 canonical」的关系（不要混淆）

两个不同的规则，都指向「不许随便 canonical」：

| 规则 | 适用对象 | 出处 |
|---|---|---|
| **L4 永不 canonical** | AI 合成内容（`authority_level: L4`） | `ARCHITECTURE.md` §3、`KNOWLEDGE_SCHEMA.md` §5；schema 层已强制 |
| **恢复的中译不得自动 canonical** | 本节的 translation | `_build_meta.json` → `not_canonical` |

中译是 L2（他人翻译），**不是 L4**，所以它不受「L4 永不 canonical」约束 ——
它受的是本节这条**恢复数据**规则。两条规则不能互相替代。

---

## 6. SQLite 投影

```sql
CREATE TABLE translations (
    id TEXT PRIMARY KEY, witness_id TEXT, language TEXT, text_role TEXT,
    edition TEXT, authority_level TEXT, status TEXT,
    canonical INTEGER, review_status TEXT
);
```

实测 `translations` 表 2 行，与 JSONL 一致。

⚠️ **投影有损**：SQLite 表**不含** `translator`、`source_state`、`provenance_note`。
其中 `provenance_note` 承载的正是「未经 source linking 与人工审核，
不得升级为 canonical」这条**操作禁令** —— 从 SQLite 读会丢掉它。
与 `WITNESS_MODEL.md` §6 是同一类问题。

---

## 7. 与 Phase 1 schema 的关系（⚠️ 不一致）

Phase 1 的 `id-namespaces.json` 定义：

```
translation  ^trans\.(?:fr|en|zh)-to-(?:fr|en|zh)\.[a-z0-9][a-z0-9-]*$
             example: trans.fr-to-zh.jouissance
```

Phase 2 实际产出：`trans.zh.translation-project`、`trans.fr.staferla`

### 7.1 ⚠️ 此冲突**仍然存在**（本轮重新核对）

逐个 `re.match` 实测当前 pattern：

| ID | 结果 |
|---|---|
| `trans.fr-to-zh.jouissance`（Phase 1 术语层） | ✅ 通过 |
| `trans.zh.translation-project`（Phase 2 文本层） | ❌ **不通过** |
| `trans.fr.staferla`（Phase 2 文本层） | ❌ **不通过** |

**不匹配** —— Phase 1 的 pattern 要求「方向对」（`fr-to-zh`），
Phase 2 的 ID 表达的是「语言 + 来源项目」（`zh.translation-project`）。

而且：Phase 1 的 translation 是**术语层**的译法条目
（`trans.fr-to-zh.jouissance` 是 jouissance 的法→中译法），
Phase 2 的 translation 是**文本层**的语言角色（整批中译语料的角色）。
**这是两个不同层级的东西共用了 `trans.` 命名空间。**

### 7.2 而新增的 validator 校验**也覆盖不到它**

本轮 `validate_vault.py` 新增了 `audit_passage_store()`（7 项检查，
含「命中 `id-namespaces.json` 的 pattern」）—— **但它校验的是 passage 的 ID**，
**不是 translation / witness 的 ID**（`translations.jsonl` 与 `witnesses.jsonl`
不在该函数的检查范围内）。

因此这个 namespace 冲突**仍然不会被任何现成检查发现**。
实测 `passage_store.errors = []` 与这个冲突并不矛盾 —— 两者检查的对象不同。

**如实记录，不擅自选择**：需要人决定是给文本层角色另立 namespace
（如 `textrole.` / `witness.`），还是改 ID 形态。
**这是本轮核对新发现的、仍然未解决的一处不一致。**

---

*配套：`WITNESS_MODEL.md` · `PASSAGE_MODEL.md` · `ALIGNMENT_MODEL.md` ·
`SOURCE_PROVENANCE.md`（Phase 1）*
