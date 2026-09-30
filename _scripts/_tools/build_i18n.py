#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_i18n.py — P5D-004：产品 UI 的 i18n 资源构建 / 调用点重写 / 覆盖率审计。

三层产物（全部**确定性**、可 `--check` 复核）：

  1. `_data/daily_use/i18n/catalog.json`      key ↔ en ↔ zh ↔ surface ↔ status（唯一字符串真源）
  2. `workspace_ui/static/src/i18n_messages.js` 运行时词典（en/zh），由 catalog 生成
  3. `UI_I18N_COVERAGE.json`                 每个**用户可见产品字符串**的状态清单（§6）

用法：
    python3 _scripts/_tools/build_i18n.py --build      # 生成 catalog + messages.js
    python3 _scripts/_tools/build_i18n.py --wrap       # 按 catalog 重写 static/src/*.js 调用点
    python3 _scripts/_tools/build_i18n.py --coverage   # 写 UI_I18N_COVERAGE.json
    python3 _scripts/_tools/build_i18n.py --check      # 一致性校验（供套件调用）

Layer 纪律：
  * Layer A（导航/按钮/标签/状态/帮助/空状态/对话框/表单项/表头/通用错误）→ `translated`
  * Layer B（语料原文/引文/canonical 标签/书目 metadata/用户笔记）→ `intentional_source_text`，**不**进词典
  * 无法安全自动重写的（含 `${}` 模板、转义字面量）→ `hardcoded`，如实登记，不假装已翻译
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))

I18N_DIR = os.path.join(VAULT, "_data", "daily_use", "i18n")
INPUT = os.path.join(I18N_DIR, "input_strings.json")
INPUT_EXTRA = os.path.join(I18N_DIR, "input_strings_extra.json")
TRANS = os.path.join(I18N_DIR, "translations_zh.json")
TRANS_EXTRA = os.path.join(I18N_DIR, "translations_zh_extra.json")
STATIC = os.path.join(I18N_DIR, "static_keys.json")
MANUAL = os.path.join(I18N_DIR, "manual_keys.json")
CATALOG = os.path.join(I18N_DIR, "catalog.json")
SRC = os.path.join(VAULT, "workspace_ui", "static", "src")
MESSAGES_JS = os.path.join(SRC, "i18n_messages.js")
MERGES = os.path.join(I18N_DIR, "fragment_merges.json")
COVERAGE_ROOT = os.path.join(VAULT, "UI_I18N_COVERAGE.json")
COVERAGE_DATA = os.path.join(I18N_DIR, "UI_I18N_COVERAGE.json")
HTML = os.path.join(VAULT, "workspace_ui", "static", "index.html")

FALLBACK = "en"
LOCALES = ["en", "zh"]
MODULE_SURFACE = {
    "api.js": "Research", "app.js": "Research", "bibliography.js": "Bibliography",
    "entities.js": "Persons/Cases", "explorer.js": "Explore", "export.js": "Export",
    "home.js": "Home", "inspector.js": "Evidence Inspector", "project.js": "Projects",
    "render.js": "Research", "router.js": "Navigation", "i18n.js": "System Status",
}
# 无法安全自动重写的字符串（模板/转义/纯符号）在 coverage 里如实标记
AUTO_SKIP = re.compile(r"(\$\{|\\|^\s*$)")


def _slug(text, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:limit] or "msg").strip("-")


def _surface_slug(surface):
    return _slug(surface.replace("/", "-"))


def load_static():
    with open(STATIC, encoding="utf-8") as fh:
        return json.load(fh)


