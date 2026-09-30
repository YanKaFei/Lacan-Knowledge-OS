#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase5a_keyboard_flows.py — Phase 5A §18/§54(G)/§52 H8：键盘关键流程

做法与**诚实边界**（务必先读）：

* 本机没有 puppeteer / playwright；`_cdp_testlib` 是手写的极简 CDP 客户端，
  其 `Input.dispatchKeyEvent`（真·硬件级按键）在本环境**实测不稳定**
  （WebSocket 帧层被浏览器异常解析 → 事件风暴），**因此不作为验收依据**。
* 验收采用两条**可靠**证据：
  1. **行为**：在真实 Chrome 页面里派发 `KeyboardEvent`（`isTrusted=false`），
     检验产品**声明的键盘契约**是否真的响应：
     `Ctrl/Cmd+Enter` 提交研究、citation 控件 Enter 打开 Inspector、
     `Esc` 关闭并交还焦点、Explorer 检索框 Enter 提交表单。
     （产品监听器不检查 `isTrusted`，这是对"按键 → 行为"映射的直接检验。）
  2. **可达性**：DOM 结构层面验证原生可聚焦控件、无正/负 tabindex 打乱顺序、
     焦点可见样式存在、交互控件都有可访问名。
* **明确不声称**：真实硬件按键的端到端遍历（trusted events）未在本环境自动化。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (os.path.join(VAULT, "_scripts", "_tools"),
          os.path.join(VAULT, "_scripts", "_tools", "lacan_mcp"), VAULT, HERE):
    sys.path.insert(0, p)

from _cdp_testlib import CDP, chrome_available, CHROME   # noqa: E402

QUESTION = "Seminar XI 中 gaze 与 objet a 是什么关系？"

DISPATCH_FN = """(function(sel, key, mods){
  const el = document.querySelector(sel);
  if (!el) return 'no-element';
  el.focus();
  const ev = new KeyboardEvent('keydown', Object.assign({key: key, bubbles: true,
    cancelable: true}, mods || {}));
  return el.dispatchEvent(ev) ? 'dispatched' : 'handled';
})"""


def dispatch(sel, key, mods="{}"):
    """→ 在真实页面里派发按键事件的 JS 表达式。"""
    return "(%s)(%s, %s, %s)" % (DISPATCH_FN, repr(sel), repr(key), mods)


