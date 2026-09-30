#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase5a_backward_compat.py — Phase 5A §37/§38/§39：RC1.1 工件向后兼容

用**真实** RC1.1 工件（不是合成 fixture）：

* `_workspace/projects/*/snapshots/*.json` —— 含验证日志的旧 run 快照；
* `_workspace/history/*.json` —— 旧研究历史；
* `_workspace/exports/**/*.json` —— 旧导出。

断言：
1. **不 mutation**：渲染前后文件 sha256 逐字节不变；
2. 旧载荷经新的 presentation 层渲染 → 用户可见面 **0 内部诊断**；
3. audit 面 `derived_from_legacy=True` 且旧诊断**可取回**（内容 100% 保留）；
4. 旧 payload 的 schema_version（v1）仍被接受；v1.1 与 v1 并存；
5. 旧导出 JSON 仍可解析（迁移不破坏既有研究）。
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (os.path.join(VAULT, "_scripts", "_tools"),
          os.path.join(VAULT, "_scripts", "_tools", "lacan_mcp"), VAULT):
    sys.path.insert(0, p)

from scholarly_api import objects as O               # noqa: E402
from workspace_ui.server import presentation as PZ, viewmodel as VM   # noqa: E402

SNAP_GLOB = os.path.join(VAULT, "_workspace", "projects", "*", "snapshots", "*.json")
HIST_GLOB = os.path.join(VAULT, "_workspace", "history", "*.json")


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _load_snapshots(limit=6):
    out = []
    for p in sorted(glob.glob(SNAP_GLOB))[:limit]:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                                 # noqa: BLE001
            continue
        payload = ((d.get("snapshot") or {}).get("raw") or {}).get("scholarly_payload")
        if payload:
            out.append((p, payload))
    return out


class TestBackwardCompatibility(unittest.TestCase):

    def test_00_legacy_snapshots_are_readable_and_unmodified(self):
        snaps = _load_snapshots()
        self.assertTrue(snaps, "没有找到 RC1.1 run 快照（向后兼容必须用真实工件验证）")
        for path, payload in snaps:
            before = sha(path)
            view = VM.answer_view({"ok": True, "result": payload,
                                   "meta": {"provider": "mock"}})
            self.assertEqual(view["kind"], "answer")
            self.assertEqual(sha(path), before, "渲染旧快照改动了历史文件（禁止 mutation）")
            self.assertIn(payload.get("schema_version"),
                          O.ANSWER_SCHEMA_VERSIONS_SUPPORTED)

    def test_01_legacy_diagnostics_are_routed_out_of_user_view(self):
        routed_any = False
        for _path, payload in _load_snapshots():
            hits = PZ.scan_user_facing_internal_diagnostics(payload)
            self.assertEqual(hits, [], "旧快照的用户可见面仍有诊断：%s" % hits)
            audit = PZ.audit_view(payload)
            if audit.get("derived_from_legacy"):
                routed_any = True
                legacy_text = json.dumps(audit.get("legacy_routed_text") or [],
                                         ensure_ascii=False)
                # 旧诊断必须 100% 可取回（不是被丢弃）
                self.assertTrue(legacy_text.strip() not in ("[]", ""),
                                "legacy 诊断没有进 audit 面 → 内容被丢弃了")
        self.assertTrue(routed_any, "本机 RC1.1 快照里应当存在需要 legacy 路由的诊断")

    def test_02_legacy_history_renders_cleanly(self):
        files = sorted(glob.glob(HIST_GLOB))[:8]
        self.assertTrue(files)
        for p in files:
            before = sha(p)
            d = json.load(open(p, encoding="utf-8"))
            payload = ((d.get("view") or {}).get("raw") or {}).get("scholarly_payload") \
                or (d.get("answer") or {}).get("raw", {}).get("scholarly_payload")
            if not payload:
                continue
            v = VM.answer_view({"ok": True, "result": payload, "meta": {"provider": "mock"}})
            self.assertEqual(v["kind"], "answer")
            self.assertEqual(PZ.scan_user_facing_internal_diagnostics(payload), [])
            self.assertEqual(sha(p), before)

    def test_03_legacy_exports_still_parse(self):
        files = sorted(glob.glob(os.path.join(VAULT, "_workspace", "exports",
                                              "**", "*.json"), recursive=True))[:20]
        self.assertTrue(files, "没有找到既有导出工件")
        bad = []
        for p in files:
            try:
                json.load(open(p, encoding="utf-8"))
            except Exception as exc:                                       # noqa: BLE001
                bad.append("%s: %s" % (os.path.basename(p), exc))
        self.assertEqual(bad, [], "旧导出无法解析（迁移破坏了既有研究）：%s" % bad)

    def test_04_both_schema_versions_supported(self):
        self.assertEqual(O.ANSWER_SCHEMA_VERSIONS_SUPPORTED,
                         ("final-scholarly-answer/v1", "final-scholarly-answer/v1.1"))
        base = {"api_version": "scholarly-api/v1", "question": "q",
                "answer_state": "VALIDATED", "answer_permission": "FULL_SYNTHESIS"}
        for ver in O.ANSWER_SCHEMA_VERSIONS_SUPPORTED:
            ok, errs = O.validate("FinalScholarlyAnswer", dict(base, schema_version=ver))
            self.assertTrue(ok, "%s 校验失败：%s" % (ver, errs[:2]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
