#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui.server.viewmodel — 学术载荷 → UI ViewModel（**只排版，不改写**）

§36/§43 的硬约束：

    MCP FinalScholarlyAnswer  →  UI ViewModel

允许：分组、排序（沿用既有 section 顺序）、本地化标签、给 citation 起显示标签、
      标记 internal section、附加 provenance/limitation 视图。
禁止：改写 claim 文本、新增 claim、删除 limitation、删除 abstention、替换 citation、
      用模型自身知识补写（弃权时必须原样呈现"无法回答"）。

因此本模块**不做 HTML 转义**（那会破坏逐字同一性）；XSS 由前端用 `textContent`
渲染 + 测试（§37）保证。
"""
from __future__ import annotations

import re

from . import config as C
from . import presentation as PZ

# ── 展示用标签（只影响显示，不改数据）──────────────────────────────
SECTION_LABELS = {
    "brief_answer": "Answer summary",
    "working_definition": "Working definition",
    "main_analysis": "Main analysis",
    "key_distinctions": "Key distinctions",
    "distinction": "Key distinctions",
    "relationship": "Relation",
    "relation": "Relation",
    "diachronic_analysis": "Diachronic development",
    "diachronic": "Diachronic development",
    "term_mapping": "Terminology",
    "terminology": "Terminology",
    "formalism": "Formalism",
    "lacanian_reinterpretation": "Lacanian reinterpretation",
    "source_philosophy": "Source and influence",
    "source_notes": "Source notes",
    "comparison": "Comparison",
    "metadata": "Metadata",
    "translation": "Translation",
    "limitations": "Limitations",
    "abstention": "Abstention",
    "evidence": "Evidence",
}
# 固定的阅读顺序（§11）：只显示实际存在的 section
SECTION_ORDER = [
    "working_definition", "main_analysis", "key_distinctions", "distinction",
    "relationship", "relation", "comparison", "diachronic_analysis", "diachronic",
    "term_mapping", "terminology", "translation", "formalism",
    "lacanian_reinterpretation", "source_philosophy", "source_notes", "metadata",
    "evidence", "limitations", "abstention", "brief_answer",
]
# Phase 5A：分类统一由 `presentation` 模块负责（冻结 taxonomy）。
#   - 新答案（schema v1.1）由**结构化** `audit_diagnostics` 决定；
#   - RC1.1 历史快照（v1）沿用 id + 工程文本规则，仅用于呈现路由（不改写历史）。
INTERNAL_SECTIONS = PZ.INTERNAL_SECTIONS
_ENGINEERING_TEXT = PZ.LEGACY_ENGINEERING_TEXT
_LEGACY_ENGINEERING_TEXT_UNUSED = re.compile(
    r"(已剔除|未通过验证|NOT_ENTAILED|PARTIALLY_ENTAILED|CONTRADICTED|"
    r"SOURCE_ROLE_MISMATCH|被剔除|strength=R\d|R\d_(FORMAL|CONTEXTUAL|EXPLICIT)_RELATION)")

EPISTEMIC_LABELS = {
    "DIRECTLY_SUPPORTED": "Direct evidence",
    "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE": "Synthesized from multiple evidence",
    "QUALIFIED_INFERENCE": "Qualified inference",
    "CORPUS_ABSENCE": "Corpus limitation",
}

STATE_LABELS = {
    "VALIDATED": "Validated",
    "VALIDATED_WITH_QUALIFICATIONS": "Validated with qualifications",
    # ⚠️ Phase 4E：以下 3 态是核心的真实取值（真实 provider 会合法返回），
    # 文案与 4D.7 的导出层保持一致 —— 绝不把「未验证」说成「已验证」。
    "PARTIALLY_SUPPORTED": "Partially supported — not a fully validated answer",
    "VALIDATION_FAILED": "Validation failed — the core could not validate this answer",
    "INSUFFICIENT_EVIDENCE": "Insufficient evidence",
    "ABSTAINED": "Abstained",
    "STRUCTURALLY_UNAVAILABLE": "Structurally unavailable",
    "UNKNOWN": "Unknown state",
}

SOURCE_LAYER_LABELS = {
    "L1_TRANSCRIPTION": ("L1", "Original / primary transcription"),
    "L1_EDITION": ("L1", "Original / primary edition"),
    "L2_RECOVERED": ("L2", "Recovered / translated material"),
}

TRACE_INCOMPLETE_NOTE = ("当前文本可在 recovered corpus 中验证，但无法完整追溯到原始物理来源。"
                         "这是 source limitation，不是系统故障。")

ABSTENTION_TITLE = "Current corpus cannot support a reliable answer"


def citation_label(passage_id):
    """`[S11 · P2253]` 之类的**显示**标签（数据不变）。"""
    if not passage_id:
        return "[?]"
    m = re.match(r"^passage\.(S\d+[A-Z]?)\.(?:[^.]+\.)*?(P\d+)$", passage_id)
    if m:
        return "[%s · %s]" % (m.group(1), m.group(2))
    parts = passage_id.split(".")
    return "[%s]" % " · ".join(parts[1:3]) if len(parts) > 2 else "[%s]" % passage_id


def source_layer_view(layer):
    if not layer:
        return {"code": None, "tag": None, "label": None}
    tag, label = SOURCE_LAYER_LABELS.get(layer, (None, None))
    return {"code": layer, "tag": tag or layer, "label": label or layer}


def _sections_view(sections, structured_audit=True):
    """→ [{id, label, text, internal, classification}]，按 SECTION_ORDER 排序，只保留非空。

    `internal`（UI 兼容字段）= 分类为 AUDIT_DIAGNOSTIC 的 section：
    内容**逐字保留**在 Advanced / raw 里，只是不放在答案正文主体。
    """
    if isinstance(sections, list):                     # 兼容 [{id,text}]
        sections = {s.get("id"): s.get("text") for s in sections if isinstance(s, dict)}

    def row(sid, text):
        cls = PZ.classify_section(sid, text, structured_audit)
        return {"id": sid, "label": SECTION_LABELS.get(sid, sid), "text": text,
                "classification": cls, "internal": cls == PZ.AUDIT_DIAGNOSTIC}

    out = []
    for sid in SECTION_ORDER:
        text = (sections or {}).get(sid)
        if text:
            out.append(row(sid, text))
    # 载荷里出现但未登记的 section：原样追加，绝不丢内容
    for sid, text in sorted((sections or {}).items()):
        if text and sid not in SECTION_ORDER:
            out.append(row(sid, text))
    return out


def _claims_view(claims):
    out = []
    for c in claims or []:
        st = c.get("epistemic_status")
        out.append({
            "claim_id": c.get("claim_id"),
            "claim_type": c.get("claim_type"),
            "claim_text": c.get("claim_text"),
            "epistemic_status": st,
            "epistemic_label": EPISTEMIC_LABELS.get(st, st),
            "entailment_status": c.get("entailment_status"),
            "source_role_status": c.get("source_role_status"),
            "evidence_ids": list(c.get("evidence_ids") or []),
        })
    return out


def _citations_view(citations):
    out = []
    for c in citations or []:
        sl = source_layer_view(c.get("source_layer"))
        out.append({
            "passage_id": c.get("passage_id"),
            "claim_id": c.get("claim_id"),
            "label": citation_label(c.get("passage_id")),
            "quoted_span": c.get("quoted_span"),
            "citation_status": c.get("citation_status"),
            "source_layer": c.get("source_layer"),
            "source_layer_tag": sl["tag"],
            "source_layer_label": sl["label"],
            "provenance_status": c.get("provenance_status"),
            "trace_incomplete": c.get("provenance_status") == "SOURCE_TRACE_INCOMPLETE",
            "trace_incomplete_note": (TRACE_INCOMPLETE_NOTE
                                      if c.get("provenance_status")
                                      == "SOURCE_TRACE_INCOMPLETE" else None),
        })
    return out


def _abstention_view(ab):
    if not ab:
        return None
    return {
        "title": ABSTENTION_TITLE,
        "categories": list(ab.get("categories") or ([ab.get("category")]
                                                    if ab.get("category") else [])),
        "missing_information": list(ab.get("missing_information") or []),
        "available_partial_information": list(ab.get("available_partial_information") or []),
        "required_sources": list(ab.get("required_sources") or []),
        "corpus_scan_reference": ab.get("corpus_scan_reference"),
        "metadata_scan_reference": ab.get("metadata_scan_reference"),
    }


def answer_view(envelope):
    """MCP envelope（`{ok, result, meta}`）→ 答案 ViewModel。"""
    if not envelope or not envelope.get("ok"):
        return error_view(envelope)
    payload = envelope.get("result") or {}
    meta = envelope.get("meta") or {}
    state = payload.get("answer_state") or "UNKNOWN"
    abstention = _abstention_view(payload.get("abstention"))
    is_abstention = (state == "ABSTAINED")
    if is_abstention and not abstention:
        # 弃权但载荷没有 abstention 块：如实呈现为"缺块"，不补内容
        abstention = {"title": ABSTENTION_TITLE, "categories": [],
                      "missing_information": [], "available_partial_information": [],
                      "required_sources": [], "corpus_scan_reference": None,
                      "metadata_scan_reference": None,
                      "missing_block": True}
    return {
        "kind": "answer",
        "question": payload.get("question"),
        "task_type": payload.get("task_type"),
        "state": state,
        "state_label": STATE_LABELS.get(state, state),
        "answer_permission": payload.get("answer_permission"),
        "is_abstention": is_abstention,
        "is_qualified": state == "VALIDATED_WITH_QUALIFICATIONS",
        "sections": _sections_view(payload.get("sections"),
                                   PZ.has_structured_audit(payload)),
        "audit": PZ.audit_view(payload),
        "audit_available": PZ.audit_available(payload),
        "presentation_taxonomy_version": PZ.TAXONOMY_VERSION,
        "claims": _claims_view(payload.get("validated_claims")),
        "citations": _citations_view(payload.get("citations")),
        "limitations": list(payload.get("source_limitations") or []),
        "abstention": abstention,
        "warnings": list(payload.get("warnings") or []),
        "advanced": {
            "request_id": meta.get("request_id"),
            "task_id": payload.get("task_id"),
            "provider": meta.get("provider"),
            "api_version": meta.get("api_version"),
            "mcp_version": meta.get("mcp_version"),
            "workspace_version": C.WORKSPACE_VERSION,
            "core_freeze_version": meta.get("core_freeze_version"),
            "duration_ms": meta.get("duration_ms"),
            "citation_count": len(payload.get("citations") or []),
            "validated_claims_n": len(payload.get("validated_claims") or []),
            "answer_schema_version": payload.get("schema_version"),
            "dense_available": meta.get("dense_available"),
            "post_filtered": meta.get("post_filtered"),
        },
        "raw": {"scholarly_payload": payload, "meta": meta},
    }


_DETAIL_BLOCKLIST = ("stack", "traceback", "trace", "file", "filename", "path",
                     "stderr", "stdout", "locals", "frame")


def _safe_detail(detail):
    """错误 detail 脱敏：丢 stack/traceback/path 类键；值只保留短的标量。"""
    if not isinstance(detail, dict):
        return None
    out = {}
    for k, v in detail.items():
        kl = str(k).lower()
        if any(b in kl for b in _DETAIL_BLOCKLIST):
            out[k] = "<redacted>"
        elif isinstance(v, (str, int, float, bool)) or v is None:
            text = str(v)
            if "Traceback" in text or 'File "' in text or text.startswith("/"):
                out[k] = "<redacted>"
            else:
                out[k] = text[:400]
        else:
            out[k] = "<omitted>"
    return out


def error_view(envelope):
    """失败 envelope / 异常 → 用户可见错误（§29/§30），永不暴露 traceback。"""
    err = ((envelope or {}).get("error") or {}) if isinstance(envelope, dict) else {}
    code = err.get("code") or "INTERNAL_ERROR"
    ux = C.ERROR_UX.get(code, C.DEFAULT_ERROR_UX)
    return {
        "kind": "error",
        "code": code,
        "title": ux["title"],
        "body": ux["body"],
        "research_disabled": ux["research_disabled"],
        "message": err.get("message"),
        "resolution": err.get("resolution"),
        "detail": _safe_detail(err.get("detail")),
        "advanced": {"request_id": ((envelope or {}).get("meta") or {}).get("request_id")},
    }


# ────────────────────────────────────────────── Evidence Inspector
def passage_panel_view(passage_env, context_env=None, trace_env=None,
                       quoted_span=None, aligned_translation=None):
    """证据面板 ViewModel：passage + context + provenance + 对齐翻译可用性（§15–§18）。"""
    if not passage_env or not passage_env.get("ok"):
        return error_view(passage_env)
    p = passage_env.get("result") or {}
    ctx = []
    if context_env and context_env.get("ok"):
        ctx = (context_env.get("result") or {}).get("items") or []
    prov = (trace_env or {}).get("result") if (trace_env or {}).get("ok") else None
    sl = source_layer_view(p.get("source_layer"))
    trace_status = (prov or {}).get("trace_status") or p.get("trace_status")
    return {
        "kind": "passage",
        "passage": {
            "passage_id": p.get("passage_id"),
            "text": p.get("text"),
            "language": p.get("language"),
            "seminar": p.get("seminar"),
            "session": p.get("session"),
            "year_from": p.get("year_from"),
            "year_to": p.get("year_to"),
            "authority_level": p.get("authority_level"),
            "text_role": p.get("text_role"),
            "witness": p.get("witness"),
            "trace_status": trace_status,
        },
        "source_layer": sl,
        "quoted_span": quoted_span,
        "context": [{"passage_id": c.get("passage_id"), "text": c.get("text"),
                     "language": c.get("language")} for c in ctx],
        "provenance": prov,
        "trace_incomplete": trace_status == "SOURCE_TRACE_INCOMPLETE",
        "trace_incomplete_note": (TRACE_INCOMPLETE_NOTE
                                  if trace_status == "SOURCE_TRACE_INCOMPLETE" else None),
        "aligned_translation": aligned_translation,
        "aligned_translation_note": (None if aligned_translation
                                     else "No aligned translation available"),
        "citation_label": citation_label(p.get("passage_id")),
        "advanced": {"request_id": ((passage_env or {}).get("meta") or {})
                     .get("request_id")},
    }


def provider_state():
    """★ Phase 5A §41/§42：provider 是**独立**的一层状态（轻量凭据能力检查，**不发 LLM 调用**）。

    READY / DEGRADED / UNAVAILABLE：
      * 有凭据 → READY（真实 provider 可用）
      * 无凭据 → DEGRADED（离线/mock 完全可用；**不是**产品故障）
      * 核心报告不可用 → UNAVAILABLE（仍不影响离线研究）
    """
    try:
        from . import api as A                                   # noqa: PLC0415
        has = A._provider_credentials_present()                  # 只看有没有，不验证、不打印
    except Exception:                                            # noqa: BLE001
        has = False
    return {"state": "READY" if has else "DEGRADED",
            "credentials_present": bool(has),
            "default_provider": C.DEFAULT_PROVIDER,
            "note": ("Real-LLM provider 需要显式凭据；离线/mock 研究不受影响，"
                     "系统不会用模型知识兜底。")}


def status_view(status):
    """§28 + Phase 5A：分层状态（Core / MCP / Workspace / Provider），状态栏用，不抢焦点。"""
    mcp_ok = bool(status.get("connected"))
    freeze_ok = bool(status.get("core_freeze_verified"))
    layers = {
        "core": "READY" if freeze_ok else "UNAVAILABLE",
        "mcp": "READY" if mcp_ok else "UNAVAILABLE",
        "corpus": "READY",
        "workspace": "READY",
        "explorer": "READY",
        "obsidian": "READY",
        "bibliography": "READY",
        "provider": provider_state()["state"],
    }
    try:                                  # §31：书目 registry 健康用**客观 count**
        import bibliography as _B                                          # noqa: PLC0415
        _man = _B.registry.manifest()
        layers["bibliography"] = "READY" if _man else "UNAVAILABLE"
        _counts = _man.get("counts") or {}
        _reviewed = len(_B.registry.items())
        _cands = len(_B.registry.candidates())
        bib_health = {"registry": layers["bibliography"],
                      # items = reviewed + candidate（客观计数，**不是**完整度百分比）
                      "items": _reviewed + _cands,
                      "reviewed": _reviewed,
                      "candidates": _cands,
                      "editions": len(_B.registry.editions()),
                      "works": len(_B.registry.works()),
                      "mappings": _counts.get("mappings"),
                      "conflicts": _counts.get("conflicts"),
                      "counts_are_objective": True,
                      "note": "items = reviewed + candidates; no completeness score"}
    except Exception:                                                      # noqa: BLE001
        layers["bibliography"] = "UNAVAILABLE"
        bib_health = {"registry": "UNAVAILABLE"}
    return {
        "kind": "status",
        "mcp_connected": mcp_ok,
        "core_freeze_verified": freeze_ok,
        "server": status.get("server"),
        "core_freeze": status.get("core_freeze"),
        "checked_at": status.get("checked_at"),
        "layers": layers,
        "bibliography_registry": bib_health,
        "provider": provider_state(),
        # 只有**离线也做不了事**时才算产品级禁用；provider 缺失只是 DEGRADED。
        "research_disabled": (not mcp_ok) or (not freeze_ok),
        "degraded": [k for k, v in layers.items() if v == "DEGRADED"],
        "presentation_taxonomy_version": PZ.TAXONOMY_VERSION,
    }
