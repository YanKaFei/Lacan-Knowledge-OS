#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system — Phase 4D.6 Export & Citation System（§5/§62/§63）

    stored validated scholarly content  →  ExportDocument  →  {Markdown, JSON, HTML, Bundle}

边界：
    * 这是 **PRESENTATION / SERIALIZATION / PORTABILITY**，不是新的学术推理；
    * 只有 **verified Research Snapshot** 能作为 scholarly export source（§64）；
      用户编辑过的 note 另标 `USER_EDITED_DOCUMENT`；
    * 导出只新增 `_workspace/exports/**` 下的工件：**不改** core、**不改** workspace
      （project revision / run / Obsidian note / history 一律不动，§63）。
"""
from __future__ import annotations

from .builders import (build_from_answer, build_from_history, build_from_passage,
                       build_from_project_run, build_project_summary,
                       build_citation_records)
from .bundle import build_bundle, collect_passage_ids, extract_zip
from .citations import (BIBLIOGRAPHIC_REQUIREMENTS, BIBLIOGRAPHIC_STYLES,
                        INTERNAL_STYLES, citation_capabilities, citation_record,
                        citation_bindings, provenance_citation, render as render_citation,
                        short_citation, full_citation)
from .manifest import MANIFEST_NAME, bundle_hash, build_manifest, verify_bundle
from .model import (ANSWER_STATES, ERROR_CODES, EXPORTER_VERSION, EXPORT_MODEL_VERSION,
                    FORMATS, SCHEMA_BUNDLE_MANIFEST, SCHEMA_CITATION_RECORD,
                    SCHEMA_EXPORT_DOCUMENT, SOURCE_TYPES, ExportError,
                    assert_identity, canonical_payload, content_hash, export_payload_hash,
                    finalize_document, make_document, scholarly_identity, validate)
from .policy import (EXPORT_ROOTS, audit, export_root, list_exports, read_audit,
                     resolve_export_path, safe_name)
from . import html as html_export
from . import json_export
from . import markdown
from . import provenance as prov

__all__ = [
    "EXPORT_MODEL_VERSION", "EXPORTER_VERSION", "SOURCE_TYPES", "FORMATS",
    "ANSWER_STATES", "ERROR_CODES",
    "SCHEMA_EXPORT_DOCUMENT", "SCHEMA_BUNDLE_MANIFEST", "SCHEMA_CITATION_RECORD",
    "ExportError", "make_document", "finalize_document", "export_payload_hash",
    "canonical_payload",
    "content_hash", "validate", "assert_identity", "scholarly_identity",
    "build_from_answer", "build_from_history", "build_from_project_run",
    "build_from_passage", "build_project_summary", "build_citation_records",
    "build_bundle", "collect_passage_ids", "extract_zip",
    "build_manifest", "verify_bundle", "bundle_hash", "MANIFEST_NAME",
    "citation_capabilities", "citation_record", "citation_bindings",
    "render_citation", "short_citation", "full_citation", "provenance_citation",
    "INTERNAL_STYLES", "BIBLIOGRAPHIC_STYLES", "BIBLIOGRAPHIC_REQUIREMENTS",
    "markdown", "json_export", "html_export", "prov",
    "export_root", "list_exports", "safe_name", "audit", "read_audit",
    "resolve_export_path", "EXPORT_ROOTS",
]

PRODUCT_VERSION = "export-system/v1"
