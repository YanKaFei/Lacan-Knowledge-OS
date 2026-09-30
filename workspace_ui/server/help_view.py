#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace_ui.server.help_view — 产品 Help Center 的**内容编译与路由契约**（产品层）。

设计要点（为什么这样做）：
  * **单一真源**：`_data/daily_use/help/help_content.json`（作者只写 en/zh 与结构）。
    本模块把它编译成"结构 + i18n key"，**不把正文一起发给浏览器** ——
    文案一律由既有 `i18n.js` 的词典渲染（§17：不建第二套 locale 系统）。
  * **key 由位置确定性推导**（`help.<slug>.<n>`），所以内容和词典永远不会漂移：
    `_scripts/_tools/build_help.py` 用同一个编译函数生成词典条目。
  * **UI 名称不写死**：正文里写 `{{ui:research.submit}}` 这类**产品 key 引用**，
    渲染时替换成产品当前真实标签（当前 locale）。这样 Help **不可能**说出一个
    实际不存在的按钮名 —— 引用不存在的 key 会被 build/link 检查当场抓出来。
  * **原文不翻译**：`kind == "source"` 的块只有一份文本（问题原文/引文），
    它**不**进词典、不随 UI 语言变化（§17 Layer B）。

编译输出（`/api/help/content` 的返回）只含结构与 key，不含正文。
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
CONTENT_PATH = os.path.join(VAULT, "_data", "daily_use", "help", "help_content.json")

SCHEMA = "help-content/v1"
UI_REF = re.compile(r"\{\{ui:([A-Za-z0-9._\-]+)\}\}")
TEXT_KINDS = ("h2", "h3", "p", "callout")
LIST_KINDS = ("ul", "ol")
DL_KINDS = ("dl",)

# ── 模块 → contextual help 目标（§9：**不得**全部指向 /help 首页）
MODULES = {
    "home": {"help": "/help", "href": "/", "title_key": "nav.home"},
    "research": {"help": "/help/research", "href": "/research", "title_key": "nav.research"},
    "explore": {"help": "/help/explore", "href": "/explore", "title_key": "nav.explore"},
    "concepts": {"help": "/help/explore", "href": "/explore", "title_key": "nav.explore"},
    "passages": {"help": "/help/explore", "href": "/explore", "title_key": "nav.explore"},
    "terminology": {"help": "/help/explore", "href": "/explore", "title_key": "nav.explore"},
    "seminars": {"help": "/help/explore", "href": "/explore", "title_key": "nav.explore"},
    "entities": {"help": "/help/persons-cases", "href": "/persons",
                 "title_key": "nav.persons"},
    "projects": {"help": "/help/projects", "href": "/projects", "title_key": "nav.projects"},
    "bibliography": {"help": "/help/bibliography", "href": "/bibliography",
                     "title_key": "nav.bibliography"},
    "zotero": {"help": "/help/zotero", "href": "/zotero",
               "title_key": "bibliography.import-zotero-csl-json"},
    "obsidian": {"help": "/help/obsidian", "href": "/help/obsidian",
                 "title_key": "nav.obsidian"},
    "saved": {"help": "/help", "href": "/", "title_key": "nav.saved"},
    "exports": {"help": "/help", "href": "/", "title_key": "nav.exports"},
    "history": {"help": "/help", "href": "/", "title_key": "nav.history"},
    "help": {"help": "/help", "href": "/", "title_key": "help.center"},
}

# ── 产品真实路由（服务端会把这些路径交给 SPA；link checker 用它判 404）
SPA_ROUTES = (
    "/", "/home", "/research", "/explore", "/projects", "/bibliography",
    "/persons", "/cases", "/zotero", "/help",
)


def spa_route_ok(path):
    """路径是否属于产品 SPA 路由（含 /help/<slug>）。"""
    p = (path or "/").split("?")[0].rstrip("/") or "/"
    if p in SPA_ROUTES:
        return True
    return p.startswith("/help/")


def _key(slug, *parts):
    return "help." + ".".join([slug] + [str(p) for p in parts])


