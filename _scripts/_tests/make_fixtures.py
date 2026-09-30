#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_fixtures.py — 生成 Schema 验证用的代表性测试数据

设计原则：
  * 内容全部来自**真实语料**（`00_System/_fixtures/` 里的样本文件），
    引文可在对应 PDF/DOCX 中逐字复核。
  * 凡是不能确证的信息（如精确课次日期），一律显式写进 provenance 说明，
    **不编造**。这正是 SOURCE_PROVENANCE.md 要求的诚实。
  * AI 产出的候选必须落在 relations.candidate.jsonl，且 review_status=candidate。

用法: python3 make_fixtures.py
"""

import json
import os
import hashlib

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = BASE                      # vault 根
FIX = os.path.join(BASE, "00_System", "_fixtures")
REL = os.path.join(BASE, "_data", "relations")

COMMON = {
    "language": "mul",
    "status": "active",
    "created_at": "2026-09-20T00:00:00Z",
    "updated_at": "2026-09-20T00:00:00Z",
    "schema_version": "1.0.0",
}


def yaml_scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    s = str(v)
    if s == "" or any(c in s for c in ":#{}[],&*?|-<>=!%@`\"'") or s.strip() != s:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def dump_yaml(d, indent=0):
    out = []
    pad = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f"{pad}{k}:")
            out.append(dump_yaml(v, indent + 1))
        elif isinstance(v, list):
            if not v:
                out.append(f"{pad}{k}: []")
            else:
                out.append(f"{pad}{k}:")
                for item in v:
                    if isinstance(item, dict):
                        body = dump_yaml(item, indent + 2)
                        out.append(f"{pad}  - " + body.lstrip())
                    else:
                        out.append(f"{pad}  - {yaml_scalar(item)}")
        else:
            out.append(f"{pad}{k}: {yaml_scalar(v)}")
    return "\n".join(out)


def write_note(relpath, fm, body):
    path = os.path.join(ROOT, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write(dump_yaml(fm))
        f.write("\n---\n\n")
        f.write(body.strip() + "\n")
    return relpath


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    man = json.load(open(os.path.join(FIX, "manifest.json"), encoding="utf-8"))
    fx = {m["entity_kind"]: m for m in man["fixtures"]}
    by_file = {m["fixture_file"]: m for m in man["fixtures"]}

    s3 = by_file["S3 PSYCHOSES.pdf"]
    s23 = by_file["【中英】23圣状 The Sinthome-拉康第二十三期研讨班-中英对照版.pdf"]
    bourbon = by_file["布里吉特·布尔邦小姐的临床演示.docx"]

    # 统一说明：日期精度问题必须显式声明，不得编造
    DATE_CAVEAT = ("课次日期未确证：本样本仅定位到 Document/Page 级。"
                   "真实 session_date 需由 .lacan-build 的课次表导入后补齐；"
                   "此处不得作为日期依据。")

    n = 0

    # ---------------- 01_Sources ----------------
    write_note("01_Sources/source.local.desktop-lacan.md", {
        "id": "source.local.desktop-lacan",
        "type": "source",
        "title": "本机桌面语料目录（拉康派精神分析项目内容）",
        "canonical_name": "desktop-lacan-corpus",
        "aliases": ["拉康派精神分析项目内容", "本机语料"],
        "language": "mul",
        "source_type": "local_directory",
        "source_path": "<HOME>",
        "authority_level": "L0",
        "review_status": "reviewed", "reviewed_by": "human:coffee",
        "reviewed_at": "2026-09-20T00:00:00Z",
        "generated_by": "human:coffee",
        "status": "active",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "tags": ["来源/本机"],
    }, """# 本机桌面语料目录

只读扫描结果（`_scripts/inventory_corpus.py`）：

- 文件总数 **143**
- 总体积 **1.198 GiB**
- 4 组 sha256 完全重复 / 5 组同书分卷
- 语言分布 zh 87 / fr 24 / en 22 / und 10
- 14 个文件需 OCR

完整清单见 [`_data/corpus_inventory.json`](../../_data/corpus_inventory.json)
与 [`_data/corpus_report.md`](../../_data/corpus_report.md)。

**原始文件全程只读，未被修改、移动或删除。**
""")
    n += 1

    write_note("01_Sources/Documents/doc.lacan.seminar-3.md", {
        "id": "doc.lacan.seminar-3",
        "type": "document",
        "title": "Le Séminaire, Livre III : Les psychoses",
        "canonical_name": "Lacan, Séminaire III: Les psychoses",
        "aliases": ["S3 PSYCHOSES", "研讨班三期：精神病", "Séminaire III"],
        "language": "fr",
        "source_id": "source.local.desktop-lacan",
        "source_path": by_file["S3 PSYCHOSES.pdf"]["origin_rel_path"],
        "source_hash": s3["origin_sha256"],
        "source_type": "seminar_primary",
        "seminar": "ST1",
        "edition": "法文底本（工作扫描件）",
        "authority_level": "L1",
        "review_status": "reviewed", "reviewed_by": "human:coffee",
        "reviewed_at": "2026-09-20T00:00:00Z",
        "generated_by": "human:coffee",
        "status": "active",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "tags": ["文献/研讨班", "期号/S3"],
    }, f"""# Le Séminaire, Livre III : Les psychoses

法文底本，247 页。`source_hash` 与 `_data/corpus_inventory.json` 中该文件的
sha256 逐字一致，可验证本文档确实来自该文件。

## 证据说明

