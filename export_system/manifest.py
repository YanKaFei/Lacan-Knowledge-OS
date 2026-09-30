#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.manifest — Bundle manifest 生成与校验（4D.6 §15/§16/§36/§48）

manifest 是 bundle 的**机器可验证**契约：文件清单 + 逐文件哈希 + 来源身份 +
citation/passage 计数 + exporter/schema 版本。

`verify_bundle(dir)` 检查（§16）：
    manifest 存在 · 文件齐全 · 哈希匹配 · citation 引用可解析 ·
    passage 引用可解析 · 来源 snapshot 身份匹配
→ VERIFIED / MODIFIED / BROKEN
"""
from __future__ import annotations

import json
import os

from .model import (SCHEMA_BUNDLE_MANIFEST, ExportError, sha256_bytes, sha256_file,
                    validate)

HASH_ALGORITHM = "sha256"
MANIFEST_NAME = "manifest.json"


def build_manifest(doc, files, *, created_at, bundle_hash=None, zip_name=None,
                   citations=0, passages=0):
    """`files` = [(relpath, bytes)]。"""
    entries = []
    for rel, blob in files:
        entries.append({"path": rel, "bytes": len(blob),
                        "hash": sha256_bytes(blob if isinstance(blob, bytes)
                                             else blob.encode("utf-8"))})
    entries.sort(key=lambda e: e["path"])
    man = {
        "schema_version": SCHEMA_BUNDLE_MANIFEST,
        "export_id": doc.get("export_id"),
        "created_at": created_at,
        "exporter_version": doc.get("exporter_version"),
        "source_type": doc.get("source_type"),
        "source_id": doc.get("source_id"),
        "source_snapshot_hash": doc.get("source_snapshot_hash"),
        "source_answer_hash": doc.get("source_answer_hash"),
        "export_payload_hash": doc.get("export_payload_hash"),
        "content_hash": doc.get("content_hash"),
        "core_freeze_version": doc.get("core_freeze_version"),
        "product_interface_version": doc.get("product_interface_version"),
        "snapshot_integrity": doc.get("snapshot_integrity"),
        "export_options": doc.get("export_options") or {},
        "file_count": len(entries),
        "files": entries,
        "hash_algorithm": HASH_ALGORITHM,
        "citation_count": citations,
        "passage_count": passages,
        "bundle_hash": bundle_hash,
        "zip": zip_name,
    }
    return man


def bundle_hash(manifest):
    """bundle 身份 = 规范化 manifest（去掉 bundle_hash 自身与 zip 名）的哈希。"""
    from .model import _canon                                              # noqa: PLC0415
    m = {k: v for k, v in manifest.items() if k not in ("bundle_hash", "zip")}
    return sha256_bytes(_canon(m).encode("utf-8"))


def verify_bundle(path, *, expect_source_id=None):
    """→ {status, problems[], manifest}。status ∈ VERIFIED / MODIFIED / BROKEN。"""
    problems = []
    if not os.path.isdir(path):
        return {"status": "BROKEN", "problems": ["bundle directory missing"],
                "manifest": None}
    mpath = os.path.join(path, MANIFEST_NAME)
    if not os.path.isfile(mpath):
        return {"status": "BROKEN", "problems": ["manifest.json missing"],
                "manifest": None}
    with open(mpath, encoding="utf-8") as f:
        try:
            man = json.load(f)
        except Exception as exc:                                          # noqa: BLE001
            return {"status": "BROKEN", "problems": ["manifest not JSON: %s" % exc],
                    "manifest": None}
    try:
        validate(man, SCHEMA_BUNDLE_MANIFEST)
    except ExportError as exc:
        problems.append("manifest schema: %s" % exc.detail)

    listed = {e["path"] for e in man.get("files") or []}
    for e in man.get("files") or []:
        p = os.path.join(path, e["path"])
        if not os.path.isfile(p):
            problems.append("missing file: %s" % e["path"])
            continue
        if sha256_file(p) != e.get("hash"):
            problems.append("hash mismatch: %s" % e["path"])
    for root, _dirs, files in os.walk(path):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), path).replace(os.sep, "/")
            if rel == MANIFEST_NAME or rel.endswith(".zip"):
                continue
            if rel not in listed:
                problems.append("unlisted file: %s" % rel)
    if man.get("file_count") != len(man.get("files") or []):
        problems.append("file_count mismatch")
    if man.get("bundle_hash") and man["bundle_hash"] != bundle_hash(man):
        problems.append("bundle_hash does not match manifest content")
    if expect_source_id and man.get("source_id") != expect_source_id:
        problems.append("source identity mismatch: %s != %s"
                        % (man.get("source_id"), expect_source_id))

    # citation / passage 引用必须可解析（§16）
    cit_path = os.path.join(path, "citations", "citations.json")
    if os.path.isfile(cit_path):
        with open(cit_path, encoding="utf-8") as f:
            cits = json.load(f)
        for rec in (cits.get("citations") or []):
            pid = rec.get("passage_id")
            if not pid:
                problems.append("citation without passage_id")
                continue
            try:
                import browse_api as B                                    # noqa: PLC0415
                if B.get_passage_view(pid) is None:
                    problems.append("citation passage not resolvable: %s" % pid)
            except Exception as exc:                                      # noqa: BLE001
                problems.append("passage store unavailable: %s" % exc)
    prov_path = os.path.join(path, "provenance", "provenance.json")
    if not os.path.isfile(prov_path):
        problems.append("provenance/provenance.json missing")

    status = "VERIFIED" if not problems else (
        "BROKEN" if any("missing" in p or "not resolvable" in p or "schema" in p
                        for p in problems) else "MODIFIED")
    return {"status": status, "problems": problems, "manifest": man}
