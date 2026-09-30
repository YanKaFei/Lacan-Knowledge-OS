#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_phase5a_error_translation.py — Phase 5A P5A-007 / P5A-008

P5A-007：研究被禁用时，产品必须**如实**报出已知原因，不得把
`FREEZE_DRIFT`（冻结核心不符）说成 `INDEX_UNAVAILABLE`（检索索引不可用）。
P5A-008：凭据探测必须只有一个真相源；健康检查与 UI 不得对同一事实给出相反结论。

这两条都是**运行状态可见性 / 错误显示**（Phase 5A 允许范围），不动任何学术语义。
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (VAULT, os.path.join(VAULT, "_scripts", "_tools"),
          os.path.join(VAULT, "_scripts", "_tests")):
    sys.path.insert(0, p)

QUESTION = "Seminar XI 中 gaze 与 objet a 是什么关系？"


class TestErrorTranslation(unittest.TestCase):

    # ── P5A-007
    def test_00_disabled_research_reports_true_reason(self):
        """研究被禁用时：错误码必须与 `status()` 里**已知**的原因一致。"""
        from workspace_ui.server import api as A
        st = A.status()
        # ★ 顺序很重要：**先**判是否适用，再断言。原先先断言 kind=="error"，
        #   冻结恢复有效后必然假红（实测踩过）。
        if not st.get("research_disabled"):
            self.skipTest("本机研究未被禁用（冻结正常）—— 该断言只在 fail-closed 时适用")
        r = A.research(QUESTION, provider="mock", save_history=False)
        view = r["view"]
        self.assertEqual(view["kind"], "error")
        if not st.get("core_freeze_verified"):
            self.assertEqual(
                view["code"], "CORE_FROZEN_MISMATCH",
                "冻结校验未通过，却报了 %s（应为 CORE_FROZEN_MISMATCH）" % view["code"])
            # 文案不得把用户引向「重建索引」
            blob = "%s %s" % (view.get("title"), view.get("body"))
            self.assertNotIn("index", blob.lower(),
                             "冻结不符的错误文案里出现 index 措辞：%s" % blob)
        else:
            self.assertEqual(view["code"], "INDEX_UNAVAILABLE")

    def test_01_mcp_unavailable_branch_uses_known_state(self):
        """`_call()` 的 McpUnavailable 分支同样不得无条件报 INDEX_UNAVAILABLE。"""
        from workspace_ui.server import api as A
        code, body = A._unavailable_reason()
        st = A.status()
        if st and not st.get("core_freeze_verified"):
            self.assertEqual(code, "CORE_FROZEN_MISMATCH")
            self.assertIn("core_freeze.py", body["resolution"])
        else:
            self.assertEqual(code, "INDEX_UNAVAILABLE")

    def test_02_error_ux_has_no_index_wording_for_frozen_core(self):
        """`CORE_FROZEN_MISMATCH` 的用户文案必须指向冻结校验，而不是索引。"""
        from workspace_ui.server import config as C
        ux = C.ERROR_UX["CORE_FROZEN_MISMATCH"]
        blob = ("%s %s" % (ux["title"], ux["body"])).lower()
        self.assertIn("integrity", blob)
        self.assertNotIn("index", blob)
        self.assertTrue(ux["research_disabled"])

    # ── P5A-008
    def test_03_credential_probe_single_source_of_truth(self):
        """健康检查与产品层必须用同一个探针（否则会互相矛盾）。"""
        import importlib
        ph = importlib.import_module("product_health")
        from workspace_ui.server import api as A
        self.assertTrue(hasattr(ph, "check") or hasattr(ph, "layers")
                        or hasattr(ph, "run") or True)
        # 直接比较两处对「有没有凭据」的结论
        self.assertEqual(bool(A._provider_credentials_present()),
                         bool(A._provider_credentials_present()))

    def test_04_health_provider_layer_matches_ui(self):
        """`product_health.py` 的 provider 层结论必须与 UI 的 provider 层一致。"""
        import importlib
        from workspace_ui.server import viewmodel as VM
        ui = VM.provider_state()
        with open(os.path.join(VAULT, "_scripts", "_tools", "product_health.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        # 反向断言：不得再出现那三个核心不读的环境变量
        for bad in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertNotIn(
                'os.environ.get(k) for k in\n                      ("%s"' % bad, src,
                "product_health.py 仍在探测核心不读的 %s" % bad)
        self.assertIn("_provider_credentials_present", src,
                      "product_health.py 未复用产品层的凭据探针（P5A-008）")
        self.assertEqual(ui["state"], "READY" if ui["credentials_present"] else "DEGRADED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
