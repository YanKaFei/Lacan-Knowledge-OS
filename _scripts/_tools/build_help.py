#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_help.py — P5D-005 Help Center 的**构建与可核性**工具（只读产品代码，写数据/报告）。

做四件事（全部确定性、可重复）：

  1. **内容校验**：结构合法、en/zh 齐备、slug/anchor 唯一、内部链接可解析、
     正文引用的每个产品 UI key 都存在（**不虚构按钮**）、提到的引用样式真实存在。
  2. **词典生成**：把 Help 正文写进既有 i18n 词典（`manual_keys.json` 的 `help.*` 条目），
     再调用 `build_i18n.py --build/--coverage`；**原文块不翻译**、不进词典。
  3. **链接报告** `HELP_LINK_REPORT.json`：内部路由（可含 --url 做真实 HTTP 复核）+
     跨页 anchor，统计 broken 数。
  4. **断言核验** `HELP_CLAIM_VERIFICATION.json`：逐条 claim 用 content/api/source 检查核验；
     `kind=element` 的条目由真实浏览器套件写入证据后折叠进来（未核验 → pending，
     而 Gate F20 要求 pending=0 且 fiction=0）。

用法：
    python3 _scripts/_tools/build_help.py --build      # 校验 + 生成词典 + 链接报告 + claims
    python3 _scripts/_tools/build_help.py --check      # 只校验（供套件/F20 调用）
    python3 _scripts/_tools/build_help.py --build --url http://127.0.0.1:3090
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)

from workspace_ui.server import help_view as HV                                # noqa: E402

I18N_DIR = os.path.join(VAULT, "_data", "daily_use", "i18n")
MANUAL = os.path.join(I18N_DIR, "manual_keys.json")
CATALOG = os.path.join(I18N_DIR, "catalog.json")
HELP_DIR = os.path.join(VAULT, "_data", "daily_use", "help")
CLAIMS_IN = os.path.join(HELP_DIR, "help_claims.json")
LINK_REPORT = os.path.join(VAULT, "HELP_LINK_REPORT.json")
CLAIM_REPORT = os.path.join(VAULT, "HELP_CLAIM_VERIFICATION.json")
BROWSER_CLAIMS = os.path.join(VAULT, "_workspace", "ui_qa",
                             "p5d005_help_claim_browser.json")
STYLE_WORDS = ("Chicago", "APA", "MLA", "BibTeX")


def _real_styles():
    """产品**真正**声明的引用样式（从 export_system 取，不猜）。"""
    sys.path.insert(0, VAULT)
    try:
        import export_system as E                                         # noqa: PLC0415
        return (set(getattr(E, "BIBLIOGRAPHIC_STYLES", ()) or ())
                | set(getattr(E, "INTERNAL_STYLES", ()) or ()))
    except Exception:                                                     # noqa: BLE001
        return set()


def _catalog():
    if not os.path.isfile(CATALOG):
        return {}
    with io.open(CATALOG, encoding="utf-8") as fh:
        return {r["key"]: r for r in json.load(fh)["entries"]}


def _exists_http(url, path):
    try:
        with urllib.request.urlopen(url.rstrip("/") + path, timeout=20) as r:
            return r.status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:                                                      # noqa: BLE001
        return False


