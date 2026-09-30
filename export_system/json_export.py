#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.json_export — ExportDocument → JSON（4D.6 §35/§57）

JSON 是**机器可读基线**：
    * 有 `schema_version`，字段名稳定；
    * 可以**反序列化回 ExportDocument**（round-trip），因此下游工具不必猜。
"""
from __future__ import annotations

import json

from .model import SCHEMA_EXPORT_DOCUMENT, ExportError, validate

REQUIRED_KEYS = ("schema_version", "export_type", "source_type", "source_id",
                 "created_at", "title", "sections", "claims", "citations",
                 "limitations", "provenance", "exporter_version", "evidence_role")


def render(doc, *, indent=2, validate_document=True):
    if validate_document:
        validate(doc, SCHEMA_EXPORT_DOCUMENT)
    return json.dumps(doc, ensure_ascii=False, indent=indent, sort_keys=True)


def load(text):
    """JSON → ExportDocument（§57）。缺字段或 schema 不对 → SCHEMA_VALIDATION_FAILED。"""
    try:
        doc = json.loads(text)
    except Exception as exc:                                              # noqa: BLE001
        raise ExportError("SCHEMA_VALIDATION_FAILED", "not valid JSON: %s" % exc)
    missing = [k for k in REQUIRED_KEYS if k not in doc]
    if missing:
        raise ExportError("SCHEMA_VALIDATION_FAILED", "missing required keys",
                          {"missing": missing})
    validate(doc, SCHEMA_EXPORT_DOCUMENT)
    return doc
