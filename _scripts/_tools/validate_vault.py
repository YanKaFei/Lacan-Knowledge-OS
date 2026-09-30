#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_vault.py — Lacanian Knowledge OS 脚手架层的节点/关系校验器

做什么（全部只读 vault 内容，只写 _index/Reports/）：
  1. 递归扫描 vault 下所有 .md，解析 YAML frontmatter；
  2. 用 jsonschema (Draft 2020-12) 按 00_System/Schemas/knowledge.schema.json 校验每个节点；
  3. 校验 ID 全局唯一、canonical_name 同 type 内唯一；
  4. 校验 ID 命名空间与 00_System/Schemas/id-namespaces.json 一致；
  5. 收集 [[wikilink]]（含 [[X]] / [[X|别名]] / [[X#锚点]] / ![[附件]]），检测断链；
  6. 校验 _data/relations/*.jsonl 里的 relation（relation.schema.json + 引用完整性）；
  7. 输出 _index/Reports/validation-report.md 与 validation-report.json。

设计取舍：
  * 代码围栏与行内代码里的 [[...]] 不算链接（写文档时要能安全地举语法例子）。
  * 断链是 warning 而非 error：Obsidian 允许先链接后建卡；--strict 时 warning 也会导致非零退出。
  * format 只强制 date-time，不强制 uri —— vault 里 source_url 常含非 ASCII 字符，
    按 RFC3986 严格判会大量误报。
  * JSON Schema 只能校验关系形状，端点是否真实存在由本工具的引用完整性检查负责。

用法：
  cd <vault-root>
  python3 _scripts/_tools/validate_vault.py            # 输出报告，有问题也返回 0
  python3 _scripts/_tools/validate_vault.py --strict   # 有 error/warning 则返回 1
  python3 _scripts/_tools/validate_vault.py --json     # 报告 JSON 打到 stdout
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deterministic import apply_stamp, add_stamp_flag  # noqa: E402

import yaml
import jsonschema
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_API = "lacan-validation/v1"

# ---------------------------------------------------------------- 扫描范围
SKIP_DIR_PATHS = {
    ".obsidian", ".git", ".trash", "_index", "_data", "_scripts", "_attachments",
    # Phase 4D.3：产品工作区（Obsidian 研究笔记 / 概念·研讨班 reference hub /
    # passage 快照 / 工作区 manifests）**不是知识节点**，不进 canonical 图谱与校验。
    # 它们是 USER_WORKSPACE（见 scholarly_api/policy.py），只读回链、绝不写回核心。
    "_workspace",
    "00_System/Templates", "00_System/Schemas", "00_System/Guidelines",
    "00_System/_fixtures", "00_System/Validation",
}
SKIP_BASENAMES = {"_index.md", "README.md", "Home.md", "CHANGELOG.md"}

# 回退用：契约真源是 00_System/Schemas/knowledge.schema.json#/$defs/stable_id.pattern。
# 运行时优先读 schema，避免两处各写一份导致漂移。
STABLE_ID_FALLBACK = r"^[a-z][a-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+$"
STABLE_ID = re.compile(STABLE_ID_FALLBACK)

# 关系主库：已审核的边。文件级权威规则（RELATION_MODEL.md §5、§6）在此强制。
MAIN_RELATIONS_FILE = "relations.jsonl"
CANDIDATE_RELATIONS_FILE = "relations.candidate.jsonl"
CONFIDENCE_MAIN_MIN = 0.5

SCHEMA_FILES = {
    "knowledge": "00_System/Schemas/knowledge.schema.json",
    "relation": "00_System/Schemas/relation.schema.json",
    "namespaces": "00_System/Schemas/id-namespaces.json",
}


# ================================================================ frontmatter
def parse_frontmatter(text):
    """返回 (front, body, error, body_line)。

    front 为 None 表示没有 frontmatter；body_line 是正文第一行在文件中的行号
    （用于让报告里的行号能直接在编辑器里定位）。
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n)?", text, re.S)
    if not m:
        return None, text, None, 1
    body = text[m.end():]
    body_line = text[:m.end()].count("\n") + 1
    try:
        data = yaml.safe_load(m.group(1))
    except Exception as exc:  # noqa: BLE001
        return None, body, "YAML 解析失败: %s" % exc, body_line
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, body, "frontmatter 不是 mapping（应为 key: value 结构）", body_line
    return data, body, None, body_line


# ================================================================ wikilink
def mask_code(text):
    """把围栏代码块与行内代码替换成等长空白，保留换行 —— 行号因此不变。"""
    out = []
    fence = None
    for line in text.split("\n"):
        stripped = line.lstrip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence is None and marker:
            fence = marker.group(1)[0]
            out.append(" " * len(line))
            continue
        if fence is not None:
            if re.match(r"^(`{3,}|~{3,})\s*$", stripped) and stripped[0] == fence:
                fence = None
            out.append(" " * len(line))
            continue
        out.append(re.sub(r"`[^`\n]*`", lambda mm: " " * len(mm.group(0)), line))
    return "\n".join(out)


_WIKILINK = re.compile(r"(!?)\[\[([^\[\]\n]+)\]\]")


def split_target(raw):
    """[[目标#锚点|别名]] → (target, alias, anchor)。

    容忍误写的方括号（frontmatter 的 related/sources 不含方括号，但有人会写成
    "[[concept.x]]"）：这里的归一化保证解析不失败，格式问题另行报警告。
    """
    alias = None
    anchor = None
    s = raw.strip()
    if "|" in s:
        s, alias = s.split("|", 1)
        alias = alias.strip() or None
    if "#" in s:
        s, anchor = s.split("#", 1)
        anchor = anchor.strip() or None
    s = s.strip().strip("[]").strip()
    return s, alias, anchor


def extract_wikilinks(text, line_offset=0):
    """收集 [[...]] 链接。代码围栏/行内代码内的写法一律忽略。

    line_offset 让行号指向文件绝对行（正文第一行 = line_offset）。
    """
    links = []
    masked = mask_code(text)
    for lineno, line in enumerate(masked.split("\n"), 1):
        for m in _WIKILINK.finditer(line):
            target, alias, anchor = split_target(m.group(2))
            links.append({
                "target": target,
                "alias": alias,
                "anchor": anchor,
                "embed": m.group(1) == "!",
                "line": lineno + line_offset,
                "raw": m.group(2).strip(),
            })
    return links


# ================================================================ schema 装载
def make_format_checker():
    """只强制 date-time：uri/uri-reference 严格判会在中文 URL 上误报。"""
    fc = FormatChecker()
    fc.checkers = {
        k: v for k, v in FormatChecker.checkers.items()
        if k not in ("uri", "uri-reference")
    }
    return fc


def load_schemas(vault, fallback_vault=None):
    """装载 schema。本 vault 缺文件时回退到工具自身所在的 vault（便于校验临时 vault）。

    返回 (schemas, validators, namespaces, problems, sources)。
    """
    schemas = {}
    problems = []
    sources = {}
    for key, rel in SCHEMA_FILES.items():
        path = Path(vault) / rel
        if not path.is_file() and fallback_vault is not None:
            alt = Path(fallback_vault) / rel
            if alt.is_file():
                path = alt
                sources[key] = "fallback:%s" % rel
        if not path.is_file():
            problems.append("缺 schema 文件: %s" % rel)
            continue
        try:
            schemas[key] = json.loads(path.read_text(encoding="utf-8"))
            sources.setdefault(key, "vault")
        except Exception as exc:  # noqa: BLE001
            problems.append("%s 无法解析: %s" % (rel, exc))

    checker = make_format_checker()
    validators = {}
    for key in ("knowledge", "relation"):
        if key in schemas:
            validators[key] = Draft202012Validator(schemas[key], format_checker=checker)

    namespaces = {}
    if "namespaces" in schemas:
        namespaces = schemas["namespaces"].get("entity_types", {}) or {}
    return schemas, validators, namespaces, problems, sources


def stable_id_pattern(schemas):
    """ID 正则的真源是 knowledge.schema.json；读不到才用回退常量。"""
    pat = (schemas.get("knowledge", {}).get("$defs", {})
           .get("stable_id", {}).get("pattern"))
    return pat or STABLE_ID_FALLBACK


def schema_consistency(schemas):
    """跨 schema 的枚举漂移检查（relation 复制了 knowledge 的枚举值）。"""
    issues = []
    k = schemas.get("knowledge", {}).get("$defs", {})
    r = schemas.get("relation", {}).get("$defs", {})
    for defname in ("review_status", "authority_level", "concept_period"):
        kv = k.get(defname, {}).get("enum")
        rv = r.get(defname, {}).get("enum")
        if kv is not None and rv is not None and kv != rv:
            issues.append("$defs/%s 在 knowledge 与 relation 中不一致" % defname)
    ks = k.get("stable_id", {}).get("pattern")
    rs = r.get("entity_ref", {}).get("pattern")
    if ks and rs and ks != rs:
        issues.append("stable_id 与 entity_ref 的 pattern 不一致")
    return issues


def iter_schema_errors(validator, data, limit=5):
    errs = []
    for e in validator.iter_errors(data):
        loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
        errs.append("%s: %s" % (loc, e.message))
        if len(errs) >= limit:
            break
    return errs


# ================================================================ 扫描
def skip_reason(rel_parts, name):
    if name in SKIP_BASENAMES:
        return "nav-file"
    if any(p.startswith(".") for p in rel_parts):
        return "hidden-dir"
    if not rel_parts:
        # vault 根目录的 .md 是设计文档 / 说明文件（ARCHITECTURE.md 等），
        # 不是知识节点：知识节点一律住在 00_System…16_Research_Projects 分区里。
        return "root-doc"
    joined = "/".join(rel_parts)
    for d in sorted(SKIP_DIR_PATHS):
        if joined == d or joined.startswith(d + "/"):
            return "system-dir"
    return None


def scan_markdown(vault):
    """返回 (md_files, skipped)。md_files 按相对路径排序。"""
    vault = Path(vault)
    md_files = []
    skipped = []
    for path in sorted(vault.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(vault)
        reason = skip_reason(rel.parts[:-1], rel.name)
        if reason:
            skipped.append({"path": str(path), "rel": str(rel), "reason": reason})
            continue
        md_files.append(path)
    return md_files, skipped


def collect_attachment_names(vault):
    names = set()
    for path in Path(vault).rglob("*"):
        if path.is_file():
            names.add(path.name)
            names.add(path.name.casefold())
    return names


def build_link_index(entities):
    """wikilink → 实体的解析索引。"""
    index = defaultdict(set)
    for ent in entities:
        eid = ent.get("id")
        if not eid:
            continue
        keys = [eid, ent.get("stem"), ent.get("canonical_name"), ent.get("title")]
        keys.extend(ent.get("aliases") or [])
        for k in keys:
            if isinstance(k, str) and k.strip():
                index[k.strip().casefold()].add(eid)
    return index


# ================================================================ 主审计

# ============================================================ Passage Store
def audit_passage_store(vault):
    """只读校验机器层 Passage Store。

    检查（每项都对应一个真实踩过的坑）：
      1. 计数守恒：zh 82,578 / fr 166,527 / 合 249,105
      2. ID 唯一
      3. ID 命中 id-namespaces.json 的 pattern（防「两套 ID 规范分叉」）
      4. 溯源字段自洽：INCOMPLETE 必须写明缺哪一环
      5. 无损：raw_text == normalized_text 时 operations 必须为空
      6. passage_witnesses 连接表的引用必须存在
      7. 未闭合的 translation 不得是 canonical
    """
    import json as _j
    from collections import Counter

    out = {"present": False, "errors": [], "warnings": [], "counts": {}}
    store = vault / "_data" / "passage_store"
    pp = store / "passages.jsonl"
    if not pp.is_file():
        out["warnings"].append("passage store 不存在（Phase 2 未构建？）")
        return out
    out["present"] = True

    ZH, FR, TOTAL = 82578, 166527, 249105

    # ID pattern（来自 id-namespaces.json）
    pats = {}
    ns_p = vault / "00_System" / "Schemas" / "id-namespaces.json"
    if ns_p.is_file():
        with open(ns_p, encoding="utf-8") as f:
            et = _j.load(f).get("entity_types") or {}
        for t in ("seminar", "session", "passage", "translation", "witness"):
            if t in et:
                pats[t] = re.compile(et[t]["pattern"])

    lang = Counter()
    seen = set()
    dup = 0
    bad_shape = 0
    trace_bad = 0
    lossy_bad = 0
    sample_bad = []
    with open(pp, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            p = _j.loads(line)
            pid = p["id"]
            if pid in seen:
                dup += 1
            else:
                seen.add(pid)
            lang[p.get("language")] += 1
            # ID 形态
            if "passage" in pats and not pats["passage"].match(pid):
                bad_shape += 1
                if len(sample_bad) < 3:
                    sample_bad.append(pid)
            # 溯源自洽
            ts = p.get("trace_status")
            if ts == "SOURCE_TRACE_INCOMPLETE" and not p.get("trace_missing"):
                trace_bad += 1
            elif ts == "COMPLETE":
                # COMPLETE 的两跳模型：
                #   ① recovered_file + sha256（承载该段的可验证文件）
                #   ② physical_source_file + sha256（该文件的上游原始下载）
                # document_id 仅当源文件属于 Phase 1 的 143 个原始件时才非空。
                prov = p.get("provenance") or {}
                if not all(prov.get(k) for k in
                           ("source_segment_id", "recovered_file_sha256",
                            "physical_source_file", "physical_source_sha256")):
                    trace_bad += 1
            # 无损
            if p.get("raw_text") != p.get("normalized_text") \
                    and not (p.get("normalization_operations") or []):
                lossy_bad += 1

    out["counts"] = {"passages": len(seen) + dup, "unique_ids": len(seen),
                     "by_language": dict(lang)}
    if len(seen) + dup != TOTAL:
        out["errors"].append(
            "PASSAGE_COUNT_MISMATCH: 总数 %d != %d" % (len(seen) + dup, TOTAL))
    if lang.get("zh") != ZH:
        out["errors"].append("PASSAGE_ZH_COUNT: %d != %d" % (lang.get("zh"), ZH))
    if lang.get("fr") != FR:
        out["errors"].append("PASSAGE_FR_COUNT: %d != %d" % (lang.get("fr"), FR))
    if dup:
        out["errors"].append("PASSAGE_DUPLICATE_ID: %d 个" % dup)
    if bad_shape:
        out["errors"].append(
            "PASSAGE_ID_PATTERN: %d 个 ID 不匹配 id-namespaces.json（例 %s）"
            % (bad_shape, sample_bad))
    if trace_bad:
        out["errors"].append("PASSAGE_TRACE_INCONSISTENT: %d 条" % trace_bad)
    if lossy_bad:
        out["errors"].append(
            "PASSAGE_LOSSY_NORMALIZATION: %d 条文本被改但无 operations" % lossy_bad)

    # translations / witnesses 的 ID 也必须命中 pattern
    # （对抗式审查指出：第一版只校验 passage 的 ID，于是 trans.* 命名空间冲突
    #   没有任何检查能发现 —— 两个 store 文件各用一个 ID 形态。）
    for fname, entity, idkey in (("translations.jsonl", "translation", "id"),
                                 ("witnesses.jsonl", "witness", "id"),
                                 ("alignments.jsonl", "alignment", "alignment_id"),
                                 ("passage_witnesses.jsonl", "passage_witness",
                                  "passage_id")):
        fp = store / fname
        if not fp.is_file():
            continue
        pat = pats.get(entity)
        if not pat:
            continue
        bad = []
        with open(fp, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                v = _j.loads(line).get(idkey)
                if v and not pat.match(v):
                    bad.append(v)
        if bad:
            out["errors"].append(
                "%s_ID_PATTERN: %d 个 ID 不匹配 namespace pattern（例 %s）"
                % (entity.upper(), len(bad), bad[:3]))

    # passage_witnesses 引用完整性
    pwp = store / "passage_witnesses.jsonl"
    wp = store / "witnesses.jsonl"
    if pwp.is_file() and wp.is_file():
        wid = set()
        with open(wp, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    wid.add(_j.loads(line)["id"])
        bad_link = 0
        nlink = 0
        with open(pwp, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                nlink += 1
                if _j.loads(line)["witness_id"] not in wid:
                    bad_link += 1
        out["counts"]["passage_witness_links"] = nlink
        if bad_link:
            out["errors"].append(
                "PASSAGE_WITNESS_DANGLING: %d 条连接指向不存在的 witness" % bad_link)

    # recovered translation 不得 canonical
    tp = store / "translations.jsonl"
    if tp.is_file():
        with open(tp, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                t = _j.loads(line)
                if t.get("status") == "recovered" and t.get("canonical"):
                    out["errors"].append(
                        "RECOVERED_TRANSLATION_CANONICAL: %s 既是 recovered 又 canonical"
                        % t.get("id"))

    # 注意：`add()` 定义在 audit() 内部，本函数是模块级函数，取不到它。
    # 因此这里只**返回**问题，由 audit() 在调用点注入 issues。
    return out


def audit(vault, relations_dir=None, write=False, report_dir=None, fallback_vault=None):
    vault = Path(vault).expanduser().resolve()
    if fallback_vault is None:
        fallback_vault = Path(__file__).resolve().parents[2]
    schemas, validators, namespaces, schema_problems, schema_sources = load_schemas(
        vault, fallback_vault)
    id_pattern = re.compile(stable_id_pattern(schemas))

    report = {
        "schema": SCHEMA_API,
        "generated_at": None,   # 由 apply_stamp() 写（默认内容推导，保证重跑无 diff）
        "vault_root": str(vault),
        "schemas_loaded": sorted(schemas.keys()),
        "schema_sources": schema_sources,
        "stable_id_pattern": id_pattern.pattern,
        "issues": [],
        "broken_wikilinks": [],
        "duplicate_ids": [],
        "duplicate_canonical_names": [],
        "filename_id_mismatches": [],
        "near_duplicate_canonical_names": [],
        "alias_collisions": [],
        "view_mismatches": [],
        "skipped": [],
        "entities": [],
        "relations": [],
    }

    def add(severity, code, path, message, detail=None, line=None):
        item = {"severity": severity, "code": code, "path": str(path), "message": message}
        if detail:
            item["detail"] = detail
        if line:
            item["line"] = line
        report["issues"].append(item)

    for p in schema_problems:
        add("error", "SCHEMA_FILE_MISSING", str(vault), p)
    for drift in schema_consistency(schemas):
        add("error", "SCHEMA_DRIFT", str(vault), drift)

    # ---------------- 1. 节点
    md_files, skipped = scan_markdown(vault)
    report["skipped"] = skipped

    entities = []
    for path in md_files:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            add("error", "READ_FAILED", path, "无法读取: %s" % exc)
            continue
        front, body, err, body_line = parse_frontmatter(text)
        if err:
            add("error", "FRONTMATTER_PARSE_ERROR", path, err)
            continue
        if front is None:
            add("warning", "MISSING_FRONTMATTER", path,
                "该 .md 没有 YAML frontmatter —— 不是知识节点，无法进入图谱")
            continue

        stem = path.stem
        ent = {
            "path": str(path),
            "rel": str(path.relative_to(vault)),
            "stem": stem,
            "front": front,
            "body": body,
            "id": front.get("id"),
            "type": front.get("type"),
            "title": front.get("title"),
            "canonical_name": front.get("canonical_name"),
            "aliases": front.get("aliases") if isinstance(front.get("aliases"), list) else [],
            "language": front.get("language"),
            "authority_level": front.get("authority_level"),
            "review_status": front.get("review_status"),
            "status": front.get("status"),
            "period": front.get("period"),
            "generated_by": front.get("generated_by"),
            "reviewed_by": front.get("reviewed_by"),
            "body_line": body_line,
        }
        entities.append(ent)

        # schema 校验（schema 缺失时已记 SCHEMA_FILE_MISSING，这里不再重复炸）
        if "knowledge" in validators:
            for msg in iter_schema_errors(validators["knowledge"], front):
                add("error", "SCHEMA_INVALID", path,
                    "不符合 knowledge.schema.json", detail=msg)

        eid = ent["id"]
        if isinstance(eid, str) and not id_pattern.match(eid):
            add("error", "ID_PATTERN_INVALID", path,
                "id 不满足 namespace.slug 形式（见 knowledge.schema.json stable_id）",
                detail="id=%r pattern=%s" % (eid, id_pattern.pattern))

        # 命名空间一致性
        ns = namespaces.get(ent["type"]) if ent["type"] else None
        if ns and isinstance(eid, str):
            if not eid.startswith(ns["namespace"] + "."):
                add("error", "NAMESPACE_MISMATCH", path,
                    "id 的命名空间与 type 不符",
                    detail="type=%s 要求前缀 %s.，实际 id=%s" % (ent["type"], ns["namespace"], eid))
            elif not re.match(ns["pattern"], eid):
                add("warning", "ID_PATTERN_MISMATCH", path,
                    "id 未命中该 type 的推荐 pattern",
                    detail="type=%s pattern=%s id=%s" % (ent["type"], ns["pattern"], eid))

        # 文件名 == id（硬规则）：Obsidian 用文件名做 wikilink 解析，
        # 两者不一致时，任何 [[<id>]] 都会指向一个不存在的文件。
        if isinstance(eid, str) and stem != eid:
            report["filename_id_mismatches"].append(
                {"filename": stem, "id": eid, "rel": ent["rel"]})
            add("error", "FILENAME_ID_MISMATCH", path,
                "文件名必须等于 id",
                detail="文件名=%s　id=%s　→ 重命名为 %s.md" % (stem, eid, eid))
        if ent["type"] == "concept_state" and isinstance(eid, str):
            cid = front.get("concept_id")
            period = front.get("period")
            if isinstance(cid, str) and period:
                expect = "state.%s.%s" % (cid.split(".", 1)[1] if "." in cid else cid, period)
                if eid != expect:
                    add("warning", "CONCEPT_STATE_ID_MISMATCH", path,
                        "concept_state 的 id 与 concept_id/period 推导不一致",
                        detail="期望 %s，实际 %s" % (expect, eid))

        # ── L4 永不 canonical（本库最核心的不变量，三重防线之一）
        # knowledge.schema.json 的 allOf 已在结构上禁止；validator 再显式报一次，
        # 这样失败信息会**指名道姓**说出违反了哪条规则，而不是只报「schema 校验失败」。
        # 缺陷来源：对抗式审查发现旧实现的唯一相关检查是「`ai:` 前缀 + 缺 reviewed_by」，
        # 只要 generated_by 写 human: 并填 reviewed_by，L4+canonical 就能 0 error 通过。
        if ent["authority_level"] == "L4" and ent["review_status"] == "canonical":
            add("error", "L4_CANONICAL_FORBIDDEN", path,
                "L4（AI 合成）永远不得标为 canonical",
                detail="authority_level=L4, review_status=canonical —— "
                       "见 ARCHITECTURE.md §3 / KNOWLEDGE_SCHEMA.md §5；"
                       "人可以复核 AI 内容（reviewed），但不能把它变成馆藏定本")

        # AI 贡献纪律：AI 产物不得自行晋升 canonical
        gb = ent["generated_by"]
        if isinstance(gb, str) and gb.startswith("ai:") and ent["review_status"] == "canonical" \
                and not ent["reviewed_by"]:
            add("error", "AI_CANONICAL_WITHOUT_HUMAN_REVIEW", path,
                "AI 生成的节点被标为 canonical 但没有人类审阅记录",
                detail="需要 reviewed_by / reviewed_at（见 Guidelines/ai-contribution-policy.md）")

    # ── Passage Store 校验（Phase 2）
    # 为什么必须有：passage store 住在 `_data/`，不在 vault 的 md 节点里，
    # 所以第一版 validator **完全不看它** —— 结果是「两套 ID 规范分叉」这件事
    # 没有任何检查会发现（对抗式审查实测：validator 里 grep "passage" 零命中）。
    report["passage_store"] = audit_passage_store(vault)
    for _e in report["passage_store"].get("errors") or []:
        add("error", _e.split(":")[0], "passage_store", _e)
    for _w in report["passage_store"].get("warnings") or []:
        add("warning", _w.split(":")[0], "passage_store", _w)

    report["entities"] = [
        {
            "id": e["id"], "type": e["type"], "title": e["title"],
            "canonical_name": e["canonical_name"], "aliases": e["aliases"],
            "language": e["language"], "authority_level": e["authority_level"],
            "review_status": e["review_status"], "status": e["status"],
            "period": e["period"], "rel": e["rel"],
        }
        for e in entities
    ]

    # ---------------- 2. 唯一性
    by_id = defaultdict(list)
    by_canon = defaultdict(list)
    for e in entities:
        if isinstance(e["id"], str):
            by_id[e["id"]].append(e["rel"])
        cn = e["canonical_name"]
        if isinstance(cn, str) and cn.strip() and isinstance(e["type"], str):
            by_canon[(e["type"], cn.strip().casefold())].append(e["rel"])

    for eid, paths in sorted(by_id.items()):
        if len(paths) > 1:
            report["duplicate_ids"].append({"id": eid, "paths": sorted(paths)})
            add("error", "DUPLICATE_ID", paths[0],
                "id 重复：%s" % eid, detail="出现在 " + ", ".join(sorted(paths)))
    for (etype, cn), paths in sorted(by_canon.items()):
        if len(paths) > 1:
            report["duplicate_canonical_names"].append(
                {"type": etype, "canonical_name": cn, "paths": sorted(paths)})
            add("error", "DUPLICATE_CANONICAL_NAME", paths[0],
                "同一 type 内 canonical_name 重复：%s" % cn,
                detail="type=%s 出现在 %s" % (etype, ", ".join(sorted(paths))))

    # 去重第 2、3 步（ENTITY_MODEL.md §5）：归一化碰撞 = 警告；别名撞规范名 = 提示
    def norm_name(s):
        s = unicodedata.normalize("NFKC", str(s)).casefold()
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)

    by_norm = defaultdict(list)
    canon_owner = {}
    for e in entities:
        cn = e["canonical_name"]
        if isinstance(cn, str) and cn.strip() and isinstance(e["type"], str):
            by_norm[(e["type"], norm_name(cn))].append(e)
            canon_owner.setdefault((e["type"], cn.strip().casefold()), e["id"])
    for (etype, norm), members in sorted(by_norm.items()):
        ids = sorted({m["id"] for m in members if m["id"]})
        if len(ids) > 1:
            report["near_duplicate_canonical_names"].append(
                {"type": etype, "normalized": norm, "ids": ids})
            add("warning", "CANONICAL_NAME_NEAR_DUPLICATE", members[0]["path"],
                "同 type 内 canonical_name 归一化后碰撞（可能是同一实体）",
                detail="type=%s ids=%s" % (etype, ", ".join(ids)))
    for e in entities:
        for alias in (e["aliases"] or []):
            if not isinstance(alias, str):
                continue
            owner = canon_owner.get((e["type"], alias.strip().casefold()))
            if owner and owner != e["id"]:
                report["alias_collisions"].append(
                    {"alias": alias, "of": e["id"], "owned_by": owner, "type": e["type"]})
                add("info", "ALIAS_COLLIDES_WITH_CANONICAL", e["path"],
                    "别名与另一个节点的 canonical_name 相同（可能应合并）",
                    detail="alias=%s 属于 %s，但 %s 的 canonical_name 就是它"
                           % (alias, e["id"], owner))

    # ---------------- 3. wikilink
    link_index = build_link_index(entities)
    attachments = collect_attachment_names(vault)
    out_links = defaultdict(list)
    n_links = 0
    n_embeds = 0
    for e in entities:
        links = extract_wikilinks(e["body"] or "",
                                  line_offset=max(e.get("body_line", 1) - 1, 0))
        for rel_target in (e["front"].get("related") or []):
            if isinstance(rel_target, str):
                t, alias, anchor = split_target(rel_target)
                if "[" in rel_target or "]" in rel_target:
                    add("warning", "WIKILINK_BRACKETS_IN_FRONTMATTER", e["path"],
                        "frontmatter 的 related 值不应含方括号",
                        detail="写成 %r；正确写法是去掉 [[ ]]：%r" % (rel_target, t))
                links.append({"target": t, "alias": alias, "anchor": anchor,
                              "embed": False, "line": None, "raw": rel_target,
                              "origin": "frontmatter.related"})
        for link in links:
            link["origin"] = link.get("origin", "body")
            target = link["target"]
            if link["embed"]:
                n_embeds += 1
                if target and target not in attachments and target.casefold() not in attachments:
                    add("warning", "ATTACHMENT_MISSING", e["path"],
                        "嵌入的附件不存在：%s" % target, line=link["line"])
                continue
            if not target or "{{" in target:
                continue
            n_links += 1
            if resolve_target(target, link_index, vault, e["path"]):
                continue
            report["broken_wikilinks"].append({
                "source": e["rel"], "source_id": e["id"], "target": target,
                "alias": link["alias"], "anchor": link["anchor"],
                "line": link["line"], "origin": link["origin"],
            })
            add("warning", "BROKEN_WIKILINK", e["path"],
                "断链：[[%s]] 找不到对应实体" % target, line=link["line"])
        if isinstance(e["id"], str):
            out_links[e["id"]] = [l["target"] for l in links
                                  if not l["embed"] and l.get("target")]

    # ---------------- 4. relation
    rdir = Path(relations_dir) if relations_dir else vault / "_data" / "relations"
    relation_files = sorted(rdir.rglob("*.jsonl")) if rdir.is_dir() else []
    id_index = set(x for x in by_id.keys())
    by_id_entity = {e["id"]: e for e in entities if isinstance(e["id"], str)}
    type_by_id = {e["id"]: e["type"] for e in entities if isinstance(e["id"], str)}
    body_links = out_links
    seen_rel_ids = defaultdict(list)
    n_relations = 0
    n_relation_errors = 0
    for rpath in relation_files:
        rel_file = str(rpath.relative_to(vault)) if str(rpath).startswith(str(vault)) else str(rpath)
        for lineno, raw_line in enumerate(rpath.read_text(encoding="utf-8").split("\n"), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                record = json.loads(line)
            except Exception as exc:  # noqa: BLE001
                n_relation_errors += 1
                add("error", "RELATION_JSON_INVALID", rpath,
                    "不是合法 JSON 行", detail=str(exc)[:200], line=lineno)
                continue
            n_relations += 1
            report["relations"].append(record)
            if "relation" in validators:
                errors = iter_schema_errors(validators["relation"], record)
                if errors:
                    n_relation_errors += 1
                    add("error", "RELATION_SCHEMA_INVALID", rpath,
                        "不符合 relation.schema.json", detail="; ".join(errors), line=lineno)
            rid = record.get("relation_id")
            if isinstance(rid, str):
                seen_rel_ids[rid].append("%s:%d" % (rel_file, lineno))
            for endpoint in ("subject", "object"):
                val = record.get(endpoint)
                if isinstance(val, str) and id_index and val not in id_index:
                    n_relation_errors += 1
                    add("error", "BROKEN_RELATION", rpath,
                        "%s 指向 vault 中不存在的实体：%s" % (endpoint, val), line=lineno)
            if record.get("subject") and record.get("subject") == record.get("object"):
                n_relation_errors += 1
                add("error", "RELATION_SELF_LOOP", rpath,
                    "subject 与 object 相同（自环），当前谓词表不允许",
                    detail="id=%s" % record.get("subject"), line=lineno)
            ev = record.get("evidence")
            if isinstance(ev, dict):
                for pid in (ev.get("passage_id") or []):
                    if isinstance(pid, str) and id_index and pid not in id_index:
                        n_relation_errors += 1
                        add("error", "SOURCE_TRACE_INCOMPLETE", rpath,
                            "evidence.passage_id 指向不存在的实体：%s" % pid, line=lineno)

            # ---- 谓词与端点的类型约束（RELATION_MODEL.md §3.1）
            if record.get("predicate") == "redefines":
                obj = record.get("object")
                otype = type_by_id.get(obj) if isinstance(obj, str) else None
                if otype and otype != "concept_state":
                    n_relation_errors += 1
                    add("error", "RELATION_REDEFINES_OBJECT_TYPE", rpath,
                        "redefines 的 object 必须是 concept_state",
                        detail="object=%s 实际 type=%s" % (obj, otype), line=lineno)

            # ---- 文件级权威规则（RELATION_MODEL.md §5、§6）
            is_main = os.path.basename(str(rpath)) == MAIN_RELATIONS_FILE
            conf = record.get("confidence")
            if is_main and isinstance(conf, (int, float)) and conf < CONFIDENCE_MAIN_MIN:
                n_relation_errors += 1
                add("error", "RELATION_CONFIDENCE_MAIN_THRESHOLD", rpath,
                    "confidence < %.2f 的关系不得进主库" % CONFIDENCE_MAIN_MIN,
                    detail="confidence=%s，请移到 %s" % (conf, CANDIDATE_RELATIONS_FILE),
                    line=lineno)
            if is_main and record.get("review_status") not in ("reviewed", "canonical"):
                n_relation_errors += 1
                add("error", "RELATION_MAIN_STATUS", rpath,
                    "主库只收已审核的关系（reviewed / canonical）",
                    detail="review_status=%s" % record.get("review_status"), line=lineno)
            if is_main:
                cb = record.get("created_by")
                if isinstance(cb, str) and cb.startswith("ai:"):
                    n_relation_errors += 1
                    add("error", "RELATION_AI_IN_MAIN", rpath,
                        "AI 不得写主库（relations.jsonl）",
                        detail="created_by=%s，AI 建议只能进 %s"
                               % (cb, CANDIDATE_RELATIONS_FILE), line=lineno)
            if isinstance(ev, dict) and record.get("review_status") in ("reviewed", "canonical") \
                    and ev.get("assertion_type") == "inferred" and not (ev.get("passage_id") or []):
                n_relation_errors += 1
                add("error", "RELATION_INFERRED_NO_EVIDENCE", rpath,
                    "已审核的 inferred 关系必须有段号（RELATION_MODEL.md §4）",
                    detail="assertion_type=inferred 且 passage_id 为空", line=lineno)

            # ---- 呈现层与语义层一致性（RELATION_MODEL.md §1）
            subj, obj = record.get("subject"), record.get("object")
            if isinstance(subj, str) and isinstance(obj, str):
                subj_e = by_id_entity.get(subj)
                if subj_e is not None:
                    targets = {t.casefold() for t in body_links.get(subj, [])}
                    if obj.casefold() not in targets:
                        report["view_mismatches"].append(
                            {"relation_id": rid, "subject": subj, "object": obj,
                             "file": subj_e["rel"]})
                        add("warning", "RELATION_VIEW_MISMATCH", subj_e["path"],
                            "语义层有这条边，但呈现层（正文）没有对应 wikilink",
                            detail="%s --%s--> %s" % (subj, record.get("predicate"), obj))
    for rid, where in sorted(seen_rel_ids.items()):
        if len(where) > 1:
            n_relation_errors += 1
            add("error", "RELATION_DUPLICATE_ID", rdir,
                "relation_id 重复：%s" % rid, detail="出现在 " + ", ".join(where))

    # ---------------- 5. 汇总
    sev = Counter(i["severity"] for i in report["issues"])
    report["summary"] = {
        "files_scanned": len(md_files),
        "entity_files": len(entities),
        "skipped": len(skipped),
        "errors": sev.get("error", 0),
        "warnings": sev.get("warning", 0),
        "infos": sev.get("info", 0),
        "wikilinks": n_links,
        "embeds": n_embeds,
        "broken_wikilinks": len(report["broken_wikilinks"]),
        "relations": n_relations,
        "relation_files": len(relation_files),
        "relation_errors": n_relation_errors,
        "duplicate_ids": len(report["duplicate_ids"]),
        "duplicate_canonical_names": len(report["duplicate_canonical_names"]),
        "filename_id_mismatches": len(report["filename_id_mismatches"]),
        "near_duplicate_canonical_names": len(report["near_duplicate_canonical_names"]),
        "alias_collisions": len(report["alias_collisions"]),
        "view_mismatches": len(report["view_mismatches"]),
        "by_type": dict(sorted(Counter(
            e["type"] for e in entities if e["type"]).items())),
        "by_authority": dict(sorted(Counter(
            e["authority_level"] for e in entities if e["authority_level"]).items())),
        "by_review_status": dict(sorted(Counter(
            e["review_status"] for e in entities if e["review_status"]).items())),
    }
    report["skipped_by_reason"] = dict(sorted(Counter(s["reason"] for s in skipped).items()))

    # 收敛说明：人工维护的 00_System/Validation/convergence-note.md，
    # 若存在则原文置顶写进报告（生成器只负责包含，不负责编内容）。
    note_path = vault / "00_System" / "Validation" / "convergence-note.md"
    report["convergence_note"] = (
        note_path.read_text(encoding="utf-8") if note_path.is_file() else None)
    report["convergence_note_path"] = (
        str(note_path.relative_to(vault)) if note_path.is_file() else None)

    if write:
        write_reports(report, report_dir or (vault / "_index" / "Reports"))
    return report


def resolve_target(target, link_index, vault, source_path):
    """wikilink 目标能否落到一个实体上。"""
    key = target.strip().casefold()
    if key in link_index:
        return True
    # 路径式链接：[[04_Concepts/objet-petit-a]]
    if "/" in target:
        p = Path(vault) / target
        if p.with_suffix(".md").is_file() or p.is_file():
            return True
    # 与源文件同目录的裸文件名
    p = Path(source_path).parent / (target + ".md")
    if p.is_file():
        return True
    return False


# ================================================================ 报告输出
def write_reports(report, report_dir):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "validation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / "validation-report.md").write_text(
        render_markdown(report), encoding="utf-8")


def _table(rows, header):
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(["---"] * len(header)) + "|"]
    out.extend("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    return out


def render_markdown(report):
    s = report["summary"]
    L = []
    a = L.append
    a("# Vault 校验报告 / Validation Report")
    a("")
    a("> 生成时间 `%s`　·　schema `%s`" % (report["generated_at"], report["schema"]))
    a("> vault `%s`" % report["vault_root"])
    a("")
    if report.get("convergence_note"):
        a("## 0. 本次收敛修了什么")
        a("")
        a(report["convergence_note"].strip())
        a("")
        if report.get("convergence_note_path"):
            a("*（本节来自 `%s`，由人工维护；生成器原样包含。）*"
              % report["convergence_note_path"])
            a("")
    a("## 1. 摘要")
    a("")
    a("| 指标 | 值 |")
    a("|---|---:|")
    for k in ("files_scanned", "entity_files", "skipped", "errors", "warnings", "infos",
              "wikilinks", "embeds", "broken_wikilinks", "relations", "relation_files",
              "relation_errors", "duplicate_ids", "duplicate_canonical_names",
              "filename_id_mismatches", "near_duplicate_canonical_names",
              "alias_collisions", "view_mismatches"):
        a("| `%s` | %s |" % (k, s.get(k, 0)))
    a("")
    verdict = "**通过**" if s["errors"] == 0 else "**不通过（有 error）**"
    a("结论：%s；warning %d 条。`--strict` 模式下 error 或 warning 任一存在即返回 1。"
      % (verdict, s["warnings"]))
    a("")

    a("## 2. 实体分布")
    a("")
    for title, key in (("按 type", "by_type"), ("按 authority_level", "by_authority"),
                       ("按 review_status", "by_review_status")):
        a("### %s" % title)
        a("")
        data = s.get(key) or {}
        if not data:
            a("（无实体）")
        else:
            a("| 值 | 数量 |")
            a("|---|---:|")
            for k, v in data.items():
                a("| `%s` | %d |" % (k, v))
        a("")

    a("## 3. 问题清单（按严重度）")
    a("")
    for severity, label in (("error", "错误"), ("warning", "警告"), ("info", "提示")):
        items = [i for i in report["issues"] if i["severity"] == severity]
        a("### %s（%d）" % (label, len(items)))
        a("")
        if not items:
            a("无。")
            a("")
            continue
        rows = []
        for i in items[:200]:
            rel = i["path"]
            try:
                rel = str(Path(i["path"]).relative_to(report["vault_root"]))
            except Exception:  # noqa: BLE001
                pass
            loc = "%s:%s" % (rel, i["line"]) if i.get("line") else rel
            rows.append([i["code"], loc, i["message"], (i.get("detail") or "")[:160]])
        L.extend(_table(rows, ["code", "位置", "说明", "细节"]))
        if len(items) > 200:
            a("")
            a("（仅显示前 200 条，完整清单见 validation-report.json）")
        a("")

    a("## 4. ID　文件名　canonical_name 一致性")
    a("")
    a("**文件名（不含 .md）必须等于 `id`** —— Obsidian 用文件名解析 `[[wikilink]]`，"
      "两者不一致时指向该 id 的链接会落到空处。")
    a("")
    if report["filename_id_mismatches"]:
        L.extend(_table(
            [["`%s`" % m["filename"], "`%s`" % m["id"], m["rel"],
              "`%s.md`" % m["id"]] for m in report["filename_id_mismatches"]],
            ["文件名（现状）", "id", "所在路径", "应重命名为"]))
    else:
        a("文件名与 id 全部一致。")
    a("")
    if not report["duplicate_ids"] and not report["duplicate_canonical_names"]:
        a("ID 与 canonical_name 均无重复。")
    for d in report["duplicate_ids"]:
        a("- **重复 id** `%s` → %s" % (d["id"], ", ".join("`%s`" % p for p in d["paths"])))
    for d in report["duplicate_canonical_names"]:
        a("- **重复 canonical_name** `%s`（type=`%s`）→ %s"
          % (d["canonical_name"], d["type"], ", ".join("`%s`" % p for p in d["paths"])))
    a("")
    if report["near_duplicate_canonical_names"]:
        a("### 4.1 归一化后碰撞（去重第 2 步：警告）")
        a("")
        L.extend(_table(
            [["`%s`" % d["type"], "`%s`" % d["normalized"],
              ", ".join("`%s`" % i for i in d["ids"])]
             for d in report["near_duplicate_canonical_names"]],
            ["type", "归一化 key", "候选 id"]))
        a("")
    if report["alias_collisions"]:
        a("### 4.2 别名撞上别人的 canonical_name（去重第 3 步：提示合并）")
        a("")
        L.extend(_table(
            [["`%s`" % d["alias"], "`%s`" % d["of"], "`%s`" % d["owned_by"]]
             for d in report["alias_collisions"]],
            ["alias", "属于", "但该 type 内它的 canonical_name 属于"]))
        a("")

    a("## 5. 断链清单")
    a("")
    if not report["broken_wikilinks"]:
        a("无断链。")
    else:
        rows = [[b["source"], b["line"] or "—", "`%s`" % b["target"],
                 b["alias"] or "—", b["origin"]] for b in report["broken_wikilinks"]]
        L.extend(_table(rows, ["来源", "行", "目标", "别名", "来源位置"]))
    a("")

    a("## 6. 关系（_data/relations/*.jsonl）")
    a("")
    a("- 关系文件 **%d** 个，记录 **%d** 条，错误 **%d** 条。"
      % (s["relation_files"], s["relations"], s["relation_errors"]))
    a("")
    if report["relations"]:
        rows = [[r.get("relation_id", "?"), r.get("subject", "?"), r.get("predicate", "?"),
                 r.get("object", "?"), r.get("authority_level", "?"),
                 r.get("review_status", "?")]
                for r in report["relations"] if isinstance(r, dict)]
        L.extend(_table(rows, ["relation_id", "subject", "predicate", "object",
                               "authority", "review"]))
    a("")
    a("### 6.1 呈现层一致性（RELATION_MODEL.md §1）")
    a("")
    a("语义层（jsonl）有边、呈现层（正文 `[[wikilink]]`）没有对应链接的关系 —— "
      "这些边在 Graph View 里看不见。")
    a("")
    if not report["view_mismatches"]:
        a("无语义层/呈现层不一致。")
    else:
        L.extend(_table(
            [["`%s`" % m["relation_id"], "`%s`" % m["subject"], "`%s`" % m["object"],
              m["file"]] for m in report["view_mismatches"]],
            ["relation_id", "subject", "object", "应补链接的文件"]))
    a("")

    skipped = report.get("skipped_by_reason") or {}
    a("## 7. 未参与校验的文件")
    a("")
    a("| 原因 | 数量 |")
    a("|---|---:|")
    for k, v in skipped.items():
        a("| `%s` | %d |" % (k, v))
    a("")
    if report.get("skipped"):
        a("<details><summary>逐条清单</summary>")
        a("")
        for item in report["skipped"]:
            a("- `%s` — %s" % (item["rel"], item["reason"]))
        a("")
        a("</details>")
        a("")

    a("## 8. 载入的 schema")
    a("")
    a("`%s`" % "`, `".join(report["schemas_loaded"]))
    a("")
    a("---")
    a("")
    a("*本报告由 `_scripts/_tools/validate_vault.py` 生成；校验过程只读 vault 内容。*")
    a("")
    return "\n".join(L)


# ================================================================ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Lacanian Knowledge OS — 节点与关系校验器（只读）")
    ap.add_argument("--vault", default=None, help="vault 根目录，默认由脚本位置推导")
    ap.add_argument("--relations", default=None, help="relation JSONL 目录")
    ap.add_argument("--report-dir", default=None, help="报告输出目录")
    ap.add_argument("--strict", action="store_true",
                    help="有 error 时返回非零（warning 不阻塞交付）")
    ap.add_argument("--warnings-as-errors", action="store_true",
                    help="连 warning 也算问题（零 warning 门禁）")
    ap.add_argument("--json", action="store_true", help="把报告 JSON 打到 stdout")
    ap.add_argument("--quiet", action="store_true", help="只打印一行结论")
    add_stamp_flag(ap)
    args = ap.parse_args(argv)

    vault = Path(args.vault).expanduser().resolve() if args.vault \
        else Path(__file__).resolve().parents[2]
    if not vault.is_dir():
        print("[fatal] vault 目录不存在: %s" % vault, file=sys.stderr)
        return 2

    if not args.json and not args.quiet:
        print("[vault] %s" % vault, file=sys.stderr)

    report = audit(vault, relations_dir=args.relations, write=False,
                   report_dir=args.report_dir)
    # 确定性时间戳必须在写盘**之前**定下来（默认由内容推导，重跑无 diff）
    apply_stamp(report, stamp=args.stamp)
    rdir = Path(args.report_dir) if args.report_dir else vault / "_index" / "Reports"
    write_reports(report, rdir)
    s = report["summary"]

    if not args.quiet:
        scan_line = ("[scan] md=%d entity=%d skipped=%d"
                     % (s["files_scanned"], s["entity_files"], s["skipped"]))
        print(scan_line, file=sys.stderr)
        print("[schemas] %s" % ", ".join(report["schemas_loaded"]), file=sys.stderr)
        print("[ids] duplicate_id=%d duplicate_canonical_name=%d"
              % (s["duplicate_ids"], s["duplicate_canonical_names"]), file=sys.stderr)
        print("[links] wikilinks=%d broken=%d embeds=%d"
              % (s["wikilinks"], s["broken_wikilinks"], s["embeds"]), file=sys.stderr)
        print("[relations] records=%d errors=%d"
              % (s["relations"], s["relation_errors"]), file=sys.stderr)

    result = ("[result] errors=%d warnings=%d infos=%d"
              % (s["errors"], s["warnings"], s["infos"]))
    print(result, file=sys.stderr)
    rdir = Path(args.report_dir) if args.report_dir else vault / "_index" / "Reports"
    print("[report] %s" % (rdir / "validation-report.md"), file=sys.stderr)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    # 退出码契约：
    #   --strict                → 只有 error 让退出码变 1（warning 是待办而非失败）
    #   --strict --warnings-as-errors → warning 也算问题（零 warning 门禁）
    failed = bool(s["errors"]) or (args.warnings_as_errors and bool(s["warnings"]))
    if args.strict and failed:
        return 1
    if args.strict and s["warnings"]:
        print("[hint] %d 条 warning 未导致失败；加 --warnings-as-errors 可把 warning 当失败"
              % s["warnings"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
