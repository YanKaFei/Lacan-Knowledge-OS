#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4d4_ui_browser_smoke.py — 4D.4 §68：真实 Chrome 走完整研究链路

覆盖 §68 的两条动线：
  ① Concepts → 搜 objet petit a → 详情 → S11 段落 → P2253 → 展开上下文 →
     看 provenance → 回 Seminar XI → 进入 session reading → 保存 passage 到 Obsidian
  ② Terminology → jouissance → 原乐 → 确认 zero attestation 正确展示
"""
import json, os, re, sys, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)
import _explorer_testlib as L
import _ui_testlib as U
from workspace_ui.server import httpserver as H

QA = os.path.join(VAULT, "_workspace", "explorer_qa")


@unittest.skipUnless(U.chrome_available(), "Chrome 不可用")
class ExplorerBrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.path.join("_workspace", "test_vaults", "explorer_browser")
        import shutil
        shutil.rmtree(os.path.join(VAULT, cls.root), ignore_errors=True)
        os.environ["OBSIDIAN_VAULT_PATH"] = cls.root
        cls.srv = H.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.port
        os.makedirs(QA, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        os.environ.pop("OBSIDIAN_VAULT_PATH", None)

    def _view(self, qs, name=None, budget=5000):
        shot = os.path.join(QA, "%s.png" % name) if name else None
        dom, ok = U.chrome_render("%s/?%s" % (self.base, qs), shot, budget_ms=budget,
                                  window="1500,1100")
        if name:
            self.assertTrue(ok, "截图失败 %s" % name)
        self.assertNotIn("Explorer request failed", dom)
        return dom

    def test_00_concept_list_and_search(self):
        dom = self._view("view=concepts", "concept_list")
        self.assertIn("Concepts", dom)
        self.assertIn("concept-list", dom)
        self.assertIn("Next page", dom)          # 分页可见（25/62）
        # ② 搜 objet petit a（深链参数 = 提交后的状态）
        dom2 = self._view("view=concepts&query=objet+petit+a", "concept_list_search")
        self.assertIn("concept.objet-petit-a", dom2)

    def test_01_concept_detail_shows_canonical_and_candidate(self):
        dom = self._view("view=concept&id=concept.objet-petit-a", "concept_detail")
        self.assertIn("Canonical Reference", dom)
        self.assertIn("Relations", dom)
        self.assertIn("No reviewed canonical relation recorded", dom)
        self.assertIn("Candidate", dom)
        self.assertIn("Corpus attestation", dom)
        self.assertIn("Seminar distribution", dom)

    def test_02_passage_via_seminar_then_detail(self):
        dom = self._view("view=passages&seminar=S11&language=fr", "passage_search")
        self.assertIn("passage.S11.unknown.", dom)
        self.assertIn("NOT research retrieval", dom)
        self.assertIn("Dense semantic retrieval unavailable", dom)
        dom2 = self._view("view=passage&id=%s" % L.P_L1, "passage_detail")
        self.assertIn("L’ objet(a) dans le champ du visible", dom2)
        self.assertIn("Trace source", dom2)
        self.assertIn("Witnesses", dom2)
        self.assertIn("No aligned realization available.", dom2)
        self.assertIn("Copy Citation", dom2)

    def test_03_context_expansion_and_session_reading(self):
        dom = self._view("view=passage&id=%s&before=5&after=5" % L.P_L1, "context_expanded")
        self.assertIn("Context (±5/5)", dom)
        self.assertIn("passage.S11.unknown.P2252", dom)
        self.assertIn("Open session", dom)
        dom2 = self._view("view=session&id=%s" % L.S_SESSION, "session_reading")
        self.assertIn("Reading mode", dom2)
        self.assertIn("Save Passage", dom2)
        self.assertIn("Copy Citation", dom2)
        self.assertIn("Open Context", dom2)

    def test_04_l2_trace_incomplete_visible(self):
        dom = self._view("view=passage&id=%s&before=1&after=1" % L.P_L2,
                         "l2_trace_incomplete")
        self.assertIn("SOURCE_TRACE_INCOMPLETE", dom)
        self.assertIn("Source trace incomplete", dom)
        self.assertIn("上游源目录已消失", dom)

    def test_05_seminar_list_and_detail(self):
        dom = self._view("view=seminars", "seminar_list")
        self.assertIn("seminar.S11", dom)
        self.assertIn("精神分析的四个基本概念", dom)
        dom2 = self._view("view=seminar&id=S11", "seminar_detail")
        self.assertIn("Formalism index", dom2)
        self.assertIn("regex over corpus text", dom2)
        self.assertIn("deterministic regex count", dom2)
        self.assertIn("Corpus occurrence", dom2)
        self.assertIn("No person/case entity layer", dom2)

    def test_06_terminology_case_c_and_zero_attestation(self):
        dom = self._view("view=term&term=jouissance", "terminology_mapping")
        for zone in ("Mapping", "Attestation", "Interpretation"):
            self.assertIn(zone, dom)
        self.assertIn("Zero corpus attestation", dom)
        self.assertIn("原乐", dom)
        self.assertIn("not generated", dom)
        dom2 = self._view("view=term&term=%E5%8E%9F%E4%B9%90", "zero_attestation")
        self.assertIn("Zero corpus attestation", dom2)

    def test_07_reel_realite_control(self):
        dom = self._view("view=term&control=reel_realite", "reel_realite")
        self.assertIn("Réel / réalité control", dom)
        self.assertIn("two distinct entities", dom)
        self.assertIn("le réel", dom.lower())
        self.assertIn("réalité", dom)

    def test_08_save_passage_from_explorer(self):
        """§68 第 10 步：Explorer 里保存 passage 到 Obsidian（复用 4D.3）。"""
        res = L.X.obsidian_create("passage", L.P_L1)
        self.assertTrue(res["ok"], res)
        from obsidian_adapter import vault as OV
        self.assertTrue(OV.Vault(self.root).exists(res["note"]))
        self.assertIn("obsidian://open", res.get("obsidian_uri") or "")

    def test_09_research_prefill_is_not_execution(self):
        """§65：Explorer 自己不产生学术结论（页面里不得出现弃权文案）。"""
        dom = self._view("view=passages&seminar=S24&language=fr")
        self.assertNotIn("Current corpus cannot support a reliable answer", dom)

    def test_09b_real_interaction_search_and_clickthrough(self):
        """§68 第 2/4 步：**真的在页面上**填搜索框提交、再点第一条结果。

        深链 `auto=` 钩子只做用户本来会做的动作（填表 + submit / click），
        因此这里验证的是真实交互后的 DOM，而不是换了个 URL 而已。
        """
        dom = self._view("view=concepts&auto=concept_search&query=objet+petit+a",
                         "concept_list_search")
        self.assertIn("concept.objet-petit-a", dom)
        # 点第一条概念 → 详情
        dom2 = self._view("view=concepts&auto=first_result_concept", "concept_first_result")
        self.assertIn("Canonical Reference", dom2)
        # 在段落检索结果里点第一条 → 段落详情
        dom3 = self._view("view=passages&seminar=S11&language=fr&auto=first_passage",
                          "passage_from_click")
        self.assertIn("Trace source", dom3)
        self.assertIn("passage.S11.unknown.", dom3)

    def test_10_screenshots_recorded(self):
        for n in ("concept_list", "concept_detail", "passage_search", "passage_detail",
                  "context_expanded", "l2_trace_incomplete", "seminar_list",
                  "seminar_detail", "session_reading", "terminology_mapping",
                  "zero_attestation", "reel_realite"):
            self.assertTrue(os.path.isfile(os.path.join(QA, n + ".png")), n)
