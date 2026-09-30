#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_project_testlib.py — 4D.5 Research Project 测试共享工具（下划线开头 → 不被收集）

隔离策略：
    * 每个套件把 `project_api.store.PROJECTS_DIR` 指到
      `_workspace/test_projects/<name>`（USER_WORKSPACE，可清理），
      不动真实 `_workspace/projects/`；
    * Research 答案很贵（mock ≈ 15s），因此**按 (question, provider) 缓存到
      `_workspace/test_cache/`**，跨套件复用；缓存本身就是工作区数据，不是学术工件。
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for p in (VAULT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import project_api as PA                                            # noqa: E402
from project_api import store as PS                                 # noqa: E402

CACHE_DIR = os.path.join(VAULT, "_workspace", "test_cache")

Q_GAZE = "Seminar XI 中 gaze 与 objet a 是什么关系？"
Q_FMRI = "拉康如何看待 fMRI 等当代神经科学影像研究？"
Q_DESIRE = "欲望、需求与要求在拉康那里是什么关系？"

P_L1 = "passage.S11.unknown.P2253"
P_L2 = "passage.S05.unknown.L05.P0056"
C_DESIR = "concept.desir"
C_OBJET = "concept.objet-petit-a"
S_SEMINAR = "seminar.S11"


class isolated_projects:
    """with isolated_projects('name'): ...  # 期间 PROJECTS_DIR 指向测试目录"""

    def __init__(self, name):
        self.name = name
        self.prev = None

    def __enter__(self):
        d = os.path.join(VAULT, "_workspace", "test_projects", self.name)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        self.prev = PS.PROJECTS_DIR
        PS.PROJECTS_DIR = d
        return d

    def __exit__(self, *exc):
        PS.PROJECTS_DIR = self.prev
        return False


def _cache_identity():
    """缓存身份：答案 schema + 冻结语料版本（Phase 5A 实测踩过：只按 (Q, provider)
    取 key，会让 schema v1 → v1.1 之后的套件读到**上一代 payload**，把
    「产品变了」误报成「导出/呈现不一致」）。"""
    ident = {"schema": None, "freeze": None}
    try:
        from scholarly_api import objects as _objs
        ident["schema"] = _objs.SCHEMA_VERSIONS.get("FinalScholarlyAnswer")
    except Exception:                                                     # noqa: BLE001
        pass
    try:
        with open(os.path.join(VAULT, "_data", "core_freeze",
                              "scholarly_core_freeze_v1.json"), encoding="utf-8") as fh:
            ident["freeze"] = (json.load(fh).get("components") or {}).get(
                "corpus_inventory_hash")
    except Exception:                                                     # noqa: BLE001
        pass
    return ident


def answer(question, provider="mock"):
    """→ workspace answer view（带跨进程缓存，避免每个套件都重跑一次研究）。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(("%s|%s|%s" % (question, provider,
                                        json.dumps(_cache_identity(), sort_keys=True)))
                         .encode("utf-8")).hexdigest()[:16]
    path = os.path.join(CACHE_DIR, "answer-%s.json" % key)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    from workspace_ui.server import api as A                        # noqa: PLC0415
    out = A.research(question, provider=provider, save_history=False)
    view = out["view"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(view, f, ensure_ascii=False)
    return view


def abstention_answer(provider="mock"):
    return answer(Q_FMRI, provider=provider)


def make_project(title="测试项目", description="", tags=None, questions=None):
    return PA.create_project(title, description=description, tags=tags,
                             questions=questions or [])