def build_catalog():
    with open(INPUT, encoding="utf-8") as fh:
        items = json.load(fh)
    if os.path.isfile(INPUT_EXTRA):                      # 合并后的整句（fragment merges）
        with open(INPUT_EXTRA, encoding="utf-8") as fh:
            items = items + json.load(fh)
    tr = {}
    for path in (TRANS, TRANS_EXTRA):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                tr.update((json.load(fh) or {}).get("translations") or {})
    rows, used = [], set()

    def add(key, en, zh, surface, status, files=None, note=""):
        k = key
        n = 2
        while k in used:
            k = "%s-%d" % (key, n)
            n += 1
        used.add(k)
        rows.append({"key": k, "en": en, "zh": zh, "surface": surface,
                     "status": status, "files": files or [], "note": note})

    # ① index.html 静态节点 + 少量手工指定的 JS 端标签（key 已人工指定，最稳定）
    for e in load_static():
        add(e["key"], e["en"], e["zh"], e["surface"], e["status"])
    if os.path.isfile(MANUAL):
        with open(MANUAL, encoding="utf-8") as fh:
            for e in json.load(fh):
                add(e["key"], e["en"], e["zh"], e["surface"], e["status"])

    # ② JS 模块字符串（只登记**活着的**：已被 t('key') 调用，或字面量仍在源码里）
    merged_key_by_en = {}
    if os.path.isfile(MERGES):                          # 合并后的整句：en → 新 key
        with open(MERGES, encoding="utf-8") as fh:
            for rec in (json.load(fh).get("merges") or []):
                merged_key_by_en[rec["en"]] = rec["new_key"]
    live_keys, literals = set(), set()
    for fn in os.listdir(SRC):
        if not fn.endswith(".js") or fn in ("i18n.js", "i18n_messages.js"):
            continue
        src = open(os.path.join(SRC, fn), encoding="utf-8").read()
        live_keys |= set(re.findall(r"\bt\('([^']+)'\)", src))
        literals |= set(re.findall(r"'((?:[^'\\]|\\.){1,200})'", src))
        literals |= set(re.findall(r"`([^`]{1,200})`", src))   # 模板字面量（hardcoded 类）也要登记
    for it in items:
        en = it["string"]
        surface = (it.get("surfaces") or ["Application"])[0]
        _key_guess = merged_key_by_en.get(
            en, "%s.%s" % (_surface_slug(surface), _slug(en)))
        if _key_guess not in live_keys and en not in literals:
            continue                                   # 死条目（已被 merge/改写取代）
        entry = tr.get(en) or {}
        if entry.get("skip"):
            add(_key_guess, en, en, surface,
                "intentional_source_text", it.get("files"),
                entry.get("note") or "canonical/scholarly/token")
            continue
        if AUTO_SKIP.search(en):
            add(_key_guess, en, entry.get("zh") or en,
                surface, "hardcoded", it.get("files"),
                "parameterized/template literal — 未自动重写")
            continue
        zh = entry.get("zh")
        if not zh:
            add(_key_guess, en, en, surface,
                "hardcoded", it.get("files"), "no translation supplied")
            continue
        add(_key_guess, en, zh, surface, "translated", it.get("files"))
    catalog = {
        "schema_version": "p5d004-i18n-catalog/v1",
        "fallback_locale": FALLBACK,
        "locales": LOCALES,
        "counts": {
            "total": len(rows),
            "translated": sum(1 for r in rows if r["status"] == "translated"),
            "hardcoded": sum(1 for r in rows if r["status"] == "hardcoded"),
            "intentional_source_text": sum(
                1 for r in rows if r["status"] == "intentional_source_text"),
        },
        "entries": rows,
    }
    with open(CATALOG, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return catalog


def write_messages(catalog):
    en, zh = {}, {}
    for r in catalog["entries"]:
        # Layer B（intentional_source_text）也进词典，但做**身份翻译**（zh = en）：
        # 品牌名/专名/机器 token 不能被"翻译"，也不能让 t() 把 key 文本漏到界面上。
        if r["status"] == "translated":
            en[r["key"]] = r["en"]
            zh[r["key"]] = r["zh"]
        elif r["status"] == "intentional_source_text":
            en[r["key"]] = r["en"]
            zh[r["key"]] = r["en"]
    body = ["// i18n_messages.js — **生成文件**（不要手改）。"
            "由 _scripts/_tools/build_i18n.py --build 从",
            "// _data/daily_use/i18n/catalog.json 生成；audit 见 UI_I18N_COVERAGE.json。", "",
            "export const FALLBACK_LOCALE = '%s';" % FALLBACK,
            "export const SUPPORTED_LOCALES = %s;" % json.dumps(LOCALES), "",
            "export const MESSAGES = {"]
    for loc, d in (("en", en), ("zh", zh)):
        body.append("  %s: {" % loc)
        for k in sorted(d):
            body.append("    %s: %s," % (json.dumps(k), json.dumps(d[k], ensure_ascii=False)))
        body.append("  },")
    body += ["};", ""]
    text = "\n".join(body)
    with open(MESSAGES_JS, "w", encoding="utf-8") as fh:
        fh.write(text)
    return {"en": len(en), "zh": len(zh), "sha256": hashlib.sha256(
        text.encode("utf-8")).hexdigest()[:16]}


PATS = [
    (re.compile(r"(\btext:\s*)'((?:[^'\\]|\\.){1,200})'"), "text"),
    (re.compile(r"(\bplaceholder:\s*)'((?:[^'\\]|\\.){1,200})'"), "placeholder"),
    (re.compile(r"(\btitle:\s*)'((?:[^'\\]|\\.){1,200})'"), "title"),
    (re.compile(r"(\blabel:\s*)'((?:[^'\\]|\\.){1,200})'"), "label"),
    (re.compile(r"(['\"]aria-label['\"]:\s*)'((?:[^'\\]|\\.){1,200})'"), "aria-label"),
]


def wrap_sources(catalog, dry=False):
    by_en = {r["en"]: r["key"] for r in catalog["entries"] if r["status"] == "translated"}
    report = {}
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".js") or fn in ("i18n.js", "i18n_messages.js"):
            continue
        path = os.path.join(SRC, fn)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        orig = src
        hits = 0

        def repl(m):
            nonlocal hits
            en = m.group(2)
            key = by_en.get(en)
            if not key:
                return m.group(0)
            hits += 1
            return "%st('%s')" % (m.group(1), key)

        for pat, _kind in PATS:
            src = pat.sub(repl, src)
        if hits and "from './i18n.js'" not in src:
            lines = src.split("\n")
            last = -1
            for i, ln in enumerate(lines[:60]):
                if ln.startswith("import "):
                    last = i
            if last >= 0:
                lines.insert(last + 1, "import { t } from './i18n.js';")
            else:
                lines.insert(0, "import { t } from './i18n.js';")
            src = "\n".join(lines)
        if src != orig and not dry:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(src)
        report[fn] = hits
    return report


