#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_p5d005_help — P5D-005 Help/Onboarding 的**结构·可核性**回归（不含浏览器）。

覆盖：
  * 13 个 Help 页 + `/help` 的编译正确性（标题/摘要/锚点/链接/en+zh 齐备）；
  * 真实 HTTP：产品路由与每一页都 200，未知 `/api/*` 仍然 404（不吞 API 错误）；
  * `HELP_LINK_REPORT.json`：broken_internal_links=0 / broken_anchors=0；
  * `HELP_CLAIM_VERIFICATION.json`：documentation_fiction=0（element 类由浏览器套件核验）；
  * §9 contextual help：6 个必需模块各自指向**模块专属**帮助页（不得全指 /help）；
  * §10 教学型空状态：Projects / Explore 零结果 / History / Bibliography 都在源码里用 teachEmpty；
  * §11 禁止虚构：正文引用的 `{{ui:KEY}}` 必须存在于 i18n 词典；说的引用样式必须真实存在；
  * §17 i18n：Help 走既有词典（en/zh 都有），`source` 块**不翻译**；
  * 状态词典收录 §8 要求的全部状态 token。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for _p in (VAULT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from workspace_ui.server import help_view as HV                            # noqa: E402
from workspace_ui.server import httpserver as H                            # noqa: E402

SRC = os.path.join(VAULT, "workspace_ui", "static", "src")
CLAIMS = os.path.join(VAULT, "_data", "daily_use", "help", "help_claims.json")
LINK_REPORT = os.path.join(VAULT, "HELP_LINK_REPORT.json")
CLAIM_REPORT = os.path.join(VAULT, "HELP_CLAIM_VERIFICATION.json")
CATALOG = os.path.join(VAULT, "_data", "daily_use", "i18n", "catalog.json")

REQUIRED_PAGES = [
    "getting-started", "research", "explore", "research-vs-explore", "projects",
    "evidence", "persons-cases", "bibliography", "zotero", "obsidian",
    "languages", "statuses", "troubleshooting",
]
REQUIRED_MODULES = {
    "research": "/help/research",
    "explore": "/help/explore",
    "projects": "/help/projects",
    "bibliography": "/help/bibliography",
    "entities": "/help/persons-cases",
    "zotero": "/help/zotero",
}
REQUIRED_STATUSES = [
    "READY", "DEGRADED", "SOURCE_TRACE_INCOMPLETE", "NOT CITABLE", "NEEDS REVIEW",
    "METADATA_CONFLICT", "UNRESOLVED", "ABSTAINED", "PROVIDER_UNAVAILABLE",
    "INSUFFICIENT_EVIDENCE", "VALIDATION_FAILED",
]


def _read(*parts):
    with io.open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


class HelpContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = HV.compile_doc()
        cls.raw = HV.load_raw()

    def test_01_required_pages_exist(self):
        slugs = [p["slug"] for p in self.doc["pages"]]
        self.assertEqual(slugs, REQUIRED_PAGES, "Help 页清单与 spec §8 不一致")

    def test_02_every_page_has_title_summary_bilingual(self):
        for p in self.raw["pages"]:
            for f in ("title", "summary"):
                self.assertTrue(p[f]["en"], "%s.%s en" % (p["slug"], f))
                self.assertTrue(p[f]["zh"], "%s.%s zh" % (p["slug"], f))

    def test_03_blocks_wellformed_and_anchors_unique(self):
        problems = HV.i18n_entries()
        self.assertTrue(problems)
        for p in self.doc["pages"]:
            anchors = p["anchors"]
            self.assertEqual(len(anchors), len(set(anchors)), "%s 锚点重复" % p["slug"])

    def test_04_sections_cover_all_pages(self):
        covered = [s for sec in self.doc["sections"] for s in sec["pages"]]
        self.assertEqual(sorted(covered), sorted(REQUIRED_PAGES))
        for sec in self.doc["sections"]:
            self.assertTrue(sec["title_key"])

    def test_05_ui_refs_all_exist_in_catalog(self):
        with io.open(CATALOG, encoding="utf-8") as fh:
            cat = {r["key"] for r in json.load(fh)["entries"]}
        missing = [r for r in HV.ui_refs() if r not in cat]
        self.assertEqual(missing, [], "Help 正文引用了不存在的产品 UI key：%s" % missing)
        self.assertGreaterEqual(len(HV.ui_refs()), 20, "Help 应当引用真实控件名")

    def test_06_source_blocks_are_not_translated(self):
        """§17 Layer B：原文块不进词典、不随 UI 语言变化。"""
        sources = [b["text"] for p in self.raw["pages"] for b in p["blocks"]
                   if b["kind"] == "source"]
        self.assertTrue(sources, "至少应有一个原文块（示例问题）")
        keys = [k for k, _en, _zh, _s in HV.i18n_entries()]
        for s in sources:
            self.assertNotIn(s, [en for _k, en, _z, _s in HV.i18n_entries()],
                             "原文块不得进入 i18n 词典")
        self.assertTrue(keys)

    def test_07_status_reference_documents_required_tokens(self):
        raw = json.dumps(self.raw, ensure_ascii=False)
        missing = [s for s in REQUIRED_STATUSES if s not in raw]
        self.assertEqual(missing, [], "状态速查未收录：%s" % missing)
        self.assertIn("scholarly limitation", raw.lower())
        self.assertIn("not an operational error", raw.lower())

    def test_08_contextual_help_modules_are_module_specific(self):
        for mod, expect in REQUIRED_MODULES.items():
            self.assertIn(mod, HV.MODULES, "缺少模块 contextual help：%s" % mod)
            self.assertEqual(HV.MODULES[mod]["help"], expect)
        # 不得全部指向 /help
        targets = {m["help"] for m in HV.MODULES.values()}
        self.assertGreaterEqual(len(targets), 7, "contextual help 目标过于笼统")

    def test_09_help_mentions_real_citation_styles_only(self):
        sys.path.insert(0, VAULT)
        import export_system as E                                          # noqa: PLC0415
        real = set(E.BIBLIOGRAPHIC_STYLES) | set(E.INTERNAL_STYLES)
        raw = json.dumps(self.raw, ensure_ascii=False)
        for word in ("Chicago", "APA", "MLA", "BibTeX"):
            if word in raw:
                self.assertIn(word.lower(), real, "Help 提到系统没有的引用样式：%s" % word)

    def test_10_zotero_formats_match_product(self):
        raw = json.dumps(self.raw, ensure_ascii=False)
        self.assertIn("CSL JSON", raw)
        self.assertIn("Better BibTeX JSON", raw)
        src = _read(SRC, "bibliography.js")
        self.assertIn("csl-json", src)
        self.assertIn("bibtex", src)


class HelpRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = H.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        try:
            cls.srv.shutdown()
        except Exception:                                                  # noqa: BLE001
            pass

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=25) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, b""

    def test_11_help_and_module_routes_serve_spa(self):
        for path in ["/help"] + ["/help/" + s for s in REQUIRED_PAGES] + [
                "/", "/home", "/research", "/explore", "/projects", "/bibliography",
                "/persons", "/cases", "/zotero"]:
            code, body = self._get(path)
            self.assertEqual(code, 200, "%s -> %s" % (path, code))
            self.assertIn(b'id="help-view"', body, "%s 未返回 SPA 外壳" % path)
            self.assertIn(b'/static/src/app.js', body, "%s 未挂载前端模块" % path)

    def test_12_unknown_api_still_404_and_unknown_path_404(self):
        code, _ = self._get("/api/definitely-not-a-route")
        self.assertEqual(code, 404)
        code, _ = self._get("/not-a-product-route")
        self.assertEqual(code, 404)

    def test_13_help_content_api_shape(self):
        code, body = self._get("/api/help/content")
        self.assertEqual(code, 200)
        doc = json.loads(body.decode("utf-8"))
        self.assertEqual(doc["schema_version"], "help-content/v1")
        self.assertEqual([p["slug"] for p in doc["pages"]], REQUIRED_PAGES)
        self.assertIn("modules", doc)
        # 结构里**不含正文**（正文只由 i18n 词典渲染）
        blob = json.dumps(doc, ensure_ascii=False)
        self.assertNotIn("Lacan Knowledge OS is a local-corpus", blob)

    def test_14_every_internal_link_is_reachable(self):
        doc = json.loads(self._get("/api/help/content")[1].decode("utf-8"))
        links = []
        for p in doc["pages"]:
            for b in p["blocks"]:
                if b["kind"] == "link" and not b.get("external"):
                    links.append(b["href"])
        for href in links:
            path = href.split("#")[0]
            code, _ = self._get(path)
            self.assertEqual(code, 200, "Help 内部链接不可达：%s" % href)


