#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scholarly_api.core — Phase 4D.0 稳定访问层（Stable API Boundary）

本模块是**唯一**允许 import Scholarly Core 内部实现的模块。产品层（UI / MCP /
Obsidian 插件 / Agent）只允许 import `scholarly_api`，不得绕过它访问
validator / repair / judge / Gold evaluator / human review 数据（§5）。

返回形态
────────
* 所有成功返回都是 `scholarly_api.objects` 里的**稳定对象**（v1 schema 校验通过）。
* 失败返回 `ApiError`（`ok=False`），**绝不**静默降级、**绝不**用模型自身知识补答。
* `research()` 默认使用 **deterministic mock provider**（不发网络请求）；
  真实 LLM 必须显式 `options={"provider": "llm"}`，且凭据不可用时返回 ApiError。

冻结关系
────────
core 的语义由 `_data/core_freeze/scholarly_core_freeze_v1.json` 钉住；
本模块只做编排与投影，不重新实现任何研究/验证语义。
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)

if os.path.join(VAULT, "_scripts", "_tools") not in sys.path:
    sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))
if os.path.join(VAULT, "_scripts", "_tools", "lacan_mcp") not in sys.path:
    sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools", "lacan_mcp"))

from . import objects as O          # noqa: E402
from . import policy as P           # noqa: E402

API_VERSION = "scholarly-api/v1"
# ★ Phase 5A（P5A-001 / PDR-0001）：FinalScholarlyAnswer 增加 `audit_diagnostics` 字段
#   （校验器诊断的结构化容器）→ 按 4D.0「加字段 = 新版本」规则升到 v1.1。
#   学术载荷（claims / citations / answer_state / source_limitations）语义**不变**。
ANSWER_SCHEMA_VERSION = "final-scholarly-answer/v1.1"
AUDIT_SCHEMA_VERSION = "answer-audit/v1"
CORE_FREEZE_VERSION = "scholarly_core_freeze_v1"
FREEZE_PATH = os.path.join(VAULT, "_data", "core_freeze",
                           "scholarly_core_freeze_v1.json")

# mode → 核心 task_type（mode 只是 routing 提示，不改变任何 contract 语义）
MODE_TO_TASK_TYPE = {
    "scholarly": "concept_definition",
    "quick": "concept_definition",
    "concept_definition": "concept_definition",
    "concept_relation": "concept_relation",
    "comparison": "concept_relation",
    "diachronic": "diachronic_development",
    "seminar_specific": "seminar_specific",
    "case_research": "case_research",
    "freud_to_lacan": "freud_to_lacan",
    "philosophy_to_lacan": "philosophy_to_lacan",
    "topology_matheme": "topology_matheme",
    "translation_terminology": "translation_terminology",
}

# 修复/剔除日志行：属核心内部记录，不进产品的 source_limitations（原文仍在 sections 内）
_REPAIR_LINE = re.compile(r"(已剔除|未通过验证|NOT_ENTAILED|PARTIALLY_ENTAILED|"
                          r"CONTRADICTED|SOURCE_ROLE_MISMATCH|被剔除)")


# ────────────────────────────────────────────────────────────── 内部工具
def _err(code, message, resolution, detail=None):
    return {"ok": False, "error_code": code, "message": message,
            "detail": detail or {}, "resolution": resolution}


# ── provider 诊断（Phase 4E §12/§14）────────────────────────────────────────
#   只做两件事：① 把已配置的 provider 凭据从任何对外文本里抹掉；② 在**内部**
#   diagnostic 里区分 provider 失败的种类。两者都**不**改变公开错误码契约。
_PROVIDER_DIAGNOSTIC_RULES = (
    ("PROVIDER_AUTH_FAILED", ("401", "403", "unauthorized", "forbidden",
                              "invalid api key", "invalid_api_key",
                              "authentication", "api key not", "permission denied")),
    ("PROVIDER_RATE_LIMITED", ("429", "rate limit", "rate_limit", "too many requests",
                               "quota", "insufficient balance", "overloaded")),
    ("PROVIDER_TIMEOUT", ("timed out", "timeout", "read timeout", "deadline exceeded")),
    ("PROVIDER_BAD_RESPONSE", ("json", "decode", "expecting value", "non-json",
                               "not json", "no choices", "empty response",
                               "未返回结构化结果", "failed to parse")),
    ("PROVIDER_CONNECTION_FAILED", ("connection", "unreachable", "name or service",
                                    "temporary failure", "ssl", "certificate",
                                    "network", "connection reset", "refused")),
)


def _stable_hash(obj):
    """对象身份的确定性 hash（排序键 + 紧凑分隔符；跨进程稳定）。"""
    import hashlib as _hashlib                            # noqa: PLC0415
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return _hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _redact_secrets(value):
    """从对外文本里抹掉 provider 凭据（§12：key 不得进日志/响应/工件）。"""
    out = str(value or "")
    for name in ("DSH_SYNTHESIS_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY"):
        secret = os.environ.get(name)
        if secret and len(secret) >= 8:
            out = out.replace(secret, "<redacted-api-key>")
    # 兜底：即使凭据不在环境里，也不让 `Bearer xxx` / `sk-xxxx` 形态漏出去
    out = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1<redacted>", out)
    out = re.sub(r"\bsk-[A-Za-z0-9_\-]{8,}", "<redacted-api-key>", out)
    return out