- 底本类型：**法文扫描/排版底本**，文字层可用（`parse_status: PARSED`）。
- 页码：可定位到 PDF 页（见各 Passage 的 `page_from`）。
- ⚠️ {DATE_CAVEAT}

## 相关

- 研讨班：`seminar.ST1`
- 二手研究：[`doc.arcachon.2001`](doc.arcachon.2001.md)
""")
    n += 1

    write_note("01_Sources/Documents/doc.lacan.seminar-23.md", {
        "id": "doc.lacan.seminar-23",
        "type": "document",
        "title": "Le Séminaire, Livre XXIII : Le sinthome（中英对照版）",
        "canonical_name": "Lacan, Séminaire XXIII: Le sinthome",
        "aliases": ["圣状", "Sinthome", "23期研讨班", "S23"],
        "language": "mul",
        "source_id": "source.local.desktop-lacan",
        "source_path": s23["origin_rel_path"],
        "source_hash": s23["origin_sha256"],
        "source_type": "seminar_primary",
        "seminar": "S23",
        "edition": "中英对照版",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "active",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "tags": ["文献/研讨班", "期号/S23"],
    }, f"""# Le Séminaire, Livre XXIII : Le sinthome

⚠️ **该文件在语料中存在 3 个 sha256 完全相同的副本**
（`dup.sha256.bc01560e95a4`）：

1. `【中英】23圣状 The Sinthome-…-中英对照版.pdf`
2. `圣状 The Sinthome-…Book X (Z-lib.io).pdf`
3. `拉康研讨班23期中英对照.pdf`

按 ARCHITECTURE.md §S1，这是**同一个 `document` 的三个物理副本**，
物理文件一律不动、不删。

- ⚠️ {DATE_CAVEAT}
""")
    n += 1

    write_note("01_Sources/Documents/doc.arcachon.2001.md", {
        "id": "doc.arcachon.2001",
        "type": "document",
        "title": "La Conversation d'Arcachon（日常精神病，第 1 部分）",
        "canonical_name": "La Conversation d'Arcachon",
        "aliases": ["阿卡雄对话会", "Arcachon"],
        "language": "fr",
        "source_id": "source.local.desktop-lacan",
        "source_path": fx["secondary"]["origin_rel_path"],
        "source_hash": fx["secondary"]["origin_sha256"],
        "source_type": "secondary_source",
        "edition": "part-01-pages-1-79",
        "authority_level": "L2",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "active",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "tags": ["文献/二手", "主题/日常精神病"],
    }, """# La Conversation d'Arcachon

二手研究（L2）。属于**同书分卷**组 `dup.split.73df64132d81`：
本文件为 part-01（pages 1–79），另有 part-02（pages 80–158）。
按架构要求，逻辑上应合并为一个 `document`。
""")
    n += 1

    # ---------------- 02_Lacan_Seminars ----------------
    write_note("02_Lacan_Seminars/ST1_Fixture/seminar.ST1.md", {
        "id": "seminar.ST1",
        "type": "seminar",
        "title": "研讨班 III：精神病（Les psychoses）",
        "canonical_name": "Séminaire III: Les psychoses",
        "aliases": ["S3", "第三期研讨班", "Les psychoses", "精神病"],
        "language": "mul",
        "seminar": "ST1",
        "period": "1955-1958",
        "period_label": "1955–1958 精神病与能指",
        "source_id": "doc.lacan.seminar-3",
        "authority_level": "L1",
        "review_status": "reviewed", "reviewed_by": "human:coffee",
        "reviewed_at": "2026-09-20T00:00:00Z",
        "generated_by": "human:coffee",
        "status": "active",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "related": ["case.schreber", "doc.lacan.seminar-3"],
        "tags": ["研讨班/S3", "领域/精神病"],
    }, """# 研讨班 III：精神病

年份：1955–1956（法文底本 247 页）。

## 本研讨班的地位

S3 是「父之名脱落（forclusion）」与 Schreber 个案分析的集中讲期，
是精神病结构理论的奠基处。

## 课次

> ⚠️ 课次级结构尚未解析。本地底本仅定位到 Page 级；
> 完整课次结构（含日期）需从 `.lacan-build/atlas/seminars.json`
> 与 STAFERLA 转录导入后补齐。**在补齐前不得给出精确课次日期。**
""")
    n += 1

    write_note("02_Lacan_Seminars/ST1_Fixture/session.ST1.unknown.md", {
        "id": "session.ST1.unknown",
        "type": "session",
        "title": "S3 · 课次未定（页级证据）",
        "canonical_name": "S3 session (page-level only)",
        "aliases": ["S3 未定课"],
        "language": "fr",
        "seminar": "ST1",
        "session_date": "1955-01-01",
        "session_date_precision": "year",
        "source_id": "doc.lacan.seminar-3",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "tags": ["研讨班/S3"],
    }, """# S3 · 课次未定

## ⚠️ SOURCE_TRACE_INCOMPLETE

本 session 的 `session_date` 为 `1955-01-01`，这是**占位值**，
表示「1955 年内的课次，具体日期未定」，**不是真实课次日期**。

- 缺哪一环：Session → 精确日期
- 为什么缺：本地 `S3 PSYCHOSES.pdf` 未保留课次分隔与日期题头
- 如何补齐：`.lacan-build/atlas/seminars.json`（含 `lesson_numbers`）
  + STAFERLA 转录的课次划分，导入后按 R0.3 回填
- 在补齐前：**任何引用都不得声称知道该段出自哪一课**

