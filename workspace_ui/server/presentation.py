#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace_ui.server.presentation — Phase 5A：Presentation Taxonomy 的落地实现。

冻结语义见 `_data/product/presentation_taxonomy_v1.json`；本模块是**唯一**分类实现。

四类：
    SCHOLARLY_CONTENT    语料支持的学术内容            → 用户可见（默认）
    SCHOLARLY_LIMITATION 关于证据本身的学术限制        → 用户可见（默认）
    AUDIT_DIAGNOSTIC     校验器/过程记录（reject 日志、计量摘要、repair trace）
                                                       → Advanced / Audit（默认不可见，**不删除**）
    OPERATIONAL_ERROR    运行态错误（provider/冻结/冲突…）→ 错误通道，不进答案正文

纪律：
* **确定性**：只用结构化来源（`audit_diagnostics`、section id、错误信封 code）分类；
  绝不用 LLM，也不以「文本里含 NOT_ENTAILED」作为新答案的主判据。
* **不丢内容**：任何被划到 AUDIT 的内容都必须在 audit view 里 100% 可取回。
* **历史兼容**：RC1.1 的 v1 载荷（无 `audit_diagnostics`）**不改写**；
  其内部诊断按冻结的 legacy 规则（section id + 工程文本特征）在**呈现时**路由。