def _provider_diagnostic(detail_text):
    """provider 失败的**内部**子分类（§14）；无法归类时如实返回 UNCLASSIFIED。"""
    blob = str(detail_text or "").lower()
    for code, needles in _PROVIDER_DIAGNOSTIC_RULES:
        if any(n in blob for n in needles):
            return code
    return "PROVIDER_ERROR_UNCLASSIFIED"


def _schema(name, obj):
    ok, errs = O.validate(name, obj)
    if not ok:
        obj = dict(obj)
        obj["_schema_errors"] = errs[:5]
    return obj


def _core_freeze_version():
    if os.path.isfile(FREEZE_PATH):
        try:
            with open(FREEZE_PATH, encoding="utf-8") as f:
                return json.load(f).get("freeze_version", CORE_FREEZE_VERSION)
        except Exception:  # noqa: BLE001
            pass
    return CORE_FREEZE_VERSION


def _load_passage_store_index(kind):
    """只读 canonical passage store 的索引文件（seminars/sessions）。"""
    p = os.path.join(VAULT, "_data", "passage_store", "%s.jsonl" % kind)
    rows = []
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def _ev_get(ev, *names, default=None):
    for n in names:
        if isinstance(ev, dict) and ev.get(n) is not None:
            return ev[n]
    return default


def _derive_source_layer(ev):
    """从**既有**核心字段机械派生 source_layer（规则写在 scholarly_api/README.md）。

    * translation_id 存在且 authority_level != L1  → <auth>_RECOVERED
    * text_role == "transcription"                → <auth>_TRANSCRIPTION
    * text_role == "edition"                      → <auth>_EDITION
    * 其余 → None（**不猜**）
    """
    if not isinstance(ev, dict):
        return None
    if ev.get("source_layer") or ev.get("layer"):
        return ev.get("source_layer") or ev.get("layer")
    auth = ev.get("authority_level")
    role = ev.get("text_role")
    if role == "transcription" and auth:
        return "%s_TRANSCRIPTION" % auth
    if role == "edition" and auth:
        return "%s_EDITION" % auth
    if auth and str(auth).startswith("L2"):
        # L2 = recovered 层；具体承载文件由 witness/corpus_source 给出
        return "L2_RECOVERED"
    if ev.get("translation_id") and auth and auth != "L1":
        return "%s_RECOVERED" % auth
    return None


def _to_evidence_packet(ev):
    """核心 evidence 条目 → EvidencePacket（容错投影，字段缺失即 null）。"""
    pid = _ev_get(ev, "passage_id", "id", "resolved_passage")
    prov = _ev_get(ev, "provenance", default={}) or {}
    return _schema("EvidencePacket", {
        "evidence_id": _ev_get(ev, "evidence_id"),
        "passage_id": pid or "unknown",
        "seminar": _ev_get(ev, "seminar_id", "seminar"),
        "session": _ev_get(ev, "session_id", "session"),
        "language": _ev_get(ev, "language"),
        "source_layer": _derive_source_layer(ev),
        "witness": _ev_get(ev, "witness_id", "witness")
                   or (prov.get("witness") if isinstance(prov, dict) else None),
        "text": _ev_get(ev, "text", "raw_text", "normalized_text", "excerpt"),
        "context": _ev_get(ev, "context", default={}) or {},
        "provenance_status": _ev_get(ev, "trace_status", "provenance_status"),
        "citation_eligibility": _ev_get(ev, "citation_eligibility"),
        "relation_level": _ev_get(ev, "relation_strength", "relation_level"),
        "formalism_metadata": _ev_get(ev, "formalism", "formalism_metadata"),
        "terminology_metadata": _ev_get(ev, "terminology", "terminology_metadata"),
    })


def _to_passage_record(ev):
    pid = _ev_get(ev, "passage_id", "id", "resolved_passage")
    return _schema("PassageRecord", {
        "passage_id": pid or "unknown",
        "seminar": _ev_get(ev, "seminar_id", "seminar"),
        "session": _ev_get(ev, "session_id", "session"),
        "language": _ev_get(ev, "language"),
        "text": _ev_get(ev, "text", "raw_text", "normalized_text"),
        "source_layer": _derive_source_layer(ev),
        "authority_level": _ev_get(ev, "authority_level"),
        "text_role": _ev_get(ev, "text_role"),
        "witness": _ev_get(ev, "witness_id", "witness"),
        "trace_status": _ev_get(ev, "trace_status"),
        "year_from": _ev_get(ev, "year_from"),
        "year_to": _ev_get(ev, "year_to"),
        "provenance": _ev_get(ev, "provenance", default={}) or {},
    })


