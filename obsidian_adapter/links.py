#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""obsidian_adapter.links — 安全 wikilink 与稳定文件名（§52/§7/§11）"""
from __future__ import annotations

import re
import unicodedata

_BAD_LINK = re.compile(r"[\[\]|#^]")
_BAD_FILE = re.compile(r"[/\\:*?\"<>|\x00-\x1f\uFF01-\uFF5E\u3000-\u303F]")
_WS = re.compile(r"\s+")


def safe_label(text, fallback="note"):
    s = _BAD_LINK.sub("", str(text or "")).replace("\n", " ").strip()
    return s or fallback


def wikilink(note_rel_path, label=None):
    """`[[Passages/S11.P2253|S11 · P2253]]` —— target 与 label 都做安全化。"""
    target = _BAD_LINK.sub("", str(note_rel_path or "")).replace("\\", "/")
    if target.endswith(".md"):
        target = target[:-3]
    if not target:
        return "[[%s]]" % safe_label(label)
    if label:
        return "[[%s|%s]]" % (target, safe_label(label))
    return "[[%s]]" % target


def slug(text, maxlen=80, fallback="note"):
    """稳定、跨平台安全的文件名片段（保留 CJK）。"""
    s = unicodedata.normalize("NFC", str(text or ""))
    s = _BAD_FILE.sub("-", s)
    s = _WS.sub(" ", s).strip(" .-")
    s = s.replace(" ", "-")
    s = re.sub(r"-{2,}", "-", s)
    if len(s) > maxlen:
        s = s[:maxlen].rstrip(" .-")
    return s or fallback


def passage_note_name(passage_id):
    """`passage.S11.unknown.P2253` → `S11.P2253`（稳定、可读）。"""
    pid = str(passage_id or "")
    m = re.match(r"^passage\.(S\d+[A-Z]?)\.(?:[^.]+\.)*?(P\d+)$", pid)
    if m:
        return "%s.%s" % (m.group(1), m.group(2))
    return slug(pid.replace(".", "-"), fallback="passage")


def duplicate_safe(path_exists, base_name, ext=".md", limit=50):
    """→ 可用文件名：`x.md` → `x (2).md` …（§7）"""
    if not path_exists(base_name + ext):
        return base_name + ext
    for i in range(2, limit + 1):
        cand = "%s (%d)%s" % (base_name, i, ext)
        if not path_exists(cand):
            return cand
    raise RuntimeError("duplicate-safe naming exhausted: %s" % base_name)
