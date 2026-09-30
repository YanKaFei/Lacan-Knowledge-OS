#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evidence_sufficiency.py — Phase 4A §7–§10 Evidence Sufficiency Engine

它判断什么、不判断什么
──────────────────────
**判断**：当前 Knowledge Base 是否提供了足够证据来支持**当前研究操作**。
**不判断**：哪个理论解释是正确的（§10 明确禁止）。

禁止 cosine threshold（§7 / Phase 3C §18 实测）
──────────────────────────────────────────────
实测不可答 query 的 top1 余弦**高于**可答 query（minilm −0.0128 / mpnet −0.0076），
所以 `cosine < t → 无证据` 在数学上就是错的。本引擎**完全不看**任何相似度分数，
只用**结构性**信号。`method` 字段固定为 `structural_only_no_cosine_threshold`。

四个状态（§7）
──────────────
| 状态 | 含义 |
|---|---|
| `SUPPORTED` | 证据量、多分量一致性、session 多样性、约束满足都到位 |
| `PARTIALLY_SUPPORTED` | 有证据，但至少一项不达标（逐条列出原因） |
| `INSUFFICIENT_EVIDENCE` | 没有证据，或关键实体完全没解析出来 |
| `CONFLICTING_EVIDENCE` | 证据**结构上无法归给单一实体**（如 ENTITY_COLLISION） |

`AMBIGUOUS_ENTITY` **不是**本引擎的状态（§7 明确：它是上游解析状态）。

14 个信号（§8）
───────────────
resolved_entity_coverage · required_entity_missing · passage_count ·
distinct_seminar_count · distinct_period_count · exact_lexical_support ·
terminology_bridge_support · provenance_completeness · primary_vs_secondary ·
duplicate_concentration · contradictory_evidence · ontology_gap ·
entity_collision · constraint_satisfaction

**不压成 0–1 confidence。** 输出是 `signals`（原始值）+ `reasons`（人话）。

用法
────
    import evidence_sufficiency as es
    es.evaluate(response_like_dict)     # → {state, signals, reasons, method}
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, TOOLS)

METHOD = "structural_only_no_cosine_threshold"

# 预登记阈值（写在代码里，不是事后凑的）
MIN_EVIDENCE = 1
SUPPORTED_MIN_AGREEMENT = 0.5      # ≥50% 证据被 ≥2 个独立分量同时召回
SUPPORTED_MIN_SESSIONS = 2
DUPLICATE_CONCENTRATION_MAX = 0.8  # 单一 session 占比超过这条即视为集中
PRIMARY_LEVELS = ("L1", "L2")      # L1 PRIMARY / L2 SECONDARY 见 KNOWLEDGE_SCHEMA

# ── 「独立检索族」：一致性信号只在**≥2 族真的跑过**时才有意义 ────────────
# 为什么必须这样（Phase 4A 修的一个真实缺陷）：
# 第一版把 `component_agreement = 被 ≥2 个分量同时召回的比例` 无条件当判据，
# 而 routing policy 是**按问题类型**决定分量组合的（Phase 3C 实测：向量是
# 辅助、不得被强制启用）。只跑词法族时，`≥2 个分量` 在结构上**不可能**满足，
# 于是所有单族查询都被判成 PARTIALLY_SUPPORTED ——
# 那等于用「我们没跑向量」去指控「证据不足」，与 Phase 3C 的结论直接冲突。
#
# exact / lexical 是**同一族**（都是词法）：它们高度相关，
# 二者同时命中不构成独立佐证。
COMPONENT_FAMILIES = {"exact": "lexical", "lexical": "lexical",
                      "terminology_bridge": "bridge", "vector": "vector"}


def _warn_codes(warnings):
    out = set()
    for w in warnings or []:
        if isinstance(w, dict):
            out.add(w.get("code") or "")
        else:
            out.add(str(w))
    return out