def _project_contract(contract):
    return _schema("ResearchContract", {
        "schema_version": contract.get("schema_version"),
        "task_id": contract.get("task_id"),
        "question": contract.get("question"),
        "task_type": contract.get("task_type"),
        "status": contract.get("status"),
        "evidence_state": contract.get("evidence_state"),
        "execution_state": contract.get("execution_state"),
        "answer_permission": contract.get("answer_permission"),
        "permission_reasons": contract.get("permission_reasons") or [],
        "synthesis_template": contract.get("synthesis_template"),
        "research_contract_summary": contract.get("research_contract_summary"),
        "source_layers": contract.get("source_layers"),
        "warnings": contract.get("warnings") or [],
    })


def _project_execution(contract):
    lanes = contract.get("execution_lanes") or {}
    completed = []
    if isinstance(lanes, dict):
        for name, v in lanes.items():
            st = v.get("status") if isinstance(v, dict) else v
            if st in ("EXECUTED", "SATISFIED", "COMPLETED"):
                completed.append(name)
    summary = contract.get("research_contract_summary") or {}
    return _schema("ResearchExecutionResult", {
        "execution_state": contract.get("execution_state"),
        "completed_operations": (summary.get("resolved_operations")
                                 if isinstance(summary, dict) else None) or [],
        "completed_lanes": completed,
        "constraints_applied": (summary.get("constraints")
                                if isinstance(summary, dict) else {}) or {},
        "limitations": contract.get("failure_modes") or [],
    })


def _project_synthesis_input(contract):
    usable = []
    for ev in (contract.get("usable_evidence") or []):
        pid = _ev_get(ev, "passage_id", "id")
        if pid:
            usable.append(pid)
    return _schema("SynthesisInput", {
        "schema_version": contract.get("schema_version"),
        "task_id": contract.get("task_id"),
        "question": contract.get("question"),
        "task_type": contract.get("task_type"),
        "evidence_state": contract.get("evidence_state"),
        "answer_permission": contract.get("answer_permission"),
        "answer_permissions": contract.get("answer_permissions"),
        "claim_permissions": contract.get("claim_permissions"),
        "citation_policy": contract.get("citation_policy"),
        "abstention_requirements": contract.get("abstention_requirements"),
        "usable_evidence_ids": usable,
        "warnings": contract.get("warnings") or [],
    })


def _project_abstention(answer):
    ab = answer.get("abstention")
    if not isinstance(ab, dict):
        return None
    codes = ab.get("abstention_reason_codes") or []
    scan_refs = []
    for c in (answer.get("claims") or []):
        ref = c.get("corpus_scan_ref")
        if isinstance(ref, dict):
            scan_refs.append(ref)
    corpus_ref = next((r for r in scan_refs
                       if r.get("source") in ("terminology_lane", "source_layer_corpus")),
                      None)
    meta_ref = next((r for r in scan_refs if r.get("source") == "metadata_scan"), None)
    return _schema("AbstentionResult", {
        "category": codes[0] if codes else None,
        "categories": codes,
        "missing_information": ab.get("missing_information") or [],
        "available_partial_information": ab.get("available_partial_information") or [],
        "required_sources": ab.get("next_required_sources") or [],
        "corpus_scan_reference": corpus_ref,
        "metadata_scan_reference": meta_ref,
    })


def _project_claims(answer, entailment):
    """→ [ValidatedClaim]；entailment 结果用于填 entailment_status / source_role_status。"""
    by_final = {}
    for r in (entailment or {}).get("results") or []:
        for key in (r.get("final_claim_id"), r.get("claim_id")):
            if key:
                by_final[key] = r
    out = []
    for c in (answer.get("claims") or []):
        cid = c.get("claim_id")
        r = by_final.get(cid) or {}
        status = r.get("status")
        out.append(_schema("ValidatedClaim", {
            "claim_id": cid,
            "claim_type": c.get("claim_type"),
            "claim_text": c.get("claim_text"),
            "epistemic_status": c.get("epistemic_status"),
            "evidence_ids": c.get("evidence_ids") or [],
            "entailment_status": status,
            "source_role_status": ("SOURCE_ROLE_MISMATCH"
                                   if status == "SOURCE_ROLE_MISMATCH" else "OK"),
        }))
    return out


def _project_citations(answer):
    quotes = {}
    for c in (answer.get("claims") or []):
        q = c.get("quotation") or {}
        if q.get("passage_id"):
            quotes[(c.get("claim_id"), q["passage_id"])] = q.get("exact_span")
    out = []
    for blk in (answer.get("citations") or []):
        cid = blk.get("claim_id")
        for ps in (blk.get("passages") or []):
            pid = ps.get("passage_id")
            out.append(_schema("CitationBinding", {
                "claim_id": cid,
                "passage_id": pid or "unknown",
                "quoted_span": quotes.get((cid, pid)),
                "citation_status": ps.get("citation_eligibility"),
                "source_layer": ps.get("source_layer"),
                "provenance_status": ps.get("trace_status"),
            }))
    return out


