#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scholarly_api.objects — Phase 4D.0 稳定领域对象（Stable Domain Objects）

纪律
────
* 这里的 schema 是**产品层与 Scholarly Core 之间的契约**：产品层只消费这些字段；
  核心内部结构的变动不得穿透到产品层（API 负责投影）。
* schema 一旦发布（v1）即为**稳定契约**：加字段需新版本，不得悄悄改语义。
* 每个对象都有 `SCHEMA_VERSION`；核心侧实现的 hash 由
  `_data/core_freeze/scholarly_core_freeze_v1.json` 钉住。

导出
────
    SCHEMAS           {object_name: JSON Schema}
    SCHEMA_VERSIONS   {object_name: version_string}
    validate(name, obj) -> (ok, errors)
    dump_schemas(dir)  把 schema 写到 scholarly_api/schemas/*.json（可复现）
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(HERE, "schemas")


def _obj(props, required=None, desc="", version=None):
    d = {
        "type": "object",
        "additionalProperties": False,
        "properties": props,
    }
    if desc:
        d["description"] = desc
    if required:
        d["required"] = list(required)
    return d


S = {"type": "string"}
SN = {"type": ["string", "null"]}
I = {"type": "integer"}
B = {"type": "boolean"}
ON = {"type": ["object", "null"]}
AN = {"type": ["array", "null"]}
AS = {"type": "array", "items": S}
# 核心 warning 是结构化对象 {code,message,severity,action}，也允许纯字符串
WARN = {"type": ["array", "null"], "items": {"type": ["string", "object"]}}
YEAR = {"type": ["string", "integer", "null"]}


def _array_of(item, nullable=False):
    t = {"type": "array", "items": item}
    if nullable:
        t["type"] = ["array", "null"]
    return t


# ─────────────────────────────────────────────────────────── 稳定对象定义
SCHEMAS = {
    # 1. ResearchRequest（产品层的输入）
    "ResearchRequest": _obj({
        "request_id": SN,
        "question": {"type": "string", "minLength": 1},
        "language": {"type": ["string", "null"],
                     "description": "zh / fr / en / any；null = 核心自行判定"},
        "research_mode": {
            "type": "string",
            "enum": ["quick", "scholarly", "concept_definition", "concept_relation",
                     "comparison", "diachronic", "seminar_specific", "case_research",
                     "freud_to_lacan", "philosophy_to_lacan", "topology_matheme",
                     "translation_terminology"],
            "description": "mode 只是**task routing 提示**，不能绕过 core contract"},
        "constraints": ON,
        "requested_source_layers": _array_of(S, nullable=True),
        "requested_output_depth": {"type": ["string", "null"],
                                  "enum": ["brief", "standard", "deep", None]},
    }, required=["question"], desc="Phase 4D.0 稳定对象 1/15：研究请求（产品层输入）"),

    # 2. ResearchContract（现有对象；产品层只读）
    "ResearchContract": _obj({
        "schema_version": S,
        "task_id": S,
        "question": S,
        "task_type": SN,
        "status": {"type": "string", "enum": ["READY", "NOT_READY"]},
        "evidence_state": SN,
        "execution_state": SN,
        "answer_permission": S,
        "permission_reasons": _array_of(S, nullable=True),
        "synthesis_template": SN,
        "research_contract_summary": ON,
        "source_layers": ON,
        "warnings": WARN,
    }, required=["schema_version", "task_id", "status", "answer_permission"],
        desc="Phase 4D.0 稳定对象 2/15：研究契约（产品层只读）"),

    # 3. ResearchExecutionResult
    "ResearchExecutionResult": _obj({
        "execution_state": SN,
        "completed_operations": _array_of(S, nullable=True),
        "completed_lanes": _array_of(S, nullable=True),
        "constraints_applied": ON,
        "limitations": _array_of(S, nullable=True),
    }, required=["execution_state"],
        desc="Phase 4D.0 稳定对象 3/15：研究执行结果"),

    # 4. EvidencePacket
    "EvidencePacket": _obj({
        "evidence_id": SN,
        "passage_id": S,
        "seminar": SN,
        "session": SN,
        "language": SN,
        "source_layer": SN,
        "witness": SN,
        "text": SN,
        "context": ON,
        "provenance_status": SN,
        "citation_eligibility": SN,
        "relation_level": SN,
        "formalism_metadata": ON,
        "terminology_metadata": ON,
    }, required=["passage_id"],
        desc="Phase 4D.0 稳定对象 4/15：证据包（可回溯到 passage/witness）"),

    # 5. SynthesisInput（SynthesisInputContract 的稳定产品表示）
    "SynthesisInput": _obj({
        "schema_version": S,
        "task_id": S,
        "question": S,
        "task_type": SN,
        "evidence_state": SN,
        "answer_permission": S,
        "answer_permissions": ON,
        "claim_permissions": ON,
        "citation_policy": ON,
        "abstention_requirements": ON,
        "usable_evidence_ids": _array_of(S, nullable=True),
        "warnings": WARN,
    }, required=["schema_version", "task_id", "answer_permission"],
        desc="Phase 4D.0 稳定对象 5/15：SynthesisInput 的稳定表示"),

    # 6. ValidatedClaim
    "ValidatedClaim": _obj({
        "claim_id": S,
        "claim_type": SN,
        "claim_text": S,
        "epistemic_status": SN,
        "evidence_ids": _array_of(S, nullable=True),
        "entailment_status": SN,
        "source_role_status": SN,
    }, required=["claim_id", "claim_text"],
        desc="Phase 4D.0 稳定对象 6/15：通过验证的断言"),

    # 7. CitationBinding
    "CitationBinding": _obj({
        "claim_id": SN,
        "passage_id": S,
        "quoted_span": SN,
        "citation_status": SN,
        "source_layer": SN,
        "provenance_status": SN,
    }, required=["passage_id"],
        desc="Phase 4D.0 稳定对象 7/15：claim → passage 引用绑定"),

    # 8. FinalScholarlyAnswer
    "FinalScholarlyAnswer": _obj({
        "schema_version": S,
        "api_version": S,
        "task_id": SN,
        "question": S,
        "task_type": SN,
        "answer_state": S,
        "answer_permission": S,
        "sections": ON,
        "validated_claims": _array_of({"$ref": "#/$defs/ValidatedClaim"}),
        "citations": _array_of({"$ref": "#/$defs/CitationBinding"}),
        "source_limitations": _array_of(S, nullable=True),
        "abstention": {"anyOf": [{"$ref": "#/$defs/AbstentionResult"}, {"type": "null"}]},
        "warnings": WARN,
        "summary": ON,
        # ★ Phase 5A（P5A-001 / PDR-0001）：校验器诊断的**结构化**容器。
        #   用户可见载荷（sections/claims/citations/source_limitations）不含内部诊断；
        #   诊断一律经 presentation taxonomy 归入 AUDIT_DIAGNOSTIC（Advanced / Audit Bundle）。
        "audit_diagnostics": ON,
        "provenance": ON,
    }, required=["schema_version", "api_version", "question", "answer_state",
                 "answer_permission"],
        desc="Phase 4D.0 稳定对象 8/15：最终学术回答（产品层唯一答案形态）；"
             "Phase 5A 起为 v1.1（新增 audit_diagnostics，学术语义不变）"),

    # 9. AbstentionResult
    "AbstentionResult": _obj({
        "category": SN,
        "categories": _array_of(S, nullable=True),
        "missing_information": _array_of(S, nullable=True),
        "available_partial_information": _array_of(S, nullable=True),
        "required_sources": _array_of(S, nullable=True),
        "corpus_scan_reference": ON,
        "metadata_scan_reference": ON,
    }, desc="Phase 4D.0 稳定对象 9/15：弃权结果（含扫描凭据引用）"),

    # 10. ProvenanceRecord
    "ProvenanceRecord": _obj({
        "passage_id": S,
        "corpus_source": SN,
        "witness": SN,
        "passage_realization": SN,
        "seminar": SN,
        "session": SN,
        "document": SN,
        "edition": SN,
        "source_layer": SN,
        "trace_status": SN,
        "trace_missing": _array_of(S, nullable=True),
        "chain": _array_of(ON, nullable=True),
    }, required=["passage_id"],
        desc="Phase 4D.0 稳定对象 10/15：溯源记录（可回答『这句话来自哪里』）"),

    # ---- 只读访问对象（§5 的 search / get_* 返回） ----
    "PassageRecord": _obj({
        "passage_id": S,
        "seminar": SN,
        "session": SN,
        "language": SN,
        "text": SN,
        "source_layer": SN,
        "authority_level": SN,
        "text_role": SN,
        "witness": SN,
        "trace_status": SN,
        "year_from": YEAR,
        "year_to": YEAR,
        "provenance": ON,
    }, required=["passage_id"],
        desc="Phase 4D.0 稳定对象 11/15：单段记录"),

    "PassageContext": _obj({
        "passage_id": S,
        "before": I,
        "after": I,
        "session_id": SN,
        "items": _array_of({"$ref": "#/$defs/PassageRecord"}),
    }, required=["passage_id", "items"],
        desc="Phase 4D.0 稳定对象 12/15：上下文窗口"),

    "PassageSearchResult": _obj({
        "query": S,
        "filters": ON,
        "evidence": _array_of({"$ref": "#/$defs/EvidencePacket"}),
        "n": I,
        "warnings": WARN,
    }, required=["query", "evidence", "n"],
        desc="Phase 4D.0 稳定对象 13/15：检索结果"),

    "ConceptRecord": _obj({
        "concept_id": S,
        "canonical_name": SN,
        "aliases": _array_of(S, nullable=True),
        "status": SN,
        "definition_summary": SN,
        "relations": _array_of(ON, nullable=True),
        "seminars": _array_of(S, nullable=True),
        "terminology": ON,
        "states": _array_of(ON, nullable=True),
        "evidence_ids": _array_of(S, nullable=True),
    }, required=["concept_id"],
        desc="Phase 4D.0 稳定对象 14/15：概念记录（ontology 只读视图）"),

    "SeminarRecord": _obj({
        "seminar_id": S,
        "title": SN,
        "year_from": YEAR,
        "year_to": YEAR,
        "sessions": _array_of(ON, nullable=True),
        "concepts": _array_of(S, nullable=True),
        "passage_count": I,
        "source_layers": _array_of(S, nullable=True),
    }, required=["seminar_id"],
        desc="Phase 4D.0 稳定对象 15/15：研讨班记录"),

    # ---- 错误信封：API 绝不静默降级，绝不替核心补答 ----
    "ApiError": _obj({
        "ok": {"const": False},
        "error_code": S,
        "message": S,
        "detail": ON,
        "resolution": S,
    }, required=["ok", "error_code", "message"],
        desc="产品层错误信封（含明确 resolution，绝不回退到模型自身知识）"),
}

def _kebab(name):
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i:
            out.append("-")
        out.append(ch.lower())
    return "".join(out)


SCHEMA_VERSIONS = {k: "%s/v1" % _kebab(k) for k in SCHEMAS}
# Phase 5A：FinalScholarlyAnswer 为 v1.1（新增 audit_diagnostics 字段）。
#   按 4D.0「加字段 = 新版本」：不静默修改稳定 schema。
#   消费者必须同时接受 v1（RC1.1 历史快照）与 v1.1（新答案）。
SCHEMA_VERSIONS["FinalScholarlyAnswer"] = "final-scholarly-answer/v1.1"
ANSWER_SCHEMA_VERSIONS_SUPPORTED = ("final-scholarly-answer/v1",
                                    "final-scholarly-answer/v1.1")


# 递归解析 `$ref` 到 `#/$defs/<Object>`（各 schema 自带 $defs 副本，便于单独校验）
def _with_defs(name, seen=None):
    seen = seen or set()
    if name in seen:
        return {}
    seen = seen | {name}
    refs = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "$ref" and isinstance(v, str) and v.startswith("#/$defs/"):
                    refs.add(v.split("/")[-1])
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(SCHEMAS[name])
    defs = {}
    for r in sorted(refs):
        if r in SCHEMAS:
            defs[r] = _with_defs(r, seen).get(r, SCHEMAS[r])
    doc = dict(SCHEMAS[name])
    doc["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    # Phase 5A：$id 跟随 SCHEMA_VERSIONS（FinalScholarlyAnswer 已升 v1.1）
    doc["$id"] = SCHEMA_VERSIONS.get(name, "%s/v1" % _kebab(name))
    doc["title"] = name
    if defs:
        doc["$defs"] = defs
    return {name: doc}


def schema_doc(name):
    """→ 可直接交给 jsonschema 校验的完整 schema（含 $defs）。"""
    return _with_defs(name)[name]


def validate(name, obj):
    """→ (ok, errors)。无 jsonschema 时退化为「必填字段存在性」检查。"""
    if name not in SCHEMAS:
        return False, ["未知稳定对象：%s" % name]
    try:
        import jsonschema  # noqa: PLC0415
        v = jsonschema.Draft202012Validator(schema_doc(name))
        errs = ["%s: %s" % ("/".join(str(p) for p in e.absolute_path) or "(root)",
                            e.message) for e in v.iter_errors(obj)]
        return (not errs), errs
    except ImportError:
        missing = [k for k in SCHEMAS[name].get("required", []) if k not in obj]
        return (not missing), ["缺必填字段 %s" % k for k in missing]
    except Exception as exc:  # noqa: BLE001
        return False, ["schema 校验器异常：%s" % exc]


def dump_schemas(out_dir=SCHEMA_DIR):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name in SCHEMAS:
        p = os.path.join(out_dir, "%s.json" % _kebab(name))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(schema_doc(name), f, ensure_ascii=False, indent=2, sort_keys=True)
        written.append(p)
    return written


if __name__ == "__main__":
    for p in dump_schemas():
        print(p)
