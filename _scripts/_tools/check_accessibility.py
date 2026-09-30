#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_accessibility.py — Phase 4D.7 §72 最终无障碍检查（只读、确定性）。

检查范围（**静态 + 真实渲染**两份证据）：

A. 静态（`workspace_ui/static/index.html`）
   1. `<html lang>` 存在
   2. `viewport` meta 存在
   3. skip-link 存在且指向真实存在的元素
   4. 每个 `input/select/textarea` 有可访问名（`aria-label`、关联 `<label for>`、
      或包在 `<label>` 里）
   5. 每个 `button` 有可访问名（文本内容或 `aria-label`）
   6. 没有内联 `on*=` 事件处理器

B. 渲染（真实 Chrome，`_ui_testlib.chrome_render`；`--static-only` 可跳过）
   1. `body[data-ready="1"]`（JS 已装配）
   2. 渲染后的 DOM 里，`input/select/textarea/button` 同样都有可访问名
   3. 标题层级不跳级（h1→h2→h3 …）
   4. 状态**不只靠颜色**：状态栏有文字（例：`MCP Connected`）
   5. 有原生可聚焦元素（button / a[href] / select / input）
   6. `img` 一律有 `alt`（没有 img 也算通过）

**诚实的边界（写进输出）**：
* 不做像素级对比度测量（WCAG 1.4.3）—— 本机没有对比度度量运行时；
* 不做屏幕阅读器 / 键盘遍历的自动化；
* 本工具**不**进入冻结 Gate，也不改任何判据；它只产出验收报告 §72 的证据。
"""
from __future__ import annotations

import json
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)

INDEX = os.path.join(VAULT, "workspace_ui", "static", "index.html")
FOCUSABLE = ("button", "a", "select", "input", "textarea")
LABELLED = ("input", "select", "textarea")

LIMITS = [
    "不做像素级对比度测量（WCAG 1.4.3）：本机无对比度度量运行时，未做该测量",
    "不做屏幕阅读器 / 键盘遍历自动化；只验证原生可聚焦元素与可访问名",
    "本工具不进入冻结 Gate，只作为 §72 的证据",
]


class Nodes(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.tags = []              # (tag, attrs dict, text)
        self.headings = []
        self._text_of = {}
        self._stack = []
        self.label_for = set()
        self.void = {"input", "img", "meta", "link", "br", "hr", "source"}

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        self.tags.append([tag, a, ""])
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append(int(tag[1]))
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag not in self.void:
            self._stack.append(len(self.tags) - 1)

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self.tags[self._stack[i]][0] == tag:
                self._stack.pop(i)
                break

    def handle_data(self, data):
        # 文本按**子树**归集（元素的可访问名是它的 text content，
        # 不能只算最内层标签 —— 否则 `<button><span>文字</span></button>`
        # 会被误判成「没有可访问名」，实测踩过这个假阳性）。
        for idx in self._stack:
            self.tags[idx][2] += data


def parse(html_text):
    p = Nodes()
    p.feed(html_text)
    return p


def _acc_name(tag, attrs, text, label_for):
    if attrs.get("aria-label") or attrs.get("aria-labelledby") or attrs.get("title"):
        return True
    if tag in LABELLED and attrs.get("id") and attrs["id"] in label_for:
        return True
    if (text or "").strip():
        return True
    if attrs.get("value") and attrs.get("type") in ("submit", "button"):
        return True
    # 复选框/单选：有 aria-label 已覆盖；否则需要 label 包裹（已由 text 覆盖）
    return False


def audit(html_text, where):
    p = parse(html_text)
    out = {"where": where, "findings": [], "notes": []}

    def bad(code, detail):
        out["findings"].append({"code": code, "detail": detail})

    if not re.search(r"<html[^>]*\slang=", html_text, re.I):
        bad("HTML_LANG_MISSING", "缺少 <html lang>")

    for tag, attrs, text in p.tags:
        if any(k.startswith("on") for k in attrs):
            bad("INLINE_HANDLER", "<%s %s>" % (tag, ",".join(k for k in attrs
                                                             if k.startswith("on"))))
        if tag in LABELLED or tag == "button":
            if not _acc_name(tag, attrs, text, p.label_for):
                bad("NO_ACCESSIBLE_NAME", "<%s %s>"
                    % (tag, attrs.get("id") or attrs.get("class") or attrs.get("type") or ""))
        if tag == "img" and "alt" not in attrs:
            bad("IMG_ALT_MISSING", attrs.get("src", "")[:60])
    return out


def static_audit():
    text = open(INDEX, encoding="utf-8").read()
    out = audit(text, "static:index.html")
    if not re.search(r'<meta[^>]*name="viewport"', text, re.I):
        out["findings"].append({"code": "VIEWPORT_MISSING", "detail": "缺 viewport meta"})
    m = re.search(r'<a[^>]*class="skip-link"[^>]*href="#([\w-]+)"', text)
    if not m:
        out["findings"].append({"code": "SKIP_LINK_MISSING", "detail": "缺 skip-link"})
    elif 'id="%s"' % m.group(1) not in text:
        out["findings"].append({"code": "SKIP_LINK_DANGLING",
                                "detail": "skip-link 指向 #%s，但该元素不存在" % m.group(1)})
    else:
        out["notes"].append("skip-link → #%s（目标存在）" % m.group(1))
    return out


def rendered_audit():
    import urllib.parse
    sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tests"))
    import _ui_testlib as U                     # noqa: PLC0415
    from workspace_ui.server import api as A
    from workspace_ui.server import httpserver as H

    srv = H.make_server("127.0.0.1", 0)
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pages = []
    try:
        q = "Seminar XI 中 gaze 与 objet a 是什么关系？"
        try:
            A.research(q, mode="scholarly", provider="mock", language="any")
        except Exception:                                                 # noqa: BLE001
            pass
        # Phase 5A §15：覆盖 Research / Explorer（列表+详情）/ Terminology /
        #   Projects / Export / Evidence Inspector（passage 详情）
        urls = [("research_shell", "%s/?view=research" % base),
                ("research_answer", "%s/?q=%s&mode=scholarly&provider=mock&autorun=1"
                 % (base, urllib.parse.quote(q))),
                ("explorer_concepts", "%s/?view=concepts&query=objet+petit+a" % base),
                ("explorer_concept_detail",
                 "%s/?view=concept&id=concept.objet-petit-a" % base),
                ("terminology", "%s/?view=term&term=jouissance" % base),
                ("seminars", "%s/?view=seminars" % base),
                ("projects", "%s/?view=projects" % base),
                ("exports", "%s/?view=exports" % base),
                ("passage_inspector",
                 "%s/?view=passage&id=passage.S11.unknown.P2253" % base)]
        for name, url in urls:
            dom = U.chrome_render(url, None, budget_ms=12000, window="1500,1600")[0]
            a = audit(dom, "rendered:%s" % name)
            if 'data-ready="1"' not in dom:
                a["findings"].append({"code": "NOT_READY",
                                      "detail": "body 没有 data-ready=1（JS 未装配）"})
            hs = a.get("_headings", []) if isinstance(a, dict) else []
            p = parse(dom)
            hs = p.headings
            for prev, cur in zip(hs, hs[1:]):
                if cur - prev > 1:
                    a["findings"].append({"code": "HEADING_SKIP",
                                          "detail": "h%d → h%d" % (prev, cur)})
            if not (p.headings and p.headings[0] == 1):
                a["findings"].append({"code": "NO_H1", "detail": "渲染页没有 h1"})
            if "MCP Connected" not in dom and "MCP" not in dom:
                a["findings"].append({"code": "STATUS_TEXT_MISSING",
                                      "detail": "状态栏没有文字（只能靠颜色传达状态？）"})
            focusable = sum(1 for t, at, _x in p.tags
                            if t in FOCUSABLE and not at.get("disabled"))
            a["notes"].append("可聚焦原语 %d 个" % focusable)
            if focusable == 0:
                a["findings"].append({"code": "NO_FOCUSABLE",
                                      "detail": "没有任何可聚焦元素"})
            pages.append(a)
    finally:
        try:
            srv.shutdown()
        except Exception:                                                 # noqa: BLE001
            pass
    return pages


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    static_only = "--static-only" in argv
    json_path = None
    if "--json" in argv:
        json_path = argv[argv.index("--json") + 1]

    report = {"kind": "accessibility_audit",
              "phase": "4D.7 §72 + Phase 5A §16",
              "static": static_audit(),
              "rendered": [] if static_only else rendered_audit(),
              "limits": LIMITS}
    findings = list(report["static"]["findings"])
    for page in report["rendered"]:
        findings += page["findings"]
    report["findings_total"] = len(findings)
    report["verdict"] = "PASS" if not findings else "FAIL"

    print("无障碍检查（§72）：%s" % report["verdict"])
    print("  静态：%d 项发现" % len(report["static"]["findings"]))
    for f in report["static"]["findings"]:
        print("    - %s %s" % (f["code"], f["detail"]))
    for page in report["rendered"]:
        print("  渲染 %-20s %d 项发现  %s"
              % (page["where"].split(":")[-1], len(page["findings"]),
                 "; ".join(page["notes"])[:90]))
        for f in page["findings"]:
            print("    - %s %s" % (f["code"], f["detail"]))
    for lim in LIMITS:
        print("  限制：%s" % lim)
    if json_path:
        os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
        print("→ %s" % os.path.relpath(json_path))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