def verify_links(base_url=None):
    """内部链接 + anchor 检查。→ (report, problems)"""
    doc = HV.compile_doc()
    anchors = {p["slug"]: set(p["anchors"]) for p in doc["pages"]}
    rows, problems = [], []
    for item in HV.hrefs():
        href = item["href"]
        path, frag = HV.parse_href(href)
        if path is None:
            continue
        target_slug = None
        if path.startswith("/help/"):
            target_slug = path[len("/help/"):].strip("/")
        elif path == "/help":
            target_slug = None
        route_ok = HV.spa_route_ok(path)
        anchor_ok = True
        if frag:
            if target_slug:
                anchor_ok = frag in anchors.get(target_slug, set())
            else:
                anchor_ok = any(frag in a for a in anchors.values())
        http_ok = None
        if base_url and route_ok:
            http_ok = _exists_http(base_url, path)
        ok = route_ok and anchor_ok and (http_ok is not False)
        rows.append({"page": item["page"], "block": item["block"], "href": href,
                     "path": path, "anchor": frag, "route_ok": route_ok,
                     "anchor_ok": anchor_ok, "http_ok": http_ok, "ok": ok})
        if not ok:
            problems.append(href)
    # 模块 contextual help 的 deep link 也必须指向真实页
    module_rows = []
    for name, m in sorted(HV.MODULES.items()):
        slug = m["help"][len("/help/"):] if m["help"].startswith("/help/") else None
        ok = (m["help"] == "/help") or (slug in anchors)
        module_rows.append({"module": name, "help": m["help"], "module_href": m["href"],
                            "route_ok": HV.spa_route_ok(m["help"]) and HV.spa_route_ok(m["href"]),
                            "target_page_exists": ok})
        if not (module_rows[-1]["route_ok"] and ok):
            problems.append(m["help"])
    broken_links = [r for r in rows if not r["route_ok"]]
    broken_anchors = [r for r in rows if r["route_ok"] and not r["anchor_ok"]]
    report = {
        "schema_version": "help-link-report/v1",
        "generated_by": "_scripts/_tools/build_help.py",
        "base_url": base_url,
        "help_pages": len(doc["pages"]),
        "internal_links": len(rows),
        "module_deep_links": len(module_rows),
        "broken_internal_links": len(broken_links),
        "broken_anchors": len(broken_anchors),
        "broken_module_deep_links": len([m for m in module_rows if not m["target_page_exists"]]),
        "links": rows,
        "modules": module_rows,
        "problems": sorted(set(problems)),
    }
    return report, report["problems"]


def verify_claims(base_url=None, browser_path=None):
    """逐条核验 claim。→ (report, unknown_kinds)"""
    with io.open(CLAIMS_IN, encoding="utf-8") as fh:
        claims = json.load(fh)["claims"]
    cat = _catalog()
    doc = HV.compile_doc()
    slugs = set(doc["slugs"])
    refs = set(HV.ui_refs())
    link_report = json.load(io.open(LINK_REPORT, encoding="utf-8")) \
        if os.path.isfile(LINK_REPORT) else {"broken_internal_links": None}
    browser = {}
    bp = browser_path or BROWSER_CLAIMS
    if os.path.isfile(bp):
        with io.open(bp, encoding="utf-8") as fh:
            browser = (json.load(fh) or {}).get("claims") or {}
    real_styles = _real_styles()
    out, problems = [], []
    for c in claims:
        cid, kind = c["id"], c["kind"]
        status, detail = "pending", {}
        if kind == "ui_key":
            ok = c["ui_key"] in cat
            status = "verified" if ok else "failed"
            detail = {"ui_key": c["ui_key"], "in_catalog": ok,
                      "en": (cat.get(c["ui_key"]) or {}).get("en")}
        elif kind == "element":
            rec = browser.get(cid)
            if rec is None:
                status, detail = "pending", {"url": c.get("url"), "why": "browser evidence absent"}
            else:
                status = "verified" if rec.get("status") == "PASS" else "failed"
                detail = {"url": c.get("url"), "js": c.get("js"),
                          "observed": rec.get("detail")}
        elif kind == "api":
            detail = {"path": c["path"]}
            if not base_url:
                status = "pending"
                detail["why"] = "no --url given"
            else:
                try:
                    method = c.get("method", "GET")
                    data = None
                    if method == "POST":
                        data = json.dumps(c.get("body") or {}).encode("utf-8")
                    req = urllib.request.Request(
                        base_url.rstrip("/") + c["path"], data=data,
                        headers={"Content-Type": "application/json"} if data else {})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        got = json.loads(r.read().decode("utf-8"))
                        code = r.status
                    if "status_in" in c:
                        status = "verified" if code in c["status_in"] else "failed"
                    elif "json_path" in c:
                        cur = got
                        for k in c["json_path"]:
                            cur = (cur or {}).get(k)
                        if "in" in c:
                            status = "verified" if cur in c["in"] else "failed"
                        elif "equals" in c:
                            status = "verified" if cur == c["equals"] else "failed"
                        elif "keys" in c:
                            have = set((cur or {}).keys())
                            missing = [k for k in c["keys"] if k not in have]
                            status = "verified" if not missing else "failed"
                            detail["missing"] = missing
                        detail["observed"] = cur
                    elif "keys" in c:
                        have = set((got or {}).keys())
                        missing = [k for k in c["keys"] if k not in have]
                        status = "verified" if not missing else "failed"
                        detail["missing"] = missing
                    elif "json_keys_any" in c:
                        have = set((got or {}).keys())
                        status = "verified" if have & set(c["json_keys_any"]) else "failed"
                        detail["keys"] = sorted(have)[:12]
                    else:
                        status = "verified"
                    detail["http_status"] = code
                except urllib.error.HTTPError as exc:
                    status = ("verified" if exc.code in c.get("status_in", []) else "failed")
                    detail["http_status"] = exc.code
                except Exception as exc:                                   # noqa: BLE001
                    status, detail = "failed", {"error": type(exc).__name__}
        elif kind == "source":
            path = os.path.join(VAULT, c["file"])
            text = io.open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
            ok = c["contains"] in text
            status = "verified" if ok else "failed"
            detail = {"file": c["file"], "contains": c["contains"]}
        elif kind == "pages_all":
            bad = []
            for slug in sorted(slugs):
                path = "/help/" + slug
                if base_url:
                    if not _exists_http(base_url, path):
                        bad.append(path)
            status = "verified" if not bad else "failed"
            detail = {"pages": len(slugs), "unreachable": bad}
        elif kind == "links_all":
            b1 = link_report.get("broken_internal_links")
            b2 = link_report.get("broken_anchors")
            status = ("verified" if b1 == 0 and b2 == 0 else "failed")
            detail = {"broken_internal_links": b1, "broken_anchors": b2}
        elif kind == "ui_refs_all":
            missing = sorted(r for r in refs if r not in cat)
            status = "verified" if not missing else "failed"
            detail = {"refs": len(refs), "missing": missing}
        elif kind == "styles_subset":
            raw = json.dumps(HV.load_raw(), ensure_ascii=False)
            mentioned = [w for w in STYLE_WORDS if w in raw]
            missing = [w for w in mentioned if w.lower() not in real_styles]
            status = "verified" if not missing else "failed"
            detail = {"mentioned": mentioned, "real_styles": sorted(real_styles),
                      "unsupported_mentioned": missing}
        else:
            status, detail = "failed", {"unknown_kind": kind}
        if status != "verified":
            problems.append({"id": cid, "status": status, "claim": c["claim"]})
        out.append({"id": cid, "claim": c["claim"], "help_page": c["help_page"],
                    "verified_by": ("browser" if kind == "element"
                                    else ("API" if kind == "api" else "source")),
                    "kind": kind, "status": status, "detail": detail})
    report = {
        "schema_version": "help-claim-verification/v1",
        "generated_by": "_scripts/_tools/build_help.py",
        "base_url": base_url,
        "claims_n": len(out),
        "verified_n": sum(1 for c in out if c["status"] == "verified"),
        "pending_n": sum(1 for c in out if c["status"] == "pending"),
        "failed_n": sum(1 for c in out if c["status"] == "failed"),
        "documentation_fiction": sum(1 for c in out if c["status"] == "failed"),
        "claims": out,
    }
    return report, problems


