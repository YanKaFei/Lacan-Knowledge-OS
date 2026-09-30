#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
schemas.py — Phase 4A §5–§6 Tool Contracts（**契约先写，实现后跟**）

本文件是 MCP tool 契约的**唯一真源**：
* `TOOLS` 定义每个 tool 的名字、用途、输入 JSON Schema；
* `SHARED_OUTPUT` 定义所有 research/evidence tool **共享的输出结构**；
* `_scripts/_tools/lacan_mcp/render_contracts.py` 从本文件生成
  `MCP_TOOL_CONTRACTS.md` 与 `_data/mcp/tool_schemas.json`，
  所以文档与代码不可能各说各话。

三条结构性纪律（写在这里，也被测试守着）
────────────────────────────────────────
1. **READ ONLY**：任何 tool 的 inputSchema **不得**出现写入类参数
   （`set` / `write` / `update` / `canonicalize` / `promote` / `merge` / `fix` …）。
   测试 `test_phase4a_mcp.py::test_no_write_parameters` 逐个 schema 扫。
2. **职责不重叠**（§5）：
   * `search_passages` —— **通用**检索（走 Phase 3 的 Query Routing Policy）
   * `find_concept_evidence` —— **实体约束**的证据（先解析实体，再在实体范围内取证据）
   * `trace_concept` —— **历时**分组证据（按 period → seminar → session 组织）
   三者不是彼此的参数别名；`MCP_TOOL_CONTRACTS.md` 里有「不做什么」的明确边界。
3. **共享输出**（§6）：8 个 section 固定；`evidence[]` 的每一项**必须**带真实
   `passage_id`，并由 validator 逐个到 canonical store 里核对。

用法
────
    python3 _scripts/_tools/lacan_mcp/render_contracts.py     # 生成文档与 JSON
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────
# §6 共享输出结构
# ─────────────────────────────────────────────────────────────
SHARED_OUTPUT = {
    "schema": "lacan-kb/evidence-response/v1",
    "sections": {
        "request": "原样回显请求参数（含补全后的默认值），便于 research trace 复现",
        "resolution": ("实体解析结果：entities / ambiguous / collisions / unresolved_terms"
                       "（来自 entity_resolution + lacanian_semantic_guard）"),
        "retrieval": ("检索层元数据：route / vector_enabled / lanes / component_counts / "
                      "component_ranks 摘要（来自 query_routing_policy + Phase 3 组件）"),
        "evidence": ("证据条目数组。**每条必须带真实 passage_id**，外加 seminar/session/"
                     "language/text/why_retrieved/component_contribution/provenance"),
        "coverage": ("覆盖度：evidence_n / session_n / seminar_n / period_n / "
                     "language_mix / term_coverage"),
        "provenance": ("溯源汇总：trace_status 分布、SOURCE_TRACE_INCOMPLETE 计数、"
                       "witness/corpus_source 分布"),
        "warnings": ("结构化告警数组：每条 {code, message, severity, action}；"
                     "**不得吞掉** SOURCE_TRACE_INCOMPLETE / ENTITY_COLLISION / "
                     "AMBIGUOUS_ENTITY"),
        "evidence_state": ("Evidence Sufficiency 的结论：SUPPORTED / PARTIALLY_SUPPORTED / "
                           "INSUFFICIENT_EVIDENCE / CONFLICTING_EVIDENCE，"
                           "附带 signals 与 reasons（**不是** 0–1 confidence）"),
    },
    "invariants": [
        "所有 evidence[].passage_id 必须存在于 canonical passage store",
        "warnings 不得为空时省略；无告警时必须是空数组而不是缺字段",
        "evidence_state 必须出现在每个 research/evidence tool 的返回里",
        "任何 tool 都不得返回对 canonical knowledge 的修改",
    ],
}

# 所有 tool 共用的输出 section 名（顺序固定）
OUTPUT_SECTIONS = ["request", "resolution", "retrieval", "evidence",
                   "coverage", "provenance", "warnings", "evidence_state"]

# §2/§21：这些词一旦出现在参数名里就是写入能力，测试会直接失败
FORBIDDEN_PARAM_PATTERNS = ["set", "write", "update", "delete", "remove", "create",
                            "canonicalize", "promote", "merge", "fix", "apply",
                            "commit", "save", "insert", "patch", "edit"]

_MODE = {"type": "string",
         "enum": ["auto", "lexical", "vector", "hybrid", "exact"],
         "default": "auto"}

