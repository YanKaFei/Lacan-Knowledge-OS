#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_ui_testlib.py — Phase 4D.2 测试共享工具（下划线开头 → 不被 unittest 收集）

* `answer(...)` / `panel(...)`：带跨进程缓存的 ViewModel 取数（让 9 个套件共享同一次核心计算）
* `serve()`：在**本进程**内起一个 HTTP 服务（线程 + 临时端口），供 HTTP/浏览器烟测使用
* `chrome_dom(url)` / `chrome_shot(url, path)`：真实 Chrome 渲染（无 build、无 Playwright）
* `js_sources()` / `core_snapshot()`
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

from scholarly_api import policy as POL                       # noqa: E402
from workspace_ui.server import api as UIA                    # noqa: E402
from workspace_ui.server import config as UIC                 # noqa: E402
from workspace_ui.server import viewmodel as VM               # noqa: E402

CACHE = os.path.join(tempfile.gettempdir(), "lacan_ui_test_cache")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
QUESTION_RELATION = "Seminar XI 中 gaze 与 objet a 是什么关系？"
QUESTION_ABSTAIN = "拉康如何看待 fMRI 等当代神经科学影像研究？"
QUESTION_METADATA = "拉康 1953 年 11 月 18 日那场报告的确切时间、地点与在场者是谁？"
QUESTION_L2 = "Réel 与 réalité 为什么要区分？"
PASSAGE_L1 = "passage.S11.unknown.P2253"
PASSAGE_L2 = "passage.S05.unknown.L05.P0056"


def _key(kind, payload):
    return "%s-%s" % (kind, hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16])


def _cached(kind, payload, fn):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, _key(kind, payload) + ".json")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    val = fn()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(val, f, ensure_ascii=False)
    return val


def mcp_envelope(tool, args):
    """直接走 MCP（用于同一性比对：view model 必须与 MCP 载荷一致）。"""
    from workspace_ui.server.mcp_client import shared_client
    return shared_client().call_tool(tool, args)


def answer(question, mode="scholarly", provider="mock", language=None,
           include_raw=True):
    payload = {"q": question, "mode": mode, "provider": provider, "language": language}
    out = _cached("answer", payload, lambda: UIA.research(
        question, mode=mode, provider=provider, language=language,
        save_history=False))
    return out["view"]


def mcp_payload(question, mode="scholarly", provider="mock", language=None):
    args = {"question": question, "provider": provider}
    if mode and mode != "auto":
        args["mode"] = mode
    if language:
        args["language"] = language
    return _cached("env", args, lambda: mcp_envelope("lacan.research", args))


def panel(passage_id, before=3, after=3):
    return _cached("panel", {"p": passage_id, "b": before, "a": after},
                   lambda: UIA.passage_panel(passage_id, before, after))


def js_sources():
    d = os.path.join(VAULT, "workspace_ui", "static", "src")
    return {fn: open(os.path.join(d, fn), encoding="utf-8").read()
            for fn in sorted(os.listdir(d)) if fn.endswith(".js")}


def static_dir():
    return os.path.join(VAULT, "workspace_ui", "static")


def core_snapshot():
    return POL.snapshot_immutable()


def core_diff(before, after):
    return POL.diff_snapshot(before, after)