这条占位与说明本身就是 Schema 的验证用例：
系统必须能表达「我知道它出自 S3，但不知道具体哪一课」，
而不是含糊地当成「已知」。
""")
    n += 1

    # ---------------- 05_Terminology ----------------
    write_note("05_Terminology/FR/term.fr.jouissance.md", {
        "id": "term.fr.jouissance",
        "type": "term",
        "title": "jouissance（享乐/快感）",
        "canonical_name": "jouissance",
        "aliases": ["享乐", "快感", "jouissance", "Jouissance"],
        "language": "mul",
        "fr": "jouissance",
        "en": "jouissance",
        "zh": "享乐（旧译「快感」）",
        "authority_level": "L2",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "aligns_with": ["trans.mul.jouissance"],
        "tags": ["术语/享乐"],
    }, """# jouissance

## 术语三语

| 语言 | 写法 |
|---|---|
| 法 | *jouissance* |
| 英 | jouissance（一般不译） |
| 中 | 享乐（亦有旧译「快感」） |

## ⚠️ 常见误译

中文旧译「快感」会与 *plaisir*（快乐原则中的快乐）混淆。
拉康严格区分 *plaisir* 与 *jouissance*：前者受快乐原则调节，
后者**越出**快乐原则。译作「快感」会抹掉这条区分。

> 本条目 `review_status: needs_review`。三语译名的最终确认
> 需要人工审核与语料证据（见 Phase 3）。

## 译法条目

- [[trans.mul.jouissance]] —— 法→中译法对齐（`translates_as` 关系的呈现层对应）

> 说明：语义层 `_data/relations/relations.candidate.jsonl` 里有
> `term.fr.jouissance --translates_as--> trans.mul.jouissance`；
> 上面这条 wikilink 是它在呈现层的对应，两层必须一致
> （否则 validator 会报 `RELATION_VIEW_MISMATCH`）。
""")
    n += 1

    write_note("05_Terminology/FR/term.fr.sinthome.md", {
        "id": "term.fr.sinthome",
        "type": "term",
        "title": "sinthome（圣状）",
        "canonical_name": "sinthome",
        "aliases": ["圣状", "sinthome", "Sinthome", "synthome"],
        "language": "mul",
        "fr": "sinthome",
        "en": "sinthome",
        "zh": "圣状",
        "authority_level": "L2",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "tags": ["术语/圣状", "期号/S23"],
    }, """# sinthome

## 术语三语

| 语言 | 写法 |
|---|---|
| 法 | *sinthome*（拉康对 *symptôme* 的古拼法改写） |
| 英 | sinthome |
| 中 | 圣状 |

## 要点

*synthome* / *sinthome* 是拉康晚期（S23）对症状的重新书写：
症状不再只是待解释的密文，而是**把 RSI 三界打结的那个第四项**。

> 分期差异必须保留：S23 之前「症状」与 S23 的「圣状」不是同一个概念状态。
> 见 `state.sinthome.1974-1976`。
""")
    n += 1

    write_note("05_Terminology/Alignments/trans.mul.jouissance.md", {
        "id": "trans.mul.jouissance",
        "type": "translation",
        "title": "jouissance → 享乐（译法条目）",
        "canonical_name": "jouissance fr-zh",
        "aliases": ["享乐译法", "jouissance 中译"],
        "language": "mul",
        "translator": "（待定，需人工审核）",
        "authority_level": "L3",
        "review_status": "candidate",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "aligns_with": ["term.fr.jouissance"],
        "tags": ["翻译/术语"],
    }, """# jouissance → 享乐

译法条目。`review_status: candidate` —— 译名尚未经人工确认。

## 为什么单独立条目

跨语言对齐必须是一等实体：同一个 passage 的 fr/en/zh 三个 rendition
通过 `aligns_with` 互指，而不是三个互不相干的块。
""")
    n += 1

    # ---------------- 04_Concepts ----------------
    write_note("04_Concepts/concept.objet-a.md", {
        "id": "concept.objet-a",
        "type": "concept",
        "title": "objet petit a（对象 a）",
        "canonical_name": "objet petit a",
        "aliases": ["对象 a", "对象小a", "小对形", "objet a", "the object a", "l'objet a"],
        "language": "mul",
        "fr": "objet petit a",
        "en": "object petit a",
        "zh": "对象 a",
        "authority_level": "L2",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "concept_states": [
            "state.objet-a.1955-1958",
            "state.objet-a.1964-1966",
            "state.objet-a.1972-1973",
        ],
        "related": ["concept.sinthome", "term.fr.jouissance"],
        "tags": ["概念/对象a"],
    }, """# objet petit a（对象 a）

> **本卡不承载定义。** 定义只存在于各历史阶段的 `concept_state` 中。
> 这是刻意的结构约束：让「合并成一个通顺定义」在物理上无处可写。

## 各阶段状态

| 分期 | 状态卡 | 该阶段的表述 |
|---|---|---|
| 1955-1958 | [`state.objet-a.1955-1958`](States/state.objet-a.1955-1958.md) | 待补 |
| 1964-1966 | [`state.objet-a.1964-1966`](States/state.objet-a.1964-1966.md) | a 作为欲望的原因 |
| 1972-1973 | [`state.objet-a.1972-1973`](States/state.objet-a.1972-1973.md) | 待补 |

## 别名与译名