class HelpReports(unittest.TestCase):
    def test_15_link_report_is_clean(self):
        with io.open(LINK_REPORT, encoding="utf-8") as fh:
            rep = json.load(fh)
        self.assertEqual(rep["broken_internal_links"], 0)
        self.assertEqual(rep["broken_anchors"], 0)
        self.assertEqual(rep["broken_module_deep_links"], 0)
        self.assertGreaterEqual(rep["internal_links"], 15)

    def test_16_claim_report_has_no_fiction(self):
        """§11：**不许有文档虚构**。

        纪律说明（为什么这里容忍 pending）：
          * `documentation_fiction` 必须为 0 —— 任何一条 claim 被真实核验判为假，本测试立刻红；
          * `element` 类需要**真实浏览器**、`api` 类需要**在跑的实例**，
            因此本套件（可离线、可单跑）只要求：**不依赖浏览器/实例的那些 claim 全部已核验**；
          * 严格版本（`pending == 0`）由 Gate F20 在真实实例 + 真实浏览器都就绪时执行。
        """
        # 说明：本测试**只读**报告，不重写它 —— 报告由 Gate F20 在
        # 「真实实例 + 真实浏览器」就绪时生成（`build_help.py --build --url`），
        # 单元测试若用离线版覆盖它，会把已经核验过的 api 类 claim 打回 pending。
        with io.open(CLAIM_REPORT, encoding="utf-8") as fh:
            rep = json.load(fh)
        self.assertEqual(rep["documentation_fiction"], 0, "出现文档虚构（claim 被判为假）")
        self.assertGreaterEqual(rep["claims_n"], 35)
        kinds = {c["kind"] for c in rep["claims"]}
        self.assertTrue({"element", "api", "source", "ui_key"} <= kinds)
        static_kinds = {"ui_key", "source", "pages_all", "links_all", "ui_refs_all",
                        "styles_subset"}
        bad = [c["id"] for c in rep["claims"]
               if c["status"] != "verified" and c["kind"] in static_kinds]
        self.assertEqual(bad, [], "可静态核验的 claim 未通过：%s" % bad)
        self.assertEqual(rep["verified_n"] + rep["pending_n"], rep["claims_n"])
        for c in rep["claims"]:
            if c["status"] == "pending":
                self.assertIn(c["kind"], ("element", "api"),
                              "非浏览器/接口类 claim 不得 pending：%s" % c["id"])

    def test_17_claims_file_covers_every_help_page(self):
        with io.open(CLAIMS, encoding="utf-8") as fh:
            claims = json.load(fh)["claims"]
        pages = {c["help_page"] for c in claims}
        for slug in REQUIRED_PAGES:
            self.assertTrue(any(("/help/" + slug) == p for p in pages),
                            "没有功能性 claim 覆盖 /help/%s" % slug)


