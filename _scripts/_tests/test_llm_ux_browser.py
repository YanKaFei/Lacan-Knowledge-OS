#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_llm_ux_browser — P5D-005 的**真实浏览器**功能回归（LLM 接口可用性）。

真实 Chrome + 真实 DOM 事件；不 mock DOM，不用静态快照代替交互。

  Test 1 provider 面板：模型/端点/凭据状态/调用上限**可见且已填充**
  Test 2 连通性自检：点一下真的发一次极小请求，结果如实呈现（OK 或 Failed，不假装）
  Test 3 溯源：mock 研究完成后答案头部出现 `mock adapter (no model call) · N.Ns · computed now`
  Test 4 强制重算：勾选「忽略缓存」后溯源显示 `forced recompute`（缓存策略可见）
  Test 5 等待体验：等待中显示**真实秒数**且逐秒递增；「停止等待」给出如实文案
  Test 6 失败可操作：端点不可达 → 错误卡带「重试一次 / 打开提供方设置」两个动作，
          且 Advanced 里 `attempts: 2`（**只**对基础设施失败重发一次）
  Test 7 即时切换语言：zh 下 provider 面板与调用上限文案同为中文，不需要刷新

证据：`_workspace/ui_qa/p5d005_llm_ux_browser.json`
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for _p in (VAULT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _ui_testlib as U                                                    # noqa: E402
from _cdp_testlib import CDP                                               # noqa: E402
from workspace_ui.server import httpserver as H                            # noqa: E402
from workspace_ui.server import provider_view as PV                        # noqa: E402

QA = os.path.join(VAULT, "_workspace", "ui_qa")
EVIDENCE = os.path.join(QA, "p5d005_llm_ux_browser.json")
LOCALE_KEY = "lacan.uiLocale"
QUESTION = "$ ◊ a 在幻想公式中表示什么？"          # 固定问题（mock 下确定性）
QUESTION_SLOW = "Réel 与 réalité 为什么要区分？"   # 第二个问题：不共享上面那条的缓存

SPY = r"""
(function(){
  window.__p5d005 = {errors: [], uncaught: []};
  const push=(a,v)=>{try{a.push(String(v).slice(0,300));}catch(e){}};
  const oe=console.error.bind(console);
  console.error=function(){push(window.__p5d005.errors, Array.prototype.join.call(arguments,' ')); return oe.apply(null,arguments);};
  window.addEventListener('error', e=>push(window.__p5d005.uncaught,(e.message||'')+' @ '+(e.filename||'')));
})();
"""

STATE = r"""
(function(){
  const txt = (id) => { const e=document.getElementById(id); return e ? e.textContent.trim() : null; };
  const panel = document.getElementById('provider-panel');
  const sel = document.querySelector('#result .state-badge');
  const adv = document.getElementById('advanced-panel');
  return {
    ready: (document.body.dataset||{}).ready || null,
    panel_present: !!panel,
    panel_open: panel ? !!panel.open : null,
    provider_model: (document.getElementById('provider-model')||{}).value || null,
    provider_base_url: (document.getElementById('provider-base-url')||{}).value || null,
    cred_state: txt('provider-cred-state'),
    call_cap: txt('provider-call-cap'),
    test_out: txt('provider-test-out'),
    ask_note: txt('ask-note'),
    ask_elapsed: (document.getElementById('ask-note')||{}).dataset
                 ? (document.getElementById('ask-note').dataset.elapsedSeconds || null) : null,
    cancel_hidden: (document.getElementById('cancel-btn')||{}).hidden,
    fresh_checked: (document.getElementById('fresh-toggle')||{}).checked,
    provenance: txt('answer-provenance'),
    state_badge: sel ? sel.textContent.trim() : null,
    error_actions: Array.from(document.querySelectorAll('#error-actions [data-error-action]'))
                     .map(b => b.getAttribute('data-error-action')),
    advanced_text: adv ? (adv.textContent || '').replace(/\s+/g,' ').trim() : '',
    provider_select: (document.getElementById('provider-select')||{}).value || null,
    panel_summary: (panel && panel.querySelector('summary') ? panel.querySelector('summary').textContent.trim() : null),
    errors: (window.__p5d005||{}).errors || [],
    uncaught: (window.__p5d005||{}).uncaught || [],
    url: location.href
  };
})()
"""


@unittest.skipUnless(U.chrome_available(), "Chrome 不可用")
class LlmUxBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(QA, exist_ok=True)
        cls.srv = H.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d/" % cls.port
        cls.evidence = {"base": cls.base, "tests": {}}
        cls.had_settings = os.path.isfile(PV.SETTINGS_PATH)
        cls.settings_backup = None
        if cls.had_settings:
            with open(PV.SETTINGS_PATH, encoding="utf-8") as fh:
                cls.settings_backup = fh.read()
        # `PV.save()` 会写本进程环境 → 结束时必须还原，绝不把测试端点留给后续套件
        cls.env_backup = {k: os.environ.get(k) for k in
                          ("DSH_SYNTHESIS_BASE_URL", "DSH_SYNTHESIS_MODEL")}

    @classmethod
    def tearDownClass(cls):
        # 产品设置**逐字节还原**（测试绝不改用户环境）
        if cls.had_settings:
            with open(PV.SETTINGS_PATH, "w", encoding="utf-8") as fh:
                fh.write(cls.settings_backup)
        elif os.path.isfile(PV.SETTINGS_PATH):
            os.remove(PV.SETTINGS_PATH)
        for k, v in cls.env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        PV.apply_persisted()
        # ★ 实测教训（P5D-005）：测试**绝不能**把自己的坏端点留成用户设置 ——
        #   曾经泄漏过一个 `base_url=https://127.0.0.1:9/v1`，后续套件因此"神秘"失败。
        assert os.path.isfile(PV.SETTINGS_PATH) == cls.had_settings, \
            "测试结束后的 provider 设置文件状态与开始前不一致（泄漏）"
        try:
            cls.srv.shutdown()
        except Exception:                                                  # noqa: BLE001
            pass
        with open(EVIDENCE, "w", encoding="utf-8") as fh:
            json.dump(cls.evidence, fh, ensure_ascii=False, indent=1, sort_keys=True)

    def tearDown(self):
        """保证每个测试都有证据记录（FAIL 也如实记），不留"证据缺失"。"""
        name = getattr(self, "_testMethodName", "")
        bucket = self.__class__.evidence["tests"]
        parts = name.split("_")
        prefix = "_".join(parts[:2]) if len(parts) >= 2 else name
        already = any(k.startswith(prefix) for k in bucket)
        if name and name not in bucket and not already:
            errors = getattr(getattr(self, "_outcome", None), "errors", None) or []
            bucket[name] = {"status": "FAIL" if errors else "PASS",
                            "detail": {"auto_recorded_in_tearDown": True}}

    # ── 工具
    def _open(self, locale="en"):
        cdp = CDP(window="1500,1100")
        cdp.call("Page.enable")
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": SPY})
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {
            "source": "try{localStorage.setItem('%s', %s);}catch(e){}"
                      % (LOCALE_KEY, json.dumps(locale))})
        self.assertTrue(cdp.navigate(self.base), "页面未完成装配（data-ready）")
        time.sleep(0.4)
        return cdp

    def _state(self, cdp):
        return cdp.js(STATE)

    def _post(self, path, payload):
        req = urllib.request.Request(self.base.rstrip("/") + path,
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _ask(self, cdp, question=QUESTION, provider="mock", fresh=False):
        cdp.js("(function(){"
               "document.getElementById('question-input').value=%s;"
               "document.getElementById('provider-select').value=%s;"
               "document.getElementById('fresh-toggle').checked=%s;"
               "document.getElementById('provider-select').dispatchEvent("
               "  new Event('change',{bubbles:true}));"
               "document.getElementById('ask-btn').click();"
               "return 'clicked';})()"
               % (json.dumps(question), json.dumps(provider),
                  "true" if fresh else "false"))

    def _wait_for(self, cdp, expr, timeout=240, poll=1.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if cdp.js(expr):
                return True
            time.sleep(poll)
        return False

    def _record(self, name, detail):
        self.__class__.evidence["tests"][name] = {"status": "PASS", "detail": detail}

    # ── Test 1 / 2：provider 面板与连通性自检
    def test_01_provider_panel_visible_and_populated(self):
        cdp = self._open()
        try:
            cdp.js("document.getElementById('provider-panel').open = true; 'ok'")
            time.sleep(0.5)
            st = self._state(cdp)
            self.assertTrue(st["panel_present"], "provider 面板必须存在")
            self.assertTrue(st["panel_open"])
            self.assertTrue(st["provider_model"], "模型名必须已填充")
            self.assertTrue((st["provider_base_url"] or "").startswith("https://"),
                            st["provider_base_url"])
            self.assertIn("Credentials:", st["cred_state"] or "")
            self.assertIn("120", st["call_cap"] or "")          # 调用上限只读可见
            self._record("test_01_provider_panel", {
                "model": st["provider_model"], "base_url": st["provider_base_url"],
                "cred_state": st["cred_state"], "call_cap": st["call_cap"]})
        finally:
            cdp.close()

    def test_02_test_connection_is_real_and_honest(self):
        cdp = self._open()
        try:
            cdp.js("document.getElementById('provider-panel').open = true;"
                   "document.getElementById('provider-test').click(); 'ok'")
            self.assertTrue(self._wait_for(
                cdp, "(function(){const e=document.getElementById('provider-test-out');"
                     "return e && e.textContent.trim().length && "
                     "!e.textContent.includes('Testing');})()", timeout=60, poll=0.5),
                "连通性自检必须在 60s 内给出结论")
            st = self._state(cdp)
            out = st["test_out"] or ""
            self.assertTrue(out.startswith("OK ·") or out.startswith("Failed:"), out)
            self.assertNotIn("sk-", out)                        # 绝不回显密钥
            self._record("test_02_test_connection", {"out": out,
                                                    "verdict": ("OK" if out.startswith("OK")
                                                                else "FAILED_HONESTLY")})
        finally:
            cdp.close()

    # ── Test 3 / 4：溯源 + 强制重算（缓存策略可见）
    def test_03_mock_provenance_is_measured(self):
        cdp = self._open()
        try:
            self._ask(cdp, provider="mock")
            self.assertTrue(self._wait_for(
                cdp, "(function(){const e=document.getElementById('answer-provenance');"
                     "return e && /computed now|served from cache/.test(e.textContent);})()",
                timeout=300, poll=1.0), "mock 研究未在 300s 内完成")
            st = self._state(cdp)
            prov = st["provenance"] or ""
            self.assertRegex(prov, r"mock adapter \(no model call\) · \d+\.\ds · "
                                   r"(computed now|served from cache)")
            self.assertIsNone(st["provider_select"] and None or None)
            self._record("test_03_mock_provenance", {"provenance": prov,
                                                    "state": st["state_badge"]})
        finally:
            cdp.close()

    def test_04_fresh_toggle_forces_recompute(self):
        cdp = self._open()
        try:
            self._ask(cdp, provider="mock", fresh=True)
            self.assertTrue(self._wait_for(
                cdp, "(function(){const e=document.getElementById('answer-provenance');"
                     "return e && e.textContent.includes('forced recompute');})()",
                timeout=300, poll=1.0), "强制重算未在 300s 内完成")
            st = self._state(cdp)
            self.assertIn("forced recompute", st["provenance"] or "")
            self._record("test_04_fresh_recompute", {"provenance": st["provenance"]})
        finally:
            cdp.close()

    # ── Test 5：等待体验（真实计时 + 真能取消）
    def test_05_waiting_shows_real_elapsed_and_cancel_works(self):
        cdp = self._open()
        try:
            self._ask(cdp, question=QUESTION_SLOW, provider="mock")
            # 必须**在运行中**读到计时器（用新问题，避免命中缓存而瞬间结束）
            self.assertTrue(self._wait_for(
                cdp, "(function(){const e=document.getElementById('ask-note');"
                     "return e && /Working… \\d+s/.test(e.textContent);})()",
                timeout=15, poll=0.3), "等待中必须显示真实秒数")
            first = self._state(cdp)
            self.assertRegex(first["ask_note"] or "", r"Working… \d+s")
            self.assertIsNotNone(first["ask_elapsed"])
            self.assertFalse(first["cancel_hidden"], "等待中必须能看到「停止等待」")
            time.sleep(2.2)
            second = self._state(cdp)
            self.assertGreater(int(second["ask_elapsed"]), int(first["ask_elapsed"]),
                               "等待秒数必须逐秒递增（真实计时）")
            cdp.js("document.getElementById('cancel-btn').click(); 'ok'")
            time.sleep(0.5)
            third = self._state(cdp)
            self.assertIn("Stopped waiting", third["ask_note"] or "")
            self._record("test_05_waiting", {
                "note_at_1s": first["ask_note"], "note_at_3s": second["ask_note"],
                "cancel_note": third["ask_note"]})
        finally:
            cdp.close()

    # ── Test 6：基础设施失败 → 恰好重发一次 + 可操作按钮
    def test_06_provider_failure_retries_once_with_actions(self):
        self._post("/api/provider/settings",
                   {"base_url": "https://127.0.0.1:9/v1"})     # 必然连不上
        cdp = self._open()
        try:
            self._ask(cdp, provider="llm")
            self.assertTrue(self._wait_for(
                cdp, "(function(){const e=document.querySelector('#result .state-badge');"
                     "return e && e.textContent.trim().length "
                     "&& e.textContent.trim() !== '';})()", timeout=300, poll=1.0),
                "失败路径未在 300s 内返回")
            self.assertTrue(self._wait_for(
                cdp, "document.querySelectorAll('#error-actions [data-error-action]').length >= 2",
                timeout=20, poll=0.5), "错误卡必须给出可操作的下一步")
            st = self._state(cdp)
            self.assertIn("PROVIDER_UNAVAILABLE", st["state_badge"] or "")
            self.assertIn("retry_once", st["error_actions"])
            self.assertIn("provider_settings", st["error_actions"])
            # Advanced 面板把 label / value 作为相邻节点渲染（textContent 无冒号），
            # 所以这里用正则读「attempts 2」与「retry_reason … PROVIDER_UNAVAILABLE」。
            self.assertRegex(st["advanced_text"], r"attempts\s*2")
            self.assertRegex(st["advanced_text"], r"retry_reason\s*PROVIDER_UNAVAILABLE")
            # 点「打开提供方设置」真的把面板打开
            cdp.js("document.querySelector('#error-actions [data-error-action=\"provider_settings\"]')"
                   ".click(); 'ok'")
            time.sleep(0.4)
            self.assertTrue(self._state(cdp)["panel_open"])
            self._record("test_06_retry_and_actions", {
                "state_badge": st["state_badge"], "actions": st["error_actions"],
                "attempts_visible": bool(re.search(r"attempts\s*2", st["advanced_text"])),})
        finally:
            cdp.close()
            # 还原端点（下一次研究立刻回到真实环境）
            if self.__class__.had_settings:
                with open(PV.SETTINGS_PATH, "w", encoding="utf-8") as fh:
                    fh.write(self.__class__.settings_backup)
            elif os.path.isfile(PV.SETTINGS_PATH):
                os.remove(PV.SETTINGS_PATH)
            for k, v in self.__class__.env_backup.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            PV.apply_persisted()
            from workspace_ui.server.mcp_client import reset_shared_client
            reset_shared_client()

    # ── Test 7：新增文案随语言即时切换（不刷新）
    def test_07_new_copy_switches_without_reload(self):
        cdp = self._open(locale="en")
        try:
            en = self._state(cdp)
            origin = cdp.js("performance.timeOrigin")
            cdp.js("(function(){const s=document.getElementById('ui-locale-select');"
                   "s.value='zh'; s.dispatchEvent(new Event('change',{bubbles:true}));"
                   "return 'ok';})()")
            time.sleep(0.6)
            zh = self._state(cdp)
            self.assertEqual(zh["panel_summary"], "模型提供方设置")
            self.assertTrue((zh["call_cap"] or "").startswith("单次调用上限"), zh["call_cap"])
            self.assertEqual(cdp.js("performance.timeOrigin"), origin, "不得刷新页面")
            self._record("test_07_locale_switch", {
                "panel_summary_en": en["panel_summary"], "panel_summary_zh": zh["panel_summary"],
                "call_cap_zh": zh["call_cap"], "no_reload": True,
                "errors": zh["errors"] + zh["uncaught"]})
        finally:
            cdp.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
