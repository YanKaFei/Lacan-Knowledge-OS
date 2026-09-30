#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
argcheck.py — 极简 JSON Schema 校验（零依赖）

MCP tool 的 `inputSchema` 是 JSON Schema。§20 要求测「invalid args」，
所以调用方传错参数必须得到**结构化错误**，而不是 Python traceback。

为什么自己写而不是装 jsonschema：
* 项目对离线可复现性有硬要求，MCP server 必须能在**只有标准库**的
  system python3 下启动（向量路径可缺席）；
* 本阶段用到的 JSON Schema 子集非常小（type/enum/required/min/max/items/
  additionalProperties/minLength/maxLength/pattern）。
不做完整实现，**做多少写多少**，未支持的关键字在
`UNSUPPORTED_KEYWORDS` 里显式列出并在校验时忽略（而不是静默当通过）。
"""

from __future__ import annotations

import re

SUPPORTED_KEYWORDS = {
    "type", "enum", "const", "required", "properties", "items",
    "additionalProperties", "minimum", "maximum", "minLength", "maxLength",
    "pattern", "default", "description", "title",
}
# 明确**不支持**的关键字（写下来，避免以为它们生效了）
UNSUPPORTED_KEYWORDS = {
    "oneOf", "anyOf", "allOf", "not", "$ref", "if", "then", "else",
    "dependentRequired", "multipleOf", "uniqueItems", "minItems", "maxItems",
}


class ValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join("%s: %s" % (e["path"], e["message"]) for e in errors))


def _type_ok(value, t):
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    if t == "null":
        return value is None
    return True


def _check(value, schema, path, errors):
    if not isinstance(schema, dict):
        return
    t = schema.get("type")
    if t and not _type_ok(value, t):
        errors.append({"path": path or "(root)",
                       "message": "期望 %s，实际 %s" % (t, type(value).__name__)})
        return
    if "const" in schema and value != schema["const"]:
        errors.append({"path": path or "(root)",
                       "message": "必须是 %r" % (schema["const"],)})
    if "enum" in schema and value not in schema["enum"]:
        errors.append({"path": path or "(root)",
                       "message": "必须是 %s 之一" % (schema["enum"],)})
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append({"path": path or "(root)",
                           "message": "长度需 ≥ %d" % schema["minLength"]})
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append({"path": path or "(root)",
                           "message": "长度需 ≤ %d" % schema["maxLength"]})
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append({"path": path or "(root)",
                           "message": "不匹配 pattern %s" % schema["pattern"]})
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append({"path": path or "(root)",
                           "message": "需 ≥ %s" % schema["minimum"]})
        if "maximum" in schema and value > schema["maximum"]:
            errors.append({"path": path or "(root)",
                           "message": "需 ≤ %s" % schema["maximum"]})
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            _check(v, schema["items"], "%s[%d]" % (path, i), errors)
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for req in schema.get("required") or []:
            if req not in value:
                errors.append({"path": path or "(root)",
                               "message": "缺必填参数 %r" % req})
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errors.append({"path": k, "message": "未知参数（schema 不允许）"})
        for k, v in value.items():
            if k in props:
                _check(v, props[k], "%s.%s" % (path, k) if path else k, errors)


def validate(instance, schema):
    """→ (ok, errors)。errors 是 [{path, message}]。"""
    errors = []
    _check(instance, schema, "", errors)
    return (not errors), errors


def apply_defaults(instance, schema):
    """填默认值（只填顶层 properties 的 default，够本阶段用）。"""
    out = dict(instance or {})
    for k, sub in (schema.get("properties") or {}).items():
        if k not in out and isinstance(sub, dict) and "default" in sub:
            out[k] = sub["default"]
    return out