class OnboardingUI(unittest.TestCase):
    """§2–§6：任务型首页与教学型空状态的**结构**契约（源码级；行为由浏览器套件验证）。"""

    @classmethod
    def setUpClass(cls):
        cls.home = _read(SRC, "home.js")

    def test_18_home_has_hero_tasks_flow_quickstart(self):
        for token in ("home-hero", "hero-start-research", "hero-first-time",
                      "home-cards", "home-flow-steps", "home-quickstart",
                      "home-quickstart-cta", "home.hero.lede"):
            self.assertIn(token, self.home, token)
        # 6 张任务卡（每组 title/desc/cta 都写全 key）
        for k in ("research", "explore", "concepts", "entities", "projects",
                  "bibliography"):
            self.assertIn("home.card.%s.title" % k, self.home)
            self.assertIn("home.card.%s.cta" % k, self.home)

    def test_19_task_cards_and_flow_are_real_links(self):
        # 卡片/步骤都用 h('a', {href…})（真实链接），而不是只有 onclick 的按钮
        self.assertIn("class: 'task-card', href, id", self.home)
        self.assertIn("class: 'flow-step-link', href", self.home)
        self.assertIn("h('a', { class: cls, href, id: id || null", self.home)
        for href in ("'/research'", "'/explore'", "'/explore?view=concepts'",
                     "'/persons'", "'/projects'", "'/bibliography'",
                     "'/help/getting-started'", "'/help/evidence'", "'/help/obsidian'"):
            self.assertIn(href, self.home, href)

    def test_20_empty_states_teach(self):
        for fname in ("project.js", "explorer.js", "app.js", "bibliography.js"):
            self.assertIn("teachEmpty", _read(SRC, fname), fname)
        teach = _read(SRC, "teach.js")
        self.assertIn("empty-teach", teach)
        self.assertIn("href", teach)

    def test_21_contextual_help_is_wired(self):
        html = _read(VAULT, "workspace_ui", "static", "index.html")
        self.assertIn('id="contextual-help"', html)
        self.assertIn('href="/help"', html)
        app = _read(SRC, "app.js")
        self.assertIn("updateContextualHelp", app)
        self.assertIn("helpModules", app)
        # 帮助视图容器存在且被 showView 管理
        self.assertIn('id="help-view"', html)
        self.assertIn("'help'", app)

    def test_22_router_supports_real_paths(self):
        router = _read(SRC, "router.js")
        for token in ("pathState", "pathFor", "goTo", "wireLinks", "contextModule"):
            self.assertIn(token, router, token)
        for path in ("'help'", "'/help'", "'/research'", "'/explore'",
                     "'/projects'", "'/bibliography'", "'/persons'", "'/cases'",
                     "'zotero'"):
            self.assertIn(path, router, path)


