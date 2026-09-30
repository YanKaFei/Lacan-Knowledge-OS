#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_obsidian_testlib.py — 4D.3 测试共享工具（下划线开头 → 不被收集）"""
from __future__ import annotations
import json, os, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
for p in (VAULT, HERE): 
    if p not in sys.path: sys.path.insert(0, p)
import _ui_testlib as U                                        # noqa: E402
from obsidian_adapter import adapter as A, vault as V          # noqa: E402
from scholarly_api import policy as POL                        # noqa: E402

Q_GAZE = "Seminar XI 中 gaze/regard 是如何与 objet a 发生关系的？"
Q_FMRI = "拉康如何看待 fMRI 等当代神经科学影像研究？"
Q_META = "拉康 1953 年 11 月 18 日那场报告的确切时间、地点与在场者是谁？"
P_L1 = "passage.S11.unknown.P2253"
P_L2 = "passage.S05.unknown.L05.P0056"


def fresh_vault(name):
    """每个套件用独立子根（在 _workspace 内，受管、可清理）。"""
    root = os.path.join("_workspace", "test_vaults", name)
    shutil.rmtree(os.path.join(VAULT, root), ignore_errors=True)
    return V.Vault(root)


def view(question=Q_GAZE, **kw):
    opts = {"provider": "mock"}; opts.update(kw)
    return U.answer(question, **opts)


def save(v, question=Q_GAZE, **kw):
    return A.save_research(view(question), vault=v, **kw)


def note(v, rel):
    return v.read(rel)


def seminar_short(v, rel):
    """`Seminars/S10.md` → `S10`（读 frontmatter，不靠行号拼）。"""
    from obsidian_adapter.frontmatter import parse_frontmatter
    meta, _ = parse_frontmatter(v.read(rel) or "")
    return str((meta or {}).get("seminar_id") or "").replace("seminar.", "")


def links_in(text):
    """note 文本里的全部 wikilink / embed 目标（去掉 label 与 .md）。"""
    import re
    out = []
    for m in re.findall(r"!?\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", text or ""):
        t = m.strip()
        out.append(t[:-3] if t.endswith(".md") else t)
    return out


def core_snapshot():
    return POL.snapshot_immutable()


def all_md(v):
    out = []
    for root, _dirs, files in os.walk(v.root):
        for f in files:
            if f.endswith(".md"):
                out.append(os.path.relpath(os.path.join(root, f), v.root))
    return sorted(out)