def evaluate(payload):
    """payload 是 knowledge_api 组装的中间结构（不是 MCP 响应本身）。

    需要的键：evidence / resolution / retrieval / coverage / provenance / warnings /
              request
    """
    ev = payload.get("evidence") or []
    res = payload.get("resolution") or {}
    ret = payload.get("retrieval") or {}
    cov = payload.get("coverage") or {}
    prov = payload.get("provenance") or {}
    req = payload.get("request") or {}
    codes = _warn_codes(payload.get("warnings"))

    reasons = []
    notes = []

    # ── 信号 1/2：实体覆盖与缺失
    ents = res.get("entities") or []
    required = [e for e in ents if e.get("required")]
    # 防御：调用方可能给 dict 也可能给 str（形状应由 `_resolution` 统一，
    # 但引擎不该因为上游写错形状就崩掉 —— 实测崩过一次）。
    def _term_label(e):
        if isinstance(e, dict):
            return e.get("entity_id") or e.get("term")
        return str(e)
    missing_required = [_term_label(e) for e in (res.get("unresolved_terms") or [])]
    entity_seeking = bool(req.get("expect_entity"))
    resolved_cov = (len([e for e in ents if e.get("entity_id")]) / len(ents)) if ents else None

    # ── 信号 3/4/5：规模与多样性
    n = len(ev)
    sessions = {e.get("session_id") for e in ev if e.get("session_id")}
    seminars = {e.get("seminar_id") for e in ev if e.get("seminar_id")}
    periods = {e.get("period") for e in ev if e.get("period")}

    # ── 信号 6/7：分量支持（按**独立族**判定适用性）
    def comp_count(e):
        cc = e.get("component_contribution") or {}
        return len([k for k, v in cc.items() if v])

    fams = {}
    for comp, cnt in ((ret or {}).get("component_counts") or {}).items():
        fam = COMPONENT_FAMILIES.get(comp)
        if fam and cnt:
            fams[fam] = fams.get(fam, 0) + cnt
    families_executed = sorted(fams)
    agreement_applicable = len(families_executed) >= 2
    multi = [e for e in ev if comp_count(e) >= 2]
    agreement = (len(multi) / n) if (n and agreement_applicable) else None
    exact_lexical = any(("lexical" in (e.get("component_contribution") or {}))
                        or ("exact" in (e.get("component_contribution") or {}))
                        for e in ev)
    bridge = any("terminology_bridge" in (e.get("component_contribution") or {})
                 for e in ev)

    # ── 信号 8：溯源完整度
    incomplete = [e for e in ev if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"]
    prov_completeness = (1 - len(incomplete) / n) if n else None

    # ── 信号 9：primary vs secondary
    levels = {}
    for e in ev:
        lv = e.get("authority_level")
        if lv:
            levels[lv] = levels.get(lv, 0) + 1
    has_primary = any(levels.get(lv) for lv in PRIMARY_LEVELS)

    # ── 信号 10：重复集中度
    dup_conc = None
    if n and sessions:
        from collections import Counter
        c = Counter(e.get("session_id") for e in ev if e.get("session_id"))
        dup_conc = max(c.values()) / n

    # ── 信号 12/13：ontology gap 与 entity collision
    # ⚠️ 显式优先：`resolution.collisions` 是**本次判定用的事实**。
    #    第一版只要 warnings 里出现 ENTITY_COLLISION 就判冲突 —— 于是
    #    Phase 4A.1 修复后仍留在告警里（供审计）的历史碰撞会继续把状态
    #    压成 CONFLICTING_EVIDENCE，等于用旧缺陷解释新数据。
    #    现在：resolution 给了 collisions 就用它；没给才退回扫告警 code。
    if "collisions" in res:
        collision = bool(res.get("collisions"))
    else:
        collision = "ENTITY_COLLISION" in codes
    ontology_gap = bool(res.get("ontology_gaps")) or "ONTOLOGY_GAP" in codes

    # ── 信号 14：约束满足
    constraints = {}
    if req.get("seminar"):
        constraints["seminar"] = any(e.get("seminar_id") == req["seminar"] for e in ev)
    if req.get("language") and req["language"] != "any":
        constraints["language"] = any(e.get("language") == req["language"] for e in ev)
    constraint_ok = all(constraints.values()) if constraints else None
    # 请求本身是否限定了范围（seminar / period / language）——
    # 受限请求不该被要求「跨 session 多样性」：法语 Staferla 语料**没有**课次级 id,
    # 单个研讨班的法文段全落在 `session.S<NN>.unknown` 一个 session 上，
    # 于是「多样性 < 2」是**语料溯源粒度**造成的，不是证据单薄。
    # 要求它 = 用知识库的编号粒度去指控证据不足（与「没跑向量就判一致性不达标」同类错误）。
    scoped = bool(req.get("seminar") or req.get("period")
                  or (req.get("language") not in (None, "any")))

    # ── 信号 11：证据是否结构上冲突
    contradictory = collision and n > 0
    if collision:
        reasons.append(
            "知识库把两个必须区分的概念绑到了**同一个 entity**（ENTITY_COLLISION）——"
            "检索到的证据在结构上**无法归给单一实体**，因此这不是「证据不足」，"
            "而是「证据无法归属」。")

    signals = {
        "resolved_entity_count": len(ents),
        "resolved_entity_coverage": resolved_cov,
        "required_entity_missing": missing_required,
        "passage_count": n,
        "distinct_session_count": len(sessions),
        "distinct_seminar_count": len(seminars),
        "distinct_period_count": len(periods),
        "component_agreement": agreement,
        "component_agreement_applicable": agreement_applicable,
        "independent_families_executed": families_executed,
        "exact_lexical_support": exact_lexical,
        "terminology_bridge_support": bridge,
        "provenance_completeness": prov_completeness,
        "source_trace_incomplete_n": len(incomplete),
        "authority_levels": levels,
        "has_primary_evidence": has_primary,
        "duplicate_concentration": dup_conc,
        "contradictory_evidence": contradictory,
        "ontology_gap": ontology_gap,
        "entity_collision": collision,
        "constraint_satisfaction": constraints or None,
        "request_scoped": scoped,
        "vector_enabled": (ret or {}).get("vector_enabled"),
    }

    # ── 判定（顺序即优先级，先判最坏的）
    if contradictory:
        state = "CONFLICTING_EVIDENCE"
    elif n < MIN_EVIDENCE:
        state = "INSUFFICIENT_EVIDENCE"
        reasons.append("检索返回 0 条证据。")
    elif entity_seeking and not ents:
        state = "INSUFFICIENT_EVIDENCE"
        reasons.append("这是实体型研究操作，但没有任何 entity 被解析出来 → 无法约束证据。")
    else:
        ok_agreement = (agreement is None) or (agreement >= SUPPORTED_MIN_AGREEMENT)
        # 受限请求（本次操作只针对某个研讨班/时期/语言）→ 多样性要求降为 ≥1，
        # 由 constraint_satisfaction 承担「范围是否被满足」的判定。
        ok_sessions = (len(sessions) >= 1) if scoped else (len(sessions) >= SUPPORTED_MIN_SESSIONS)
        if scoped and len(sessions) < SUPPORTED_MIN_SESSIONS and n:
            notes.append(
                "请求**本身限定了范围**（seminar=%s period=%s language=%s）→ "
                "不再要求跨 session 多样性；范围内证据数 %d、session 数 %d。"
                "（法语 Staferla 语料没有课次级 id，单一研讨班的段会共用一个 session —— "
                "这是溯源粒度，不是证据单薄。）"
                % (req.get("seminar"), req.get("period"), req.get("language"),
                   n, len(sessions)))
        ok_constraints = (constraint_ok is not False)
        ok_entity = (resolved_cov is None) or resolved_cov > 0
        if agreement is None:
            notes.append(
                "本次只跑了 %d 个**独立检索族**（%s）→ 多分量一致性信号**不适用**："
                "只跑一族不是「一致性不达标」。routing policy 按问题类型决定分量组合，"
                "Phase 3C 实测向量是辅助、不得强制启用，因此不能因为「没跑向量」降级。"
                % (len(families_executed), families_executed or "?"))
        elif not ok_agreement:
            reasons.append("仅 %.0f%% 的证据被 ≥2 个独立分量同时召回（阈值 %.0f%%）。"
                           % (100 * agreement, 100 * SUPPORTED_MIN_AGREEMENT))
        if not ok_sessions and not scoped:
            reasons.append("证据只来自 %d 个 session（阈值 %d）——"
                           "单一 session 的表述不足以支撑跨文本结论。"
                           % (len(sessions), SUPPORTED_MIN_SESSIONS))
        if not ok_constraints:
            reasons.append("查询给出的约束未被满足：%s" % constraints)
        if not ok_entity:
            reasons.append("实体解析覆盖率为 0。")
        if ontology_gap:
            reasons.append("检测到 ontology gap（知识库缺少某一侧的概念实体）。")
        if has_primary is False and n:
            reasons.append("证据里没有 L1/L2 层级条目（primary/secondary 都缺）。")
        state = ("SUPPORTED" if (ok_agreement and ok_sessions and ok_constraints and ok_entity)
                 else "PARTIALLY_SUPPORTED")
        if state == "SUPPORTED":
            reasons.append("证据量、多分量一致性、session 多样性、约束满足四项均达标。")

    # 溯源不完整永远是 warning，但**不**单独把状态降级（否则中文语料永远无法 SUPPORTED）——
    # 它作为可读原因附上，并保留在 warnings 里由调用方展示。
    if incomplete:
        reasons.append("其中 %d / %d 条证据的 trace_status = SOURCE_TRACE_INCOMPLETE"
                       "（中文 recovered 语料的上游原件缺失）—— **不隐藏**，"
                       "但也不因此否认证据本身可引用。" % (len(incomplete), n))

    return {
        "state": state,
        "signals": signals,
        "reasons": reasons,
        # `notes` 是**信息性**说明（例如「某个信号不适用」）：
        # 它不参与状态判定，但必须可见 —— 否则「为什么这次没有报一致性」
        # 会变成一个看不见的推理。
        "notes": notes,
        "method": METHOD,
        "prohibited": ("禁止用 `cosine < threshold → 无证据`：实测不可答 query 的 top1 余弦"
                       "**高于**可答 query，该规则在数学上就是错的（Phase 3C §18）。"),
        "scope_note": ("本引擎只判断「当前 KB 是否提供足够证据支持当前研究操作」，"
                       "**不判断哪个理论解释正确**（§10）。"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(evaluate(json.load(sys.stdin)), ensure_ascii=False, indent=1))
