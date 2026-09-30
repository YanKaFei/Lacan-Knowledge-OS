#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.model — 统一 Export Model（Phase 4D.6 §5/§6/§36/§57/§59/§60）

唯一纪律：
    source FinalScholarlyAnswer  →  ExportDocument  →  {Markdown, JSON, HTML, Bundle}

**所有 renderer 只能消费 ExportDocument**，不得各自回去重新解释 source object
（否则「四格式内容一致」就只能靠人眼保证）。

硬门禁（§6）：
    claim 文本 / answer 段落 / citation passage_id / quoted span / limitations /
    abstention 必须**逐字不变**；允许变化的只有标题、显示标签、citation 格式与序列化。

身份与哈希（§59/§60）：
    source_answer_hash  来自核心答案（跨阶段身份）
    source_snapshot_hash 存储侧快照哈希（Project run / 4D.3 snapshot）
    export_payload_hash  **规范化 ExportDocument** 的哈希 —— 与格式无关，
                        因此 Markdown / HTML / JSON / Bundle 指向同一个 scholarly payload。
"""
from __future__ import annotations

import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)

EXPORT_MODEL_VERSION = "export-document/v1"
EXPORTER_VERSION = "export-system/v1"
SCHEMA_DIR = os.path.join(HERE, "schemas")

SCHEMA_EXPORT_DOCUMENT = "export_document_v1"
SCHEMA_BUNDLE_MANIFEST = "research_bundle_manifest_v1"
SCHEMA_CITATION_RECORD = "citation_record_v1"

SOURCE_TYPES = ("research_run", "research_note", "research_project", "saved_passage",
                "final_scholarly_answer")
FORMATS = ("markdown", "json", "html", "bundle")

# ⚠️ 必须覆盖**冻结核心真实会产出的全部状态**（4D.7 验收发现）：
#    只列 3 个时，PARTIALLY_SUPPORTED / VALIDATION_FAILED / INSUFFICIENT_EVIDENCE
#    的答案在导出层会抛 SCHEMA_VALIDATION_FAILED —— 那是产品层与核心状态词表脱节，
#    不是核心的问题。导出**原样保留**状态，绝不升级。
ANSWER_STATES = ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "PARTIALLY_SUPPORTED",
                 "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "ABSTAINED")

STATE_NOT_VALIDATED = ("VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE")

# 允许出现在导出里的「非学术」区块 —— 必须分区，不得与核心输出混排（§39/§40）
USER_BLOCK_LABELS = {
    "user_notes": "USER NOTES (not scholarly output)",
    "user_hypotheses": "USER HYPOTHESIS — NOT VALIDATED",
    "open_questions": "OPEN RESEARCH QUESTIONS (not claims)",
    "bibliography": "PROJECT BIBLIOGRAPHY (user references, not corpus provenance)",
}

ABSTENTION_TITLE = "Current corpus cannot support a reliable answer"


class ExportError(RuntimeError):
    """统一错误契约（§68）。"""

    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def as_dict(self):
        return {"ok": False, "code": self.code, "message": self.message,
                "detail": self.detail}


ERROR_CODES = ("EXPORT_SOURCE_NOT_FOUND", "EXPORT_SOURCE_MODIFIED", "BROKEN_REFERENCE",
               "SCHEMA_VALIDATION_FAILED", "BIBLIOGRAPHIC_METADATA_INCOMPLETE",
               "EXPORT_POLICY_DENIED", "EXPORT_WRITE_FAILED",
               "BUNDLE_VERIFICATION_FAILED", "UNSUPPORTED_FORMAT")


# ─────────────────────────────────────────────────────────── 规范化
def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def sha256_bytes(blob):
    h = hashlib.sha256()
    h.update(blob)
    return h.hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# 这些字段属于「每次导出都不同」的元数据，不参与 scholarly payload 哈希（§60）
_VOLATILE_KEYS = ("export_id", "created_at", "format", "rendered_at")


def canonical_payload(doc):
    """→ 去掉 volatile 字段后的规范 JSON（用于 export_payload_hash / content_hash）。"""
    d = {k: v for k, v in doc.items() if k not in _VOLATILE_KEYS}
    d.pop("export_payload_hash", None)
    d.pop("content_hash", None)
    return _canon(d)


def export_payload_hash(doc):
    return sha256_text(canonical_payload(doc))


def content_hash(doc):
    """§60：同一 source snapshot + 同一 options → 规范化 payload 必须一致。"""
    return sha256_text(_canon({
        "source_type": doc.get("source_type"),
        "source_id": doc.get("source_id"),
        "source_answer_hash": doc.get("source_answer_hash"),
        "sections": doc.get("sections"),
        "claims": doc.get("claims"),
        "citations": doc.get("citations"),
        "limitations": doc.get("limitations"),
        "abstention": doc.get("abstention"),
        "answer_state": doc.get("answer_state"),
    }))


# ─────────────────────────────────────────────────────────── 模型
def new_export_id(source_type, source_id):
    """`exp_<type>_<ts>_<rand4><hash4>`（§44：磁盘名不依赖 title，可排序、可区分）。

    ⚠️ 实测踩过：只按 (source_type, source_id, 秒级时间戳) 生成 id 时，
    **同一秒内导出同一来源两次会得到同一个 export_id** —— 第二次导出直接覆盖第一次
    （文件被改写、bundle 目录被替换）。因此加一个极短随机段，保证每次导出互不覆盖；
    §60 的确定性针对的是 **scholarly payload**（export_payload_hash），不是 export_id。
    """
    from datetime import datetime, timezone                            # noqa: PLC0415
    import secrets                                                     # noqa: PLC0415
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = re.sub(r"[^a-z0-9]+", "", str(source_type or "x").lower())[:8]
    h = sha256_text("%s|%s" % (source_type, source_id))[:4]
    return "exp_%s_%s_%s%s" % (tag, ts, secrets.token_hex(2), h)


def make_document(*, export_type, source_type, source_id, title, created_at,
                  question=None, answer_state=None, answer_state_label=None,
                  task_type=None, sections=None, claims=None, citations=None,
                  limitations=None, abstention=None, provenance=None,
                  bibliographic_metadata=None, source_answer_hash=None,
                  source_snapshot_hash=None, snapshot_integrity=None,
                  core_freeze_version=None, product_interface_version=None,
                  extra_blocks=None, export_options=None, notes=None):
    """构造 ExportDocument（**唯一**的数据入口）。"""
    if source_type not in SOURCE_TYPES:
        raise ExportError("SCHEMA_VALIDATION_FAILED",
                          "unknown source_type: %r" % source_type,
                          {"allowed": list(SOURCE_TYPES)})
    if answer_state is not None and answer_state not in ANSWER_STATES:
        raise ExportError("SCHEMA_VALIDATION_FAILED",
                          "unknown answer_state: %r" % answer_state,
                          {"allowed": list(ANSWER_STATES)})
    doc = {
        "schema_version": EXPORT_MODEL_VERSION,
        "export_id": None,                     # 由 finalize 填
        "export_type": export_type,
        "source_type": source_type,
        "source_id": source_id,
        "created_at": created_at,
        "title": title,
        "question": question,
        "answer_state": answer_state,
        "answer_state_label": answer_state_label,
        "task_type": task_type,
        "sections": list(sections or []),
        "claims": list(claims or []),
        "citations": list(citations or []),
        "limitations": list(limitations or []),
        "abstention": abstention,
        "provenance": provenance or {},
        "bibliographic_metadata": bibliographic_metadata or {},
        "source_answer_hash": source_answer_hash,
        "source_snapshot_hash": source_snapshot_hash,
        "snapshot_integrity": snapshot_integrity,
        "core_freeze_version": core_freeze_version,
        "product_interface_version": product_interface_version,
        "exporter_version": EXPORTER_VERSION,
        "export_options": export_options or {},
        "user_blocks": extra_blocks or {},
        "notes": list(notes or []),
        "evidence_role": ("SCHOLARLY_CORE_OUTPUT" if source_type in
                          ("research_run", "final_scholarly_answer")
                          else "WORKSPACE_DOCUMENT"),
    }
    doc["export_payload_hash"] = export_payload_hash(doc)
    doc["content_hash"] = content_hash(doc)
    return doc


def finalize_document(doc, export_id=None):
    """填 export_id（volatile），**不改变** export_payload_hash。"""
    out = dict(doc)
    out["export_id"] = export_id or new_export_id(doc.get("source_type"),
                                                  doc.get("source_id"))
    out["export_payload_hash"] = export_payload_hash(out)
    out["content_hash"] = content_hash(out)
    return out


# ─────────────────────────────────────────────────────────── 身份校验（§6）
def scholarly_identity(doc):
    """→ 参与「四格式一致」比较的 scholarly payload（不含排版信息）。"""
    return {
        "answer_state": doc.get("answer_state"),
        "question": doc.get("question"),
        "section_texts": [s.get("text") for s in (doc.get("sections") or [])],
        "claim_texts": [c.get("claim_text") for c in (doc.get("claims") or [])],
        "citation_ids": [c.get("passage_id") for c in (doc.get("citations") or [])],
        "quoted_spans": [c.get("quoted_span") for c in (doc.get("citations") or [])],
        "limitations": list(doc.get("limitations") or []),
        "abstention": doc.get("abstention"),
    }


def assert_identity(source_doc, other_doc):
    """两个 ExportDocument 的 scholarly payload 必须一致；否则 `EXPORT_SOURCE_MODIFIED`。"""
    a, b = scholarly_identity(source_doc), scholarly_identity(other_doc)
    if a != b:
        diff = [k for k in a if a[k] != b.get(k)]
        raise ExportError("EXPORT_SOURCE_MODIFIED",
                          "scholarly payload differs across formats",
                          {"differing_fields": diff})
    return True


# ─────────────────────────────────────────────────────────── schema 校验（§36）
def schema_path(name):
    return os.path.join(SCHEMA_DIR, "%s.json" % name)


def load_schema(name):
    with open(schema_path(name), encoding="utf-8") as f:
        return json.load(f)


_JSON_TYPES = {"object": dict, "array": list, "string": str, "integer": int,
              "number": (int, float), "boolean": bool, "null": type(None)}


def _one_type_ok(value, want):
    if want == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if want == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    py = _JSON_TYPES.get(want)
    return isinstance(value, py) if py else True


def _type_ok(value, want):
    """支持 JSON Schema 的 `"type": "x"` 与 `"type": ["x","null"]` 两种写法。"""
    if isinstance(want, (list, tuple)):
        return any(_one_type_ok(value, w) for w in want)
    return _one_type_ok(value, want)


def validate(doc, schema_name=SCHEMA_EXPORT_DOCUMENT):
    """轻量 JSON Schema 校验（够用即可：type / required / enum / additionalProperties）。"""
    schema = load_schema(schema_name)
    problems = []

    def check(obj, sch, path):
        if "type" in sch and not _type_ok(obj, sch["type"]):
            problems.append("%s: expected %s" % (path, sch["type"]))
            return
        if "enum" in sch and obj not in sch["enum"]:
            problems.append("%s: %r not in enum" % (path, obj))
        if sch.get("type") == "object":
            for key in sch.get("required", []):
                if key not in obj:
                    problems.append("%s: missing required %s" % (path, key))
            props = sch.get("properties") or {}
            if sch.get("additionalProperties") is False:
                for key in obj:
                    if key not in props:
                        problems.append("%s: unexpected property %s" % (path, key))
            for key, sub in props.items():
                if key in obj and obj[key] is not None:
                    check(obj[key], sub, "%s.%s" % (path, key))
        elif sch.get("type") == "array" and "items" in sch:
            for i, item in enumerate(obj):
                check(item, sch["items"], "%s[%d]" % (path, i))
    check(doc, schema, "$")
    if problems:
        raise ExportError("SCHEMA_VALIDATION_FAILED", "export document invalid",
                          {"problems": problems[:12]})
    return True
