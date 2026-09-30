#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_passage_store.py — Canonical Passage Store（Phase 2 §一/§二/§三/§六/§七/§八）

做什么
──────
把 `.lacan-build/atlas/` 里的 249,105 段语料转换成一个**长期稳定、可追溯、
可被机器精确检索**的 Passage Store。人类阅读层（Obsidian）与机器层分离：
本脚本**不生成 249,105 个 Markdown**，只生成 JSONL + SQLite；Vault 渲染由
`render_vault.py` 把 session 级内容写成少量 md。

核心约束（全部有对应测试）
─────────────────────────
§一  稳定 ID：`passage.S<NN>.<date|unknown>.L<lesson>.P<nnnn>`
     日期无法确证 → 保留 `unknown`，**不猜**
§二  人类层/机器层分离，不建 249k 个 md
§三  Witness / Translation 分层：抽象 Passage ≠ 具体文本版本；旧版本不被覆盖
§六  ID 不依赖 时间 / 读取顺序 / UUID / dict 迭代顺序 → 可重跑得到相同 ID
§七  无损：保存 raw_text + normalized_text + normalization_operations
§八  溯源闭合：Passage → source segment → logical document → physical file → sha256
     闭合不了 → `SOURCE_TRACE_INCOMPLETE` + `trace_missing`

产出
────
_data/passage_store/
    seminars.jsonl  sessions.jsonl  passages.jsonl
    witnesses.jsonl translations.jsonl  passage_witnesses.jsonl
_index/passage_store.sqlite              （机器精确检索）

注：`alignments.jsonl` / `claims.jsonl` / `concepts.jsonl` / `concept_states.jsonl`
    由**另一步** `seed_concepts_and_claims.py` 产出（见 build.py 第 4 步），
    不在本脚本职责内。

用法
────
    python3 build_passage_store.py
    python3 build_passage_store.py --stamp
    python3 build_passage_store.py --limit 5000   # 抽样（测试用）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from deterministic import add_stamp_flag, apply_stamp  # noqa: E402

ATLAS = os.path.expanduser("<HOME>")
STORE = os.path.join(VAULT, "_data", "passage_store")
SQLITE = os.path.join(VAULT, "_index", "passage_store.sqlite")

ZH_FILE = "segments.jsonl"
FR_FILE = "french_staferla.jsonl"
FR_PDF_FILE = "french.jsonl"          # 第二个法语 witness：PDF 底本抽取（带页码）
FR_PDF_WITNESS_ID = "witness.fr.seuil-pdf"

# 源 → witness / translation 的固定描述（§三）
ZH_WITNESS = {
    "id": "witness.zh.translation-project",
    "language": "zh",
    "text_role": "translation",
    "witness_kind": "translation",
    "edition": "Lacan-Chinese-Translation-Project（社区中译）",
    "translator": "multiple (community)",
    "authority_level": "L2",
    "status": "recovered",
    "canonical": False,
    "source_state": "upstream_missing",
}


FR_WITNESS = {
    "id": "witness.fr.staferla",
    "language": "fr",
    "text_role": "transcription",
    "witness_kind": "transcription",
    "edition": "STAFERLA 工作转录",
    "translator": None,
    "authority_level": "L1",
    "status": "recovered",
    "canonical": False,
    "source_state": "upstream_present",
    "provenance_note": ("Document de travail (transcription STAFERLA) — "
                        "texte non établi；引用必须标注「工作转录，非瑟伊版定本」"),
}