def _source_limitations(answer):
    """产品的 source_limitations：只保留来源层事实，剔除核心内部修复日志行。"""
    lines = []
    for key in ("limitations", "source_notes"):
        for line in str(answer.get(key) or "").split("\n"):
            s = line.strip()
            if not s:
                continue
            if _REPAIR_LINE.search(s):
                continue
            lines.append(s)
    return lines



# ── Phase 5A / P5A-001：validator 诊断的**结构化**呈现路由 ─────────────────
#   原则（§4/§9）：不隐藏、不删除、不靠关键词猜测；diagnostic 必须 100% 保留到 Audit。
#   冻结渲染器（synthesis_validation.render_validated_answer）把诊断写进
#   `sections["limitations"]`（每行 = "- 已剔除未通过蕴含验证的断言：<text[:80]>（<status>）"）
#   与 `sections["brief_answer"]`（验证计量摘要），同时**已经**在 answer 上留下结构化副本
#   `answer["rejected_claims"]`。因此这里按**结构化重建 + 行级精确比对**摘除，
#   不做「包含 NOT_ENTAILED 就删」这类脆弱正则。
_REPAIR_LINE_PREFIX = "- 已剔除未通过蕴含验证的断言："
_BRIEF_ANSWER_SECTION = "brief_answer"


def _rejected_diagnostic_lines(answer):
    """由**结构化** rejected_claims 重建诊断行（与冻结渲染器同格式）。"""
    out = []
    for r in (answer or {}).get("rejected_claims") or []:
        text = str(r.get("claim_text"))[:80]
        status = str(r.get("status"))
        out.append("%s%s（%s）" % (_REPAIR_LINE_PREFIX, text, status))
    return out


def _route_validator_diagnostics(sections, answer, pipeline):
    """→ (user_facing_sections, audit_diagnostics)。

    * 用户可见 sections：移除**能由结构化来源精确重建**的诊断行；移除验证计量摘要 section。
      重建格式不匹配时**不移除**（fail-soft：宁可少摘，绝不误删学术内容），
      格式漂移由 `test_phase5a_final_answer_routing` 钉住。
    * audit_diagnostics：结构化保留全部诊断（rejected/repaired/dropped/quote_fixes/
      计量摘要原文/被路由的 section 记录）。
    """
    sect = dict(sections or {})
    pipe = pipeline or {}
    ent = pipe.get("entailment") or {}
    rejected = (answer or {}).get("rejected_claims") or [
        {"claim_id": r.get("claim_id"), "claim_text": r.get("claim_text"),
         "status": r.get("status"), "reason": r.get("reason")}
        for r in (ent.get("rejected") or [])]
    known_lines = set(_rejected_diagnostic_lines({"rejected_claims": rejected}))
    routed = []
    for sid in ("limitations",):
        text = sect.get(sid)
        if not isinstance(text, str) or not text.strip():
            continue
        keep, removed = [], []
        for line in text.split("\n"):
            if line.strip() and line.strip() in known_lines:
                removed.append(line.strip())
            elif line.strip().startswith(_REPAIR_LINE_PREFIX):
                # 结构化重建对不上（渲染格式可能已变）：**保留**该行并记录告警，
                # 由测试暴露格式漂移，而不是在这里猜。
                keep.append(line)
            else:
                keep.append(line)
        if removed:
            routed.append({"section": sid, "reason": "validator_diagnostic",
                           "lines_removed": len(removed)})
            cleaned = "\n".join(keep).strip()
            if cleaned:
                sect[sid] = cleaned
            else:
                sect.pop(sid, None)
    brief = sect.pop(_BRIEF_ANSWER_SECTION, None)
    if brief:
        routed.append({"section": _BRIEF_ANSWER_SECTION,
                       "reason": "validator_metric_summary", "lines_removed": 1})
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_claims_n": pipe.get("generated_claims"),
        "validated_claims_n": len((answer or {}).get("claims") or []),
        "repaired_claims_n": len(ent.get("repaired") or []),
        "rejected_claims_n": len(rejected),
        "rejected": [{"claim_id": r.get("claim_id"),
                      "claim_text": (str(r.get("claim_text"))[:200]
                                     if r.get("claim_text") else None),
                      "status": r.get("status"), "reason": r.get("reason")}
                     for r in rejected],
        "repaired": [{"original_claim_id": r.get("original_claim_id"),
                      "repaired_claim_id": r.get("repaired_claim_id"),
                      "attempts": r.get("attempts")} for r in (ent.get("repaired") or [])],
        "prevalidation_dropped": pipe.get("prevalidation_dropped") or [],
        "c_stage_dropped": pipe.get("c_dropped") or [],
        "quote_fixes": pipe.get("quote_fixes") or [],
        "brief_answer_verbatim": brief,
        "routed_sections": routed,
        "note": ("校验器内部记录。属 AUDIT_DIAGNOSTIC（见 "
                 "_data/product/presentation_taxonomy_v1.json）：默认不出现在用户可见答案/"
                 "Obsidian/标准导出；保留在 Advanced / Audit Bundle。"),
    }
    return sect, audit