中文译名分歧较大：对象 a / 对象小a / 小对形。全部进 `aliases`，
用于 exact-alias 检索层。ID 用**法语原词** `objet-a`，
因为中文译名不稳定，用中文做 ID 会让别名归并变得不可能。
""")
    n += 1

    write_note("04_Concepts/States/state.objet-a.1964-1966.md", {
        "id": "state.objet-a.1964-1966",
        "type": "concept_state",
        "title": "objet a — 1964–1966：作为欲望的原因",
        "canonical_name": "objet a (1964-1966)",
        "aliases": ["对象a 1964", "objet a S11"],
        "language": "mul",
        "concept_id": "concept.objet-a",
        "period": "1964-1966",
        "period_label": "S11–S12 时期（四个基本概念）",
        "state_label": "a 作为欲望的原因（cause du désir），与缺失、阉割绑定",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "sources": ["doc.lacan.seminar-3"],
        "passages": ["passage.ST1.unknown.L01.P0010"],
        "supersedes": "state.objet-a.1955-1958",
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "tags": ["概念/对象a", "分期/1964-1966"],
    }, """# objet a — 1964–1966

## 本阶段的表述

a 作为**欲望的原因**，而非欲望的对象；与缺失（manque）、阉割绑定。

## ⚠️ SOURCE_TRACE_INCOMPLETE

本卡 `period: 1964-1966`，但当前 `passages` 指向的是 **S3（1955–1956）**
的页级证据 `passage.ST1.unknown.L01.P0010`。二者**时期不匹配**。

- 缺哪一环：与 1964–1966 对应的 Passage
- 为什么缺：本地语料**没有 S11 底本**（实测 seminar 覆盖仅 S1/S3/S5/S10/S20/S23）
- 正确做法：不得用 S3 的段落去支撑 1964–1966 的判断；
  待 S11 导入后替换 `passages`
- 本条故意保留为反例：**Schema 允许表达「时期与证据不匹配」这种状态**，
  校验器把它报为 `SOURCE_TRACE_INCOMPLETE`，而不是假装完整

## 改写了哪一期

- [[state.objet-a.1955-1958]] —— 本阶段改写的前一阶段（`redefines` 关系的呈现层对应）
""")
    n += 1

    write_note("04_Concepts/States/state.sinthome.1974-1976.md", {
        "id": "state.sinthome.1974-1976",
        "type": "concept_state",
        "title": "sinthome — 1974–1976：把 RSI 打结的第四项",
        "canonical_name": "sinthome (1974-1976)",
        "aliases": ["圣状 1974", "sinthome S23"],
        "language": "mul",
        "concept_id": "concept.sinthome",
        "period": "1974-1976",
        "period_label": "S23 圣状时期",
        "state_label": "圣状作为第四项，使 RSI 三界结成波罗米结",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "sources": ["doc.lacan.seminar-23"],
        "passages": [],
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "tags": ["概念/圣状", "分期/1974-1976"],
    }, """# sinthome — 1974–1976

## 本阶段的表述

圣状作为**第四项**，把 R/S/I 三界打成波罗米结；症状由此从
「待解释的密文」变为「使主体得以维系的结构性补充」。

## ⚠️ SOURCE_TRACE_INCOMPLETE

`passages` 为空 —— 尚未在 S23 中英对照本中定位到具体段落。

- 缺哪一环：Passage
- 为什么缺：S23 中英对照本尚未做结构解析（Phase 2 S3/S4 任务）
- 当前只能支撑到 `doc.lacan.seminar-23`（Document 级），到不了 Passage 级
""")
    n += 1

    # ---------------- 07_Cases ----------------
    write_note("07_Cases/case.schreber.md", {
        "id": "case.schreber",
        "type": "case",
        "title": "Schreber 个案（Daniel Paul Schreber）",
        "canonical_name": "Schreber case",
        "aliases": ["施雷伯", "Schreber", "Memoirs of My Nervous Illness"],
        "language": "mul",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "passages": ["passage.ST1.unknown.L01.P0010"],
        "sources": ["doc.lacan.seminar-3"],
        "related": ["structure.psychosis", "concept.forclusion"],
        "tags": ["个案/Schreber", "领域/精神病"],
    }, """# Schreber 个案

## 拉康的用法（S3，法文底本 p.10）

法文底本第 10 页（PDF 页）讨论弗洛伊德如何解读 Schreber 的《回忆录》。
原文摘录见 [`passage.ST1.unknown.L01.P0010`](../02_Lacan_Seminars/ST1_Fixture/passage.ST1.unknown.L01.P0010.md)。

> 引用时务必注意：该页属 S3，但**具体课次日期未确证**，
> 因此引用应写「S3 法文底本 p.10」，不得写成「S3 第 N 课」。
""")
    n += 1

    write_note("07_Cases/case.bourbon-brigitte.md", {
        "id": "case.bourbon-brigitte",
        "type": "case",
        "title": "布里吉特·布尔邦小姐的临床演示",
        "canonical_name": "Brigitte Bourbon clinical presentation",
        "aliases": ["布尔邦小姐", "B小姐", "布里吉特·布尔邦"],
        "language": "zh",
        "source_id": "doc.bourbon.presentation",
        "source_path": fx["case"]["origin_rel_path"],
        "source_hash": fx["case"]["origin_sha256"],
        "source_type": "case_meeting",
        "authority_level": "L3",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "passages": ["passage.ST1.unknown.L01.P0004"],
        "related": ["structure.psychosis"],
        "tags": ["个案/临床演示", "领域/精神病"],
    }, """# 布里吉特·布尔邦小姐的临床演示