@unittest.skipUnless(chrome_available(), "本机未安装 Google Chrome")
class TestKeyboardFlows(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from workspace_ui.server import api as A
        from workspace_ui.server import httpserver as H
        cls.srv = H.make_server("127.0.0.1", 0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        try:                      # 预热 mock 研究（离线、确定性），避免键盘流程等 15s
            A.research(QUESTION, mode="scholarly", provider="mock", language="any",
                       save_history=True)
        except Exception:                                                 # noqa: BLE001
            pass
        cls.records = [{
            "criterion": "ENV", "contract": "真实 Chrome 实例（CDP）",
            "observed": {"chrome": CHROME, "base_url": cls.base}, "ok": True}]
        cls.cdp = CDP(window="1500,1200")
        cls.ready = cls.cdp.navigate(cls.base + "/?view=research")

    @classmethod
    def tearDownClass(cls):
        # §18/§54(G)：把**可核**的键盘证据落盘（不是把测试日志当证据，
        # 而是记录「声明的契约 → 实际观察」这一对，并显式写明边界）。
        try:
            out_dir = os.path.join(VAULT, "_data", "phase5a")
            os.makedirs(out_dir, exist_ok=True)
            payload = {
                "schema_version": "phase5a-keyboard-evidence/v1",
                "kind": "keyboard_flows",
                "phase": "Phase 5A §18 / §54(G) / §52 H8",
                "method": "real Chrome (CDP) + synthetic KeyboardEvent + DOM structure",
                "records": cls.records,
                "honest_limits": [
                    "本机无 puppeteer/playwright；手写 CDP 的 Input.dispatchKeyEvent"
                    "（trusted 硬件按键）在本环境实测不稳定，**未**作为验收依据",
                    "因此「按键 → 行为」用派发的 KeyboardEvent 检验（产品监听器不检查"
                    " isTrusted），「键盘可达性」用 DOM 结构检验",
                    "citation 控件是原生 <button type=button>，Enter/Space 激活由浏览器保证，"
                    "这里验证的是它的原生性与激活后果，不伪造 trusted 按键",
                    "未做屏幕阅读器实测、未做完整 Tab 遍历的逐焦点断言",
                ],
            }
            with open(os.path.join(out_dir, "keyboard_flows.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
        except Exception:                                                 # noqa: BLE001
            pass
        try:
            cls.cdp.close()
        finally:
            cls.srv.shutdown()

    def ev(self, criterion, contract, observed, ok):
        """记录一条「契约 → 观察」证据。ok=False 也会写盘（证据不美化）。

        **纪律**：调用方必须**先 ev() 再 assert**。若先 assert，失败时这条证据
        根本不会落盘 —— 实测踩过：K1/K2 失败而工件里没有对应记录。
        """
        type(self).records.append({
            "criterion": criterion, "contract": contract,
            "observed": observed, "ok": bool(ok)})

    def check(self, ok, msg, criterion, contract, observed):
        """先记录、后断言（ok 为 False 时证据仍在）。"""
        self.ev(criterion, contract, observed, ok)
        self.assertTrue(ok, msg)

    # ── 行为：声明的键盘契约
    def test_00_page_is_wired(self):
        wired = self.cdp.js("!!document.getElementById('question-input')")
        self.check(bool(self.ready) and bool(wired),
                   "页面未装配（data-ready != 1 或缺少 #question-input）",
                   "K0", "页面装配完成（data-ready=1）且研究输入框存在",
                   {"ready": bool(self.ready), "question_input": bool(wired)})

    def test_01_ctrl_enter_submits_research(self):
        self.cdp.js("document.getElementById('question-input').value = %r" % QUESTION)
        r = self.cdp.js(dispatch("#question-input", "Enter", "{ctrlKey: true}"))
        self.assertIn(r, ("dispatched", "handled"))
        # 断言必须落在**学术答案卡**上，不能只看到 state-badge ——
        # renderError() 也画 .state-badge 与 h2.answer-q，只看它们会把
        # 「研究被冻结门停用」误判成「提交成功」（实测踩过）。
        # 判别式：答案卡带 data-state，错误卡**没有**。
        rq = repr(QUESTION)
        ok = self.cdp.wait_js(
            "(() => { const el = document.getElementById('result');"
            " if (!el || el.hidden) return false;"
            " const card = el.querySelector('article.card[data-state]');"
            " if (!card) return false;"
            " const q = card.querySelector('h2.answer-q');"
            " return !!q && q.textContent.indexOf(%s) >= 0; })()" % rq, 90)
        state = self.cdp.js(
            "(() => { const c = document.querySelector('#result article.card[data-state]');"
            " return c ? c.getAttribute('data-state') : null; })()")
        err = self.cdp.js(
            "(() => { const el = document.getElementById('result');"
            " const c = el && el.querySelector('article.card:not([data-state])');"
            " return c ? (c.textContent || '').slice(0, 160) : null; })()")
        self.check(ok, "Ctrl+Enter 未产出学术答案卡（data-state 缺失）；错误卡=%r" % err,
                   "K1", "Ctrl/Cmd+Enter 在 #question-input 上提交研究并产出学术答案卡"
                         "（data-state 存在且问题回显一致）",
                   {"dispatch_result": r, "answer_card_rendered": bool(ok),
                    "answer_state": state, "error_card": err})

    def test_02_citation_enter_opens_inspector_and_escape_closes(self):
        """citation 控件必须是**原生 <button>**：Enter/Space 激活由浏览器保证
        （不可信事件不会触发默认动作，因此这里不伪造"按 Enter 变 click"，
        而是分别验证：① 控件是原生 button；② 激活行为确实打开 Inspector；
        ③ Esc 的 document 级契约真的关闭并交还焦点）。"""
        obs = {"cite_tag": None, "inspector_opened": False,
               "inspector_close_btn": False, "esc_closed": False,
               "focus_returned_to": None}
        try:
            tag = self.cdp.js(
                "(() => { const c = document.querySelector('#result .cite');"
                " return c ? c.tagName + ':' + (c.getAttribute('type') || '') : null; })()")
            obs["cite_tag"] = tag
            self.assertEqual(
                tag, "BUTTON:button",
                "citation 控件不是原生 <button type=button>（键盘激活无保证）：%s" % tag)
            self.cdp.js("document.querySelector('#result .cite').focus()")
            self.cdp.js("document.querySelector('#result .cite').click()")
            obs["inspector_opened"] = bool(self.cdp.wait_js(
                "(() => { const i = document.getElementById('inspector');"
                " return i && !i.hidden; })()", 30))
            self.assertTrue(obs["inspector_opened"],
                            "激活 citation 未打开 Evidence Inspector")
            obs["inspector_close_btn"] = bool(
                self.cdp.js("!!document.getElementById('inspector-close')"))
            self.assertTrue(obs["inspector_close_btn"])
            # Esc 是 document 级监听（app.js wire()）
            self.cdp.js("document.dispatchEvent(new KeyboardEvent('keydown',"
                        " {key: 'Escape', bubbles: true}))")
            obs["esc_closed"] = bool(self.cdp.wait_js(
                "(() => { const i = document.getElementById('inspector');"
                " return i && i.hidden; })()", 15))
            self.assertTrue(obs["esc_closed"], "Esc 未关闭 Inspector")
            obs["focus_returned_to"] = self.cdp.js(
                "document.activeElement && document.activeElement.id")
            self.assertEqual(obs["focus_returned_to"], "question-input",
                             "关闭后焦点未交还研究输入框")
        finally:
            self.ev("K2", "citation 是原生 <button type=button>；激活打开 Inspector；"
                          "Esc 关闭并把焦点交还 #question-input", obs,
                    obs["cite_tag"] == "BUTTON:button" and obs["inspector_opened"]
                    and obs["esc_closed"]
                    and obs["focus_returned_to"] == "question-input")

    def test_03_explorer_search_submits_on_enter(self):
        self.cdp.navigate(self.base + "/?view=concepts")
        self.assertTrue(self.cdp.wait_js("!!document.getElementById('concept-search')"))
        self.cdp.js("document.getElementById('concept-search').value = 'objet petit a'")
        # input 在 <form> 内：Enter 触发 form submit（产品用 onsubmit）
        self.cdp.js("""(() => { const i = document.getElementById('concept-search');
          i.focus();
          const f = i.form;
          f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
          return 'ok'; })()""")
        rendered = bool(self.cdp.wait_js(
            "(() => { const el = document.getElementById('explorer-concepts');"
            " return el && /concept\\.objet-petit-a/.test(el.innerHTML); })()", 40))
        self.check(rendered, "检索表单提交后未渲染概念结果",
                   "K3", "Explorer 检索表单提交（Enter 语义）后渲染概念结果",
                   {"form_submit": "dispatched", "results_rendered": rendered})

    # ── 可达性：结构层（不依赖 trusted 按键）
    def test_04_focusability_and_tab_order(self):
        self.cdp.navigate(self.base + "/?view=research")
        self.assertTrue(self.cdp.wait_js("!!document.getElementById('question-input')"))
        bad_tabindex = self.cdp.js(
            "Array.from(document.querySelectorAll('[tabindex]'))"
            ".filter(e => Number(e.getAttribute('tabindex')) > 0).length")
        focusables = self.cdp.js(
            "Array.from(document.querySelectorAll("
            "'a[href],button,input,select,textarea,[tabindex=\"0\"]'))"
            ".filter(e => !e.disabled && e.offsetParent !== null).length")
        skip_link = self.cdp.js(
            "!!document.querySelector('a.skip-link[href=\"#question-input\"]')")
        editable = self.cdp.js(
            "(() => { const el = document.getElementById('question-input');"
            " return el.tagName === 'TEXTAREA' && !el.disabled && !el.readOnly; })()")
        # 焦点可见样式必须存在（CSS 层）
        has_focus_css = self.cdp.js(
            "Array.from(document.styleSheets).some(s => { try {"
            " return Array.from(s.cssRules).some(r => r.selectorText &&"
            " /focus-visible|:focus/.test(r.selectorText)); } catch (e) { return false; } })")
        obs4 = {"positive_tabindex": int(bad_tabindex), "focusables": int(focusables),
                "skip_link": bool(skip_link), "editable_textarea": bool(editable),
                "focus_css": bool(has_focus_css)}
        self.check(obs4["positive_tabindex"] == 0 and obs4["focusables"] > 8
                   and obs4["skip_link"] and obs4["editable_textarea"]
                   and obs4["focus_css"],
                   "键盘可达性结构检查未通过：%r" % obs4,
                   "K4", "无正 tabindex；可聚焦控件充足；skip-link 存在；"
                         "研究框可编辑；存在 :focus/:focus-visible 样式", obs4)

    def test_05_interactive_controls_have_accessible_names(self):
        missing = self.cdp.js("""(() => {
          const out = [];
          document.querySelectorAll('button,input,select,textarea').forEach(e => {
            if (e.disabled || e.hidden) return;
            const t = (e.textContent || '').trim();
            const name = e.getAttribute('aria-label') || e.getAttribute('aria-labelledby')
              || e.getAttribute('title') || t;
            let labelled = name;
            if (!labelled && e.id) {
              const l = document.querySelector('label[for="' + e.id + '"]');
              if (l) labelled = l.textContent;
            }
            if (!labelled && e.placeholder) labelled = e.placeholder;
            if (!labelled) out.push(e.tagName + '#' + (e.id || e.className));
          });
          return JSON.stringify(out); })()""")
        miss = json.loads(missing)
        self.check(miss == [], "存在无可访问名的交互控件：%s" % missing,
                   "K5", "所有启用且可见的 button/input/select/textarea 都有可访问名",
                   {"missing_names": miss})


if __name__ == "__main__":
    unittest.main(verbosity=2)