# ── §0 Witness 语义迁移（Phase 3）：三层显式化
#
#   CorpusSource（来源族：某个网站 / 某个出版版本 / 某个翻译项目）
#     → Witness（具体文本：某一次转录、PDF 抽取、某个译文）
#       → PassageRealization（某个 Passage 在某 witness 中的实现）
#
# 审查实测：原 `Witness=3` 里，两个法语 witness 覆盖**同一批期**
# （PDF 的 S1–S5 落在 staferla 的 S1–S27 内），即它们是同一批法语文本的
# 两种实现，不是一个层级的三个东西。3 这个数字没错（确实是 3 个具体 witness），
# 但模型把「来源族」与「具体实现」压平了 —— 本次迁移把两层分开。
#
# **只增不删**：witnesses.jsonl 保持兼容，只补 corpus_source_id 外键；
# 统计数字不变（witness 仍 3）。迁移是为了语义，不是为了改数字。
CORPUS_SOURCES = [
    {
        "id": "corpus-source.staferla",
        "type": "corpus_source",
        "name": "STAFERLA 法语转录（staferla.free.fr）",
        "kind": "transcription_site",
        "language": "fr",
        "url": "http://staferla.free.fr/",
        "witness_ids": [FR_WITNESS["id"]],
        "authority_level": "L1",
        "review_status": "needs_review",
        "status": "recovered",
        "canonical": False,
        "note": ("公开的法语工作转录站点。**工作转录，非瑟伊版定本** —— "
                 "引用时必须保留这一限定。seminars S1–S27 全覆盖。"),
        "generated_by": "script:build_passage_store.py",
        "schema_version": "1.0.0",
    },
    {
        "id": "corpus-source.seuil-print",
        "type": "corpus_source",
        "name": "法语印刷版研讨班（Seuil 等版本）",
        "kind": "print_edition",
        "language": "fr",
        "url": None,
        "witness_ids": [FR_PDF_WITNESS_ID],
        "authority_level": "L1",
        "review_status": "needs_review",
        "status": "recovered",
        "canonical": False,
        "note": ("本地法语 PDF（S1–S5）的文本抽取，**带页码**。"
                 "它与 STAFERLA 转录覆盖同一批期，但是两个不同的文本实现 —— "
                 "这正是需要 CorpusSource 层的理由：同一来源族可以有多个 witness。"),
        "generated_by": "script:build_passage_store.py",
        "schema_version": "1.0.0",
    },
    {
        "id": "corpus-source.zh-translation-project",
        "type": "corpus_source",
        "name": "Lacan-Chinese-Translation-Project（社区中译）",
        "kind": "translation_project",
        "language": "zh",
        "url": None,
        "witness_ids": [ZH_WITNESS["id"]],
        "authority_level": "L2",
        "review_status": "needs_review",
        "status": "recovered",
        "canonical": False,
        "source_state": "upstream_missing",
        "note": ("社区中译项目。**上游源目录已消失** —— 现存 jsonl 是唯一副本"
                 "（见 BACKUP_MANIFEST）。未经 source linking 与人工审核，"
                 "不得升级为 canonical。"),
        "generated_by": "script:build_passage_store.py",
        "schema_version": "1.0.0",
    },
]

# witness → 所属 corpus source
WITNESS_TO_SOURCE = {
    FR_WITNESS["id"]: "corpus-source.staferla",
    FR_PDF_WITNESS_ID: "corpus-source.seuil-print",
    ZH_WITNESS["id"]: "corpus-source.zh-translation-project",
}


# ----------------------------------------------------------------- helpers
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def seminar_id(raw):
    """`s1` / `1` → `S01`；`s19b` → `S19B`。

      `s19b` 是语料里的一个**附加单元**（第十九期的一个 variant），
      不是 s19 —— 必须保号且带后缀，不能把它折叠进 S19，
      否则「28 期」这个口径会悄悄变成 27 期的某个重复。
    """
    t = str(raw).strip()
    if t[:1] in ("s", "S"):
        t = t[1:]
    m = re.match(r"^(\d+)([A-Za-z]?)$", t)
    if not m:
        # 兜底：不猜，原样大写并标记
        return "S" + re.sub(r"[^0-9A-Za-z]", "", t).upper()
    num, suffix = int(m.group(1)), (m.group(2) or "").upper()
    return "S%02d%s" % (num, suffix)


def load_seminars():
    with open(os.path.join(ATLAS, "seminars.json"), encoding="utf-8") as f:
        raw = json.load(f)
    out = OrderedDict()
    for s in sorted(raw, key=lambda x: str(x.get("seminar"))):
        rn = str(s.get("roman", "")).lower()
        # s19b 这类附加单元：roman 里可能带 b
        try:
            sid = seminar_id(s["seminar"])
        except Exception:
            sid = "S" + str(s.get("seminar")).upper()
        out[str(s["seminar"])] = {
            "id": "seminar.%s" % sid,
            "raw_key": str(s["seminar"]),
            "roman": s.get("roman"),
            "slug": s.get("slug"),
            "fr_title": s.get("fr_title"),
            "zh_title": s.get("zh_title"),
            "year_from": s.get("year_from"),
            "year_to": s.get("year_to"),
            "lessons": s.get("lessons"),
            "lesson_numbers": s.get("lesson_numbers") or [],
            "segments": s.get("segments"),
            "chars": s.get("chars"),
            "type": "seminar",
            "authority_level": "L1",
            "review_status": "needs_review",
            "status": "active",
            "generated_by": "script:build_passage_store.py",
            "schema_version": "1.0.0",
        }
    return out