中文记录，433 段。`source_hash` 与 inventory 一致。

## 为何选作测试数据

它是语料中少见的**对话体临床材料**（拉康与 B 小姐的往返），
可以检验 Passage 是否能承载「说话人 + 轮次」这类结构，
而不只是连续散文。

表达「被赋予价值（valoriser）」与「需要被承认」的段落见
[`passage.ST1.unknown.L01.P0004`](passage.ST1.unknown.L01.P0004.md)。
""")
    n += 1

    # ---------------- 08_Topology ----------------
    write_note("08_Topology_Mathemes/Topology/topology.borromean-knot.md", {
        "id": "topology.borromean-knot",
        "type": "topology",
        "title": "波罗米结（nœud borroméen）",
        "canonical_name": "Borromean knot",
        "aliases": ["波罗米结", "borromean", "nœud borroméen", "三环结"],
        "language": "mul",
        "fr": "nœud borroméen",
        "en": "Borromean knot",
        "zh": "波罗米结",
        "authority_level": "L2",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "tags": ["拓扑/波罗米结"],
    }, """# 波罗米结（nœud borroméen）

三个环彼此相扣，去掉任意一个，另外两个即散开。
拉康用它建模 R（实在界）/ S（象征界）/ I（想象界）的相互依存关系。

## 与概念的关联

- 圣状（sinthome）作为**第四项**使三环成结 →
  `concept.sinthome`、`state.sinthome.1974-1976`
- 载体期：S23（1975–1976）
""")
    n += 1

    # ---------------- 11_Thinkers ----------------
    write_note("11_Thinkers/Psychoanalysts/person.jacques-lacan.md", {
        "id": "person.jacques-lacan",
        "type": "psychoanalyst",
        "title": "Jacques Lacan（雅克·拉康）",
        "canonical_name": "Jacques Lacan",
        "aliases": ["拉康", "Jacques Lacan", "J. Lacan", "雅克·拉康"],
        "language": "mul",
        "authority_level": "L0",
        "review_status": "reviewed", "reviewed_by": "human:coffee",
        "reviewed_at": "2026-09-20T00:00:00Z",
        "generated_by": "human:coffee",
        "status": "active",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "tags": ["人物/拉康"],
    }, """# Jacques Lacan（1901–1981）

法国精神分析家。本知识库的 L1 一手来源作者。

## 相关内容

- 研讨班：`seminar.ST1`（fixture）、`seminar.S23`（语料）
- 概念：`concept.objet-a`、`concept.sinthome`
""")
    n += 1

    write_note("04_Concepts/concept.sinthome.md", {
        "id": "concept.sinthome",
        "type": "concept",
        "title": "sinthome（圣状）",
        "canonical_name": "sinthome",
        "aliases": ["圣状", "sinthome", "synthome"],
        "language": "mul",
        "fr": "sinthome",
        "en": "sinthome",
        "zh": "圣状",
        "authority_level": "L2",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "concept_states": ["state.sinthome.1974-1976"],
        "related": ["term.fr.sinthome", "topology.borromean-knot"],
        "tags": ["概念/圣状"],
    }, """# sinthome（圣状）

> **本卡不承载定义。** 定义见 [`state.sinthome.1974-1976`](States/state.sinthome.1974-1976.md)。

## 各阶段状态

| 分期 | 状态卡 | 该阶段的表述 |
|---|---|---|
| 1974-1976 | [`state.sinthome.1974-1976`](States/state.sinthome.1974-1976.md) | 圣状作为第四项使 RSI 成结 |

## 分期提示

S23 之前「症状（symptôme）」与 S23 的「圣状（sinthome）」
**不是同一个概念状态**，不得合并叙述。史前阶段的状态卡待补。
""")
    n += 1

    write_note("04_Concepts/concept.forclusion.md", {
        "id": "concept.forclusion",
        "type": "concept",
        "title": "forclusion（父之名的脱落 / 除权）",
        "canonical_name": "forclusion",
        "aliases": ["脱落", "除权", "forclusion", "Verwerfung", "foreclosure"],
        "language": "mul",
        "fr": "forclusion",
        "en": "foreclosure",
        "zh": "脱落（亦有译「除权」）",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "concept_states": ["state.forclusion.1955-1958"],
        "related": ["structure.psychosis", "case.schreber", "term.fr.sinthome"],
        "tags": ["概念/脱落", "领域/精神病"],
    }, """# forclusion（父之名的脱落）

> **本卡不承载定义。** 定义见 [`state.forclusion.1955-1958`](States/state.forclusion.1955-1958.md)。

## 各阶段状态

| 分期 | 状态卡 | 该阶段的表述 |
|---|---|---|
| 1955-1958 | [`state.forclusion.1955-1958`](States/state.forclusion.1955-1958.md) | 父之名被除权，精神病结构的机制 |

## 术语提示

中文译名分歧大：脱落 / 除权 / 排除。法文 *forclusion* 对应弗洛伊德的
*Verwerfung*。英文作 *foreclosure*。

