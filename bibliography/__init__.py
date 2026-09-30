#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bibliography — Phase 5C 书目层（BibliographicItem / Edition / Work / Zotero）。

定位：**书目身份真源**是该 registry；Zotero 只是外部导入/导出源（§53）。
本层不修改任何 scholarly answer semantics（§56）。
"""
from . import model, registry, render, zotero                            # noqa: F401

__all__ = ["model", "registry", "render", "zotero"]