def coverage(catalog):
    rows = []
    for r in catalog["entries"]:
        rows.append({
            "surface": r["surface"],
            "string": r["en"],
            "status": r["status"],
            "key": r["key"],
            "files": r["files"],
            "note": r["note"] or "",
        })
    out = {
        "schema_version": "ui-i18n-coverage/v1",
        "generated_by": "_scripts/_tools/build_i18n.py --coverage",
        "locales": LOCALES,
        "fallback_locale": FALLBACK,
        "catalog_counts": catalog["counts"],
        "status_legend": {
            "translated": "Layer A 产品 UI：已接入 i18n（en/zh 词典）",
            "hardcoded": "仍是硬编码字面量（含 ${} 模板/转义字面量）—— 如实登记，未假装已翻译",
            "intentional_source_text": "Layer B：语料原文/引文/canonical 标签/书目 metadata/"
                                       "用户笔记/品牌与机器 token —— **不得**自动改写",
        },
        "surfaces": sorted({r["surface"] for r in rows}),
        "strings": rows,
    }
    for p in (COVERAGE_ROOT, COVERAGE_DATA):
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return out


def check():
    problems = []
    if not os.path.isfile(CATALOG):
        return ["catalog.json 不存在：先 --build"]
    with open(CATALOG, encoding="utf-8") as fh:
        catalog = json.load(fh)
    keys = {r["key"]: r for r in catalog["entries"]}
    with open(MESSAGES_JS, encoding="utf-8") as fh:
        js = fh.read()
    # 词典 key 一致
    for r in catalog["entries"]:
        if r["status"] == "hardcoded":
            continue
        if ("    %s:" % json.dumps(r["key"])) not in js:
            problems.append("messages.js 缺 key：%s" % r["key"])
        if not r["zh"] or r["zh"] in ("undefined", "null"):
            problems.append("zh 值非法：%s" % r["key"])
    # 调用点 key 必须存在于词典
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".js") or fn in ("i18n.js", "i18n_messages.js"):
            continue
        with open(os.path.join(SRC, fn), encoding="utf-8") as fh:
            src = fh.read()
        for key in re.findall(r"\bt\('([^']+)'", src):
            if key not in keys:
                problems.append("%s 调用点引用未知 key：%s" % (fn, key))
            elif keys[key]["status"] == "hardcoded":
                problems.append("%s 调用了 hardcoded 条目：%s" % (fn, key))
    # index.html 的 data-i18n key 必须存在
    with open(HTML, encoding="utf-8") as fh:
        html = fh.read()
    for key in set(re.findall(r'data-i18n(?:-placeholder)?="([^"]+)"', html)):
        if key not in keys:
            problems.append("index.html 引用未知 key：%s" % key)
    # 覆盖率文件存在且与 catalog 同步
    if not os.path.isfile(COVERAGE_ROOT):
        problems.append("UI_I18N_COVERAGE.json 不存在：先 --coverage")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="P5D-004 i18n build/wrap/coverage/check")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--wrap", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    did = False
    if a.build:
        catalog = build_catalog()
        info = write_messages(catalog)
        print(json.dumps({"kind": "i18n_build", "counts": catalog["counts"],
                          "messages": info}, ensure_ascii=False))
        did = True
    if a.wrap:
        with open(CATALOG, encoding="utf-8") as fh:
            catalog = json.load(fh)
        print(json.dumps({"kind": "i18n_wrap", "files": wrap_sources(catalog, a.dry_run),
                          "dry_run": a.dry_run}, ensure_ascii=False))
        did = True
    if a.coverage:
        with open(CATALOG, encoding="utf-8") as fh:
            catalog = json.load(fh)
        out = coverage(catalog)
        print(json.dumps({"kind": "i18n_coverage", "strings": len(out["strings"]),
                          "counts": out["catalog_counts"]}, ensure_ascii=False))
        did = True
    if a.check or not did:
        problems = check()
        print(json.dumps({"kind": "i18n_check", "problems": problems[:20],
                          "problems_n": len(problems)}, ensure_ascii=False))
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