TOOLS = [
    {
        "name": "search_passages",
        "title": "通用证据检索",
        "purpose": ("把研究问题交给 Phase 3 已验证的检索链。**不重新实现检索**："
                    "内部调用 query_routing_policy + Phase 3 组件（Exact/Entity/Alias/"
                    "Lexical/Terminology Bridge X/Metadata/MiniLM vector）。"),
        "not_for": ("不要用它做「某概念的历时演变」（用 trace_concept）"
                    "或「某概念的全部支持证据」（用 find_concept_evidence）。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1,
                          "description": "研究问题或检索串（自然语言可）"},
                "language": {"type": "string", "enum": ["zh", "fr", "en", "mul", "any"],
                             "default": "any", "description": "限定证据语言"},
                "seminar": {"type": "string",
                            "description": "研讨班约束，如 seminar.S11 或 S11"},
                "period": {"type": "string",
                           "description": ("时期约束，如 1964-1965；分期表来自 seminars.jsonl 的 "
                            "year_from/year_to（**不是** query_router —— 它没有分期表）")},
                "entities": {"type": "array", "items": {"type": "string"},
                             "description": "额外指定的 entity_id（补充自动解析结果）"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10,
                          "description": "返回证据条数上限"},
                "retrieval_mode": dict(_MODE, description=("强制检索路径。auto=交给 routing policy 决定"
                                                           "（默认，也是唯一推荐的用法）")),
                "include_context": {"type": "boolean", "default": False,
                                    "description": "是否为 top evidence 附上前后文引用"},
                "explain": {"type": "boolean", "default": False,
                            "description": "是否返回 component ranks 明细"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "get_passage",
        "title": "取单个 Passage",
        "purpose": "按 stable ID 取 canonical passage 及其 witness / provenance / 邻居可用性。",
        "not_for": "不要用它检索；也不要用它猜 ID —— 不存在必须返回 PASSAGE_NOT_FOUND。",
        "inputSchema": {
            "type": "object",
            "properties": {"passage_id": {"type": "string",
                                          "description": "passage.S… 形式 stable ID"}},
            "required": ["passage_id"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "get_context",
        "title": "取本地上下文",
        "purpose": ("按 store 原顺序取前后 before/after 条**真实** passage。"
                    "**不做 LLM 总结** —— 只返回原文与顺序。"),
        "not_for": "不要用它跨 session 拼证据（那会破坏顺序语义）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "passage_id": {"type": "string",
                               "description": "中心 passage 的 stable ID"},
                "before": {"type": "integer", "minimum": 0, "maximum": 20, "default": 3,
                           "description": "向前取几条（沿 store 原序）"},
                "after": {"type": "integer", "minimum": 0, "maximum": 20, "default": 3,
                          "description": "向后取几条（沿 store 原序）"},
            },
            "required": ["passage_id"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "resolve_entity",
        "title": "实体解析（含歧义与碰撞）",
        "purpose": ("把词映射到 concept entity。状态只能是 RESOLVED / AMBIGUOUS / "
                    "UNRESOLVED / ENTITY_COLLISION，**不静默解析**。"),
        "not_for": "不要用它取证据（用 find_concept_evidence）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "minLength": 1,
                         "description": "待解析的词或短语（如 objet a / l'Autre / 凝视）"},
                "language": {"type": "string", "enum": ["zh", "fr", "en", "any"],
                             "default": "any",
                             "description": "限定解析语言（一般留 any）"},
                "context": {"type": "string",
                            "description": "可选上下文，用于在歧义时给出来源线索"},
            },
            "required": ["term"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "get_concept",
        "title": "取概念卡",
        "purpose": ("返回 canonical name / aliases / 语言 / status / period / 链接的 passage / "
                    "relations / source links / ontology gaps。"
                    "**不自动生成概念定义**；没有 reviewed definition 就明说没有。"),
        "not_for": "不要用它找证据（用 find_concept_evidence）。",
        "inputSchema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string",
                                         "description": "concept.* 形式 entity id"}},
            "required": ["entity_id"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "find_concept_evidence",
        "title": "实体约束的证据检索",
        "purpose": ("先解析实体，再**在该实体范围内**取支持证据；"
                    "可选 seminar / period / language / top_k。"),
        "not_for": ("不要用它做通用检索（用 search_passages）；"
                    "也不要用它做历时组织（用 trace_concept）。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "concept": {"type": "string",
                            "description": "entity_id（如 concept.jouissance）或可解析的术语"},
                "seminar": {"type": "string",
                            "description": "研讨班约束，如 seminar.S11 或 S11"},
                "period": {"type": "string",
                           "description": "时期约束（分期表来自 seminars.jsonl）"},
                "language": {"type": "string", "enum": ["zh", "fr", "en", "any"],
                             "default": "any", "description": "限定证据语言"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15,
                          "description": "返回证据条数上限"},
            },
            "required": ["concept"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "trace_concept",
        "title": "历时证据组织",
        "purpose": ("按 period → seminar → session 组织某概念的证据，"
                    "返回覆盖缺口（如 NO_EVIDENCE_FOR_PERIOD）。**不直接生成历史总结。**"),
        "not_for": "不要用它做横向对比（用 compare_concepts）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "concept": {"type": "string",
                            "description": "entity_id 或可解析的术语"},
                "language": {"type": "string", "enum": ["zh", "fr", "en", "any"],
                             "default": "any", "description": "限定证据语言"},
                "per_period": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5,
                               "description": "每个时期最多取几条"},
            },
            "required": ["concept"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "compare_concepts",
        "title": "两概念对比（独立 lane）",
        "purpose": ("对比两个概念。内部**必须**用独立 retrieval lane（§8）："
                    "绝不把两个词拼成一个 query 做一次搜索。返回两侧证据、"
                    "共享上下文、contrastive warnings、覆盖度。**不下理论结论。**"),
        "not_for": "不要用它做单概念的证据收集。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "concept_a": {"type": "string",
                              "description": "对比 A 侧（entity_id 或术语）"},
                "concept_b": {"type": "string",
                              "description": "对比 B 侧（entity_id 或术语）"},
                "language": {"type": "string", "enum": ["zh", "fr", "en", "any"],
                             "default": "any", "description": "限定两侧证据语言"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10,
                          "description": "**每侧**返回条数上限"},
            },
            "required": ["concept_a", "concept_b"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "trace_source",
        "title": "溯源链追溯",
        "purpose": ("Passage → PassageRealization → Witness → CorpusSource → source file "
                    "→ sha256 → provenance status。中文 recovered 语料必须继续显式标 "
                    "SOURCE_TRACE_INCOMPLETE。"),
        "not_for": "不要用它取语义证据（用 get_passage / search_passages）。",
        "inputSchema": {
            "type": "object",
            "properties": {"passage_id": {"type": "string",
                                          "description": "要追溯溯源链的 passage ID"}},
            "required": ["passage_id"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
    {
        "name": "terminology_lookup",
        "title": "受控术语映射查询",
        "purpose": ("查 Cross-lingual Terminology Bridge 的受控映射："
                    "entity identity / review status / ambiguity / contrastive warnings。"
                    "**不做普通机器翻译。**"),
        "not_for": "不要用它取证据；也不要期待它翻译任意句子。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "minLength": 1,
                         "description": "要查受控映射的术语（不会翻译任意句子）"},
                "source_language": {"type": "string",
                                    "enum": ["zh", "fr", "en", "any"], "default": "any",
                                    "description": "限定源语言（一般留 any）"},
                "target_language": {"type": "string",
                                    "enum": ["zh", "fr", "en", "any"], "default": "any",
                                    "description": "限定目标语言；any = 全部同 entity 写法"},
            },
            "required": ["term"],
            "additionalProperties": False,
        },
        "output": OUTPUT_SECTIONS,
    },
]

