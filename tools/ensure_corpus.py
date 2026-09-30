#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ensure_corpus.py — 让**人**和**AI**都能一眼看清：语料在不在、缺什么、下一步做什么。

为什么需要它：这个仓库刻意不含语料（第三方的版权文本）。于是"下载了引擎却跑不起来"
是这套系统最常见的第一个坑。本脚本把这件事变成**一条命令 + 一个明确的退出码**，
并把"下一步怎么做"直接打印出来（含私有语料包的下载命令）。

退出码（AI 应据此决定是否提醒用户）：
    0  语料就绪（可以真正跑研究）
    3  语料缺失或不完整 → **必须提醒用户**
    4  语料包存在但校验失败 → 不要继续，先修包

用法：
    python3 tools/ensure_corpus.py --status          # 只检查（默认）
    python3 tools/ensure_corpus.py --json            # 结构化输出（给 agent 读）
    python3 tools/ensure_corpus.py --install --pack corpus-pack-v1.tar.gz \
        --manifest corpus-pack-v1.manifest.json      # 校验并安装
    python3 tools/ensure_corpus.py --install --token-env GITHUB_TOKEN
                                                     # 直接从私有仓库 Release 取包
    python3 tools/ensure_corpus.py --print-instructions
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CORPUS_JSON = os.path.join(REPO, "corpus.json")

REQUIRED = [
    ("_data/passage_store/passages.jsonl", "passage store (corpus text)"),
    ("_data/passage_store/witnesses.jsonl", "witness registry"),
    ("_data/passage_store/seminars.jsonl", "work registry"),
    ("_data/passage_store/_build_meta.json", "passage-store build metadata (freeze input)"),
    ("_data/corpus_inventory.json", "corpus inventory (freeze input)"),
    ("_data/index/lexical.sqlite", "lexical retrieval index"),
    ("_data/index/alias_index.jsonl", "alias index"),
    ("_data/terminology_bridge.jsonl", "terminology bridge"),
]
OPTIONAL = [
    ("_data/index/vector/VECTOR_INDEX_MANIFEST.json", "vector index manifest (semantic retrieval)"),
    ("_index/passage_store.sqlite", "passage-store SQLite (fast browsing)"),
    ("_data/ontology/v4a1/entities.jsonl", "ontology entities (needed for validated answers)"),
]


def reference():
    if not os.path.isfile(CORPUS_JSON):
        return {}
    with io.open(CORPUS_JSON, encoding="utf-8") as fh:
        return json.load(fh).get("reference_corpus") or {}


def check():
    present, missing, optional_missing = [], [], []
    for rel, why in REQUIRED:
        (present if os.path.isfile(os.path.join(REPO, rel)) else missing).append(
            {"path": rel, "why": why})
    for rel, why in OPTIONAL:
        if not os.path.isfile(os.path.join(REPO, rel)):
            optional_missing.append({"path": rel, "why": why})
    n_passages = 0
    p = os.path.join(REPO, "_data", "passage_store", "passages.jsonl")
    if os.path.isfile(p):
        try:
            with io.open(p, encoding="utf-8") as fh:
                n_passages = sum(1 for _ in fh)
        except OSError:
            n_passages = -1
    ready = not missing and n_passages > 0
    return {"ready": ready, "passages": n_passages, "present": present,
            "missing": missing, "optional_missing": optional_missing}