def _final_answer(question, task_type, answer, pipeline, contract, options):
    citations = _project_citations(answer)
    claims = _project_claims(answer, (pipeline or {}).get("entailment"))
    abstention = _project_abstention(answer)
    sections = answer.get("sections") or {}
    if isinstance(sections, list):
        sections = {s.get("id"): s.get("text") for s in sections if isinstance(s, dict)}
    # ★ Phase 5A / P5A-001（F-1）：**呈现路由**（不是删除）。
    #   冻结渲染器会把校验器诊断写进 sections（`- 已剔除未通过蕴含验证的断言：…
    #   （NOT_ENTAILED）`）与 `brief_answer`（验证计量摘要）。产品边界把它们
    #   **结构化地**摘出来放进 audit_diagnostics；用户可见 sections 只留学术内容。
    sections, audit_diagnostics = _route_validator_diagnostics(sections, answer, pipeline)
    summary = {
        "validated_claims_n": len(claims),
        "citations_n": len(citations),
        "generated_claims_n": (pipeline or {}).get("generated_claims"),
        "rejected_claims_n": len(((pipeline or {}).get("entailment") or {})
                                 .get("rejected") or []),
        "repaired_claims_n": len(((pipeline or {}).get("entailment") or {})
                                 .get("repaired") or []),
        "source_limitations_n": len(_source_limitations(answer)),
        "abstained": answer.get("answer_state") == "ABSTAINED",
        "evidence_state": contract.get("evidence_state"),
        "execution_state": contract.get("execution_state"),
    }
    return _schema("FinalScholarlyAnswer", {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "api_version": API_VERSION,
        "task_id": answer.get("task_id"),
        "question": question,
        "task_type": task_type,
        "answer_state": answer.get("answer_state") or "UNKNOWN",
        "answer_permission": answer.get("answer_permission"),
        "sections": sections,
        "validated_claims": claims,
        "citations": citations,
        "source_limitations": _source_limitations(answer),
        "abstention": abstention,
        "warnings": contract.get("warnings") or [],
        "summary": summary,
        "audit_diagnostics": audit_diagnostics,
        "provenance": {
            "api_version": API_VERSION,
            "core_freeze_version": _core_freeze_version(),
            "mode": (options or {}).get("mode", "scholarly"),
            "provider": (options or {}).get("provider", "mock"),
            "answer_schema_version": answer.get("schema_version"),
        },
    })