> ⚠️ 概念辨析：*forclusion*（脱落，精神病机制）≠ *Verneinung*（否认/否定）
> ≠ *Verleugnung*（否弃）≠ *Verdrängung*（压抑）。四者在中文里都容易被
> 笼统译成「否认」，必须分开立卡。
""")
    n += 1

    write_note("04_Concepts/States/state.forclusion.1955-1958.md", {
        "id": "state.forclusion.1955-1958",
        "type": "concept_state",
        "title": "forclusion — 1955–1958：父之名被除权",
        "canonical_name": "forclusion (1955-1958)",
        "aliases": ["脱落 1955", "forclusion S3"],
        "language": "mul",
        "concept_id": "concept.forclusion",
        "period": "1955-1958",
        "period_label": "S3 精神病时期",
        "state_label": "父之名（Nom-du-Père）被除权，能指秩序中留下空洞",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "sources": ["doc.lacan.seminar-3"],
        "passages": ["passage.ST1.unknown.L01.P0010"],
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "tags": ["概念/脱落", "分期/1955-1958"],
    }, """# forclusion — 1955–1958

## 本阶段的表述

父之名（*Nom-du-Père*）**从未被登记进象征界**，故不是「被压抑后返回」，
而是「根本没有被写进去」——这是拉康区分精神病与神经症的核心机制。

## ⚠️ SOURCE_TRACE_INCOMPLETE

`passages` 指向 `passage.ST1.unknown.L01.P0010`，该页讨论 Schreber 与
弗洛伊德的解码方法，是**本阶段核心个案的上下文**，但**不是 forclusion
定义的直接论述段**。

- 缺哪一环：直接论述 forclusion 的 Passage
- 为什么缺：本地 S3 法文底本未做课次级解析，无法定位到具体论述段
- 处置：先以页级证据支撑，并显式标注不是直接定义出处；待 S3 结构解析后替换
""")
    n += 1

    write_note("04_Concepts/States/state.objet-a.1955-1958.md", {
        "id": "state.objet-a.1955-1958",
        "type": "concept_state",
        "title": "objet a — 1955–1958：想象的他人 / 小他者",
        "canonical_name": "objet a (1955-1958)",
        "aliases": ["对象a 1955", "objet a S3-S5"],
        "language": "mul",
        "concept_id": "concept.objet-a",
        "period": "1955-1958",
        "period_label": "S3–S5 时期",
        "state_label": "a 与想象的他人（petit autre）交织，尚未成为欲望的原因",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "sources": ["doc.lacan.seminar-3"],
        "passages": ["passage.ST1.unknown.L01.P0010"],
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "tags": ["概念/对象a", "分期/1955-1958"],
    }, """# objet a — 1955–1958

## 本阶段的表述

此期 a 尚未成为后来的「欲望的原因」，主要在想象界的关系中活动，
与小写的他人（*petit autre*）交织。**不要用后期的定义回填此期。**

## ⚠️ SOURCE_TRACE_INCOMPLETE

`passages` 指向 `passage.ST1.unknown.L01.P0010`。该页讨论的是弗洛伊德对 Schreber
的解读，**并非 objet a 的直接论述** —— 它是本阶段的**上下文证据**，
不是「a 在此期的定义」的直接证据。

- 缺哪一环：直接论述 objet a 的 Passage
- 为什么缺：本地无 S4/S5 底本；S3 中亦未定位到直接论述段
- 处置：保留为 L1 上下文证据，并显式标注不是直接定义出处
""")
    n += 1

    write_note("04_Concepts/States/state.objet-a.1972-1973.md", {
        "id": "state.objet-a.1972-1973",
        "type": "concept_state",
        "title": "objet a — 1972–1973：与享乐、剩余享乐相关",
        "canonical_name": "objet a (1972-1973)",
        "aliases": ["对象a 1972", "objet a S20"],
        "language": "mul",
        "concept_id": "concept.objet-a",
        "period": "1972-1973",
        "period_label": "S20 Encore 时期",
        "state_label": "a 与 plus-de-jouir（剩余享乐）及性分化公式相关",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "sources": ["doc.lacan.seminar-23"],
        "passages": [],
        "supersedes": "state.objet-a.1964-1966",
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "tags": ["概念/对象a", "分期/1972-1973"],
    }, """# objet a — 1972–1973

## 本阶段的表述

a 与 *plus-de-jouir*（剩余享乐）关联，并进入性分化公式的位置。

## ⚠️ SOURCE_TRACE_INCOMPLETE

`passages` 为空。

- 缺哪一环：Passage
- 为什么缺：本地**无 S20 底本**（虽有 S20 Encore 中英对照本，
  但未做结构解析，无法定位到具体课次与段落）
- 注意：`sources` 暂记 `doc.lacan.seminar-23` 仅为占位，
  **不能作为本阶段（1972–1973）的证据**；正确来源应为 S20
- 待补：S20 结构解析完成后替换
""")
    n += 1

    write_note("06_Clinical/Structures/structure.psychosis.md", {
        "id": "structure.psychosis",
        "type": "clinical_structure",
        "title": "精神病结构（psychose）",
        "canonical_name": "psychosis",
        "aliases": ["精神病", "psychose", "psychosis"],
        "language": "mul",
        "fr": "psychose",
        "en": "psychosis",
        "zh": "精神病",
        "authority_level": "L2",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "sources": ["doc.lacan.seminar-3"],
        "related": ["case.schreber", "topology.borromean-knot"],
        "tags": ["临床/精神病"],
    }, """# 精神病结构（psychose）

> **非诊断声明**：本卡是理论与临床结构的整理，**不构成诊断标准**，
> 也不用于临床诊断。拉康派的「结构」指主体在能指秩序中的位置，
> 不是症状清单。

## 两类材料不得混用

本地语料同时包含两条进路：

- **拉康派结构进路**：`doc.lacan.seminar-3`（S3 精神病）、
  `doc.arcachon.2001`（阿卡雄对话会·日常精神病）