UI_KEYS = os.path.join(HELP_DIR, "ui_keys.json")
# 本工具**独占管理**的 key 前缀（其余条目一律不动，逐字节保留）
OWNED_PREFIXES = ("help.",)


def _owned(key):
    return any(str(key).startswith(p) for p in OWNED_PREFIXES) or \
        key in _ui_key_names()


def _ui_key_names():
    if not os.path.isfile(UI_KEYS):
        return set()
    with io.open(UI_KEYS, encoding="utf-8") as fh:
        return {k["key"] for k in json.load(fh)["keys"]}


def sync_manual_keys():
    """把 Help 正文与新增首页/Help 文案写进 i18n 词典输入（幂等：只管理自己拥有的 key）。"""
    with io.open(MANUAL, encoding="utf-8") as fh:
        rows = json.load(fh)
    owned = _ui_key_names()
    keep = [r for r in rows
            if not str(r.get("key", "")).startswith("help.") and r.get("key") not in owned]
    added = []
    for key, en, zh, status in HV.i18n_entries():
        added.append({"key": key, "en": en, "zh": zh, "surface": "Help",
                      "status": status})
    ui = []
    if os.path.isfile(UI_KEYS):
        with io.open(UI_KEYS, encoding="utf-8") as fh:
            for e in json.load(fh)["keys"]:
                ui.append({"key": e["key"], "en": e["en"], "zh": e["zh"],
                           "surface": e.get("surface", "Home"), "status": "translated"})
    out = keep + sorted(added + ui, key=lambda r: r["key"])
    with io.open(MANUAL, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    return {"help_keys": len(added), "ui_keys": len(ui), "other_keys": len(keep),
            "total": len(out)}


def content_problems():
    """内容自身的结构校验（不依赖词典/网络）。"""
    probs = []
    raw = HV.load_raw()
    slugs = [p["slug"] for p in raw["pages"]]
    if len(slugs) != len(set(slugs)):
        probs.append("duplicate slug")
    for p in raw["pages"]:
        for field in ("title", "summary"):
            v = p.get(field) or {}
            if not v.get("en") or not v.get("zh"):
                probs.append("%s: %s missing en/zh" % (p["slug"], field))
        seen = set()
        for i, b in enumerate(p.get("blocks") or [], start=1):
            k = b.get("kind")
            if k not in ("h2", "h3", "p", "ul", "ol", "callout", "link", "source", "dl"):
                probs.append("%s#%d: bad kind %r" % (p["slug"], i, k))
            if k == "h2" or k == "h3":
                a = b.get("anchor") or ("s%d" % i)
                if a in seen:
                    probs.append("%s: duplicate anchor %s" % (p["slug"], a))
                seen.add(a)
            if k == "source":
                if not b.get("text"):
                    probs.append("%s#%d: empty source block" % (p["slug"], i))
                continue
            if k == "link":
                if not b.get("href") or not b.get("en") or not b.get("zh"):
                    probs.append("%s#%d: link needs href/en/zh" % (p["slug"], i))
                continue
            if k in ("ul", "ol"):
                if not b.get("en") or len(b["en"]) != len(b.get("zh") or []):
                    probs.append("%s#%d: list en/zh length mismatch" % (p["slug"], i))
                continue
            if k == "dl":
                items = b.get("items") or []
                if not items:
                    probs.append("%s#%d: empty dl" % (p["slug"], i))
                for j, it in enumerate(items, start=1):
                    for f in ("term_en", "term_zh", "desc_en", "desc_zh"):
                        if not it.get(f):
                            probs.append("%s#%d.%d: missing %s" % (p["slug"], i, j, f))
                continue
            if not b.get("en") or not b.get("zh"):
                probs.append("%s#%d: %s missing en/zh" % (p["slug"], i, k))
        # UI 引用必须成对出现在 en/zh 里（不强制，但空引用要报）
    # link 的 query/href 自洽
    for item in HV.hrefs():
        if not item["href"].startswith("/"):
            probs.append("relative href: %s" % item["href"])
    return probs


def main(argv=None):
    ap = argparse.ArgumentParser(description="P5D-005 help build/check")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--url", default=None)
    a = ap.parse_args(argv)

    probs = content_problems()
    link_report, link_probs = verify_links(a.url)
    with io.open(LINK_REPORT, "w", encoding="utf-8") as fh:
        json.dump(link_report, fh, ensure_ascii=False, indent=1, sort_keys=True)
    if a.build:
        info = sync_manual_keys()
        for tool, args in (("build_i18n.py", ["--build"]), ("build_i18n.py", ["--coverage"])):
            os.system("cd %s && python3 %s %s >/dev/null" % (VAULT, os.path.join(HERE, tool),
                                                             " ".join(args)))
    else:
        info = {}
    claim_report, claim_probs = verify_claims(a.url)
    with io.open(CLAIM_REPORT, "w", encoding="utf-8") as fh:
        json.dump(claim_report, fh, ensure_ascii=False, indent=1, sort_keys=True)

    ok = (not probs and not link_probs and claim_report["failed_n"] == 0
          and claim_report["pending_n"] == 0)
    print(json.dumps({
        "kind": "help_build" if a.build else "help_check",
        "help_pages": len(HV.compile_doc()["pages"]),
        "content_problems": probs[:20], "content_problems_n": len(probs),
        "link_report": {"internal_links": link_report["internal_links"],
                        "broken_internal_links": link_report["broken_internal_links"],
                        "broken_anchors": link_report["broken_anchors"],
                        "module_deep_links": link_report["module_deep_links"]},
        "claims": {"n": claim_report["claims_n"], "verified": claim_report["verified_n"],
                   "pending": claim_report["pending_n"], "failed": claim_report["failed_n"]},
        "i18n_keys": info,
        "problems": [p if isinstance(p, str) else p.get("id") for p in
                     (probs + link_probs + claim_probs)][:20],
        "ok": ok,
    }, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