def load_raw():
    with open(CONTENT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def compile_doc():
    """→ 结构化的 Help 文档（含 key / anchor / href；**不含正文**）。"""
    raw = load_raw()
    pages, slugs = [], []
    for page in raw.get("pages") or []:
        slug = page["slug"]
        slugs.append(slug)
        blocks, anchors = [], []
        for i, b in enumerate(page.get("blocks") or [], start=1):
            kind = b.get("kind")
            out = {"kind": kind, "key": _key(slug, i)}
            if kind == "h2":
                anchor = b.get("anchor") or ("s%d" % i)
                out["anchor"] = anchor
                anchors.append(anchor)
            elif kind == "link":
                out["href"] = b.get("href")
                out["external"] = bool(b.get("external"))
            elif kind == "source":
                out["text"] = b.get("text")          # 原文：不进词典、不翻译
                out.pop("key", None)
            elif kind in LIST_KINDS:
                out["item_keys"] = [_key(slug, i, j)
                                    for j in range(1, len(b.get("en") or []) + 1)]
            elif kind in DL_KINDS:
                out["items"] = [{"term_key": _key(slug, i, j, "term"),
                                 "desc_key": _key(slug, i, j, "desc")}
                                for j in range(1, len(b.get("items") or []) + 1)]
            elif kind != "p" and kind != "h3" and kind != "callout":
                raise ValueError("unknown help block kind: %r (page %s)" % (kind, slug))
            if kind == "h3":
                out["anchor"] = b.get("anchor") or ("s%d" % i)
                anchors.append(out["anchor"])
            blocks.append(out)
        pages.append({
            "slug": slug,
            "title_key": _key(slug, "title"),
            "summary_key": _key(slug, "summary"),
            "section": page.get("section"),
            "module": page.get("module"),
            "module_href": (MODULES.get(page.get("module")) or {}).get("href"),
            "module_help": (MODULES.get(page.get("module")) or {}).get("help"),
            "anchors": anchors,
            "blocks": blocks,
        })
    sections = []
    for sec in raw.get("sections") or []:
        sections.append({"id": sec["id"], "title_key": "help.section." + sec["id"],
                         "pages": [p for p in (sec.get("pages") or []) if p in slugs]})
    return {"schema_version": SCHEMA,
            "index": {"title_key": "help.center",
                      "intro_key": "help.index.intro",
                      "topics": list(slugs)},
            "sections": sections, "pages": pages, "slugs": slugs,
            "modules": MODULES}


def content():
    """HTTP 返回体（结构 + key；正文由前端 i18n 词典渲染）。"""
    return compile_doc()


def i18n_entries():
    """→ [(key, en, zh, status)]，供词典构建与覆盖率审计使用。

    * 普通块 → `translated`
    * `source` 块 → **不进词典**（原文不翻译）
    """
    raw = load_raw()
    out = []

    def add(key, en, zh, status="translated"):
        if en is None:
            return
        out.append((key, en, zh if zh is not None else en, status))

    add("help.center", raw["index"]["en"], raw["index"]["zh"])
    add("help.index.intro", raw["index"]["intro_en"], raw["index"]["intro_zh"])
    for sec in raw.get("sections") or []:
        add("help.section." + sec["id"], sec["en"], sec["zh"])
    for page in raw.get("pages") or []:
        slug = page["slug"]
        add(_key(slug, "title"), page["title"]["en"], page["title"]["zh"])
        add(_key(slug, "summary"), page["summary"]["en"], page["summary"]["zh"])
        for i, b in enumerate(page.get("blocks") or [], start=1):
            kind = b.get("kind")
            if kind == "source":
                continue
            if kind in LIST_KINDS:
                for j, (en, zh) in enumerate(zip(b.get("en") or [], b.get("zh") or []),
                                              start=1):
                    add(_key(slug, i, j), en, zh)
            elif kind in DL_KINDS:
                for j, item in enumerate(b.get("items") or [], start=1):
                    add(_key(slug, i, j, "term"), item["term_en"], item["term_zh"])
                    add(_key(slug, i, j, "desc"), item["desc_en"], item["desc_zh"])
            else:
                add(_key(slug, i), b.get("en"), b.get("zh"))
    return out


def ui_refs():
    """文档里被引用的**产品 UI key**（`{{ui:...}}`），供"不得虚构按钮"检查。"""
    raw = load_raw()
    text = json.dumps(raw, ensure_ascii=False)
    return sorted(set(UI_REF.findall(text)))


def hrefs():
    """文档里出现的内部链接（含 anchor 片段）。"""
    raw = load_raw()
    out = []
    for page in raw.get("pages") or []:
        for i, b in enumerate(page.get("blocks") or [], start=1):
            if b.get("kind") == "link" and b.get("href"):
                if not str(b["href"]).startswith(("http://", "https://", "obsidian://")):
                    out.append({"page": page["slug"], "block": i, "href": b["href"]})
    return out


def parse_href(href):
    """→ (path, anchor)；外部链接返回 (None, None)。"""
    if str(href).startswith(("http://", "https://", "obsidian://", "mailto:")):
        return None, None
    u = urlparse(href)
    return (u.path or ""), (u.fragment or None)