"""
from __future__ import annotations

import re

from . import config as C

TAXONOMY_VERSION = "presentation-taxonomy/v1"
AUDIT_SCHEMA_VERSION = "answer-audit/v1"

SCHOLARLY_CONTENT = "SCHOLARLY_CONTENT"
SCHOLARLY_LIMITATION = "SCHOLARLY_LIMITATION"
AUDIT_DIAGNOSTIC = "AUDIT_DIAGNOSTIC"
OPERATIONAL_ERROR = "OPERATIONAL_ERROR"
CLASSES = (SCHOLARLY_CONTENT, SCHOLARLY_LIMITATION, AUDIT_DIAGNOSTIC, OPERATIONAL_ERROR)

# 工程性 section：内容属过程记录（不再是用户可见正文）。
#   （4D.2 起 `brief_answer` 就是 validator 计量摘要；Phase 5A 起边界层已不再写入，
#     这里保留以兼容 RC1.1 历史快照。）
INTERNAL_SECTIONS = ("brief_answer",)

# legacy v1 载荷里，核心渲染器把验证日志写进 limitations 段。
#   **只**用于历史快照的呈现路由（新答案由边界层结构化摘除）。
LEGACY_ENGINEERING_TEXT = re.compile(
    r"(已剔除|未通过验证|NOT_ENTAILED|PARTIALLY_ENTAILED|CONTRADICTED|"
    r"SOURCE_ROLE_MISMATCH|被剔除|strength=R\d|R\d_(FORMAL|CONTEXTUAL|EXPLICIT)_RELATION)")

# 学术限制 section（用户可见）
LIMITATION_SECTIONS = ("limitations", "source_notes", "corpus_attestation",
                       "what_cannot_be_verified", "what_would_be_needed",
                       "period_source_qualification")


def classify_section(sid, text, has_structured_audit=True):
    """→ 类别。结构化优先；legacy 回退；绝不猜语义。"""
    if sid in INTERNAL_SECTIONS:
        return AUDIT_DIAGNOSTIC
    if not has_structured_audit and sid == "limitations" \
            and LEGACY_ENGINEERING_TEXT.search(str(text or "")):
        # 仅历史载荷：该段含工程日志 → 整段进 Audit（不改写历史，只改呈现）
        return AUDIT_DIAGNOSTIC
    if sid in LIMITATION_SECTIONS:
        return SCHOLARLY_LIMITATION
    return SCHOLARLY_CONTENT


def classify_error(payload_or_env):
    """错误信封 → OPERATIONAL_ERROR（答案正文里的一切错误都必须走这里）。"""
    if not isinstance(payload_or_env, dict):
        return None
    code = payload_or_env.get("code") or payload_or_env.get("error_code")
    if not code:
        err = (payload_or_env.get("error") or {})
        code = err.get("code")
    return OPERATIONAL_ERROR if code else None


def has_structured_audit(payload):
    ad = (payload or {}).get("audit_diagnostics")
    return isinstance(ad, dict) and bool(ad)


def _sections_dict(payload):
    s = (payload or {}).get("sections") or {}
    if isinstance(s, list):
        return {x.get("id"): x.get("text") for x in s if isinstance(x, dict)}
    return dict(s)


def user_facing_view(payload):
    """→ 只含用户可见面的视图（学术内容 + 学术限制 + 状态/引用/弃权）。

    不返回 Audit 面内容；也不改写任何学术载荷（claims/citations/state 原样）。
    """
    payload = payload or {}
    structured = has_structured_audit(payload)
    sections, routed = [], []
    for sid, text in _sections_dict(payload).items():
        if not text:
            continue
        cls = classify_section(sid, text, structured)
        if cls == AUDIT_DIAGNOSTIC:
            routed.append({"id": sid, "classification": cls, "text": text,
                           "reason": ("structured_audit" if structured
                                      else "legacy_engineering_text")})
            continue
        sections.append({"id": sid, "classification": cls, "text": text})
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "schema_version": payload.get("schema_version"),
        "task_id": payload.get("task_id"),
        "question": payload.get("question"),
        "task_type": payload.get("task_type"),
        "answer_state": payload.get("answer_state"),
        "answer_permission": payload.get("answer_permission"),
        "sections": sections,
        "validated_claims": list(payload.get("validated_claims") or []),
        "citations": list(payload.get("citations") or []),
        "source_limitations": list(payload.get("source_limitations") or []),
        "abstention": payload.get("abstention"),
        "warnings": list(payload.get("warnings") or []),
        "summary": payload.get("summary") or {},
        "provenance": payload.get("provenance") or {},
        "routed_to_audit": routed,
    }


def audit_view(payload):
    """→ Audit 面视图（结构化优先；legacy 时由呈现层派生并标注 derived=True）。

    保证：**任何**被 user_facing_view 划走的内容都能在这里取回。
    """
    payload = payload or {}
    ad = payload.get("audit_diagnostics")
    structured = isinstance(ad, dict) and bool(ad)
    if structured:
        out = dict(ad)
        out["derived_from_legacy"] = False
    else:
        routed = [s for s in user_facing_view(payload).get("routed_to_audit") or []]
        out = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "generated_claims_n": (payload.get("summary") or {}).get("generated_claims_n"),
            "validated_claims_n": len(payload.get("validated_claims") or []),
            "repaired_claims_n": (payload.get("summary") or {}).get("repaired_claims_n"),
            "rejected_claims_n": (payload.get("summary") or {}).get("rejected_claims_n"),
            "rejected": [],
            "repaired": [],
            "prevalidation_dropped": [],
            "c_stage_dropped": [],
            "quote_fixes": [],
            "brief_answer_verbatim": None,
            "routed_sections": [{"section": s["id"], "reason": s["reason"],
                                 "lines_removed": None} for s in routed],
            "derived_from_legacy": True,
            "legacy_routed_text": [{"section": s["id"], "text": s["text"]} for s in routed],
            "note": ("RC1.1 历史快照没有结构化 audit 容器：此处按 legacy 规则在**呈现时**"
                     "派生（历史载荷未被改写）。"),
        }
    out.setdefault("taxonomy_version", TAXONOMY_VERSION)
    return out


def audit_available(payload):
    a = audit_view(payload)
    return bool(a.get("rejected") or a.get("repaired") or a.get("routed_sections")
                or a.get("brief_answer_verbatim") or a.get("prevalidation_dropped")
                or a.get("c_stage_dropped") or a.get("quote_fixes"))


def internal_diagnostics_in(text):
    """acceptance 判定用：用户可见文本里是否出现内部诊断特征。

    返回命中列表（空 = 干净）。**不只**看 NOT_ENTAILED，也看 repair/计量措辞。
    """
    if not isinstance(text, str):
        return []
    hits = []
    for pat, label in ((LEGACY_ENGINEERING_TEXT, "validator_log"),
                       (re.compile(r"本回答由\s*\d+\s*条通过蕴含验证的断言构成"), "metric_summary"),
                       (re.compile(r"因未通过验证被剔除"), "metric_summary")):
        if pat.search(text):
            hits.append(label)
    return sorted(set(hits))


def scan_user_facing_internal_diagnostics(payload):
    """整份用户可见视图里出现的内部诊断（acceptance H1 直接用它）。"""
    uv = user_facing_view(payload)
    found = []
    for s in uv["sections"]:
        for hit in internal_diagnostics_in(s["text"]):
            found.append({"section": s["id"], "kind": hit})
    for lim in uv["source_limitations"]:
        for hit in internal_diagnostics_in(str(lim)):
            found.append({"section": "source_limitations", "kind": hit})
    for c in uv["validated_claims"]:
        for hit in internal_diagnostics_in(str(c.get("claim_text") or "")):
            found.append({"section": "validated_claims", "kind": hit})
    for w in uv["warnings"]:
        for hit in internal_diagnostics_in(str(w)):
            found.append({"section": "warnings", "kind": hit})
    if str(uv.get("question") or ""):
        for hit in internal_diagnostics_in(uv["question"]):
            found.append({"section": "question", "kind": hit})
    return found