# ────────────────────────────────────────────────────────────── 研究入口
def research(question, options=None):
    """统一研究入口 → FinalScholarlyAnswer。

    options:
      mode (str)          task routing 提示（默认 "scholarly"）
      language (str)      zh / fr / en / any
      provider (str)      "mock"（默认，确定性、不发网络）| "llm"
      judge (bool)        llm provider 下是否启用 entailment judge（默认 True）
      task_id (str)       自定义 id（默认 product-<n>）
      budget (int)        检索预算上限（可选）
    """
    options = dict(options or {})
    question = (question or "").strip()
    req = {"question": question, "research_mode": options.get("mode", "scholarly"),
           "language": options.get("language"), "constraints": options.get("constraints"),
           "requested_source_layers": options.get("requested_source_layers"),
           "requested_output_depth": options.get("requested_output_depth")}
    ok, errs = O.validate("ResearchRequest", req)
    if not ok:
        return _err("INVALID_RESEARCH_REQUEST", "ResearchRequest 不符合 v1 schema",
                    "修正请求字段后重试", {"schema_errors": errs[:5]})

    provider_kind = options.get("provider", "mock")
    if provider_kind not in ("mock", "llm"):
        return _err("INVALID_PROVIDER", "provider 必须是 mock 或 llm",
                    "显式选择 mock（确定性）或 llm（需凭据）")

    import research_answer as ans                     # noqa: PLC0415
    import synthesis_contract as sc                   # noqa: PLC0415
    import synthesis_adapters as sad                  # noqa: PLC0415
    import synthesis_validation as sv                 # noqa: PLC0415
    import synthesis_entailment as se                 # noqa: PLC0415

    mode = options.get("mode", "scholarly")
    task_type = MODE_TO_TASK_TYPE.get(mode, "concept_definition")
    import hashlib                                    # noqa: PLC0415
    # 稳定 task_id：不用内置 hash()（跨进程随 PYTHONHASHSEED 变化，会破坏可复现性）
    stable_id = hashlib.sha1(question.encode("utf-8")).hexdigest()[:8]
    task = {"task_id": options.get("task_id") or "product-%s" % stable_id,
            "question": question, "language": options.get("language") or "any",
            "task_type": task_type, "split": "product"}

    # ★ CCR-0001（Phase 4E §8–§10）：**completion provider ≠ synthesis adapter**。
    #   adapter 只能经 `synthesis_adapters.make_adapter()` 这一**既有工厂**选择，
    #   真 provider 必须被**包进** `ScholarlySynthesisAdapter`（4C.1-D / D2 已验证的
    #   engine，逐字节未变），而不是直接塞给 synthesis boundary 调 `.synthesize()`。
    #   旧 wiring（`adapter = OpenAICompatibleProvider(...)`）必然 AttributeError。
    adapter = None
    if provider_kind == "llm":
        import run_synthesis_4c1d as rt               # noqa: PLC0415
        if not rt.load_dsh_key():
            return _err("PROVIDER_UNAVAILABLE",
                        "未配置 synthesis provider 凭据",
                        "配置凭据后重试；**不要**用 Agent 自身知识替代核心回答",
                        {"env": "DSH_SYNTHESIS_API_KEY"})
        adapter = sad.make_adapter("llm", sad.OpenAICompatibleProvider(timeout=120))
    else:
        adapter = sad.make_adapter("mock")

    # ★ Phase 4E §16：**只读审计接收器**（默认关闭，仅内部验收调用传入）。
    #   它把「这一次真实调用到底经过了哪些冻结阶段」如实记下来（contract / evidence /
    #   synthesis 原始载荷 hash / 流水线计数 / final answer hash），便于事后审计。
    #   它**不**改变任何语义、**不**参与答案构造、**不**联网、**不**落盘。
    audit = options.get("_audit_sink") if isinstance(options.get("_audit_sink"), dict) \
        else None

    def _audit(key, value):
        if audit is not None:
            audit[key] = value

    _audit("research_request", req)
    _audit("task", task)
    _audit("provider_kind", provider_kind)
    _audit("mode", mode)

    try:
        run = ans.run_task(task, budget=options.get("budget"), record_gaps=False)
        contract = sc.build_synthesis_input_contract(run)
    except Exception as exc:                          # noqa: BLE001
        return _err("CORE_EXECUTION_FAILED", "核心检索/契约阶段失败：%s" % exc,
                    "检查 passage store / 索引是否可用后重试")

    _audit("input_contract", contract)
    _audit("input_contract_hash", _stable_hash(contract))
    _audit("evidence_ids", sorted((e or {}).get("passage_id")
                                  for e in (contract.get("usable_evidence") or [])))

    permission = contract.get("answer_permission")
    if contract.get("status") != "READY" or permission == "BLOCKED":
        # 不调用 provider；返回结构性不可用（绝不补答）
        answer = {"schema_version": "scholarly-answer/v1", "task_id": task["task_id"],
                  "question": question, "task_type": task_type,
                  "answer_state": "ABSTAINED" if permission == "ABSTAIN"
                                  else "STRUCTURALLY_UNAVAILABLE",
                  "answer_permission": permission or "BLOCKED",
                  "sections": {}, "claims": [], "citations": [],
                  "abstention": contract.get("abstention_requirements") or {},
                  "limitations": "\n".join(contract.get("permission_reasons") or [])}
        return _final_answer(question, task_type, answer, {}, contract, options)

    try:
        # mock adapter 无 strict 参数（契约严格性由 C 阶段校验承担）；llm adapter 用 raw 模式，
        # 逐条清洗/验证/修复交由冻结的 D 流水线（与 4C.1-D 诊断器一致）
        draft = (adapter.synthesize(question, contract, strict=False)
                 if provider_kind == "llm" else adapter.synthesize(question, contract))
    except Exception as exc:                          # noqa: BLE001
        # adapter 自身出错（不是 provider transport 失败 —— 那种失败已被
        # ScholarlySynthesisAdapter 捕获成 LLM_PROVIDER_FAILURE）。§12：脱敏。
        detail_txt = _redact_secrets(exc)
        return _err("PROVIDER_CALL_FAILED",
                    "synthesis provider 调用失败：%s" % detail_txt,
                    "稍后重试或改用 mock provider；**不要**用模型知识补答",
                    {"api_error_code": "PROVIDER_CALL_FAILED",
                     "provider_diagnostic": "SYNTHESIS_ADAPTER_ERROR",
                     "provider": getattr(getattr(adapter, "provider", None), "name", None),
                     "detail": detail_txt})
    if not draft.get("ok"):
        failure_mode = draft.get("failure_mode")
        detail_txt = _redact_secrets(draft.get("detail"))
        provider_name = getattr(getattr(adapter, "provider", None), "name", None)
        if failure_mode == "LLM_PROVIDER_FAILURE":
            # ★ Phase 4E §13/§14/§35：provider 失败必须是 **provider 类**错误，
            #   公开错误码与修复前**同一契约**（产品层据此映射 PROVIDER_UNAVAILABLE），
            #   子分类只放在内部 diagnostic 里，不改 public schema。
            diag = _provider_diagnostic(detail_txt)
            return _err("PROVIDER_CALL_FAILED",
                        "synthesis provider 调用失败（%s）" % diag,
                        "稍后重试或改用 mock provider；**不要**用模型知识补答",
                        {"api_error_code": "PROVIDER_CALL_FAILED",
                         "provider_diagnostic": diag,
                         "provider": provider_name,
                         "detail": detail_txt})
        return _err("SYNTHESIS_FAILED", "provider 未产出可用 draft：%s" % failure_mode,
                    "查看 failure_mode 后重试",
                    {"failure_mode": failure_mode, "provider": provider_name,
                     "detail": detail_txt})

    _audit("synthesis", {
        "adapter": "llm" if provider_kind == "llm" else "mock",
        "provider": getattr(getattr(adapter, "provider", None), "name", None),
        "model": getattr(getattr(adapter, "provider", None), "model", None),
        "ok": bool(draft.get("ok")), "failure_mode": draft.get("failure_mode"),
        "claims_n": len(draft.get("claims") or []),
        "usage": draft.get("usage") or {},
        # 冻结的 provider 在返回前已把 HTTP body 解析成 JSON 并丢弃原文，
        # 因此这里能钉住的是**结构化原始载荷**的 hash（不是 HTTP 字节）。
        "raw_payload_hash": _stable_hash({"claims": draft.get("claims"),
                                          "sections": draft.get("sections"),
                                          "abstention": draft.get("abstention")}),
        "raw_completion_bytes_retained": False,
    })
    judge_on = bool(options.get("judge", provider_kind == "llm"))
    judge = se.EntailmentJudge(provider=adapter.provider if provider_kind == "llm"
                               else None, enabled=judge_on) \
        if provider_kind == "llm" else None
    try:
        pipeline = sv.run_validation_pipeline(run, contract, draft, judge=judge,
                                             question=question)
    except Exception as exc:                          # noqa: BLE001
        return _err("VALIDATION_PIPELINE_FAILED", "蕴含验证流水线失败：%s" % exc,
                    "检查 validator 版本与 core freeze 是否一致")

    _audit("judge_enabled", judge_on)
    _audit("pipeline", pipeline)
    final = _final_answer(question, task_type, pipeline.get("answer") or {}, pipeline,
                          contract, options)
    _audit("final_answer", final)
    _audit("final_answer_hash", _stable_hash(final))
    return final