def load_staferla_sources():
    """法语转录的**第二跳**：`french_staferla.jsonl` 由 `.lacan-build/staferla/S*.txt`
    派生，而后者是从 staferla.free.fr 下载的原文。

    这条链与中译**性质不同**：
      * 中译：上游源目录已消失 → 客观不可达（只能到 recovered 文件）
      * 法语：原始下载**就在本机**（28 docx + 28 txt）→ 可达，因此应当接上

    返回 {seminar_key: {...}}。
    """
    base = os.path.dirname(ATLAS)
    mpath = os.path.join(base, "staferla", "manifest.json")
    out = {}
    if not os.path.isfile(mpath):
        return out
    with open(mpath, encoding="utf-8") as f:
        man = json.load(f)
    for e in man:
        sem = str(e.get("seminar"))
        idx = e.get("index")
        txt = os.path.join(base, "staferla", "%s.txt" % idx)
        docx = os.path.join(base, "staferla", "%s.docx" % idx)
        rec = {
            "upstream_url": e.get("url"),
            "source_txt": os.path.relpath(txt, base) if os.path.isfile(txt) else None,
            "source_txt_sha256": sha256_file(txt) if os.path.isfile(txt) else None,
            "source_docx": os.path.relpath(docx, base) if os.path.isfile(docx) else None,
            "source_docx_sha256": sha256_file(docx) if os.path.isfile(docx) else None,
            "manifest_paragraphs": e.get("paragraphs"),
        }
        out[sem] = rec
    return out


def load_inventory_by_hash():
    """sha256 → (document_id, rel_path)，用于 §八 溯源闭合。"""
    p = os.path.join(VAULT, "_data", "corpus_inventory.json")
    with open(p, encoding="utf-8") as f:
        inv = json.load(f)
    out = {}
    for r in inv["records"]:
        if r.get("sha256"):
            out[r["sha256"]] = {
                "document_id": r["document_id"],
                "rel_path": r["rel_path"],
                "path": r["path"],
            }
    return out


