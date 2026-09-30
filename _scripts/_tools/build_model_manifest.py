#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_model_manifest.py — Phase 3B.1 §12 Model Manifest

为什么要有它
───────────
语义 benchmark 的结论只在「模型文件没被换过」时才成立。因此每个模型目录里
**决定行为的每个文件**都要有 sha256 锚点，且 manifest 必须能被 program 校验
（不是一句声明）。

第一版只记了 config.json / tokenizer.json / sentencepiece / 1_Pooling / onnx，
**漏了 `sentence_bert_config.json`** —— 而它正是决定截断长度 128 的那个文件
（见 §11 的发现）。漏记它就是漏掉一个能改变所有向量与全部指标的参数。
v2 起把长度契约涉及的四个文件全部纳入，并把生效长度写进 manifest。

用法
────
    python3 build_model_manifest.py --build
    python3 build_model_manifest.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(VAULT, "MODEL_MANIFEST.json")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
REF_MANIFEST = os.path.join(VECDIR, "REFERENCE_MODEL_MANIFEST.json")

sys.path.insert(0, HERE)

MODEL_ROOTS = {
    "minilm": os.path.expanduser("<HOME>"),
    "mpnet": os.path.expanduser("<HOME>"),
}

# 决定行为的文件 —— 少一个，manifest 就少一个能改变全部指标的锚点。
# required=False 的是「有则记录、无不算缺陷」：config_sentence_transformers.json
# 只存 prompts / similarity_fn_name，sentence-transformers 缺它照样跑
# （实测本地 mpnet 就没有，而参考目录里有 —— 如实记录，不假装一致）。
BEHAVIOUR_FILES = [
    ("config.json", True),
    ("config_sentence_transformers.json", False),
    ("modules.json", True),
    ("sentence_bert_config.json", True),
    ("1_Pooling/config.json", True),
    ("tokenizer.json", True),
    ("tokenizer_config.json", True),
    ("special_tokens_map.json", True),
    ("sentencepiece.bpe.model", True),
    ("onnx/model.onnx", True),
]
BEHAVIOUR_FILE_NAMES = [f for f, _ in BEHAVIOUR_FILES]


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def cmd_build():
    import embedding_provider as ep
    ref = {}
    if os.path.isfile(REF_MANIFEST):
        ref = json.load(open(REF_MANIFEST, encoding="utf-8")).get("models", {})

    out = {
        "schema_version": "model-manifest/v2",
        "purpose": ("§12：语义 benchmark 必须引用本 manifest 的 hash —— "
                    "防止模型文件被替换而 benchmark 仍沿用旧结果。"),
        "hash_algorithm": "sha256",
        "files_that_change_behaviour": [
            {"path": f, "required": req} for f, req in BEHAVIOUR_FILES],
        "usage_rule": ("跑 semantic benchmark / parity 前先 `--verify`；"
                       "任一 hash 不符则结果作废。"),
        "models": {},
    }
    for key, root in MODEL_ROOTS.items():
        lc = ep.model_length_contract(root)
        files = {}
        for rel, required in BEHAVIOUR_FILES:
            p = os.path.join(root, rel)
            if not os.path.isfile(p):
                files[rel] = {"present": False, "required": required}
                continue
            files[rel] = {
                "present": True,
                "required": required,
                "sha256": sha256_file(p),
                "size_bytes": os.path.getsize(p),
            }
            up = ref.get(key, {}).get("files", {}).get(rel)
            if up and up.get("sha256"):
                files[rel]["upstream_sha256"] = up["sha256"]
                files[rel]["upstream_match"] = (up["sha256"] == files[rel]["sha256"])
        meta = ep.ONNX_REGISTRY[key]
        out["models"][key] = {
            "model_directory": root,
            "model": meta["model"],
            "architecture": meta["architecture"],
            "dimension": meta["dimensions"],
            "pooling": meta["pooling"],
            "onnx_bytes": os.path.getsize(os.path.join(root, "onnx", "model.onnx")),
            "length_contract": lc,
            "effective_max_length": lc["effective_max_length"],
            "files": files,
        }
        missing = [k for k, v in files.items()
                   if not v.get("present") and v.get("required")]
        mism = [k for k, v in files.items() if v.get("upstream_match") is False]
        print("[%s] files=%d missing=%s upstream_mismatch=%s max_len=%s" % (
            key, len(files), missing or "-", mism or "-", lc["effective_max_length"]))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("[manifest] %s" % OUT)
    return out


def cmd_verify():
    if not os.path.isfile(OUT):
        return {"status": "FAIL", "reason": "MODEL_MANIFEST.json 不存在"}
    man = json.load(open(OUT, encoding="utf-8"))
    problems = []
    checked = 0
    for key, m in man["models"].items():
        root = m["model_directory"]
        for rel, f in m["files"].items():
            if not f.get("present"):
                if f.get("required", True):
                    problems.append("%s/%s 文件缺失（required）" % (key, rel))
                continue
            p = os.path.join(root, rel)
            if not os.path.isfile(p):
                problems.append("%s/%s 文件不存在" % (key, rel))
                continue
            h = sha256_file(p)
            checked += 1
            if h != f["sha256"]:
                problems.append("model_manifest_hash_mismatch: %s/%s" % (key, rel))
    return {"status": "PASS" if not problems else "FAIL",
            "files_checked": checked, "problems": problems}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.build:
        cmd_build()
        return 0
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
