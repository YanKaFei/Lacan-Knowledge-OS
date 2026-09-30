#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
obsidian_adapter.frontmatter — 受控 YAML frontmatter 序列化（§51/§50）

**绝不**用 `f"---\\n{user_text}\\n---"` 拼接。只序列化受控字段：
标量（str/int/bool/None）、标量列表、或「字符串 → 标量」的浅 dict。
不可信文本（用户问题、corpus 原文）只进正文。
"""
from __future__ import annotations

import re

_NEEDS_QUOTE = re.compile(r"[:#\[\]{}&*!|>'\"%@`,\-?]|^\s|\s$|^$|^(true|false|null|~)$",
                          re.IGNORECASE)
_SAFE_PLAIN = re.compile(r"^[A-Za-z0-9_./]+$")


def _scalar(v):
    # bool/None 放前面（bool 是 int 的子类）
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return ("%r" % v)
    s = str(v)
    if _SAFE_PLAIN.match(s) and not _NEEDS_QUOTE.search(s):
        return s
    # 双引号 + 转义（YAML 双引号风格）
    esc = (s.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", " ").replace("\r", " ").replace("\t", " "))
    return '"%s"' % esc


def _dump_value(v, indent=0):
    pad = "  " * indent
    lines = []
    if isinstance(v, dict):
        for k, vv in sorted(v.items(), key=lambda kv: str(kv[0])):
            if isinstance(vv, (dict, list)):
                lines.append("%s%s:" % (pad, k))
                lines.extend(_dump_value(vv, indent + 1))
            else:
                lines.append("%s%s: %s" % (pad, k, _scalar(vv)))
        return lines
    if isinstance(v, (list, tuple)):
        for it in v:
            if isinstance(it, (dict, list)):
                sub = _dump_value(it, indent + 1)
                lines.append("%s-" % pad)
                lines.extend(sub)
            else:
                lines.append("%s- %s" % (pad, _scalar(it)))
        return lines
    lines.append("%s%s" % (pad, _scalar(v)))
    return lines


def dump_frontmatter(meta: dict) -> str:
    """→ `---\\n…\\n---\\n`（键排序，受控字段）。"""
    body = "\n".join(_dump_value(meta, 0))
    return "---\n%s\n---\n" % body


def parse_frontmatter(text):
    """→ (meta, body)。只做轻量解析（够用于"是不是本系统管理的 note"判断）。"""
    if not text or not text.startswith("---"):
        return None, text or ""
    end = text.find("\n---", 3)
    if end < 0:
        return None, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:]
    if body.startswith("\n"):
        body = body[1:]
    meta, key = {}, None
    for line in raw.split("\n"):
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val == "":
                meta[key] = []
            else:
                meta[key] = _unquote(val)
        elif line.strip().startswith("- ") and key is not None:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_unquote(line.strip()[2:].strip()))
    return meta, body


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if v in ("true", "false"):
        return v == "true"
    if v == "null":
        return None
    if re.fullmatch(r"-?\d+", v):
        try:
            return int(v)
        except ValueError:
            return v
    return v


# ── managed block（§14 方案 B：只更新受管区块，区块外逐字节不动）
MARK_START = "<!-- LACAN-OS:GENERATED:START -->"
MARK_END = "<!-- LACAN-OS:GENERATED:END -->"


def has_managed_block(text):
    return MARK_START in (text or "") and MARK_END in (text or "")


def upsert_managed(existing_text, generated_body):
    """只替换 managed 区块内容；区块外**逐字节保留**。没有标记则追加（不覆盖已有内容）。"""
    existing_text = existing_text or ""
    block = "%s\n%s\n%s" % (MARK_START, generated_body.strip("\n"), MARK_END)
    if has_managed_block(existing_text):
        i = existing_text.index(MARK_START)
        j = existing_text.index(MARK_END) + len(MARK_END)
        return existing_text[:i] + block + existing_text[j:]
    sep = "" if existing_text.endswith("\n") or not existing_text else "\n"
    tail = "" if existing_text.endswith("\n\n") or not existing_text else "\n"
    return existing_text + sep + tail + block + "\n"


def strip_managed(text):
    """→ 去掉 managed 区块后的剩余文本（用于「区块外是否被改动」比对）。"""
    if not has_managed_block(text or ""):
        return text or ""
    i = text.index(MARK_START)
    j = text.index(MARK_END) + len(MARK_END)
    return text[:i] + text[j:]