# ── 进程内 HTTP 服务（供 HTTP 与浏览器烟测）
class LiveServer:
    def __init__(self):
        from workspace_ui.server.httpserver import make_server
        self.srv = make_server("127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path, timeout=120):
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")

    def get_json(self, path, timeout=300):
        st, body = self.get(path, timeout=timeout)
        return st, json.loads(body)

    def post_json(self, path, payload, timeout=600):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def close(self):
        try:
            self.srv.shutdown()
            self.srv.server_close()
        except Exception:                                     # noqa: BLE001
            pass


CHROME_FLAGS = ["--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-background-networking",
                "--disable-sync", "--disable-features=Translate"]


def _pin_locale(url):
    """P5D-004：把渲染用的 UI locale 钉成 en。

    产品支持 `?uiLocale=` 深链覆盖（i18n.js 的确定性优先级）。既有浏览器套件断言的是
    **英文文案**，而本机 Chrome 的语言是 zh-CN（默认会按浏览器语言显示中文）——
    因此测试基座显式钉住 locale，而不是去改产品的默认行为。
    需要中文渲染的套件请自行传 `uiLocale=zh`。
    """
    if "uiLocale=" in url:
        return url
    return url + ("&" if "?" in url else "?") + "uiLocale=en"


def chrome_render(url, shot_path=None, budget_ms=4000, window="1400,1000",
                  settle_s=1.0, hard_timeout=150, retries=2):
    """真实 Chrome 渲染 → (dom, shot_ok)。

    ⚠️ 实测：本机 Chrome 写完 `--dump-dom` / `--screenshot` 后**不会自行退出**
    （会一直挂着），所以这里用「轮询产物 → 稳定后 kill」的看门狗模式，
    而不是等进程结束。

    实测还见过**偶发卡死**（一次 97s 未稳定 → DOM 里没有保存结果 → 2 个断言假红；
    紧接着单独重跑 25.9s 全绿）。因此：只有当看门狗是**超时**退出（而非产物稳定）
    时才重试 `retries` 次 —— 这是对「Chrome 卡住」的重试，不是对断言失败的重试。
    """
    url = _pin_locale(url)
    dom, shot_ok, settled = _chrome_render_once(url, shot_path, budget_ms, window,
                                                settle_s, hard_timeout)
    # P5D-004：高负载实测 —— 看门狗偶尔在「产物稳定」之前退出，DOM 只剩骨架
    #   （长度异常短）。这与断言失败无关，属于**渲染**未完成；对"过短 DOM"同样重试
    #   （仍受 retries 限制，且**不放松任何断言**）。
    def _too_short(d):
        return not d or len(d) < 2000
    while (not settled or _too_short(dom)) and retries > 0:
        retries -= 1
        dom, shot_ok, settled = _chrome_render_once(url, shot_path, budget_ms, window,
                                                    settle_s, hard_timeout)
    return dom, shot_ok


def _chrome_render_once(url, shot_path, budget_ms, window, settle_s, hard_timeout):
    """单次渲染 → (dom, shot_ok, settled)。`settled=False` 表示看门狗超时。"""
    with tempfile.TemporaryDirectory() as prof:
        dom_file = os.path.join(prof, "dom.html")
        cmd = [CHROME] + CHROME_FLAGS + [
            "--user-data-dir=" + os.path.join(prof, "profile"),
            "--window-size=" + window,
            "--virtual-time-budget=%d" % budget_ms]
        if shot_path:
            os.makedirs(os.path.dirname(shot_path), exist_ok=True)
            if os.path.exists(shot_path):
                os.remove(shot_path)
            cmd.append("--screenshot=" + shot_path)
        cmd.append("--dump-dom")
        cmd.append(url)
        with open(dom_file, "wb") as out:
            proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.DEVNULL)
            t0 = time.time()
            stable_since = None
            last_size = -1
            settled = False
            while time.time() - t0 < hard_timeout:
                time.sleep(0.4)
                size = os.path.getsize(dom_file)
                shot_ready = (not shot_path) or (
                    os.path.isfile(shot_path) and os.path.getsize(shot_path) > 5000)
                if shot_ready and size > 200 and size == last_size:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= settle_s:
                        settled = True
                        break
                else:
                    stable_since = None
                last_size = size
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:                                 # noqa: BLE001
                pass
        with open(dom_file, encoding="utf-8", errors="replace") as f:
            dom = f.read()
    shot_ok = True if not shot_path else (
        os.path.isfile(shot_path) and os.path.getsize(shot_path) > 5000)
    return dom, shot_ok, settled


def chrome_dom(url, budget_ms=4000, window="1400,1000", extra=None):
    return chrome_render(url, None, budget_ms, window)[0]


def chrome_shot(url, out_path, budget_ms=4000, window="1600,1200", extra=None):
    return chrome_render(url, out_path, budget_ms, window)[1]


def chrome_available():
    return os.path.isfile(CHROME)


def wait_for(pred, timeout=30, interval=0.2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(interval)
    return False
