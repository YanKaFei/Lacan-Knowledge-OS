#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.schemas — Phase 4D.1 MCP Tool Set v1（10 个只读工具）

纪律
────
* 工具描述**克制**（§21）：不写「回答任何关于 Lacan 的问题」，而是说明它调用的是
  **冻结的** Lacan Scholarly Research Core，返回 validated claims / citations /
  provenance / limitations 或 abstention。这样 Agent 不会把它当普通知识模型。
* 输入 schema 一律 `additionalProperties: false`（§30：只接受领域参数，
  不接受文件路径 / shell / SQL / Python 表达式）。
* 输出 schema 复用 `scholarly_api.objects` 的稳定对象（不新增第二套形状）。
"""
from __future__ import annotations

import os
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from scholarly_api import objects as O          # noqa: E402
from . import config as C                       # noqa: E402

RESEARCH_DESC = (
    "Use the frozen Lacan Scholarly Research Core to research corpus-supported "
    "questions and return validated claims, citations, provenance, limitations, "
    "or abstention. It does NOT answer from model knowledge: if the corpus cannot "
    "support the question the core abstains and that abstention is propagated "
    "verbatim."
)

_LANG = {"type": ["string", "null"], "enum": ["zh", "fr", "en", "any", None]}
_MODE = {"type": ["string", "null"],
         "enum": ["quick", "scholarly", "concept_definition", "concept_relation",
                  "comparison", "diachronic", "seminar_specific", "case_research",
                  "freud_to_lacan", "philosophy_to_lacan", "topology_matheme",
                  "translation_terminology", None]}
_PROVIDER = {"type": ["string", "null"], "enum": ["mock", "llm", None],
             "default": "mock",
             "description": "mock = deterministic, no network (default). "
                            "llm = explicit opt-in; requires credentials."}
_PASSAGE_ID = {"type": "string", "pattern": C.PASSAGE_ID_RE}
_CONCEPT_ID = {"type": "string", "pattern": C.CONCEPT_ID_RE}
_SEMINAR_ID = {"type": "string", "pattern": C.SEMINAR_ID_RE}


def _inp(props, required, desc):
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": desc, "type": "object", "additionalProperties": False,
            "properties": props, "required": required}


_RESEARCH_OPTS = {
    "language": dict(_LANG, default="any"),
    "mode": dict(_MODE, default="scholarly"),
    "constraints": {"type": ["object", "null"]},
    "requested_source_layers": {"type": ["array", "null"], "items": {"type": "string"}},
    "requested_output_depth": {"type": ["string", "null"],
                               "enum": ["brief", "standard", "deep", None]},
    "provider": _PROVIDER,
    "judge": {"type": ["boolean", "null"], "default": None},
    "budget": {"type": ["integer", "null"], "minimum": 1, "maximum": 200},
    "task_id": {"type": ["string", "null"], "maxLength": 120},
}


def _research_input(question_desc, extra=None, required=("question",)):
    props = {"question": {"type": "string", "minLength": 4, "maxLength": 2000,
                          "description": question_desc}}
    props.update(extra or {})
    props.update(_RESEARCH_OPTS)
    return _inp(props, list(required), question_desc)


TOOLS = [
    # ── 1 研究入口
    {
        "name": "lacan.research",
        "title": "Frozen scholarly research (validated answer or abstention)",
        "purpose": RESEARCH_DESC,
        "not_for": "open-ended Lacan chat, model-knowledge answers, or quoting "
                   "without passage_id",
        "inputSchema": _research_input(
            "Research question about Lacan / psychoanalysis, answerable from the "
            "local corpus."),
        "output_object": "FinalScholarlyAnswer",
        "timeout_class": "research",
    },
    # ── 2 检索
    {
        "name": "lacan.search_passages",
        "title": "Search corpus passages (exact/lexical, dense auxiliary if available)",
        "purpose": ("Search the lacanian corpus and return passages with passage_id, "
                    "snippet, seminar, language, source_layer and provenance_status. "
                    "Lexical path is always available; the dense path is auxiliary "
                    "and its availability is reported in meta.dense_available."),
        "not_for": "semantic paraphrase without corpus grounding, or generating "
                   "quotations that were not returned",
        "inputSchema": _inp({
            "query": {"type": "string", "minLength": 1, "maxLength": 500},
            "seminar": {"type": ["string", "null"], "pattern": C.SEMINAR_ID_RE},
            "session": {"type": ["string", "null"], "pattern": C.SESSION_ID_RE},
            "language": dict(_LANG, default="any"),
            "source_layer": {"type": ["string", "null"],
                             "enum": ["L1_TRANSCRIPTION", "L2_RECOVERED",
                                      "L1_EDITION", None]},
            "date_range": {"type": ["object", "null"],
                           "additionalProperties": False,
                           "properties": {"from": {"type": ["string", "integer", "null"]},
                                          "to": {"type": ["string", "integer", "null"]}}},
            "concept": {"type": ["string", "null"], "maxLength": 80},
            "formalism": {"type": ["string", "null"], "maxLength": 80},
            "limit": {"type": ["integer", "null"], "minimum": 1,
                      "maximum": C.MAX_SEARCH_LIMIT,
                      "default": C.DEFAULT_SEARCH_LIMIT},
        }, ["query"], "Corpus passage search"),
        "output_object": "PassageSearchResult",
        "timeout_class": "search",
    },
    # ── 3 取段
    {
        "name": "lacan.get_passage",
        "title": "Get one stored passage by passage_id",
        "purpose": ("Return the stored passage record (text, language, seminar, "
                    "session, source_layer, witness, provenance). Use it to verify "
                    "any citation you received."),
        "not_for": "batch export, corpus dumping, or retrieving passages by file path",
        "inputSchema": _inp({"passage_id": _PASSAGE_ID}, ["passage_id"],
                            "Get passage"),
        "output_object": "PassageRecord",
        "timeout_class": "lookup",
    },
    # ── 4 上下文
    {
        "name": "lacan.get_context",
        "title": "Get a passage with its neighbouring context window",
        "purpose": ("Return the passage plus neighbours in original order "
                    "(before ≤ %d, after ≤ %d). Passage ids and order are preserved."
                    % (C.MAX_CONTEXT_BEFORE, C.MAX_CONTEXT_AFTER)),
        "not_for": "pulling a whole seminar at once (use bounded windows instead)",
        "inputSchema": _inp({
            "passage_id": _PASSAGE_ID,
            "before": {"type": ["integer", "null"], "minimum": 0,
                       "maximum": C.MAX_CONTEXT_BEFORE, "default": 3},
            "after": {"type": ["integer", "null"], "minimum": 0,
                      "maximum": C.MAX_CONTEXT_AFTER, "default": 3},
        }, ["passage_id"], "Get passage context"),
        "output_object": "PassageContext",
        "timeout_class": "lookup",
    },
    # ── 5 概念
    {
        "name": "lacan.get_concept",
        "title": "Get a canonical concept record (read-only ontology view)",
        "purpose": ("Return concept_id, canonical name, aliases, status, relations, "
                    "terminology and evidence ids from the canonical ontology. "
                    "Read-only: candidate relations are never written back."),
        "not_for": "editing ontology, approving mappings, or inventing relations",
        "inputSchema": _inp({"concept_id": _CONCEPT_ID}, ["concept_id"],
                            "Get concept"),
        "output_object": "ConceptRecord",
        "timeout_class": "lookup",
    },
    # ── 6 研讨班
    {
        "name": "lacan.get_seminar",
        "title": "Get a seminar record (sessions, years, source layers, counts)",
        "purpose": ("Return seminar_id, title, years, sessions (lesson, passage "
                    "count, languages, trace_status), available source layers and "
                    "passage_count. Missing bibliography is reported as absent, "
                    "never fabricated."),
        "not_for": "fabricating publication data or bibliography",
        "inputSchema": _inp({"seminar_id": _SEMINAR_ID}, ["seminar_id"],
                            "Get seminar"),
        "output_object": "SeminarRecord",
        "timeout_class": "lookup",
    },
    # ── 7 溯源
    {
        "name": "lacan.trace_source",
        "title": "Trace a passage back to corpus source / witness / realization",
        "purpose": ("Return the provenance chain (corpus_source, witness, passage "
                    "realization, seminar, session, edition, source_layer, "
                    "trace_status). SOURCE_TRACE_INCOMPLETE is returned verbatim "
                    "and must not be hidden."),
        "not_for": "upgrading a recovered source into a primary one",
        "inputSchema": _inp({"passage_id": _PASSAGE_ID}, ["passage_id"],
                            "Trace passage provenance"),
        "output_object": "ProvenanceRecord",
        "timeout_class": "lookup",
    },
    # ── 8-10 专门研究入口（只是 specialized ResearchRequest，不另写引擎）
    {
        "name": "lacan.compare_terms",
        "title": "Compare two terms through the frozen research core",
        "purpose": ("Specialized ResearchRequest (concept_relation) comparing two "
                    "terms with corpus evidence per side. No second engine: it "
                    "delegates to the same frozen core as lacan.research."),
        "not_for": "inventing distinctions the corpus does not support",
        "inputSchema": _research_input(
            "Comparison question (auto-filled from term_a/term_b).",
            extra={"term_a": {"type": "string", "minLength": 1, "maxLength": 80},
                   "term_b": {"type": "string", "minLength": 1, "maxLength": 80}},
            required=("term_a", "term_b")),
        "output_object": "FinalScholarlyAnswer",
        "timeout_class": "research",
        "question_from_args": lambda a: "%s 与 %s 有什么区别？请分别给出各自的语料证据。"
                                        % (a["term_a"], a["term_b"]),
    },
    {
        "name": "lacan.research_diachronic",
        "title": "Diachronic research on a concept through the frozen core",
        "purpose": ("Specialized ResearchRequest (diachronic) asking how a concept "
                    "changes over a period, with per-stage corpus evidence. If the "
                    "corpus lacks the endpoints, the core's limitation/abstention is "
                    "propagated unchanged."),
        "not_for": "filling missing periods with model knowledge",
        "inputSchema": _research_input(
            "Diachronic question (auto-filled from concept/start/end).",
            extra={"concept": {"type": "string", "minLength": 1, "maxLength": 80},
                   "start": {"type": ["string", "integer", "null"]},
                   "end": {"type": ["string", "integer", "null"]}},
            required=("concept",)),
        "output_object": "FinalScholarlyAnswer",
        "timeout_class": "research",
        "question_from_args": lambda a: (
            "%s 在 %s 之间发生了什么变化？请给出各阶段的语料依据。"
            % (a["concept"],
               ("%s–%s" % (a.get("start"), a.get("end")))
               if (a.get("start") or a.get("end")) else "其语料覆盖的全部时期")),
    },
    {
        "name": "lacan.research_translation",
        "title": "Chinese translation-terminology research through the frozen core",
        "purpose": ("Specialized ResearchRequest (translation_terminology): which "
                    "Chinese renderings exist for a French term and what the "
                    "differences mean. Mapping / attestation / interpretation "
                    "levels are kept distinct by the core."),
        "not_for": "asserting a rendering is attested when the corpus has no witness",
        "inputSchema": _research_input(
            "Translation question (auto-filled from term).",
            extra={"term": {"type": "string", "minLength": 1, "maxLength": 80}},
            required=("term",)),
        "output_object": "FinalScholarlyAnswer",
        "timeout_class": "research",
        "question_from_args": lambda a: (
            "中文语料里 %s 有哪些译法？这些译名差异意味着什么？" % a["term"]),
    },
]

TOOL_NAMES = [t["name"] for t in TOOLS]

# 输出对象的稳定 schema（来自 Phase 4D.0 的 objects，不新造形状）
OUTPUT_SCHEMAS = {t["name"]: t["output_object"] for t in TOOLS}


def tool_by_name(name):
    for t in TOOLS:
        if t["name"] == name:
            return t
    return None


def validate_input(name, args):
    """→ (ok, errors, filled)。fail closed：任何不合 schema 都拒绝执行。"""
    t = tool_by_name(name)
    if t is None:
        return False, ["unknown tool: %s" % name], {}
    try:
        import jsonschema
        v = jsonschema.Draft202012Validator(t["inputSchema"])
        # ⚠️ 不回显用户输入：只报「哪个字段 + 违反哪条规则」（脱敏，且避免把
        #    任意输入（例如路径样式串）原样回灌到客户端 —— §30 纵深防御）
        errs = []
        for e in v.iter_errors(args or {}):
            field = "/".join(str(x) for x in e.absolute_path) or "(root)"
            rule = e.validator
            if rule == "additionalProperties":
                extra = [k for k in (args or {})
                         if k not in (t["inputSchema"].get("properties") or {})]
                errs.append({"field": field, "rule": rule,
                             "message": "出现未声明参数：%s" % ", ".join(extra[:5])})
            elif rule == "required":
                errs.append({"field": field, "rule": rule,
                             "message": "缺少必填参数"})
            else:
                errs.append({"field": field, "rule": rule,
                             "message": "取值不符合该字段的约束（%s）" % rule})
    except ImportError:
        req = t["inputSchema"].get("required") or []
        errs = [{"field": k, "rule": "required", "message": "缺少必填参数"}
                for k in req if k not in (args or {})]
    if errs:
        return False, errs, {}
    return True, [], apply_defaults(name, args or {})


def apply_defaults(name, args):
    """从 inputSchema 的 `default` 注解显式填充缺省值（jsonschema 不会自动填）。

    关键缺省：`provider` = "mock"（§6：真实 LLM 必须显式请求）。
    """
    t = tool_by_name(name)
    out = dict(args or {})
    for k, spec in (t["inputSchema"].get("properties") or {}).items():
        if k not in out and "default" in spec:
            out[k] = spec["default"]
    return out


def validate_output(name, obj):
    """→ (ok, errors)。用 Phase 4D.0 稳定对象校验输出（fail closed）。"""
    t = tool_by_name(name)
    if t is None:
        return False, ["unknown tool"]
    return O.validate(t["output_object"], obj)


def input_schema_id(name):
    return "%s/input/v1" % name
