#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scholarly_api — Phase 4D.0 **产品层唯一入口**（Stable Scholarly API Boundary）

    PRODUCT LAYER  (UI / MCP / Obsidian / Agent)
          ↓   只允许 import scholarly_api
    STABLE SCHOLARLY API        ← 本包（v1 稳定对象 + 10 个入口 + 读写闸门）
          ↓
    FROZEN SCHOLARLY CORE       ← _data/core_freeze/scholarly_core_freeze_v1.json 钉住
          ↓
    CORPUS / INDEX / ONTOLOGY

产品层**不得**绕过本包访问 validator / repair / judge / Gold evaluator /
human review 数据。写文件必须走 `scholarly_api.policy.write_text/write_json`。
"""
from .core import (          # noqa: F401
    API_VERSION,
    research,
    search_passages,
    get_passage,
    get_context,
    get_concept,
    get_seminar,
    trace_source,
    compare_terms,
    research_concept,
    research_diachronic,
    research_translation,
)
from . import objects as objects     # noqa: F401
from . import policy as policy       # noqa: F401

__all__ = [
    "API_VERSION", "objects", "policy",
    "research", "search_passages", "get_passage", "get_context", "get_concept",
    "get_seminar", "trace_source", "compare_terms", "research_concept",
    "research_diachronic", "research_translation",
]
