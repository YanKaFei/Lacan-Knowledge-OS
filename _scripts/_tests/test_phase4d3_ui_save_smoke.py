#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4d3_ui_save_smoke.py — 4D.3 §58：Workspace UI 上的真实浏览器 Save 烟测

起 HTTP 服务 + 真实 Chrome：跑 gaze 研究 → 自动点 Save（?save=1）→ 断言
"Saved to Obsidian" 与 note 路径出现；再用 fMRI 题确认保存的是 **Abstention Research Note**。
"""
import os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _ui_testlib as L
import _obsidian_testlib as OL

@unittest.skipUnless(L.chrome_available(), "Chrome 不可用")
class UiSaveSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from obsidian_adapter import vault as V
        # UI 保存走默认真实工作区（_workspace/obsidian_vault）——这里换成受控 QA 根
        cls.vault = OL.fresh_vault("ui_save_qa")
        os.environ["OBSIDIAN_VAULT_PATH"] = cls.vault.root
        L.answer(OL.Q_GAZE); L.answer(OL.Q_FMRI)          # 预热
        cls.srv = L.LiveServer()
        cls.qa = os.path.join(VAULT, "_workspace", "ui_qa")

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()
        os.environ.pop("OBSIDIAN_VAULT_PATH", None)

    def _dom(self, name, url, budget=5000):
        shot = os.path.join(self.qa, "%s.png" % name)
        dom, ok = L.chrome_render(url, shot, budget_ms=budget, window="1600,1200")
        self.assertTrue(ok, "截图失败 %s" % name)
        return dom

    def test_00_save_research_from_ui(self):
        dom = self._dom("E_saved_research",
                        "%s/?q=%s&mode=scholarly&provider=mock&autorun=1&save=1"
                        % (self.srv.base, OL.Q_GAZE.replace("/", "%2F")))
        self.assertIn("Saved to Obsidian", dom, dom[-2000:])
        self.assertRegex(dom, r"Research/\d{4}-\d{2}-\d{2}")
        self.assertIn("Open in Obsidian", dom)
        self.assertTrue(any(f.startswith("Research/") for f in OL.all_md(self.vault)))

    def test_01_save_abstention_note_from_ui(self):
        dom = self._dom("F_saved_abstention",
                        "%s/?q=%s&provider=mock&autorun=1&save=1"
                        % (self.srv.base, OL.Q_FMRI))
        self.assertIn("Saved to Obsidian", dom)
        notes = [f for f in OL.all_md(self.vault) if f.startswith("Research/")]
        abst = [f for f in notes if "fMRI" in f]
        self.assertTrue(abst, notes)
        txt = OL.note(self.vault, abst[0])
        self.assertIn("Current corpus cannot support a reliable answer", txt)
        self.assertNotIn("[[Concepts/", txt)      # §43：弃权不制造概念关系

    def test_02_saved_passages_exist_and_link(self):
        md = OL.all_md(self.vault)
        passages = [f for f in md if f.startswith("Passages/")]
        self.assertTrue(passages, md)
        for p in passages:
            self.assertTrue(OL.note(self.vault, p).startswith("---"))

    def test_03_inspector_has_save_passage_button(self):
        dom = L.chrome_render("%s/?inspect=%s" % (self.srv.base, OL.P_L2),
                              None, budget_ms=4000)[0]
        self.assertIn("Save Passage", dom)

    def test_04_screenshots_recorded(self):
        for name in ("E_saved_research.png", "F_saved_abstention.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.qa, name)), name)

if __name__ == "__main__":
    unittest.main()