# ────────────────────────────────────────────────────────────── 只读访问
def search_passages(query, filters=None):
    filters = dict(filters or {})
    import knowledge_api as api                       # noqa: PLC0415
    try:
        res = api.search_passages(
            query, language=filters.get("language", "any"),
            seminar=filters.get("seminar"), period=filters.get("period"),
            top_k=filters.get("top_k", 10))
    except Exception as exc:                          # noqa: BLE001
        return _err("SEARCH_FAILED", "检索失败：%s" % exc,
                    "检查索引是否已构建（rebuildable machine data 可重建）")
    ev = res.get("evidence") or []
    return _schema("PassageSearchResult", {
        "query": query, "filters": filters,
        "evidence": [_to_evidence_packet(e) for e in ev],
        "n": len(ev),
        "warnings": res.get("warnings") or [],
    })


def get_passage(passage_id):
    import knowledge_api as api                       # noqa: PLC0415
    res = api.get_passage(passage_id)
    ev = res.get("evidence") or []
    if not ev:
        return _err("PASSAGE_NOT_FOUND", "未找到 passage：%s" % passage_id,
                    "检查 passage_id 拼写；可在 search_passages 中检索")
    rec = _to_passage_record(ev[0])
    if ev[0].get("trace_status") is None:
        rec["trace_status"] = (res.get("provenance") or {}).get("trace_status")
    return rec


def get_context(passage_id, before=3, after=3):
    import knowledge_api as api                       # noqa: PLC0415
    res = api.get_context(passage_id, before=before, after=after)
    ev = res.get("evidence") or []
    if not ev:
        return _err("PASSAGE_NOT_FOUND", "未找到 passage 上下文：%s" % passage_id,
                    "检查 passage_id；可先 search_passages")
    items = [_to_passage_record(e) for e in ev]
    return _schema("PassageContext", {
        "passage_id": passage_id, "before": before, "after": after,
        "session_id": ev[0].get("session_id") or ev[0].get("session"),
        "items": items,
    })


def get_concept(concept_id):
    import knowledge_api as api                       # noqa: PLC0415
    res = api.get_concept(concept_id)
    resolution = res.get("resolution") or {}
    ents = resolution.get("entities") or []
    ent = ents[0] if ents else {}
    ev = res.get("evidence") or []
    rec = {
        "concept_id": concept_id,
        "canonical_name": ent.get("canonical_name") or ent.get("label"),
        "aliases": ent.get("aliases") or [],
        "status": ent.get("status") or ent.get("review_status"),
        "definition_summary": ent.get("definition") or ent.get("summary"),
        "relations": ent.get("relations") or [],
        "seminars": sorted({e.get("seminar_id") for e in ev if e.get("seminar_id")}),
        "terminology": ent.get("terminology") or {},
        "states": ent.get("states") or [],
        "evidence_ids": [e.get("passage_id") or e.get("id") for e in ev
                         if (e.get("passage_id") or e.get("id"))],
    }
    return _schema("ConceptRecord", rec)


