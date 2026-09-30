#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_ui_artifacts.py — §13：确认用户打开的 127.0.0.1:3090 用的**就是**磁盘上的源码。

本项目**没有打包器**：`index.html` 直接以 ESM 加载 `/static/src/*.js`，
HTTP 层把 `workspace_ui/static/**` 原样送出。因此"源码 = 产物 = 被服务的字节"
必须**逐字节证明**，避免"源码改对了、网页还加载旧 bundle"。

做三件事（只读；需要一个在跑的 UI 实例；不传 --url 则从 runtime pid 记录推断端口）：
  1. 取磁盘上每个 static 资产的 sha256；
  2. 通过 HTTP 取同一个路径的字节并算 sha256；
  3. 逐个比对，并额外确认 `index.html` 引用的模块（app.js/i18n.js/i18n_messages.js）
     **真的能被服务到**且字节一致。

输出：结构化 JSON（可写入文件），exit 0 = 全部一致。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STATIC = os.path.join(VAULT, "workspace_ui", "static")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def listed_assets():
    out = []
    for root, _dirs, files in os.walk(STATIC):
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, STATIC).replace(os.sep, "/")
            out.append(rel)
    return sorted(out)


def fetch(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("LACAN_UI_URL", "http://127.0.0.1:3090"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    base = a.url.rstrip("/")
    assets, mismatches, missing = {}, [], []
    for rel in listed_assets():
        with open(os.path.join(STATIC, rel), "rb") as fh:
            disk = fh.read()
        url = "%s/static/%s" % (base, rel)
        try:
            served = fetch(url)
        except Exception as exc:                                           # noqa: BLE001
            missing.append({"asset": rel, "error": type(exc).__name__})
            continue
        entry = {"disk_sha256": sha(disk)[:16], "served_sha256": sha(served)[:16],
                 "bytes": len(disk), "match": disk == served}
        assets[rel] = entry
        if not entry["match"]:
            mismatches.append(rel)
    # index.html 引用的模块必须都能被服务到
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    refs = sorted(set(re.findall(r'src="(/static/[^"]+)"', html)))
    refs += sorted(set(re.findall(r'href="(/static/[^"]+\.css)"', html)))
    module_checks = {}
    for ref in refs:
        rel = ref[len("/static/"):]
        p = os.path.join(STATIC, rel)
        ok = os.path.isfile(p)
        if ok:
            with open(p, "rb") as fh:
                disk = fh.read()
            try:
                served = fetch(base + ref)
                ok = (disk == served)
            except Exception:                                              # noqa: BLE001
                ok = False
        module_checks[ref] = ok
    i18n_load = {}
    for mod in ("i18n.js", "i18n_messages.js"):
        try:
            i18n_load[mod] = len(fetch("%s/static/src/%s" % (base, mod))) > 0
        except Exception:                                                  # noqa: BLE001
            i18n_load[mod] = False
    ok_all = (not mismatches and not missing
              and all(module_checks.values()) and all(i18n_load.values()))
    doc = {
        "schema_version": "ui-artifact-verification/v1",
        "url": base,
        "verdict": "PASS" if ok_all else "FAIL",
        "assets_checked": len(assets),
        "mismatched": mismatches,
        "unreachable": missing,
        "entry_modules": module_checks,
        "i18n_modules_served": i18n_load,
        "note": ("无打包器：index.html 直接 ESM 加载 static/src；这里证明"
                 "磁盘字节 == HTTP 服务字节。"),
        "assets": assets,
    }
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print(json.dumps({k: doc[k] for k in ("verdict", "assets_checked", "mismatched",
                                          "unreachable", "entry_modules",
                                          "i18n_modules_served")},
                     ensure_ascii=False))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
