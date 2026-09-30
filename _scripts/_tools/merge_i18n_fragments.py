#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_i18n_fragments.py — P5D-004 质量修正：把被拼接的句子合并成**整句**翻译条目。

问题：机械重写只把**单个字面量**换成 `t('key')`，于是
`t('projects.x') + 'verdicts. Researching ...'` 这类**拼接句**在中文模式下会中英混排。

做法（确定性、可复核）：
  1. 扫描 `static/src/*.js`，找出 `t('<key>')` 紧跟 `+ '<fragment>'` 的位置；
  2. 生成整句 en = `catalog[key].en + fragment`，登记为**新 key**（`<key>--full`）；
  3. 把源码改写成单个 `t('<newkey>')`（去掉拼接）；
  4. 把整句写进 `_data/daily_use/i18n/input_strings_extra.json`（供翻译），
     并写 `fragment_merges.json` 作为审计记录。
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
I18N = os.path.join(VAULT, "_data", "daily_use", "i18n")
SRC = os.path.join(VAULT, "workspace_ui", "static", "src")
CATALOG = os.path.join(I18N, "catalog.json")
MERGES = os.path.join(I18N, "fragment_merges.json")
EXTRA_IN = os.path.join(I18N, "input_strings_extra.json")

PAT = re.compile(r"t\('([^']+)'\)(\s*\n?\s*)\+\s*'((?:[^'\\]|\\.){1,400})'")


def main():
    with open(CATALOG, encoding="utf-8") as fh:
        catalog = json.load(fh)
    en_of = {r["key"]: r["en"] for r in catalog["entries"]}
    records, extra, used = [], [], set()
    changed_files = {}
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".js") or fn in ("i18n.js", "i18n_messages.js"):
            continue
        path = os.path.join(SRC, fn)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        orig = src
        counter = [0]

        def repl(m):
            key, gap, frag = m.group(1), m.group(2), m.group(3)
            base = en_of.get(key)
            if base is None:
                return m.group(0)
            merged = base + frag
            newkey = key + "--full"
            n = 2
            while newkey in used:
                newkey = "%s--full%d" % (key, n)
                n += 1
            used.add(newkey)
            records.append({"file": fn, "old_key": key, "new_key": newkey,
                            "en": merged, "fragment": frag})
            extra.append({"string": merged, "surfaces": ["Application"], "files": [fn]})
            counter[0] += 1
            return "t('%s')" % newkey

        src = PAT.sub(repl, src)
        if src != orig:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(src)
            changed_files[fn] = counter[0]
    # append-safe（幂等）：与既有记录/输入取并集，绝不丢已经合并过的整句
    old_records, old_extra = [], []
    if os.path.isfile(MERGES):
        with open(MERGES, encoding="utf-8") as fh:
            old_records = (json.load(fh) or {}).get("merges") or []
    if os.path.isfile(EXTRA_IN):
        with open(EXTRA_IN, encoding="utf-8") as fh:
            old_extra = json.load(fh) or []
    merged = {r["en"]: r for r in old_records}
    for r in records:
        merged.setdefault(r["en"], r)
    inputs = {e["string"]: e for e in old_extra}
    for e in extra:
        inputs.setdefault(e["string"], e)
    with open(MERGES, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": "p5d004-fragment-merges/v1",
                   "count": len(merged), "merges": sorted(merged.values(),
                                                           key=lambda r: r["en"])},
                  fh, ensure_ascii=False, indent=1, sort_keys=True)
    with open(EXTRA_IN, "w", encoding="utf-8") as fh:
        json.dump(sorted(inputs.values(), key=lambda e: e["string"]), fh,
                  ensure_ascii=False, indent=1)
    print(json.dumps({"kind": "merge_fragments", "merged": len(records),
                      "files": changed_files, "extra_input": EXTRA_IN},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
