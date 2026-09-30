#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cdp_testlib.py — 极简 Chrome DevTools Protocol 客户端（stdlib only）。

用途：Phase 5A §18/§54(G) 的**真实键盘**端到端检查 —— 需要真的派发 keydown/keyup，
而不是只断言「元素可聚焦」。本机没有 puppeteer/playwright，所以用 stdlib 实现：

  * `--remote-debugging-port=<free>` 启动 headless Chrome；
  * HTTP `GET /json/list` 拿 page target 的 webSocketDebuggerUrl；
  * 手写 WebSocket 握手 + 帧收发（客户端帧必须 mask）；
  * `Runtime.evaluate` 读 DOM、`Input.dispatchKeyEvent` 真派发按键。

限制（如实声明）：只实现本测试需要的最小 API；不做 CDP 事件订阅。
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.request

CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FLAGS = ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
         "--no-default-browser-check", "--disable-extensions",
         "--disable-background-networking", "--disable-sync",
         "--disable-features=Translate"]


def chrome_available():
    return os.path.isfile(CHROME)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class CDP:
    """一个 page target 的极简 CDP 会话。"""

    def __init__(self, window="1500,1200", timeout=30):
        self.port = _free_port()
        self._prof = "/tmp/cdp-prof-%d-%d" % (os.getpid(), int(time.time() * 1000) % 100000)
        self.proc = subprocess.Popen(
            [CHROME] + FLAGS + ["--remote-debugging-port=%d" % self.port,
                                "--user-data-dir=" + self._prof,
                                "--window-size=" + window, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._id = 0
        self.sock = None
        deadline = time.time() + timeout
        ws_url = None
        while time.time() < deadline and ws_url is None:
            time.sleep(0.4)
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % self.port,
                                            timeout=2) as r:
                    for t in json.loads(r.read().decode("utf-8")):
                        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                            ws_url = t["webSocketDebuggerUrl"]
                            break
            except Exception:                                             # noqa: BLE001
                continue
        if not ws_url:
            self.close()
            raise RuntimeError("CDP: 无法连上 Chrome DevTools（port=%d）" % self.port)
        self._connect(ws_url)

    # ── WebSocket（最小实现）
    def _connect(self, ws_url):
        rest = ws_url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key))
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        assert b"101" in buf.split(b"\r\n")[0], "WS 握手失败：%r" % buf[:120]

    def _send(self, obj):
        data = json.dumps(obj).encode("utf-8")
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv(self):
        def rd(n):
            out = b""
            while len(out) < n:
                chunk = self.sock.recv(n - len(out))
                if not chunk:
                    raise RuntimeError("CDP socket closed")
                out += chunk
            return out
        h = rd(2)
        length = h[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", rd(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", rd(8))[0]
        return json.loads(rd(length).decode("utf-8"))

    def call(self, method, params=None, timeout=25):
        self._id += 1
        mid = self._id
        self._send({"id": mid, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self._recv()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("CDP %s 错误：%s" % (method, msg["error"]))
                return msg.get("result") or {}
        raise TimeoutError("CDP %s 超时" % method)

    # ── 便利方法
    def navigate(self, url):
        self.call("Page.enable")
        # headless 里页面默认**没有焦点**，Tab/Enter 会被丢弃 → 必须显式启用焦点模拟
        #（实测踩过：不加这两行，所有键盘流程都「不生效」，看起来像产品缺陷）
        try:
            self.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        except Exception:                                                 # noqa: BLE001
            pass
        try:
            self.call("Page.bringToFront")
        except Exception:                                                 # noqa: BLE001
            pass
        self.call("Page.navigate", {"url": url})
        ok = self.wait_js("document.body && document.body.dataset.ready === '1'", 40)
        self.wait_js("document.hasFocus()", 10)
        return ok

    def js(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True})
        return (r.get("result") or {}).get("value")

    def wait_js(self, expr, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js(expr):
                    return True
            except Exception:                                             # noqa: BLE001
                pass
            time.sleep(0.3)
        return False

    def key(self, key, code=None, vk=0, text=None):
        common = {"key": key, "code": code or key, "windowsVirtualKeyCode": vk,
                  "nativeVirtualKeyCode": vk}
        self.call("Input.dispatchKeyEvent", dict(common, type="keyDown"))
        if text:
            self.call("Input.dispatchKeyEvent", dict(common, type="char", text=text))
        self.call("Input.dispatchKeyEvent", dict(common, type="keyUp"))

    def ctrl_enter(self):
        common = {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                  "nativeVirtualKeyCode": 13, "modifiers": 2}          # 2 = Ctrl
        self.call("Input.dispatchKeyEvent", dict(common, type="rawKeyDown"))
        self.call("Input.dispatchKeyEvent", dict(common, type="keyUp"))

    def escape(self):
        self.key("Escape", "Escape", 27)

    def tab(self, shift=False):
        m = 8 if shift else 0
        common = {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9,
                  "nativeVirtualKeyCode": 9, "modifiers": m}
        self.call("Input.dispatchKeyEvent", dict(common, type="rawKeyDown"))
        self.call("Input.dispatchKeyEvent", dict(common, type="keyUp"))

    def enter(self):
        self.key("Enter", "Enter", 13)

    def type_text(self, text):
        self.call("Input.insertText", {"text": text})

    @classmethod
    def attach(cls, ws_url, port=None):
        """连接到一个**已存在**的浏览器 target（例如同 profile 的新 tab）。

        不拥有其生命周期：`close()` 不会 kill 浏览器，也不会删 profile。
        用途：验证 localStorage 这类 **per-profile** 状态在新开页面里仍然可见。
        """
        obj = cls.__new__(cls)
        obj.port = port
        obj._prof = None
        obj.proc = None
        obj._id = 0
        obj.sock = None
        obj._connect(ws_url)
        return obj

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:                                                 # noqa: BLE001
            pass
        try:
            if self.proc:
                self.proc.kill()
                self.proc.wait(timeout=10)
        except Exception:                                                 # noqa: BLE001
            pass
        if self._prof:
            subprocess.run(["rm", "-rf", self._prof], check=False)