class Diagrams(unittest.TestCase):
    """P5D-005 UI 升级：产品内示意图的**结构与词典边界**（行为由浏览器 claim 核验）。

    守三件事：
      ① 服务端 help_view.DIAGRAMS 与客户端 diagrams.js 的名字集合**完全一致**；
      ② 图里的每一句文字都走 `t('字面量 key')`，key 在词典里 en/zh 齐备
         （机器 token 走 intentional_source_text，**不得**被翻译）；
      ③ Help 正文/首页真的用了这些图（不是写了模块没人调用）。
    """

    @classmethod
    def setUpClass(cls):
        cls.js = _read(SRC, "diagrams.js")
        # 注释里出现 t(…) 只是**说明**，不算调用点；检查一律针对去掉注释的源码
        cls.code = re.sub(r"(?m)\s*//.*$", "", re.sub(r"/\*.*?\*/", "", cls.js,
                                                      flags=re.S))
        cls.help_js = _read(SRC, "help.js")
        cls.home = _read(SRC, "home.js")
        with io.open(CATALOG, encoding="utf-8") as fh:
            cls.catalog = {r["key"]: r for r in json.load(fh)["entries"]}

    def test_23_diagram_names_match_between_server_and_client(self):
        m = re.search(r"DIAGRAM_NAMES\s*=\s*\[([^\]]*)\]", self.code)
        self.assertIsNotNone(m, "diagrams.js 必须导出声明的 DIAGRAM_NAMES")
        names = re.findall(r"'([^']+)'", m.group(1))
        self.assertEqual(sorted(names), sorted(HV.DIAGRAMS),
                         "服务端 DIAGRAMS 与客户端 DIAGRAM_NAMES 漂移")
        build = re.search(r"const BUILD = \{(.*?)\n\};", self.code, re.S)
        self.assertIsNotNone(build, "diagrams.js 必须有 BUILD 分发表")
        for n in names:
            key = "'%s'" % n if "-" in n else n
            self.assertIn(key, build.group(1), "BUILD 表里没有示意图 %s" % n)
        for fn in re.findall(r":\s*(\w+)\s*,", build.group(1)):
            self.assertIn("function %s(" % fn, self.code,
                          "BUILD 引用了未定义的绘制函数 %s" % fn)

    def test_24_every_diagram_label_is_a_literal_catalog_key(self):
        keys = sorted(set(re.findall(r"\bt\('(diagram\.[^']+)'\)", self.code)))
        self.assertTrue(keys, "diagrams.js 里没有任何 diagram.* 词典调用")
        declared = {k for k in self.catalog if k.startswith("diagram.")}
        self.assertEqual(keys, sorted(declared),
                         "图的文字与词典条目不是一一对应（漏译或多写）")
        untranslated = []
        for k in keys:
            e = self.catalog[k]
            self.assertTrue(e["en"] and e["zh"], "词典条目缺 en/zh：%s" % k)
            self.assertIn(e["status"], ("translated", "intentional_source_text"),
                          "示意图文字不得是 hardcoded：%s" % k)
            if e["status"] == "translated" and e["zh"] == e["en"]:
                untranslated.append(k)
        # 只允许极少数天然同形（如 Obsidian）；其余必须真的有中文
        self.assertLessEqual(len(untranslated), 4,
                             "以下条目标为 translated 却没有中文：%s" % untranslated)

    def test_25_diagram_text_is_never_a_dynamic_key(self):
        # 反例：t(altKey) 这类变量调用会让 i18n 检查器看不见调用点（曾出过 key 漏到界面）
        bad = [m.group(0) for m in re.finditer(r"\bt\((?!'|\))", self.code)]
        self.assertEqual(bad, [], "diagrams.js 出现非常量 t() 调用：%s" % bad[:5])
        self.assertNotIn("innerHTML", self.code)
        self.assertIn("createElementNS", self.code)
        self.assertNotIn("document.createElement(", self.code)

    def test_26_figures_are_wired_into_help_and_home(self):
        raw = HV.load_raw()
        ev = [p for p in raw["pages"] if p["slug"] == "evidence"][0]
        figs = [(i, b) for i, b in enumerate(ev["blocks"], start=1)
                if b.get("kind") == "figure"]
        self.assertEqual([b["name"] for _i, b in figs], ["evidence-chain"],
                         "/help/evidence 必须且只能有一个证据链示意图")
        self.assertTrue(figs[0][1].get("en") and figs[0][1].get("zh"),
                        "示意图必须双语题注")
        # 编译层：figure 块带 alt_key，且指向词典里真实存在的 key
        page = [p for p in HV.compile_doc()["pages"] if p["slug"] == "evidence"][0]
        fig = [b for b in page["blocks"] if b["kind"] == "figure"][0]
        self.assertEqual(fig["alt_key"], "diagram.evidence-chain.alt")
        self.assertIn(fig["alt_key"], self.catalog)
        self.assertIn(fig["key"], self.catalog)          # 题注 key 也进词典
        idx = HV.compile_doc()["index"]["figure"]
        self.assertEqual(idx["name"], "architecture")
        self.assertIn(idx["key"], self.catalog)
        # 渲染层：help.js 支持 figure 块，home.js 在 hero 里放 workflow 图
        self.assertIn("case 'figure'", self.help_js)
        self.assertIn("richFigure(doc.index.figure)", self.help_js)
        self.assertIn("diagram('workflow')", self.home)
        self.assertIn("home.hero.figure", self.home)
        self.assertIn("home.hero.figure", self.catalog)


if __name__ == "__main__":
    unittest.main(verbosity=2)
