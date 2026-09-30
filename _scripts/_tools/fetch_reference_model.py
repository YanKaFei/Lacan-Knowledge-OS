#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_reference_model.py — Phase 3B.1 §11 Reference Parity 的**参考权重**获取

为什么需要它
───────────
§11 要求把本地 ONNX 的结果与「可信参考实现」比对。本机**没有** torch /
sentence-transformers，也**连不上** huggingface.co（DNS 返回不可达的 IPv6，
`hf-mirror.com` 现在 308 跳回 huggingface.co，同样不可达）。

因此在 `.venv-reference/` 里装 PyTorch + sentence-transformers（从 PyPI，可达），
再从 **ModelScope**（可达，实测 200）取上游权重 —— 这样参考实现跑的是**上游官方
权重**，不是「我自己再实现一遍」，§11 的"可信"才成立。

本脚本
──────
1. 从 ModelScope 拉上游模型文件（含 `model.safetensors`）到
   `<HOME>`
2. 逐文件算 sha256，并与本地 `models/<key>/` 的同名文件**比对** ——
   「本地 tokenizer/config 是不是上游那一份」本身就是 parity 证据。
3. 写 `_data/index/vector/REFERENCE_MODEL_MANIFEST.json`（小、可 diff、入 git）。

用法
────
    python3 fetch_reference_model.py --fetch       # 下载 + 比 hash + 写 manifest
    python3 fetch_reference_model.py --verify      # 只校验已有文件与 manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
REF_ROOT = os.path.expanduser("<HOME>")
MANIFEST_OUT = os.path.join(VAULT, "_data", "index", "vector",
                            "REFERENCE_MODEL_MANIFEST.json")

ENDPOINT = "https://www.modelscope.cn/api/v1/models/{repo}/repo?Revision={rev}&FilePath={path}"
REVISION = "master"

REPOS = {
    "minilm": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "mpnet": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
}

# 参考实现要跑起来，这些文件缺一不可（顺序无关）。
# `sentence_bert_config.json` 是 sentence-transformers 自己的长度契约 ——
# **不是** config.json 的 max_position_embeddings。两者确实不同（实测 128 vs 512），
# 这一条是 §11 做下来才发现的，见 RUNTIME_PARITY_REPORT.md。
FILES = [
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
    "model.safetensors",
]


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def local_model_dir(key):
    return os.path.expanduser("<HOME>" % key)


def fetch_one(repo, rel_path, dest, force=False):
    if os.path.isfile(dest) and not force:
        return {"status": "cached", "path": dest}
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = ENDPOINT.format(repo=urllib.parse.quote(repo, safe="/"),
                          rev=REVISION, path=urllib.parse.quote(rel_path, safe="/"))
    # 走 curl：ModelScope 会 302 到 resouces.modelscope.cn，需要跟随重定向。
    tmp = dest + ".part"
    cmd = ["curl", "-sSL", "--fail", "--retry", "3", "--retry-delay", "3",
           "--max-time", "1800", "-o", tmp, url]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        if os.path.exists(tmp):
            os.remove(tmp)
        return {"status": "FAILED", "rel_path": rel_path, "url": url,
                "error": (p.stderr or "").strip()[-400:]}
    os.replace(tmp, dest)
    return {"status": "downloaded", "path": dest}


def cmd_fetch(force=False):
    out = {"schema_version": "reference-model-manifest/v1",
           "purpose": "§11 reference parity 的上游参考权重来源与 hash 锚点",
           "source": {
               "huggingface": "不可达（实测 DNS 只给不可达 IPv6；hf-mirror.com 308 跳回 huggingface.co）",
               "modelscope": "可达（HTTP 200 实测）",
               "endpoint": ENDPOINT,
               "revision": REVISION,
               "note": "本地 models/<key>/ 与上游同名文件逐文件 sha256 比对，结果见 upstream_vs_local。",
           },
           "models": {}}

    for key, repo in REPOS.items():
        dest_dir = os.path.join(REF_ROOT, key)
        entry = {"repo": repo, "revision": REVISION, "dir": dest_dir, "files": {}}
        for rel in FILES:
            dest = os.path.join(dest_dir, rel)
            r = fetch_one(repo, rel, dest, force=force)
            if r["status"] == "FAILED":
                entry["files"][rel] = {"status": "FAILED", "error": r["error"],
                                       "url": r["url"]}
                continue
            h = sha256_file(dest)
            size = os.path.getsize(dest)
            entry["files"][rel] = {
                "status": r["status"],
                "sha256": h,
                "size_bytes": size,
            }
            # 与本地模型目录比对
            lpath = os.path.join(local_model_dir(key), rel)
            if os.path.isfile(lpath):
                lh = sha256_file(lpath)
                entry["files"][rel]["local_sha256"] = lh
                entry["files"][rel]["local_match"] = (lh == h)
            else:
                entry["files"][rel]["local_sha256"] = None
                entry["files"][rel]["local_match"] = "local_file_absent"
        matched = sum(1 for f in entry["files"].values() if f.get("local_match") is True)
        differ = [k for k, f in entry["files"].items() if f.get("local_match") is False]
        failed = [k for k, f in entry["files"].items() if f.get("status") == "FAILED"]
        entry["summary"] = {
            "local_files_matching_upstream": matched,
            "local_files_differing": differ,
            "download_failed": failed,
            "all_downloaded": not failed,
        }
        out["models"][key] = entry
        print("[%s] downloaded=%d matched_local=%d differ=%s failed=%s" % (
            key, sum(1 for f in entry["files"].values()
                     if f.get("status") in ("downloaded", "cached")),
            matched, differ or "-", failed or "-"))

    out["all_downloaded"] = all(m["summary"]["all_downloaded"]
                                for m in out["models"].values())
    os.makedirs(os.path.dirname(MANIFEST_OUT), exist_ok=True)
    with open(MANIFEST_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("[manifest] %s  all_downloaded=%s" % (MANIFEST_OUT, out["all_downloaded"]))
    return out


def cmd_verify():
    if not os.path.isfile(MANIFEST_OUT):
        return {"status": "FAIL", "reason": "REFERENCE_MODEL_MANIFEST.json 不存在"}
    man = json.load(open(MANIFEST_OUT, encoding="utf-8"))
    problems = []
    for key, m in man["models"].items():
        for rel, f in m["files"].items():
            if f.get("status") == "FAILED":
                problems.append("%s/%s 未下载成功" % (key, rel))
                continue
            p = os.path.join(m["dir"], rel)
            if not os.path.isfile(p):
                problems.append("%s/%s 文件缺失" % (key, rel))
                continue
            if sha256_file(p) != f["sha256"]:
                problems.append("%s/%s sha256 不符" % (key, rel))
    return {"status": "PASS" if not problems else "FAIL", "problems": problems}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fetch", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.fetch:
        out = cmd_fetch(force=a.force)
        return 0 if out["all_downloaded"] else 1
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
