#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack-corpus.py — 把本地语料库打成**一个可分发的、可校验的**语料包。

为什么需要它（而不是直接 git push 语料）：

  * 语料是**他人作品**（拉康研讨班文本：Staferla 转录站 / 瑟伊版印刷本抽取 /
    社区中译项目）。公开发布 = 再分发受版权保护的作品；
  * 但"下载了系统却不能用"是真问题。语料包让语料可以走**任何你控制的渠道**
    （私有仓库的 Release 资产、自己的服务器、U 盘），并且**可校验**：
    接收方拿到包后能用 `fetch-corpus.py` 验证哈希、缺一不可地还原。

因此：**包是渠道无关的，分发范围由你决定。**

包含什么（默认）：
    02_Lacan_Seminars/**                研讨班全文（md，带 frontmatter）
    _data/passage_store/*.jsonl         段落库本体（raw/normalized_text）
    _data/render_normalization.jsonl    渲染规范化表
    _data/terminology_bridge.jsonl      术语桥
    _data/ontology/**                   canonical 本体（实体/关系/证据）
    _data/entities/**                   人物/个案登记
    _data/bibliography/**               书目登记（不含 workspace 私有部分）
    _index/passage_store.sqlite         段落库 SQLite（即装即用）
    _data/index/lexical.sqlite          词法索引（即装即用）

可选（`--with-vector`，+365 MB）：
    _data/index/vector/full_index_minilm.npy + 清单     向量索引

用法：
    python3 tools/pack-corpus.py --out /tmp/corpus-pack                 # 生成
    python3 tools/pack-corpus.py --out /tmp/corpus-pack --with-vector   # 含向量
    python3 tools/pack-corpus.py --out /tmp/corpus-pack --split 1800    # 分卷（MB）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import time

SCHEMA = "lacan-corpus-pack/v1"

DEFAULT_PATHS = [
    "02_Lacan_Seminars",
    "_data/passage_store",
    "_data/render_normalization.jsonl",
    "_data/terminology_bridge.jsonl",
    "_data/ontology",
    "_data/entities",
    "_data/bibliography",
    "_index/passage_store.sqlite",
    "_data/index/lexical.sqlite",
    # ── 冻结校验读的"数据版本"输入：**必须随语料一起走**，否则装完 core_freeze 会判 drift，
    #    启动器 fail-closed 直接拒绝研究（实测踩过：只装了语料却缺这三份清单）。
    "_data/corpus_inventory.json",
    "_data/index/INDEX_MANIFEST.json",
    "_data/index/vector/VECTOR_INDEX_MANIFEST.json",
    # 冻结里属于 scholarly_semantic 的**人工评审与 gold 记录**：它们也是数据，
    # 不随语料走的话，装完 core_freeze 会判 SEMANTIC_DRIFT（实测踩过）。
    # 内容是评分/评审意见/gold 判定与 task id（抽样 205 条长字符串，0 条命中语料正文）。
    "_data/eval/research_human_review.jsonl",
    "_data/eval/research_human_review_round2.jsonl",
    "_data/eval/human_adjudication_queue.jsonl",
    "_data/eval/scholarly_readiness_gate_v1.json",
    "_data/eval/round2_taxonomy_v1.json",
    "_data/eval/round2_review_schema.json",
    "_data/eval/gold_v2",
    "_data/eval/phase4c1d2_frozen_identity.json",
]
# 向量索引本体（.npy，+365 MB）。清单始终随包走（冻结校验需要），本体可选：
#   --with-vector → 语义检索也能即装即用；不给则退回词法检索（界面会显示 dense 不可用）
VECTOR_PATHS = ["_data/index/vector"]
# 明确**不**进包：私有工作区、缓存、模型权重
EXCLUDE_DIR = {"__pycache__", ".git", "_workspace", "wheelhouse", ".venv-embedding"}
EXCLUDE_SUFFIX = (".pyc", ".DS_Store", ".tmp", ".lock")


CODE_PATH_RE = re.compile(r"""["']((?:_data|_index)/[A-Za-z0-9_./\-]+\.(?:json|jsonl|csv|sqlite|npy|txt|md))["']""")
CODE_SCAN_DIRS = ("scholarly_api", "mcp_server", "browse_api", "workspace_ui",
                  "export_system", "bibliography", "project_api", "obsidian_adapter",
                  "_scripts")


def referenced_data_files(vault, max_mb=16, skip=()):
    """引擎代码里以字面量引用到的 `_data/**`、`_index/**` 文件。

    为什么必须自动收集：漏一个就是"下载完跑不起来"。实测踩过两轮 ——
    先是 `_data/index/alias_index.jsonl`，后是 `_data/eval/gold_v2/*`
    与冻结校验读的清单。手工维护的清单必然漂移，所以从代码引用反推。
    """
    found = {}
    for d in CODE_SCAN_DIRS:
        for root, dirs, files in os.walk(os.path.join(vault, d)):
            dirs[:] = [x for x in dirs if x not in EXCLUDE_DIR]
            for fn in files:
                if not fn.endswith((".py", ".mjs", ".js")):
                    continue
                p = os.path.join(root, fn)
                try:
                    text = io.open(p, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                for m in CODE_PATH_RE.finditer(text):
                    rel = m.group(1).lstrip("./")
                    if rel in skip:
                        continue
                    fp = os.path.join(vault, rel)
                    if not os.path.isfile(fp):
                        continue
                    if os.path.getsize(fp) > max_mb * 1048576:
                        continue          # 大产物（如向量索引）另行决定
                    found[rel] = fp
    return found


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(vault, paths):
    out = []
    for rel in paths:
        p = os.path.join(vault, rel)
        if not os.path.exists(p):
            continue
        if os.path.isfile(p):
            out.append((rel, p, os.path.getsize(p)))
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR]
            for fn in files:
                if fn.endswith(EXCLUDE_SUFFIX):
                    continue
                fp = os.path.join(root, fn)
                r = os.path.relpath(fp, vault)
                try:
                    out.append((r, fp, os.path.getsize(fp)))
                except OSError:
                    pass
    out.sort(key=lambda t: t[0])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pack the local corpus into one verifiable archive")
    ap.add_argument("--vault", default=None, help="repository root (default: parent of tools/)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--with-vector", action="store_true", help="also include the vector index (+365 MB)")
    ap.add_argument("--name", default="corpus-pack-v1")
    ap.add_argument("--split", type=int, default=0,
                    help="split into volumes of N megabytes (0 = single file)")
    a = ap.parse_args(argv)

    vault = a.vault or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = list(DEFAULT_PATHS) + (VECTOR_PATHS if a.with_vector else [])
    files = collect(vault, paths)
    # 再把代码引用到、但不在上面清单里的数据文件补进来（缺一个就少一个功能）
    have = {rel for rel, _p, _s in files}
    extra = {rel: fp for rel, fp in referenced_data_files(vault).items()
             if rel not in have and not rel.startswith(tuple(p + "/" for p in VECTOR_PATHS))}
    files += [(rel, fp, os.path.getsize(fp)) for rel, fp in extra.items()]
    files.sort(key=lambda t: t[0])
    if extra:
        print("auto-added %d engine-referenced data files (%.1f MB)"
              % (len(extra), sum(os.path.getsize(p) for p in extra.values()) / 1048576))
    if not files:
        print("no corpus files found under %s" % vault, file=sys.stderr)
        return 2

    os.makedirs(a.out, exist_ok=True)
    archive = os.path.join(a.out, a.name + ".tar.gz")
    total = sum(sz for _r, _p, sz in files)
    print("packing %d files (%.1f MB uncompressed) → %s" % (len(files), total / 1048576, archive))

    t0 = time.time()
    with tarfile.open(archive, "w:gz", compresslevel=6) as tf:
        for rel, fp, _sz in files:
            tf.add(fp, arcname=rel)
    pack_bytes = os.path.getsize(archive)
    print("packed in %.1fs → %.1f MB (%.0f%% of raw)"
          % (time.time() - t0, pack_bytes / 1048576, 100.0 * pack_bytes / max(total, 1)))

    volumes = []
    if a.split:
        limit = a.split * 1024 * 1024
        with open(archive, "rb") as fh:
            i = 0
            while True:
                chunk = fh.read(limit)
                if not chunk:
                    break
                part = "%s.tar.gz.part%02d" % (os.path.join(a.out, a.name), i)
                with open(part, "wb") as out:
                    out.write(chunk)
                volumes.append({"path": os.path.basename(part), "bytes": len(chunk),
                                "sha256": sha256(part)})
                i += 1
        print("split into %d volumes of ≤%d MB" % (len(volumes), a.split))

    manifest = {
        "schema_version": SCHEMA,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pack": {"path": os.path.basename(archive), "bytes": pack_bytes,
                 "sha256": sha256(archive)},
        "volumes": volumes,
        "counts": {
            "files": len(files),
            "raw_bytes": total,
            "seminars": sum(1 for r, _p, _s in files if r.startswith("02_Lacan_Seminars/")),
            "passages": sum(1 for r, _p, _s in files if r.startswith("_data/passage_store/")),
        },
        "includes_vector": bool(a.with_vector),
        "rights_notice": (
            "This pack contains third-party copyrighted texts (Lacan seminar transcriptions, "
            "a print-edition extraction, and a community translation). It is NOT for public "
            "redistribution. Whoever receives it must have the right to use those texts. "
            "See NOTICE and CORPUS.md in the engine repository."
        ),
        "files": [{"path": r, "bytes": s, "sha256": sha256(p)} for r, p, s in files],
    }
    mpath = os.path.join(a.out, a.name + ".manifest.json")
    with io.open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print("manifest → %s (%d entries)" % (mpath, len(manifest["files"])))
    print("pack sha256: %s" % manifest["pack"]["sha256"][:32])
    return 0


if __name__ == "__main__":
    sys.exit(main())