def get_seminar(seminar_id):
    sems = {r["id"]: r for r in _load_passage_store_index("seminars")}
    if seminar_id not in sems:
        return _err("SEMINAR_NOT_FOUND", "未找到研讨班：%s" % seminar_id,
                    "使用 seminar.S<NN> 形式，例如 seminar.S11")
    s = sems[seminar_id]
    sessions = [x for x in _load_passage_store_index("sessions")
                if x.get("seminar_id") == seminar_id]
    sessions.sort(key=lambda x: (x.get("lesson") if isinstance(x.get("lesson"), int)
                                 else 10**6, x.get("id") or ""))
    return _schema("SeminarRecord", {
        "seminar_id": seminar_id,
        "title": s.get("zh_title") or s.get("fr_title"),
        "year_from": s.get("year_from"), "year_to": s.get("year_to"),
        "sessions": [{"session_id": x.get("id"), "lesson": x.get("lesson"),
                      "passage_count": x.get("passage_count"),
                      "languages": x.get("languages") or [],
                      "trace_status": x.get("trace_status")} for x in sessions],
        "concepts": [],
        "passage_count": sum(int(x.get("passage_count") or 0) for x in sessions),
        "source_layers": sorted({x.get("authority_level") for x in sessions
                                 if x.get("authority_level")}),
    })


def trace_source(passage_id):
    """回答「这句话来自哪里」：corpus_source → witness → passage → seminar → session。

    字段全部取自**既有**核心输出（`knowledge_api.trace_source` envelope）：
    `evidence[0]` 提供 passage 级事实，`provenance.chain` 提供 witness/corpus 链；
    核心未提供的字段如实为 null，**不猜**。SOURCE_TRACE_INCOMPLETE 原样返回。
    """
    import knowledge_api as api                       # noqa: PLC0415
    res = api.trace_source(passage_id)
    prov = res.get("provenance") or {}
    ev = res.get("evidence") or []
    item = ev[0] if ev else {}
    chain = prov.get("chain") or res.get("chain") or []
    first = chain[0] if chain and isinstance(chain[0], dict) else {}
    return _schema("ProvenanceRecord", {
        "passage_id": passage_id,
        "corpus_source": (item.get("corpus_source_id")
                          or first.get("corpus_source_id")
                          or prov.get("corpus_source")),
        "witness": (item.get("witness_id") or first.get("witness_id")
                    or prov.get("witness_id")),
        "passage_realization": prov.get("passage_realization"),
        "seminar": item.get("seminar_id") or prov.get("seminar_id"),
        "session": item.get("session_id") or prov.get("session_id"),
        "document": item.get("document_id") or prov.get("document_id"),
        "edition": item.get("edition") or prov.get("edition"),
        "source_layer": _derive_source_layer(item) or prov.get("source_layer"),
        "trace_status": item.get("trace_status") or prov.get("trace_status"),
        "trace_missing": (item.get("trace_missing") or prov.get("trace_missing")
                          or prov.get("trace_missing_fields") or []),
        "chain": chain,
    })


# ────────────────────────────────────────────────────────────── 便捷研究入口
def research_concept(concept_id, mode="concept_definition", options=None):
    q = "请给出 %s 的工作定义、关键区分与语料证据。" % concept_id
    o = dict(options or {})
    o.setdefault("mode", mode)
    o.setdefault("task_id", "product-concept-%s" % concept_id.replace(".", "-"))
    return research(q, o)


def compare_terms(term_a, term_b, options=None):
    q = "%s 与 %s 有什么区别？请分别给出各自的语料证据。" % (term_a, term_b)
    o = dict(options or {})
    o.setdefault("mode", "concept_relation")
    o.setdefault("task_id", "product-compare-%s-%s"
                 % (str(term_a).replace(" ", "-"), str(term_b).replace(" ", "-")))
    return research(q, o)


def research_diachronic(concept, start=None, end=None, options=None):
    span = ("%s–%s" % (start, end)) if (start or end) else "其语料覆盖的全部时期"
    q = "%s 在 %s 之间发生了什么变化？请给出各阶段的语料依据。" % (concept, span)
    o = dict(options or {})
    o.setdefault("mode", "diachronic")
    o.setdefault("task_id", "product-diachronic-%s" % str(concept).replace(" ", "-"))
    return research(q, o)


def research_translation(term, options=None):
    q = "中文语料里 %s 有哪些译法？这些译名差异意味着什么？" % term
    o = dict(options or {})
    o.setdefault("mode", "translation_terminology")
    o.setdefault("task_id", "product-translation-%s" % str(term).replace(" ", "-"))
    return research(q, o)