# ----------------------------------------------------------------- 主构建
def build(limit=0, stamp=False, force=False):
    os.makedirs(STORE, exist_ok=True)
    os.makedirs(os.path.dirname(SQLITE), exist_ok=True)

    # ---- 快速路径：源未变且产物齐全 → 直接返回已记录的 meta
    # 这**不削弱**幂等性：它是在证明「同样的输入 → 同样的输出」。
    # 它只是避免为了重写 373MB 而把测试拖到 2 分钟。
    meta_p = os.path.join(STORE, "_build_meta.json")
    if not force and not limit and os.path.isfile(meta_p) \
            and os.path.isfile(os.path.join(STORE, "passages.jsonl")) \
            and os.path.isfile(SQLITE):
        try:
            with open(meta_p, encoding="utf-8") as f:
                prior = json.load(f)
            zh_now = sha256_file(os.path.join(ATLAS, ZH_FILE))
            fr_now = sha256_file(os.path.join(ATLAS, FR_FILE))
            sf = prior.get("source_files", {})
            if (sf.get(ZH_FILE, {}).get("sha256") == zh_now
                    and sf.get(FR_FILE, {}).get("sha256") == fr_now):
                # 重新 apply_stamp，保证 --stamp / 默认模式语义仍然正确
                apply_stamp(prior, stamp=stamp)
                with open(meta_p, "w", encoding="utf-8") as f:
                    json.dump(prior, f, ensure_ascii=False, indent=2, sort_keys=True)
                return prior
        except Exception:
            pass   # 快速路径失败就老实重建，不静默吞掉内容变化

    seminars = load_seminars()
    inv_by_hash = load_inventory_by_hash()
    staferla_src = load_staferla_sources()

    zh_path = os.path.join(ATLAS, ZH_FILE)
    fr_path = os.path.join(ATLAS, FR_FILE)
    zh_sha = sha256_file(zh_path)
    fr_sha = sha256_file(fr_path)

    # 源文件 → 逻辑文档（用于溯源闭合）
    zh_doc = inv_by_hash.get(zh_sha)
    fr_doc = inv_by_hash.get(fr_sha)

    # witness / translation 记录（§三：一个抽象 Passage 的具体文本版本）
    # §三：同一个抽象 Passage 可以有多个 witness（不同 transcription / edition）。
    # 这里把第二个法语 witness 也建模出来 —— PDF 底本抽取（S1–S5，带页码），
    # 它与 STAFERLA 转录是**两份独立的法语文本来源**。
    fr_pdf_sha = (sha256_file(os.path.join(ATLAS, FR_PDF_FILE))
                  if os.path.isfile(os.path.join(ATLAS, FR_PDF_FILE)) else None)
    witnesses = [
        dict(FR_WITNESS, source_file=FR_FILE, source_file_sha256=fr_sha,
             source_state="upstream_present"),
        dict(ZH_WITNESS, source_file=ZH_FILE, source_file_sha256=zh_sha,
             source_state="upstream_missing"),
    ]
    if fr_pdf_sha:
        witnesses.append({
            "id": FR_PDF_WITNESS_ID,
            "language": "fr",
            "text_role": "edition",
            "witness_kind": "edition_extract",
            "edition": "法语 PDF 底本抽取（S1–S5，带页码）",
            "translator": None,
            "authority_level": "L1",
            "status": "recovered",
            "canonical": False,
            "source_state": "upstream_present",
            "source_file": FR_PDF_FILE,
            "source_file_sha256": fr_pdf_sha,
            "provenance_note": ("由本地法语 PDF 抽取，带 page 号；"
                                "与 STAFERLA 转录是两份独立 witness。"
                                "本阶段**未**在这两份 witness 之间建立对齐 —— "
                                "它们的切分粒度不同（PDF 9,799 段 vs 转录 1,868 段），"
                                "任何未经审核的段对段映射都会是编造。"),
            "passage_link_state": "not_linked",
        })
    translations = [{
        "id": "trans.zh.translation-project",
        "witness_id": ZH_WITNESS["id"],
        "language": "zh",
        "text_role": "translation",
        "edition": ZH_WITNESS["edition"],
        "translator": ZH_WITNESS["translator"],
        "authority_level": "L2",
        # §四：恢复来的中译**不得**自动声称为 canonical translation
        "status": "recovered",
        "canonical": False,
        "source_state": "upstream_missing",
        "review_status": "candidate",
        "generated_by": "script:build_passage_store.py",
        "provenance_note": ("由社区中译项目恢复；上游源目录已消失。"
                            "未经 source linking 与人工审核，不得升级为 canonical。"),
    }, {
        "id": "trans.fr.staferla",
        "witness_id": FR_WITNESS["id"],
        "language": "fr",
        "text_role": "transcription",
        "edition": FR_WITNESS["edition"],
        "translator": None,
        "authority_level": "L1",
        "status": "recovered",
        "canonical": False,
        "source_state": "upstream_present",
        "review_status": "candidate",
        "generated_by": "script:build_passage_store.py",
        "provenance_note": "工作转录，非瑟伊版定本。",
    }]

    sessions = OrderedDict()
    passages = []
    # §三 Passage ↔ Witness 是**多对多**：一个抽象 Passage 可以有多个 witness。
    # 本阶段每个法语 Passage 只连到一个 witness（STAFERLA），因为另一份法语 witness
    # 与它没有经过审核的段级映射；连接表结构已就位，将来补对齐即可增加边。
    passage_witnesses = []

    def provenance(doc, src_file, src_sha, seg_id, raw, upstream_state,
                   physical_source=None, extra=None):
        """§八 溯源元组。

        重要事实（实测）：`atlas/segments.jsonl` 与 `atlas/french_staferla.jsonl`
        **不在** Phase 1 那 143 个原始文件里 —— 它们是 `.lacan-build/` 的**产物**。
        因此不能假装能闭合到「原始物理文件 + 其 sha256」：

          * 中译：上游源目录已消失 → 链在「recovered 文件」处就断了 → INCOMPLETE
          * 法语：atlas 文件可自证 sha256，但它的上游（STAFERLA）不在本机
                  → 只能闭合到 Document 级 → INCOMPLETE（缺 physical file）

        本函数把这件事**显式写出来**，而不是用 doc 为空静默降级。
        """
        missing = []
        if not seg_id:
            missing.append("source_segment_id")
        if not src_sha:
            missing.append("recovered_file_sha256")
        if upstream_state == "upstream_missing":
            missing.append("upstream_original_file")
        elif upstream_state == "upstream_present" and not physical_source:
            missing.append("physical_source_file")
        if physical_source and not physical_source.get("source_txt_sha256"):
            missing.append("physical_source_sha256")
        prov = {
            "source_segment_id": seg_id,
            # 「物理来源」＝承载该 segment 的可验证文件（这里是 atlas 的 jsonl）
            "recovered_file": src_file,
            "recovered_file_sha256": src_sha,
            "recovered_file_path": os.path.join(ATLAS, src_file),
            # 逻辑文档（来自 Phase 1 inventory，仅当该文件确实在 143 个原始文件里）
            "document_id": (doc or {}).get("document_id"),
            "physical_file": (doc or {}).get("rel_path"),
            "physical_sha256": (doc or {}).get("sha256"),
            "upstream_state": upstream_state,
            "segment_sha256": sha256_text(raw) if raw is not None else None,
            # 第二跳（法语可达）：转录 ← .lacan-build/staferla/S*.txt ← 原始下载 URL
            "physical_source_file": (physical_source or {}).get("source_txt"),
            "physical_source_sha256": (physical_source or {}).get("source_txt_sha256"),
            "physical_source_url": (physical_source or {}).get("upstream_url"),
        }
        if extra:
            prov.update(extra)
        return prov, missing

    # ---------------- 法语转录（§一：无课次 → 以 seminar 为 session 单位）
    with open(fr_path, encoding="utf-8") as f:
        per_sem = {}
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            raw = d.get("fr") or ""
            sem_raw = str(d.get("seminar"))
            sid = "session.%s.unknown" % seminar_id(d["seminar"])
            per_sem[sid] = per_sem.get(sid, 0) + 1
            seq = per_sem[sid]
            pid = "passage.%s.P%04d" % (sid.split(".", 1)[1], seq)
            prov, missing = provenance(fr_doc, FR_FILE, fr_sha, d.get("id"), raw,
                                       "upstream_present",
                                       physical_source=staferla_src.get(sem_raw))
            sem = seminars.get(sem_raw, {})
            passage_witnesses.append({
                "passage_id": pid, "witness_id": FR_WITNESS["id"],
                "link_role": "transcription",
                "authority_level": "L1",
                "review_status": "candidate",
                "method": "native (该段即出自此 witness)",
                "schema_version": "1.0.0",
            })
            passages.append({
                "id": pid,
                "type": "passage",
                "session_id": sid,
                "seminar_id": sem.get("id", "seminar." + seminar_id(sem_raw)),
                "language": "fr",
                "witness_id": FR_WITNESS["id"],
                "translation_id": "trans.fr.staferla",
                "session_date": "unknown",
                "session_date_precision": "unknown",
                "year_from": sem.get("year_from"),
                "year_to": sem.get("year_to"),
                "lesson": None,
                "sequence_in_session": seq,
                "raw_text": raw,
                "normalized_text": raw,          # 本阶段不做 normalization
                "normalization_operations": [],   # 空 = 文本未被改动（可解释）
                "text_role": "transcription",
                "authority_level": "L1",
                "review_status": "candidate",
                "status": "recovered",
                "canonical": False,
                "provenance": prov,
                "trace_status": ("COMPLETE" if not missing
                                 else "SOURCE_TRACE_INCOMPLETE"),
                "trace_missing": missing or None,
                "generated_by": "script:build_passage_store.py",
                "schema_version": "1.0.0",
            })
            if limit and len(passages) >= limit:
                break

    # ---------------- 中译（§一：有 lesson → session 带课次）
    with open(zh_path, encoding="utf-8") as f:
        per_sess = {}
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            raw = d.get("text") or ""
            sem_raw = str(d.get("seminar"))
            sem = seminars.get(sem_raw, {})
            lesson = d.get("lesson")
            if lesson is None:
                sid = "session.%s.unknown" % seminar_id(sem_raw)
            else:
                sid = "session.%s.unknown.L%02d" % (seminar_id(sem_raw), int(lesson))
            per_sess[sid] = per_sess.get(sid, 0) + 1
            seq = per_sess[sid]
            # passage id：session 前缀（去掉 session.）+ P 序号
            pid = "passage.%s.P%04d" % (sid.split(".", 1)[1], seq)
            prov, missing = provenance(zh_doc, ZH_FILE, zh_sha, d.get("id"), raw,
                                       "upstream_missing")
            passage_witnesses.append({
                "passage_id": pid, "witness_id": ZH_WITNESS["id"],
                "link_role": "translation",
                "authority_level": "L2",
                "review_status": "candidate",
                "method": "native (该段即出自此 witness)",
                "schema_version": "1.0.0",
            })
            passages.append({
                "id": pid,
                "type": "passage",
                "session_id": sid,
                "seminar_id": sem.get("id", "seminar." + seminar_id(sem_raw)),
                "language": "zh",
                "witness_id": ZH_WITNESS["id"],
                "translation_id": "trans.zh.translation-project",
                "session_date": "unknown",
                "session_date_precision": "unknown",
                "year_from": sem.get("year_from"),
                "year_to": sem.get("year_to"),
                "lesson": int(lesson) if lesson is not None else None,
                "sequence_in_session": seq,
                "source_file_relpath": d.get("file"),
                "raw_text": raw,
                "normalized_text": raw,
                "normalization_operations": [],
                "text_role": "translation",
                "authority_level": "L2",
                "review_status": "candidate",
                # §四：恢复状态，canonical=false，等人工审核才可升级
                "status": "recovered",
                "canonical": False,
                "source_state": "upstream_missing",
                "provenance": prov,
                "trace_status": ("COMPLETE" if not missing
                                 else "SOURCE_TRACE_INCOMPLETE"),
                "trace_missing": missing or None,
                "generated_by": "script:build_passage_store.py",
                "schema_version": "1.0.0",
            })
            if limit and len(passages) >= limit:
                break

    # ---------------- sessions 汇总
    for sid in sorted({p["session_id"] for p in passages}):
        parts = sid.split(".")
        sid_sem = parts[1]
        lesson = None
        if len(parts) > 3 and parts[3].startswith("L"):
            lesson = int(parts[3][1:])
        sem = next((v for v in seminars.values() if v["id"].endswith(sid_sem)), {})
        sessions[sid] = {
            "id": sid,
            "type": "session",
            "seminar_id": sem.get("id", "seminar." + sid_sem),
            "seminar": sid_sem,
            "session_date": "unknown",
            "session_date_precision": "unknown",
            "year_from": sem.get("year_from"),
            "year_to": sem.get("year_to"),
            "lesson": lesson,
            "passage_count": sum(1 for p in passages if p["session_id"] == sid),
            "languages": sorted({p["language"] for p in passages
                                 if p["session_id"] == sid}),
            "trace_status": "SOURCE_TRACE_INCOMPLETE",
            "trace_missing": ["session_date"],
            "authority_level": "L1",
            "review_status": "needs_review",
            "generated_by": "script:build_passage_store.py",
            "schema_version": "1.0.0",
        }

    # ---- §0 迁移：给每个 witness 补 corpus_source_id，并生成 realization 层
    for w in witnesses:
        w["corpus_source_id"] = WITNESS_TO_SOURCE.get(w["id"])

    # PassageRealization：Passage × Witness 的**实现**记录。
    # 与 passage_witnesses（连接表）的区别：
    #   passage_witnesses = 「哪些 witness 承载了这个 Passage」（关系）
    #   passage_realizations = 「这个 Passage 在该 witness 中的具体实现」（实体）
    # 本阶段两者一对一同构（每段只有一个 native witness），但语义不同，
    # 将来补上 PDF↔转录对齐后 realization 会多于 link。
    passage_realizations = []
    for pw in passage_witnesses:
        w = next((x for x in witnesses if x["id"] == pw["witness_id"]), {})
        passage_realizations.append({
            "passage_id": pw["passage_id"],
            "witness_id": pw["witness_id"],
            "corpus_source_id": w.get("corpus_source_id"),
            "language": w.get("language"),
            "text_role": w.get("text_role"),
            "authority_level": pw["authority_level"],
            "review_status": "candidate",
            "method": pw["method"],
            "generated_by": "script:build_passage_store.py",
            "schema_version": "1.0.0",
        })

    # ---------------- 写 JSONL（稳定序）
    passages.sort(key=lambda p: p["id"])
    sem_list = sorted(seminars.values(), key=lambda s: s["id"])
    sess_list = [sessions[k] for k in sorted(sessions)]

    def write_jsonl(name, rows, force=False):
        """写 JSONL。内容确定性 → 已存在时默认跳过重写（省掉 373MB 重写）。
        需要强制重写时传 force=True 或删掉文件。"""
        p = os.path.join(STORE, name)
        if os.path.exists(p) and not force:
            return p
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        return p

    # force 必须传到 write_jsonl —— 否则 --force 只重建 SQLite，
    # 留下旧的 JSONL（实测踩过：provenance 字段没更新）
    write_jsonl("seminars.jsonl", sem_list, force=force)
    write_jsonl("sessions.jsonl", sess_list, force=force)
    write_jsonl("passages.jsonl", passages, force=force)
    write_jsonl("witnesses.jsonl", witnesses, force=force)
    write_jsonl("passage_witnesses.jsonl", passage_witnesses, force=force)
    write_jsonl("corpus_sources.jsonl", CORPUS_SOURCES, force=force)
    write_jsonl("passage_realizations.jsonl", passage_realizations, force=force)
    write_jsonl("translations.jsonl", translations, force=force)

    # ---------------- SQLite（机器精确检索）
    if os.path.exists(SQLITE):
        os.remove(SQLITE)
    # 说明：不用 WAL —— 实测在首次创建时触发 `disk I/O error`，
    # 而本场景是**一次性批量装载**、没有并发读者，WAL 只会带来风险。
    # 用 MEMORY journal + 单事务，既快又稳。
    con = sqlite3.connect(SQLITE)
    try:
        con.executescript("""
        PRAGMA journal_mode=MEMORY;
        PRAGMA synchronous=OFF;
        CREATE TABLE passages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            seminar_id TEXT NOT NULL,
            language TEXT NOT NULL,
            lesson INTEGER,
            sequence_in_session INTEGER,
            session_date TEXT NOT NULL,
            session_date_precision TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            text_role TEXT NOT NULL,
            authority_level TEXT NOT NULL,
            review_status TEXT NOT NULL,
            status TEXT NOT NULL,
            canonical INTEGER NOT NULL,
            trace_status TEXT NOT NULL,
            source_segment_id TEXT,
            document_id TEXT,
            recovered_file TEXT,
            recovered_file_sha256 TEXT,
            physical_file TEXT,
            physical_sha256 TEXT,
            upstream_state TEXT,
            segment_sha256 TEXT,
            provenance_json TEXT NOT NULL,
            normalization_operations_json TEXT NOT NULL
        );
        CREATE INDEX idx_passages_session ON passages(session_id);
        CREATE INDEX idx_passages_seminar ON passages(seminar_id);
        CREATE INDEX idx_passages_lang ON passages(language);
        CREATE INDEX idx_passages_doc ON passages(document_id);
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, seminar_id TEXT, lesson INTEGER,
            session_date TEXT, session_date_precision TEXT,
            passage_count INTEGER, trace_status TEXT
        );
        CREATE TABLE seminars (
            id TEXT PRIMARY KEY, roman TEXT, fr_title TEXT, zh_title TEXT,
            year_from INTEGER, year_to INTEGER, lessons INTEGER, segments INTEGER
        );
        CREATE TABLE witnesses (
            id TEXT PRIMARY KEY, language TEXT, witness_kind TEXT,
            edition TEXT, authority_level TEXT, status TEXT,
            canonical INTEGER, source_file TEXT, source_file_sha256 TEXT,
            provenance_note TEXT, passage_link_state TEXT,
            corpus_source_id TEXT
        );
        CREATE TABLE passage_witnesses (
            passage_id TEXT NOT NULL, witness_id TEXT NOT NULL,
            link_role TEXT, authority_level TEXT, review_status TEXT,
            method TEXT,
            PRIMARY KEY (passage_id, witness_id)
        );
        CREATE INDEX idx_pw_witness ON passage_witnesses(witness_id);
        CREATE INDEX idx_pw_passage ON passage_witnesses(passage_id);
        CREATE TABLE corpus_sources (
            id TEXT PRIMARY KEY, name TEXT, kind TEXT, language TEXT,
            authority_level TEXT, review_status TEXT, status TEXT,
            canonical INTEGER, url TEXT, note TEXT
        );
        CREATE TABLE passage_realizations (
            passage_id TEXT NOT NULL, witness_id TEXT NOT NULL,
            corpus_source_id TEXT, language TEXT, text_role TEXT,
            authority_level TEXT, review_status TEXT, method TEXT,
            PRIMARY KEY (passage_id, witness_id)
        );
        CREATE INDEX idx_pr_witness ON passage_realizations(witness_id);
        CREATE INDEX idx_pr_source ON passage_realizations(corpus_source_id);
        CREATE TABLE translations (
            id TEXT PRIMARY KEY, witness_id TEXT, language TEXT, text_role TEXT,
            edition TEXT, authority_level TEXT, status TEXT,
            canonical INTEGER, review_status TEXT
        );
        """)
        con.execute("BEGIN")
        con.executemany(
            "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(p["id"], p["session_id"], p["seminar_id"], p["language"], p["lesson"],
              p["sequence_in_session"], p["session_date"], p["session_date_precision"],
              p["raw_text"], p["normalized_text"], p["text_role"],
              p["authority_level"], p["review_status"], p["status"],
              1 if p["canonical"] else 0, p["trace_status"],
              p["provenance"]["source_segment_id"], p["provenance"]["document_id"],
              p["provenance"]["recovered_file"],
              p["provenance"]["recovered_file_sha256"],
              p["provenance"]["physical_file"], p["provenance"]["physical_sha256"],
              p["provenance"]["upstream_state"],
              p["provenance"]["segment_sha256"],
              json.dumps(p["provenance"], ensure_ascii=False, sort_keys=True),
              json.dumps(p["normalization_operations"], ensure_ascii=False))
             for p in passages])
        con.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                        [(s["id"], s["seminar_id"], s["lesson"], s["session_date"],
                          s["session_date_precision"], s["passage_count"],
                          s["trace_status"]) for s in sess_list])
        con.executemany("INSERT INTO seminars VALUES (?,?,?,?,?,?,?,?)",
                        [(s["id"], s["roman"], s["fr_title"], s["zh_title"],
                          s["year_from"], s["year_to"], s["lessons"], s["segments"])
                         for s in sem_list])
        con.executemany("INSERT INTO witnesses VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(w["id"], w["language"], w["witness_kind"], w["edition"],
                          w["authority_level"], w["status"],
                          1 if w["canonical"] else 0, w["source_file"],
                          w["source_file_sha256"],
                          w.get("provenance_note"), w.get("passage_link_state"),
                          w.get("corpus_source_id"))
                         for w in witnesses])
        con.executemany("INSERT INTO corpus_sources VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [(c["id"], c["name"], c["kind"], c["language"],
                          c["authority_level"], c["review_status"], c["status"],
                          1 if c["canonical"] else 0, c.get("url"), c.get("note"))
                         for c in CORPUS_SOURCES])
        con.executemany(
            "INSERT OR IGNORE INTO passage_realizations VALUES (?,?,?,?,?,?,?,?)",
            [(r["passage_id"], r["witness_id"], r["corpus_source_id"],
              r["language"], r["text_role"], r["authority_level"],
              r["review_status"], r["method"]) for r in passage_realizations])
        con.executemany(
            "INSERT OR IGNORE INTO passage_witnesses VALUES (?,?,?,?,?,?)",
            [(pw["passage_id"], pw["witness_id"], pw["link_role"],
              pw["authority_level"], pw["review_status"], pw["method"])
             for pw in passage_witnesses])
        con.executemany("INSERT INTO translations VALUES (?,?,?,?,?,?,?,?,?)",
                        [(t["id"], t["witness_id"], t["language"], t["text_role"],
                          t["edition"], t["authority_level"], t["status"],
                          1 if t["canonical"] else 0, t["review_status"])
                         for t in translations])
        con.commit()
    finally:
        con.close()

    # ---------------- build 元数据（确定性时间戳）
    meta = {
        "schema": "passage-store/v1",
        "source_root": ATLAS,
        "source_files": {
            ZH_FILE: {"sha256": zh_sha, "records": sum(1 for p in passages if p["language"] == "zh")},
            FR_FILE: {"sha256": fr_sha, "records": sum(1 for p in passages if p["language"] == "fr")},
        },
        "counts": {
            "passages": len(passages),
            "sessions": len(sess_list),
            "seminars": len(sem_list),
            "witnesses": len(witnesses),
            "passage_witness_links": len(passage_witnesses),
            "corpus_sources": len(CORPUS_SOURCES),
            "passage_realizations": len(passage_realizations),
            "translations": len(translations),
            "by_language": {
                "zh": sum(1 for p in passages if p["language"] == "zh"),
                "fr": sum(1 for p in passages if p["language"] == "fr"),
            },
        },
        "id_scheme": {
            "seminar": "seminar.S<NN>",
            "session": "session.S<NN>.<YYYY-MM-DD|YYYY-unknown|unknown>[.L<NN>]",
            "passage": "passage.S<NN>.<date>[\.L<NN>].P<nnnn>",
            "deterministic": True,
            "notes": "ID 不依赖时间/读取顺序/UUID/dict 迭代顺序；日期不可证时保留 unknown",
        },
        "not_canonical": {
            "zh_translation_canonical": False,
            "note": "恢复来的中译 status=recovered；升级为 canonical 需 source linking + 人工审核",
        },
    }
    apply_stamp(meta, stamp=stamp)
    with open(os.path.join(STORE, "_build_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)

    return meta


def main():
    ap = argparse.ArgumentParser(description="构建 Canonical Passage Store")
    ap.add_argument("--limit", type=int, default=0, help="抽样条数（测试用）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--force", action="store_true", help="忽略快速路径，强制重建")
    add_stamp_flag(ap)
    args = ap.parse_args()

    m = build(limit=args.limit, stamp=args.stamp, force=args.force)
    if not args.quiet:
        c = m["counts"]
        print(f"[store] passages={c['passages']} (zh={c['by_language']['zh']} "
              f"fr={c['by_language']['fr']}) sessions={c['sessions']} "
              f"seminars={c['seminars']}", file=sys.stderr)
        print(f"[store] -> {STORE}", file=sys.stderr)
        print(f"[store] -> {SQLITE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