- **精神病学描述进路**：Karl Jaspers《General Psychopathology》、
  Henri Ey、Clérambault 作品集（均为 L2/L3）

引用时不得用精神病学描述冒充拉康派结构判断。

## 相关

- 个案：`case.schreber`、`case.bourbon-brigitte`
- 拓扑：`topology.borromean-knot`
""")
    n += 1

    print(f"写入笔记 {n} 篇")

    # ---------------- Passage（真实引文，可逐字复核） ----------------
    # 引文取自 00_System/_fixtures/S3 PSYCHOSES.pdf 第 10 页文字层，
    # 换行与多余空格已归一化，词句未改动。
    # 逐字引文：撇号必须是源文件的排版撇号 U+2019（’），不是 ASCII直引号（'）。
    # 这是本项目第一版引文校验抓到的真实缺陷 —— 引用必须与底本逐字符一致，
    # 不能做「看起来一样」的归一化。
    # 复核：00_System/_fixtures/S3 PSYCHOSES.pdf 第 10 页。
    s3_quote = (
        "…mais que FREUD prenne le livre d\u2019un paranoïaque - ce livre de SCHREBER "
        "dont il recommande bien platoniquement la lecture au moment où il écrit "
        "son œuvre, car il dit « ne manquez pas de le lire avant de me lire » - "
        "FREUD prend donc ce livre des Mémoires d\u2019un malade nerveux et il donne "
        "un déchiffrage champolionesque, un déchiffrage à la façon dont on "
        "déchiffre des hiéroglyphes"
    )
    write_note("01_Sources/Documents/doc.bourbon.presentation.md", {
        "id": "doc.bourbon.presentation",
        "type": "document",
        "title": "布里吉特·布尔邦小姐的临床演示（中文记录）",
        "canonical_name": "Présentation de malade: Mlle Brigitte Bourbon",
        "aliases": ["布尔邦临床演示", "B小姐临床演示"],
        "language": "zh",
        "source_id": "source.local.desktop-lacan",
        "source_path": fx["case"]["origin_rel_path"],
        "source_hash": fx["case"]["origin_sha256"],
        "source_type": "case_meeting",
        "authority_level": "L3",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "tags": ["文献/临床演示", "领域/精神病"],
    }, """# 布尔邦小姐的临床演示

中文记录稿，433 段，对话体（拉康与患者的往返轮次）。

## 权威层级说明

`authority_level: L3` —— 这是**中文记录/整理稿**，
不是拉康的法文原话，也不是瑟伊版定本。
引用时必须声明这一点，不得让它冒充 L1 一手断言。

## 溯源

- 文件 sha256 与 `_data/corpus_inventory.json` 中该文件一致
- 定位到段级（`paragraph_index`），无页码（DOCX 无页码概念）
""")
    n += 1

    write_note("02_Lacan_Seminars/ST1_Fixture/passage.ST1.unknown.L01.P0010.md", {
        "id": "passage.ST1.unknown.L01.P0010",
        "type": "passage",
        "title": "S3 · p.10 · 弗洛伊德对 Schreber《回忆录》的解码",
        "canonical_name": "S3 p.10 Freud Schreber déchiffrage",
        "aliases": ["S3 p10", "S3 Schreber 段落"],
        "language": "fr",
        "source_id": "doc.lacan.seminar-3",
        "source_hash": s3["origin_sha256"],
        "seminar": "ST1",
        "session_date": "1955-01-01",
        "session_date_precision": "year",
        "structure_path": "S3/page/010",
        "page_from": 10,
        "page_to": 10,
        "paragraph_index": None,
        "edition": "法文底本（工作扫描件）",
        "authority_level": "L1",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "tags": ["Passage/S3"],
    }, f"""# S3 · p.10

> **证据单元 ID 形态说明**：本 Passage 用 `page010` 而非规范形态
> `passage.S3.<session_date>.P010`，因为**课次日期尚未确定**。
> 规范 ID 需要 Session 级结构；在解析出课次前，不得伪造日期来凑 ID。
> 这是刻意的：ID 是一种断言，不知道就不能写。

## 引文（法文，逐字）

> {s3_quote}

## 溯源

| 环节 | 值 |
|---|---|
| Passage | `passage.ST1.unknown.L01.P0010` |
| Session | `session.ST1.unknown`（日期未确证） |
| Seminar | `seminar.ST1` |
| Document | `doc.lacan.seminar-3` |
| Edition | 法文底本（工作扫描件） |
| Source | `source.local.desktop-lacan` |
| 文件 sha256 | `{s3['origin_sha256'][:16]}…` |
| 定位 | PDF 第 10 页（`page_from: 10`） |

## ⚠️ trace_status: SOURCE_TRACE_INCOMPLETE

Document / Edition / Source / 页码 均可确证；
**Session 日期不可**。因此整条链未达 COMPLETE。

