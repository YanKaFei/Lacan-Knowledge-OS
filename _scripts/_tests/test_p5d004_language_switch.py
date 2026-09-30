#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_p5d004_language_switch — P5D-004 语言切换的**真实浏览器**功能回归（§10 Test 1–8）。

真实 Chrome + 真实 DOM 事件；不 mock DOM、不用静态 DOM 快照代替交互。

  Test 1  EN → ZH：点击切换后**不刷新页面**，Research→研究 等 ≥6 个独立标签同时变化
  Test 2  ZH → EN：反向同样成立
  Test 3  persistence：选择语言 → reload → 仍保持（中英各一次）
  Test 4  navigation persistence：Home→Research→Explore→Projects→Bibliography 全程不丢 locale
  Test 5  deep route：直接打开深链（bibliography 详情）时 locale 初始化正确
  Test 6  <html lang>：zh → zh-CN；en → en
  Test 7  no JS error：EN→ZH→EN 两次切换不产生 uncaught error / console error
  Test 8  scholarly content integrity：切换 UI 语言前后，固定 passage 的
          passage_id / 原文 / citation / provenance **逐字节不变**

证据：`_workspace/ui_qa/p5d004_i18n_evidence.json`（Gate F19 从这份结构化证据取判定）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for _p in (VAULT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _ui_testlib as U                                                    # noqa: E402
from _cdp_testlib import CDP                                               # noqa: E402
from workspace_ui.server import httpserver as H                             # noqa: E402

QA = os.path.join(VAULT, "_workspace", "ui_qa")
EVIDENCE = os.path.join(QA, "p5d004_i18n_evidence.json")
LOCALE_KEY = "lacan.uiLocale"
PASSAGE = "passage.S11.unknown.P2253"        # 固定 passage（S11, L1, Staferla）
NAV_IDS = ["nav-home", "nav-research", "nav-explore", "nav-projects",
           "nav-bibliography", "nav-obsidian", "nav-history", "nav-saved",
           "nav-exports"]

SPY = r"""
(function(){
  window.__p5d004 = {errors: [], uncaught: []};
  const push=(a,v)=>{try{a.push(String(v).slice(0,300));}catch(e){}};
  const oe=console.error.bind(console);
  console.error=function(){push(window.__p5d004.errors, Array.prototype.join.call(arguments,' ')); return oe.apply(null,arguments);};
  window.addEventListener('error', e=>push(window.__p5d004.uncaught, (e.message||'')+' @ '+(e.filename||'')));
  window.addEventListener('unhandledrejection', e=>push(window.__p5d004.uncaught, String(e.reason).slice(0,200)));
})();
"""

STATE = r"""
(function(){
  const txt = (id) => { const e=document.getElementById(id); return e ? e.textContent.trim() : null; };
  const nav = {}; %s.forEach(id => { nav[id] = txt(id); });
  const loc = document.getElementById('ui-locale-select');
  return {
    locale_select: loc ? loc.value : null,
    locale_options: loc ? Array.from(loc.options).map(o=>o.value) : [],
    html_lang: document.documentElement.getAttribute('lang'),
    storage: (function(){ try { return localStorage.getItem('lacan.uiLocale'); } catch(e){ return null; } })(),
    nav: nav,
    ask_title: (document.querySelector('.ask-title')||{}).textContent || null,
    ask_btn: txt('ask-btn'),
    research_lang_note: txt('language-status'),
    marker_alive: window.__p5d004_marker || null,
    time_origin: window.__p5d004_origin || null,
    errors: (window.__p5d004||{}).errors || [],
    uncaught: (window.__p5d004||{}).uncaught || [],
    url: location.href
  };
})()
""" % json.dumps(NAV_IDS)

MARKER = ("window.__p5d004_marker='alive'; window.__p5d004_origin=performance.timeOrigin;"
          "'ok'")

EN_NAV = {"nav-home": "Home", "nav-research": "Research", "nav-explore": "Explore",
          "nav-projects": "Projects", "nav-bibliography": "Bibliography",
          "nav-history": "History", "nav-saved": "Saved", "nav-exports": "Exports"}
ZH_NAV = {"nav-home": "首页", "nav-research": "研究", "nav-explore": "探索",
          "nav-projects": "项目", "nav-bibliography": "文献",
          "nav-history": "历史", "nav-saved": "已保存", "nav-exports": "导出"}


def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


@unittest.skipUnless(U.chrome_available(), "Chrome 不可用")
class LanguageSwitchI18N(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(QA, exist_ok=True)
        cls.srv = H.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d/" % cls.port
        cls.evidence = {"base": cls.base, "tests": {}}

    @classmethod
    def tearDownClass(cls):
        try:
            cls.srv.shutdown()
        except Exception:                                                  # noqa: BLE001
            pass
        with open(EVIDENCE, "w", encoding="utf-8") as fh:
            json.dump(cls.evidence, fh, ensure_ascii=False, indent=1, sort_keys=True)

    def tearDown(self):
        """保证**每个**测试都有证据记录（即使断言失败/异常提前退出）。

        P5D-004 第二次验收实测：一次 Chrome/CDP 抖动让某个测试在 `_record` 之前就异常退出，
        证据里因此**缺**了那一条，Gate 只能看到"缺失"而不是原因。这里在 tearDown 兜底补记，
        使 `p5d004_i18n_evidence.json` 永远包含全部测试项（FAIL 也如实记录）。
        """
        name = getattr(self, "_testMethodName", "")
        bucket = self.__class__.evidence["tests"]
        parts = name.split("_")
        prefix = "_".join(parts[:2]) if len(parts) >= 2 else name   # test_01 / test_02 …
        already = any(k.startswith(prefix) for k in bucket)
        if name and name not in bucket and not already:
            errors = getattr(getattr(self, "_outcome", None), "errors", None) or []
            bucket[name] = {"status": "FAIL" if errors else "PASS",
                            "detail": {"auto_recorded_in_tearDown": True}}

    # ── 工具
    def _open(self, url=None, locale=None):
        """新开一个真实浏览器会话。

        `locale`：在页面脚本运行**之前**把初始 locale 写进 localStorage（同源新文档脚本），
        用来把「初始语言」钉死在测试期望上 —— 否则会受本机浏览器语言（zh-CN）影响。
        """
        cdp = CDP(window="1500,1100")
        cdp.call("Page.enable")
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": SPY})
        if locale:
            cdp.call("Page.addScriptToEvaluateOnNewDocument", {
                "source": "try{localStorage.setItem('%s', %s);}catch(e){}"
                          % (LOCALE_KEY, json.dumps(locale))})
        self.assertTrue(cdp.navigate(url or self.base), "页面未完成装配（data-ready）")
        time.sleep(0.5)
        cdp.js(MARKER)
        return cdp

    def _state(self, cdp):
        return cdp.js(STATE)

    def _click_locale(self, cdp, value):
        """真实鼠标点击控件（可达性）→ 选中该语言（用户在原生下拉里选中时派发的 change）。"""
        box = cdp.js("(function(){const e=document.getElementById('ui-locale-select');"
                     "if(!e) return null; const r=e.getBoundingClientRect();"
                     "return {x:r.left+r.width/2, y:r.top+r.height/2};})()")
        if box:
            for t in ("mousePressed", "mouseReleased"):
                cdp.call("Input.dispatchMouseEvent",
                         {"type": t, "x": box["x"], "y": box["y"], "button": "left",
                          "clickCount": 1})
        cdp.js("(function(){const s=document.getElementById('ui-locale-select');"
               "s.value=%s; s.dispatchEvent(new Event('change',{bubbles:true}));})()"
               % json.dumps(value))
        time.sleep(0.6)
        return box

    def _record(self, name, ok, detail):
        self.__class__.evidence["tests"][name] = {"status": "PASS" if ok else "FAIL",
                                                  "detail": detail}
        return ok

    # ── Test 1 / 2：EN→ZH、ZH→EN，不刷新页面
    def test_01_en_to_zh_without_reload(self):
        cdp = self._open(locale="en")
        try:
            before = self._state(cdp)
            self.assertEqual(before["locale_select"], "en")
            self.assertEqual(before["html_lang"], "en")
            for k, v in EN_NAV.items():
                self.assertEqual(before["nav"][k], v, k)
            box = self._click_locale(cdp, "zh")
            after = self._state(cdp)
            changed = [k for k in EN_NAV if before["nav"][k] != after["nav"][k]]
            ok_labels = all(after["nav"][k] == ZH_NAV[k] for k in ZH_NAV)
            no_reload = (after["marker_alive"] == "alive"
                         and after["time_origin"] == before["time_origin"])
            self.assertEqual(after["locale_select"], "zh")
            self.assertEqual(after["storage"], "zh")
            self.assertTrue(ok_labels, json.dumps(after["nav"], ensure_ascii=False))
            self.assertGreaterEqual(len(changed), 6, changed)
            self.assertTrue(no_reload, "切换语言不得刷新页面")
            self._record("test_01_en_to_zh", True,
                         {"click_target": box, "changed_labels": changed,
                          "nav_after": after["nav"], "no_reload": no_reload})
        finally:
            cdp.close()

    def test_02_zh_to_en_without_reload(self):
        cdp = self._open(locale="zh")
        try:
            self._click_locale(cdp, "zh")
            zh = self._state(cdp)
            self.assertEqual(zh["nav"]["nav-research"], "研究")
            self._click_locale(cdp, "en")
            en = self._state(cdp)
            self.assertEqual(en["nav"]["nav-research"], "Research")
            for k, v in EN_NAV.items():
                self.assertEqual(en["nav"][k], v, k)
            self.assertEqual(en["html_lang"], "en")
            self.assertEqual(en["storage"], "en")
            ok = en["marker_alive"] == "alive"
            self.assertTrue(ok, "反向切换同样不得刷新页面")
            self._record("test_02_zh_to_en", True, {"nav_after": en["nav"],
                                                    "no_reload": ok})
        finally:
            cdp.close()

    # ── Test 3：持久化（reload 保持）
    def test_03_persistence_across_reload(self):
        cdp = self._open()
        try:
            res = {}
            for loc, label in (("zh", "研究"), ("en", "Research")):
                self._click_locale(cdp, loc)
                self.assertTrue(cdp.navigate(self.base), "reload 失败")
                time.sleep(0.5)
                st = self._state(cdp)
                res[loc] = {"locale_select": st["locale_select"], "storage": st["storage"],
                            "nav_research": st["nav"]["nav-research"],
                            "html_lang": st["html_lang"]}
                self.assertEqual(st["locale_select"], loc, "reload 后必须保持 %s" % loc)
                self.assertEqual(st["storage"], loc)
                self.assertEqual(st["nav"]["nav-research"], label)
            self._record("test_03_persistence", True, res)
        finally:
            cdp.close()

    # ── Test 4：路由导航不丢 locale
    def test_04_navigation_preserves_locale(self):
        cdp = self._open()
        try:
            self._click_locale(cdp, "zh")
            steps = []
            for nav_id in ("nav-home", "nav-research", "nav-explore", "nav-projects",
                           "nav-bibliography"):
                cdp.js("document.getElementById(%s).click()" % json.dumps(nav_id))
                time.sleep(0.8)
                st = self._state(cdp)
                steps.append({"clicked": nav_id, "url": st["url"],
                              "locale_select": st["locale_select"],
                              "html_lang": st["html_lang"],
                              "nav_research": st["nav"]["nav-research"],
                              "storage": st["storage"]})
                self.assertEqual(st["locale_select"], "zh", nav_id)
                self.assertEqual(st["html_lang"], "zh-CN", nav_id)
                self.assertEqual(st["nav"]["nav-research"], "研究", nav_id)
                self.assertEqual(st["storage"], "zh", nav_id)
            self._record("test_04_navigation_persistence", True, {"steps": steps})
        finally:
            cdp.close()

    # ── Test 5：深链初始化
    def test_05_deep_route_initializes_locale(self):
        cdp = self._open()
        try:
            cdp.js("localStorage.setItem('lacan.uiLocale','zh')")
            url = self.base + "?view=bibliography&id=bib.witness.staferla"
            self.assertTrue(cdp.navigate(url), "深链未完成装配")
            time.sleep(1.0)
            st = self._state(cdp)
            head = cdp.js("(function(){const h=document.querySelector('#bibliography-explorer h2');"
                          "return h? h.textContent.trim():null;})()")
            self.assertEqual(st["locale_select"], "zh")
            self.assertEqual(st["html_lang"], "zh-CN")
            self.assertEqual(st["nav"]["nav-bibliography"], "文献")
            self.assertEqual(head, "文献", "深链下的视图标题必须是中文：%r" % head)
            self._record("test_05_deep_route", True,
                         {"url": url, "locale_select": st["locale_select"],
                          "html_lang": st["html_lang"], "view_heading": head})
        finally:
            cdp.close()

    # ── Test 6：<html lang> 同步
    def test_06_html_lang_sync(self):
        cdp = self._open()
        try:
            seen = {}
            for loc, lang in (("zh", "zh-CN"), ("en", "en")):
                self._click_locale(cdp, loc)
                st = self._state(cdp)
                seen[loc] = st["html_lang"]
                self.assertEqual(st["html_lang"], lang)
            self._record("test_06_html_lang", True, seen)
        finally:
            cdp.close()

    # ── Test 7：两次切换无 JS 错误
    def test_07_no_js_errors_on_switching(self):
        cdp = self._open(locale="en")
        try:
            cdp.js("window.__p5d004.errors=[]; window.__p5d004.uncaught=[]")
            for loc in ("zh", "en", "zh", "en"):
                self._click_locale(cdp, loc)
            st = self._state(cdp)
            self.assertEqual(st["errors"], [])
            self.assertEqual(st["uncaught"], [])
            self._record("test_07_no_js_errors", True,
                         {"errors": st["errors"], "uncaught": st["uncaught"],
                          "switches": 4})
        finally:
            cdp.close()

    # ── Test 8：学术内容完整性（UI 语言切换不得改语料）
    def test_08_scholarly_content_integrity(self):
        cdp = self._open()
        fetch_js = """
        (async () => {
          const a = await fetch('/api/explore/passage?id=%s&before=1&after=1').then(r=>r.json());
          const b = await fetch('/api/export/citation?id=%s&style=internal-full').then(r=>r.json());
          return {passage: a.passage, citation: a.citation, trace: a.trace,
                  witness: a.witnesses, formatter: b};
        })()
        """ % (PASSAGE, PASSAGE)
        try:
            cdp.js("localStorage.setItem('lacan.uiLocale','en')")
            cdp.navigate(self.base)
            time.sleep(0.4)
            before = cdp.js(fetch_js)
            dom_before = cdp.js("(function(){const e=document.querySelector('.pr-text')||"
                                "document.querySelector('.pi-snippet');"
                                "return e? e.textContent : null;})()")
            self._click_locale(cdp, "zh")
            after = cdp.js(fetch_js)
            dom_after = cdp.js("(function(){const e=document.querySelector('.pr-text')||"
                               "document.querySelector('.pi-snippet');"
                               "return e? e.textContent : null;})()")
            p0, p1 = before.get("passage") or {}, after.get("passage") or {}
            c0, c1 = before.get("citation") or {}, after.get("citation") or {}
            same = {
                "passage_id": p0.get("passage_id") == p1.get("passage_id"),
                "source_text": p0.get("text") == p1.get("text"),
                "citation_full": c0.get("full") == c1.get("full"),
                "citation_short": c0.get("short") == c1.get("short"),
                "provenance": json.dumps(p0.get("provenance_status")) ==
                              json.dumps(p1.get("provenance_status")),
                "witness": json.dumps(before.get("witness")) == json.dumps(after.get("witness")),
                "trace": json.dumps(before.get("trace")) == json.dumps(after.get("trace")),
                "formatter": json.dumps(before.get("formatter")) ==
                             json.dumps(after.get("formatter")),
            }
            self.assertTrue(all(same.values()), json.dumps(same))
            self.assertNotEqual(p0.get("text"), None)
            self.assertEqual(dom_before, dom_after)     # 渲染出的语料文本也不得变
            self._record("test_08_scholarly_integrity", True,
                         {"passage_id": p0.get("passage_id"),
                          "text_sha256": _sha(p0.get("text")),
                          "citation_sha256": _sha(c0.get("full")),
                          "checks": same, "dom_text_identical": dom_before == dom_after})
        finally:
            cdp.close()

    # ── 附带：Research language 控件（上一轮修复）仍然工作，未被本轮破坏
    def test_09_research_language_control_still_works(self):
        cdp = self._open()
        try:
            note_before = cdp.js("(document.getElementById('language-status')||{}).textContent")
            cdp.js("(function(){const s=document.getElementById('language-select');"
                   "s.value='fr'; s.dispatchEvent(new Event('change',{bubbles:true}));})()")
            time.sleep(0.4)
            st = cdp.js("(function(){return {note:(document.getElementById('language-status')||{}).textContent,"
                        "stored:localStorage.getItem('lacan.researchLanguage'),"
                        "value:(document.getElementById('language-select')||{}).value};})()")
            self.assertEqual(st["value"], "fr")
            self.assertEqual(st["stored"], "fr")
            self.assertNotEqual(st["note"], note_before)
            self._record("test_09_research_language_control", True, st)
        finally:
            cdp.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
