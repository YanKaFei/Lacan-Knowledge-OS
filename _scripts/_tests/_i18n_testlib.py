#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_i18n_testlib.py — P5D-004 之后，测试如何断言"某句产品文案仍然存在"。

背景（**测试策略变更，已披露**）：i18n 之后，产品文案不再以内联字面量出现在
`static/src/*.js` 里，而是 `t('<key>')` + `i18n_messages.js` 词典。旧的
`assertIn("'Overview'", js_source)` 会因此失败 —— 但**不是**产品回归。

新的断言**更强**：同时要求
  ① 该 key 真的被源码调用（`t('key')` 存在）；
  ② 该 key 在 **en 与 zh 两个词典**里都有非空值（缺一即失败）。

用法：
    from _i18n_testlib import key_for, assert_rendered, messages
    key = key_for("Overview")                     # 由英文原文找 key
    assert_rendered(self, "bibliography.js", key) # 源码调用 + 双语词典都在
"""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(VAULT, "workspace_ui", "static", "src")
CATALOG = os.path.join(VAULT, "_data", "daily_use", "i18n", "catalog.json")


def catalog():
    with open(CATALOG, encoding="utf-8") as fh:
        return json.load(fh)


def messages():
    """解析生成的 i18n_messages.js → {'en': {...}, 'zh': {...}}。"""
    with open(os.path.join(SRC, "i18n_messages.js"), encoding="utf-8") as fh:
        js = fh.read()
    out = {}
    for loc in ("en", "zh"):
        block = re.search(r"\b%s:\s*\{(.*?)\n  \}," % loc, js, re.S)
        d = {}
        if block:
            for k, v in re.findall(r'"([^"]+)":\s*("(?:[^"\\]|\\.)*")', block.group(1)):
                d[k] = json.loads(v)
        out[loc] = d
    return out


def keys_for(en_text):
    """英文原文 → 候选 key 列表（精确优先，其次包含该文本的条目，按长度升序）。"""
    entries = catalog()["entries"]
    exact = sorted(r["key"] for r in entries if r["en"] == en_text)
    subs = sorted((r for r in entries if en_text in r["en"]),
                  key=lambda r: (len(r["en"]), r["key"]))
    out = list(exact)
    for r in subs:
        if r["key"] not in out:
            out.append(r["key"])
    if not out:
        raise AssertionError("catalog 里没有这条英文原文：%r" % en_text)
    return out


def key_for(en_text):
    return keys_for(en_text)[0]


def source_uses(module, key):
    with open(os.path.join(SRC, module), encoding="utf-8") as fh:
        return ("t('%s')" % key) in fh.read()


def assert_rendered(test, module, key):
    """断言：源码调用该 key，且 en/zh 词典都有非空值。"""
    test.assertTrue(source_uses(module, key),
                    "%s 未调用 t('%s')（i18n 未接线）" % (module, key))
    m = messages()
    test.assertIn(key, m["en"], "en 词典缺 key：%s" % key)
    test.assertIn(key, m["zh"], "zh 词典缺 key：%s" % key)
    test.assertTrue(m["en"][key].strip() and m["zh"][key].strip(),
                    "词典值为空：%s" % key)


def assert_text_wired(test, module, en_text):
    """按英文原文断言：只要**有一个**候选 key 在该模块里被接线，且双词典都有值即可。

    （同一句话可能既有"片段 key"又有合并后的"整句 key"；以源码实际调用者为准。）
    """
    keys = keys_for(en_text)
    used = [k for k in keys if source_uses(module, k)]
    test.assertTrue(used, "%s 未接线：%r（候选 keys=%s）"
                    % (module, en_text[:60], keys[:4]))
    m = messages()
    for k in used:
        test.assertIn(k, m["en"], "en 词典缺 key：%s" % k)
        test.assertIn(k, m["zh"], "zh 词典缺 key：%s" % k)
        test.assertTrue(m["en"][k].strip() and m["zh"][k].strip(), "词典值为空：%s" % k)