TOOL_NAMES = [t["name"] for t in TOOLS]

# 每个 tool 的语义边界（§5：证明它们不是彼此的参数别名）
RESPONSIBILITY_MATRIX = {
    "search_passages": {"scope": "通用", "entity_constrained": False,
                        "diachronic_grouping": False, "lanes": "按 route 决定"},
    "find_concept_evidence": {"scope": "单实体", "entity_constrained": True,
                              "diachronic_grouping": False, "lanes": 1},
    "trace_concept": {"scope": "单实体 · 历时", "entity_constrained": True,
                      "diachronic_grouping": True, "lanes": "按 period 分组"},
    "compare_concepts": {"scope": "双实体", "entity_constrained": True,
                         "diachronic_grouping": False, "lanes": "每概念一条"},
    "get_passage": {"scope": "单 passage", "entity_constrained": False,
                    "diachronic_grouping": False, "lanes": 0},
    "get_context": {"scope": "单 passage 邻域", "entity_constrained": False,
                    "diachronic_grouping": False, "lanes": 0},
    "resolve_entity": {"scope": "解析", "entity_constrained": True,
                       "diachronic_grouping": False, "lanes": 0},
    "get_concept": {"scope": "实体元数据", "entity_constrained": True,
                    "diachronic_grouping": False, "lanes": 0},
    "trace_source": {"scope": "溯源", "entity_constrained": False,
                     "diachronic_grouping": False, "lanes": 0},
    "terminology_lookup": {"scope": "术语映射", "entity_constrained": True,
                           "diachronic_grouping": False, "lanes": 0},
}
