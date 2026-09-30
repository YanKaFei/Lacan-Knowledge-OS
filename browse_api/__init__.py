#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browse_api — Phase 4D.4 **Corpus Browse** 产品只读层（§41/§42/§43）

    Research Retrieval  = 冻结学术核心的检索语义（MCP `lacan.search_passages` 等）
    Corpus Browse       = 本模块：对 canonical 语料元数据做 deterministic 浏览

边界（硬）：
    * **只读**：不写任何 canonical 工件；不 import 冻结核心内部；**不调用 LLM**；
    * 不是 scholarly core 的一部分，也不进 `SCHOLARLY_CORE_READY` 语义冻结组件；
      它注册在 **product interface lineage** 里（见报告 §22）；
    * 所有「语料事实」（attestation / distribution / formalism）都标注来源与算法，
      与「本体事实」（mapping / relation / definition）分开呈现。

入口（§42）：
    list_concepts / get_concept_view / concept_graph
    list_seminars / get_seminar_view / list_sessions
    browse_passages / get_passage_view / session_stream
    list_terminology / get_term_view
    （+ provenance: source_trace / witnesses / realization_languages / context）
"""
from __future__ import annotations

from .concepts import concept_graph, get_concept_view, list_concepts
from .passages import (browse, context, diachronic_view, formalism_counts,
                       get_passage, realization_languages, seminar_distribution,
                       session_stream, source_trace, witnesses)
from .seminars import get_seminar_view, list_seminars, list_sessions
from .store import (BROWSE_API_VERSION, BrowseUnavailable, attestation, availability,
                    clear_cache, concept_index, corpus_total, relations_view)
from .terminology import get_term_view, list_terminology, reel_realite_control

__all__ = [
    "BROWSE_API_VERSION", "BrowseUnavailable", "availability", "clear_cache",
    "corpus_total", "attestation", "concept_index", "relations_view",
    "list_concepts", "get_concept_view", "concept_graph",
    "list_seminars", "get_seminar_view", "list_sessions",
    "browse_passages", "get_passage_view", "session_stream", "context",
    "source_trace", "witnesses", "realization_languages",
    "seminar_distribution", "diachronic_view", "formalism_counts",
    "list_terminology", "get_term_view", "reel_realite_control",
]

# §42 命名别名（对外契约名 → 实现名）
browse_passages = browse
get_passage_view = get_passage