def instructions(status, ref):
    repo = ref.get("repo") or "https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus"
    tag = ref.get("release_tag") or "corpus-v1"
    asset = ref.get("asset_name") or "corpus-pack-v1.tar.gz"
    manifest = ref.get("manifest_path") or "corpus-pack-v1.manifest.json"
    lines = [
        "",
        "语料缺失 / CORPUS MISSING",
        "────────────────────────────────────────────────────────────────",
        "引擎本身不含任何源文本（研讨班全文属第三方版权）。研究要真正跑起来，"
        "必须先安装一份语料。两条路，任选其一：",
        "",
        "A) 安装参考语料包（需要对该私有仓库有读权限）",
        "   %s" % repo,
        "   # 该包为私有：用一个有 repo 读权限的 token",
        "   export GITHUB_TOKEN=<your-token>",
        "   python3 tools/ensure_corpus.py --install --token-env GITHUB_TOKEN",
        "   # 或者手工下载后本地安装：",
        "   python3 tools/ensure_corpus.py --install --pack %s --manifest %s" % (asset, manifest),
        "   # 校验（必须通过，否则启动器会 fail-closed 拒绝研究）",
        "   python3 _scripts/_tools/core_freeze.py --verify",
        "",
        "B) 自备语料（你有权使用的文本）",
        "   docs: CORPUS.md · 快速试跑（公有领域 demo）: docs/DEMO_CORPUS.md",
        "   python3 tools/build_demo_corpus.py . && python3 _scripts/_tools/build_lexical_index.py",
        "   python3 _scripts/inventory_corpus.py --help && python3 _scripts/build.py --help",
        "",
        "无论哪条路：**不要**编造段落、引文或书目字段；语料不足时系统会如实弃权。",
        "────────────────────────────────────────────────────────────────",
    ]
    if status.get("missing"):
        lines.insert(6, "缺失文件 / missing: %s" % ", ".join(
            m["path"] for m in status["missing"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check / install the corpus this engine needs")
    ap.add_argument("--status", action="store_true", default=True)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--print-instructions", action="store_true")
    ap.add_argument("--install", action="store_true", help="verify and install a corpus pack")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--token-env", default=None,
                    help="download the pack from the private release using this env var as token")
    a = ap.parse_args(argv)

    ref = reference()
    if a.install and a.token_env:
        token = os.environ.get(a.token_env)
        if not token:
            print("token env %s is empty" % a.token_env, file=sys.stderr)
            return 3
        d = ref.get("download") or {}
        tag = ref.get("release_tag") or "corpus-v1"
        repo = (ref.get("repo") or "").replace("https://github.com/", "")
        asset_name = ref.get("asset_name") or "corpus-pack-v1.tar.gz"
        # 取 asset id（私有仓库必须走 API 端点）
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/releases/tags/%s" % (repo, tag),
            headers={"Authorization": "Bearer %s" % token,
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            rel = json.loads(r.read().decode("utf-8"))
        assets = [x for x in (rel.get("assets") or []) if x["name"] == asset_name]
        if not assets:
            print("asset %s not found in release %s" % (asset_name, tag), file=sys.stderr)
            return 3
        aid = assets[0]["id"]
        tmp = os.path.join(REPO, asset_name)
        dl = [sys.executable, os.path.join(HERE, "fetch-corpus.py"),
              "--url", "https://api.github.com/repos/%s/releases/assets/%d" % (repo, aid),
              "--token-env", a.token_env, "--pack-out", tmp] if False else None
        # 直接用 fetch-corpus.py 的能力：它已处理跨主机重定向时的 Authorization 保留
        rc = subprocess.call([sys.executable, os.path.join(HERE, "fetch-corpus.py"),
                              "--url", "https://api.github.com/repos/%s/releases/assets/%d" % (repo, aid),
                              "--token-env", a.token_env, "--into", REPO], cwd=REPO)
        status = check()
        print(json.dumps(status, ensure_ascii=False, indent=1) if a.json
              else "installed (fetch exit=%d)" % rc)
        return 0 if status["ready"] else 4

    if a.install:
        if not a.pack:
            print("give --pack (or --token-env to download)", file=sys.stderr)
            return 3
        cmd = [sys.executable, os.path.join(HERE, "fetch-corpus.py"),
               "--pack", a.pack, "--into", REPO]
        if a.manifest:
            cmd += ["--manifest", a.manifest]
        rc = subprocess.call(cmd, cwd=REPO)
        status = check()
        if a.json:
            print(json.dumps(status, ensure_ascii=False, indent=1))
        else:
            print("fetch exit=%d · corpus ready=%s · passages=%d"
                  % (rc, status["ready"], status["passages"]))
        return 0 if (rc == 0 and status["ready"]) else 4

    status = check()
    if a.json:
        status["reference_corpus"] = {"repo": ref.get("repo"), "private": True,
                                      "release": ref.get("release_tag")}
        status["next"] = ("ready" if status["ready"] else "run ensure_corpus.py --print-instructions")
        print(json.dumps(status, ensure_ascii=False, indent=1))
        return 0 if status["ready"] else 3

    if status["ready"]:
        print("corpus READY · %d passages · research can run" % status["passages"])
        if status["optional_missing"]:
            print("optional, missing: %s" % ", ".join(
                m["path"] for m in status["optional_missing"]))
        return 0

    if a.print_instructions or True:
        print(instructions(status, ref))
    return 3


if __name__ == "__main__":
    sys.exit(main())