复核方法：打开 `00_System/_fixtures/S3 PSYCHOSES.pdf` 第 10 页，
引文应与上文逐字一致。
""")
    n += 1

    write_note("07_Cases/passage.ST1.unknown.L01.P0004.md", {
        "id": "passage.ST1.unknown.L01.P0004",
        "type": "passage",
        "title": "布尔邦临床演示 · 第 4 轮 · 「人们想赋予我价值」",
        "canonical_name": "Bourbon demonstration P0004 passage",
        "aliases": ["布尔邦 P004"],
        "language": "zh",
        "source_id": "doc.bourbon.presentation",
        "source_hash": fx["case"]["origin_sha256"],
        "seminar": "ST1",
        "session_date": "1955-01-01",
        "session_date_precision": "year",
        "structure_path": "bourbon/turn/004",
        "page_from": None,
        "page_to": None,
        "paragraph_index": 3,
        "authority_level": "L3",
        "review_status": "needs_review",
        "generated_by": "human:coffee",
        "status": "draft",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "schema_version": "1.0.0",
        "trace_status": "SOURCE_TRACE_INCOMPLETE",
        "tags": ["Passage/临床演示"],
    }, """# 布尔邦临床演示 · 第 4 轮

## 引文（中文，逐字，含说话人）

> **B小姐**—— 是的，是对您说的。人们想赋予我价值（valoriser）。
>
> **拉康**—— 人们想赋予您价值？

（源文件 `布里吉特·布尔邦小姐的临床演示.docx` 第 4–5 段）

## 为何单独立为一个 Passage

这份材料是**对话体**。Passage 的边界取「一个完整轮次」，
而不是字数。这正是禁止固定 token 切分的具体体现：
按 token 切会把「B小姐说」和「拉康回应」切开，论证单位就没了。

## 溯源

| 环节 | 值 |
|---|---|
| Passage | `passage.ST1.unknown.L01.P0004` |
| Document | `doc.bourbon.presentation` |
| 定位 | DOCX 第 4–5 段（`paragraph_index: 3`） |
| 文件 sha256 | `%s…` |
| 页码 | 无（DOCX 无页码，`page_from/page_to` 为 null） |
| trace_status | `SOURCE_TRACE_INCOMPLETE` —— 缺 Session 日期 |

> 注意：本材料 `authority_level: L3`（中文记录/整理稿），
> 不是拉康的法文原话。引用时必须声明这一点，
> 不得让它冒充 L1 一手断言。
""" % fx["case"]["origin_sha256"][:16])
    n += 1

    print(f"写入 Passage 2 篇，累计 {n} 篇")

    # ---------------- relations ----------------
    os.makedirs(REL, exist_ok=True)
    main_rels = [
        {
            "relation_id": "rel.000001",
            "subject": "seminar.ST1",
            "predicate": "appears_in",
            "object": "case.schreber",
            "evidence": {"passage_id": ["passage.ST1.unknown.L01.P0010"],
                          "assertion_type": "explicit",
                          "note": "S3 法文底本 p.10 讨论弗洛伊德对 Schreber《回忆录》的解读"},
            "confidence": 0.95, "review_status": "reviewed",
            "authority_level": "L1",
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
            "created_by": "human:coffee", "schema_version": "1.0.0",
        },
    ]
    with open(os.path.join(REL, "relations.jsonl"), "w", encoding="utf-8") as f:
        for r in main_rels:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    cand_rels = [
        {
            "relation_id": "rel.000003",
            "subject": "term.fr.jouissance",
            "predicate": "translates_as",
            "object": "trans.mul.jouissance",
            "evidence": {"passage_id": [], "assertion_type": "editorial",
                          "note": "译法条目由人工建立；assertion_type=editorial 不要求 passage。未审核，故留候选库。"},
            "confidence": 0.8, "review_status": "candidate",
            "authority_level": "L3",
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
            "created_by": "human:coffee", "schema_version": "1.0.0",
        },
        {
            "relation_id": "rel.000002",
            "subject": "state.objet-a.1964-1966",
            "predicate": "redefines",
            "object": "state.objet-a.1955-1958",
            "evidence": {"passage_id": ["passage.ST1.unknown.L01.P0010"],
                          "assertion_type": "inferred",
                          "note": "占位：真实改写证据需 S11 Passage，当前 SOURCE_TRACE_INCOMPLETE，故不进主库"},
            "confidence": 0.55, "review_status": "candidate",
            "authority_level": "L1",
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
            "created_by": "human:coffee", "schema_version": "1.0.0",
        },
        {
            "relation_id": "rel.c000001",
            "subject": "concept.objet-a",
            "predicate": "formalized_as",
            "object": "concept.sinthome",
            "evidence": {"passage_id": [], "assertion_type": "inferred",
                          "note": "缺证据：尚未在 S23 中定位到把 objet a 形式化为圣状的段落；本地无 S23 结构解析，无法给段号。故仅作假设，不进主库。"},
            "confidence": 0.3, "review_status": "candidate",
            "authority_level": "L4",
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
            "created_by": "ai:deepseek/test-run", "schema_version": "1.0.0",
        },
        {
            "relation_id": "rel.c000002",
            "subject": "structure.psychosis",
            "predicate": "topological_model",
            "object": "topology.borromean-knot",
            "evidence": {"passage_id": [], "assertion_type": "inferred",
                          "note": "缺证据：仅依据 concept-state.sinthome.1974-1976 的二手概述，未取得 S23 原文段号。升主库前必须先补 passage_id。"},
            "confidence": 0.45, "review_status": "candidate",
            "authority_level": "L4",
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z",
            "created_by": "ai:deepseek/test-run", "schema_version": "1.0.0",
        },
    ]
    with open(os.path.join(REL, "relations.candidate.jsonl"), "w", encoding="utf-8") as f:
        for r in cand_rels:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    open(os.path.join(REL, "relations.rejected.jsonl"), "w").close()
    print(f"写入 relations: {len(main_rels)} 主库 / {len(cand_rels)} 候选")


if __name__ == "__main__":
    main()
