#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_export_testlib.py — 4D.6 Export 测试共享工具（下划线开头 → 不被收集）

隔离：把 `export_system.policy.EXPORT_ROOTS["default"]` 指到
`_workspace/test_exports/<name>`，不污染真实 `_workspace/exports/`。
"""
from __future__ import annotations
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for p in (VAULT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import export_system as EX                                            # noqa: E402
import _project_testlib as PL                                         # noqa: E402

Q_GAZE = "Seminar XI 中 gaze 与 objet a 是什么关系？"
Q_FMRI = "拉康如何看待 fMRI 等当代神经科学影像研究？"
P_L1 = "passage.S11.unknown.P2253"
P_L2 = "passage.S05.unknown.L05.P0056"


class export_root:
    """with export_root('name'): ...  # 期间 default 导出根指向测试目录"""

    def __init__(self, name):
        self.name = name
        self.prev = None

    def __enter__(self):
        d = os.path.join(VAULT, "_workspace", "test_exports", self.name)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        self.prev = EX.policy.EXPORT_ROOTS.get("default")
        EX.policy.EXPORT_ROOTS["default"] = os.path.join("_workspace", "test_exports",
                                                        self.name)
        return d

    def __exit__(self, *exc):
        if self.prev is not None:
            EX.policy.EXPORT_ROOTS["default"] = self.prev
        return False


def view(question=Q_GAZE):
    """带跨进程缓存的 mock 研究答案（复用 4D.5 的缓存）。"""
    return PL.answer(question)


def abstention_view():
    return PL.abstention_answer()


def doc(question=Q_GAZE, **kw):
    return EX.build_from_answer(view(question), **kw)


def rendered(doc_obj):
    """→ {format: text}（三格式都渲染一遍）。"""
    return {"markdown": EX.markdown.render(doc_obj),
            "json": EX.json_export.render(doc_obj),
            "html": EX.html_export.render(doc_obj)}


def identity(doc_obj):
    return EX.scholarly_identity(doc_obj)


def read_bundle(path):
    with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    return man


def bundle_files(path):
    out = []
    for root, _dirs, files in os.walk(path):
        for fn in files:
            out.append(os.path.relpath(os.path.join(root, fn), path).replace(os.sep, "/"))
    return sorted(out)
