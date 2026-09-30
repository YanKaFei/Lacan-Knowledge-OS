#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_secret_audit.py — Phase 4E §68：凭据泄漏审计（只读）

扫描 Phase 4E 产生/触及的**运行工件**，确认 provider 凭据没有落进：
`_workspace/**`（history / exports / obsidian 笔记 / test_cache）、`_data/phase4e/**`、
`_data/product_acceptance/**`、`_workspace/**` 下的日志与截图（PNG 文本块也会被扫）。

判定三类命中：
  * 完整 API key 字面量（值取自环境或 `~/.dsh/.credentials.yaml`，**只比对不打印**）；
  * `sk-…` 形态的凭据串；
  * `Authorization: Bearer …` / `Bearer sk-…`。

**不扫描源码树**（`_scripts/**`、`scholarly_api/**`）：那里有意留了一个**测试用 canary**
（`sk-CANARY-…`）用来验证脱敏，它不是真实凭据。该例外在输出里显式记录。

用法：
    python3 _scripts/_tools/phase4e_secret_audit.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
OUT_DEFAULT = os.path.join(VAULT, "_data", "phase4e", "secret_audit.json")

TARGETS = [
    ("_workspace", True),
    ("_data/phase4e", True),
    ("_data/product_acceptance", True),
    ("_index/Reports", True),
]
TEXT_EXT = (".json", ".jsonl", ".md", ".txt", ".log", ".html", ".csv", ".tsv", ".yaml",
            ".yml", ".png", ".js")
MAX_BYTES = 40 * 1024 * 1024
KEY_PATTERNS = (re.compile(rb"sk-[A-Za-z0-9_\-]{16,}"),
                re.compile(rb"(?i)authorization\s*[:=]\s*bearer\s+\S{12,}"))


def collect_keys():
    """收集需要比对的凭据值（**不打印**）。"""
    vals = []
    for name in ("DSH_SYNTHESIS_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        v = os.environ.get(name)
        if v and len(v) >= 8:
            vals.append(v.encode("utf-8"))
    p = os.path.expanduser("~/.dsh/.credentials.yaml")
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8", errors="replace"):
            m = re.match(r"\s*([A-Z_]*API_KEY):\s*(\S{8,})\s*$", line)
            if m:
                vals.append(m.group(2).encode("utf-8"))
    return vals


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E secret audit")
    ap.add_argument("--json", default=OUT_DEFAULT)
    a = ap.parse_args(argv)

    keys = collect_keys()
    findings, scanned, skipped = [], 0, []
    for rel, recursive in TARGETS:
        root = os.path.join(VAULT, rel)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                if not fn.lower().endswith(TEXT_EXT):
                    continue
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                if size > MAX_BYTES:
                    skipped.append({"path": os.path.relpath(p, VAULT),
                                    "reason": "size>%d" % MAX_BYTES})
                    continue
                try:
                    blob = open(p, "rb").read()
                except OSError:
                    continue
                scanned += 1
                rp = os.path.relpath(p, VAULT)
                for kv in keys:
                    if kv in blob:
                        findings.append({"code": "API_KEY_LITERAL", "path": rp})
                for pat in KEY_PATTERNS:
                    for m in pat.finditer(blob):
                        # 测试 canary 不是真实凭据，但仍如实记录其出现位置
                        token = m.group(0)
                        findings.append({
                            "code": ("TEST_CANARY" if b"CANARY" in token
                                     else "KEY_SHAPED_TOKEN"),
                            "path": rp, "preview": token[:8].decode("utf-8", "replace") + "…"})
    real = [f for f in findings if f["code"] in ("API_KEY_LITERAL", "KEY_SHAPED_TOKEN")]
    doc = {
        "schema_version": "phase4e-secret-audit/v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "targets": [t[0] for t in TARGETS],
        "excluded": ["_scripts/**", "scholarly_api/**", "mcp_server/**",
                     "workspace_ui/**", "_data/eval/**"],
        "exclusion_reason": ("源码树内含**测试用 canary**（sk-CANARY-…）用于验证脱敏，"
                            "不是真实凭据；真实凭据的扫描面是所有运行工件。"),
        "keys_checked_n": len(keys),
        "files_scanned_n": scanned,
        "files_skipped": skipped,
        "findings": findings,
        "real_credential_findings": real,
        "verdict": "PASS" if not real else "FAIL",
        "note": ("只比对、不打印凭据；输出里最多出现命中 token 的前 8 个字符。"),
    }
    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print("secret audit: %s | files=%d | keys=%d | real findings=%d | test canaries=%d"
          % (doc["verdict"], scanned, len(keys), len(real),
             len([f for f in findings if f["code"] == "TEST_CANARY"])))
    for f in real[:10]:
        print("  !! %s %s" % (f["code"], f["path"]))
    for f in [x for x in findings if x["code"] == "TEST_CANARY"][:5]:
        print("  (canary) %s" % f["path"])
    print("-> %s" % os.path.relpath(a.json, VAULT))
    return 0 if doc["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
