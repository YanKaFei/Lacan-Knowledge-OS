#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_public_edition.py — 从私有研究库里切出**可公开发布的引擎版**。

为什么需要它（这一步不是可选的）：
    私有库里**包含受版权保护的语料**（Lacan 研讨班原文/译本 1,979 个文件、
    以及 152 MB 的 passage 文本 JSONL）。把它们推到公开仓库等于再分发他人作品。
    因此公开发布版只包含**引擎 + 契约 + 文档 + 测试**，语料由使用者自备（CORPUS.md）。

做法：
    1. **白名单**（只复制明确列出的目录/文件），而不是"排除已知的大文件"；
    2. 复制后再跑一遍**黑名单断言**（任何命中即失败退出，不产出交付物）；
    3. `--verify`：语料泄漏扫描（从私有库抽 N-gram 反查公开树）、密钥扫描、
       绝对路径扫描、体积/文件数门禁。

用法：
    python3 _scripts/_tools/build_public_edition.py --out /tmp/lacan-os-public
    python3 _scripts/_tools/build_public_edition.py --verify-only /tmp/lacan-os-public
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))

# ── 这些目录**整体**属于语料 / 个人研究 / 本地环境：一个字节都不公开
DENY_DIRS = {
    ".git", ".obsidian", ".venv-embedding", "_attachments", "_index", "_workspace",
    "wheelhouse", "__pycache__", ".pytest_cache",
    "00_System", "01_Sources", "02_Lacan_Seminars", "03_Ecrits", "04_Concepts",
    "05_Terminology", "06_Clinical", "07_Cases", "08_Topology_Mathemes",
    "09_Philosophy", "10_Freud", "11_Thinkers", "12_Schools_Debates",
    "13_Reading_Notes", "14_Synthesis", "15_Questions", "16_Research_Projects",
}
# ── 语料文本 / 派生大产物：按后缀与路径拒绝
DENY_SUFFIX = (".sqlite", ".sqlite-wal", ".sqlite-shm", ".npy", ".npz", ".so", ".dylib",
               ".zip", ".whl", ".pyc", ".png", ".jpg", ".jpeg", ".webp", ".pdf",
               ".DS_Store")
DENY_REL = (
    re.compile(r"^_data/passage_store/.*\.jsonl$"),
    re.compile(r"^_data/(render_normalization|terminology_bridge|corpus_inventory)\.jsonl$"),
    re.compile(r"^_data/ontology/.*\.jsonl$"),
    re.compile(r"^_data/eval/.*\.jsonl$"),
    re.compile(r"^_data/eval/research_tasks_v1\.jsonl$"),
    re.compile(r"^_data/index/vector/.*\.jsonl$"),
    re.compile(r"^_data/bibliography/registry\.jsonl$"),
    re.compile(r".*/passage_realizations\.jsonl$"),
    re.compile(r".*/passage_witnesses\.jsonl$"),
)
# ── 白名单：引擎包 + 工具链 + 契约 + 文档
INCLUDE_DIRS = ("scholarly_api", "mcp_server", "browse_api", "export_system",
                "bibliography", "project_api", "obsidian_adapter", "workspace_ui",
                "integrations", "_scripts", "_data")
INCLUDE_ROOT_FILES = ("AGENTS.md", ".gitignore", "package.json", "pnpm-workspace.yaml",
                      "entity_browse_api.py")
# _data 下**只**放契约/清单/模式，不放任何语料或语料派生文本
DATA_ALLOW = (
    re.compile(r"^_data/core_freeze/.*\.json$"),
    re.compile(r"^_data/mcp/.*\.json$"),
    re.compile(r"^_data/index/[^/]*MANIFEST[^/]*\.json$"),
    re.compile(r"^_data/index/[^/]*manifest[^/]*\.json$"),
    re.compile(r"^_data/passage_store/[^/]*_meta\.json$"),
    re.compile(r"^_data/passage_store/[^/]*meta\.json$"),
    re.compile(r"^_data/eval/.*\.schema\.json$"),
    re.compile(r"^_data/eval/.*manifest.*\.json$"),
    re.compile(r"^_data/eval/.*_meta\.json$"),
    re.compile(r"^_data/eval/READONLY.*\.json$"),
    re.compile(r"^_data/daily_use/help/.*\.json$"),
    re.compile(r"^_data/daily_use/i18n/catalog\.json$"),
    re.compile(r"^_data/daily_use/i18n/(static_keys|manual_keys|input_strings|translations_zh)\.json$"),
    re.compile(r"^_data/daily_use/daily_use_gate_v[123]\.json$"),
    re.compile(r"^_data/schemas/.*\.json$"),
    re.compile(r"^_data/ontology/[^/]*/[^/]*schema[^/]*\.json$"),
    re.compile(r"^_data/[A-Z_]+\.json$"),
)

# 公开版收录的文档（面向使用者/架构/集成；不含内部阶段交付报告）
DOCS_KEEP = (
    "ARCHITECTURE.md", "ALIGNMENT_MODEL.md", "CLAIM_MODEL.md", "CLAIM_CITATION_MODEL.md",
    "ENTITY_MODEL.md", "PASSAGE_MODEL.md", "WITNESS_MODEL.md", "SOURCE_PROVENANCE.md",
    "TRANSLATION_MODEL.md", "TERMINOLOGY_BRIDGE.md", "TOPICALITY_MODEL.md",
    "RELATION_MODEL.md", "KNOWLEDGE_SCHEMA.md", "QUERY_MODEL.md",
    "QUERY_ROUTING_POLICY.md", "RETRIEVAL_ARCHITECTURE.md", "HYBRID_RETRIEVAL.md",
    "LEXICAL_INDEX.md", "VECTOR_INDEX.md", "EMBEDDING_PROVIDER.md",
    "INGESTION_PIPELINE.md", "EVIDENCE_BUNDLE.md", "EVIDENCE_SUFFICIENCY.md",
    "EVIDENCE_SUFFICIENCY_V2.md", "RESEARCH_ANSWER_CONTRACT.md",
    "RESEARCH_TASK_MODEL.md", "RESEARCH_EVALUATION_METHOD.md",
    "RESEARCH_FAILURE_TAXONOMY.md", "MCP_ARCHITECTURE.md", "MCP_TOOL_CONTRACTS.md",
    "MCP_DSH_INTEGRATION.md", "LACANIAN_SEMANTIC_GUARD.md", "USER_GUIDE.md",
    "DAILY_USE_GUIDE.md", "DEVELOPER_AUDIT_GUIDE.md", "OFFLINE_RUNTIME_GUIDE.md",
    "HUMAN_REVIEW_GUIDE.md", "ADJUDICATED_GOLD_GUIDE.md",
    "HELP_SYSTEM_ARCHITECTURE.md", "HELP_TASK_COMPLETION_REPORT.md",
    "P5D-005-UX-AUDIT.md", "P5D-005-LLM-UX-REPRODUCTION.md",
    "LACAN_KNOWLEDGE_OS_POSITIONING.md", "SCHOLARLY_REGRESSION_SPEC_V1.md",
    "RUNTIME_GATES_REPORT.md", "HARD_GATES_REPORT.md", "ROADMAP.md",
)
# 允许命中的"看起来像密钥"的文件（它们**定义**了密钥模式用于断言，本身不含真密钥）
SECRET_ALLOW = (
    "_scripts/_tests/test_llm_ux.py",
    "_scripts/_tests/test_phase4e_ccr0001_wiring.py",
    "_scripts/_tests/test_phase4c1d_llm_integration.py",
    "_scripts/_tools/build_public_edition.py",
    "_scripts/_tools/daily_use_acceptance.py",
    "_scripts/_tools/phase4e_secret_audit.py",
    "_scripts/_tools/build_public_edition.py",
)
# 同理：本工具需要写出"/Users/…"的**模式**用于扫描，因此跳过对它的路径扫描
PATH_SCAN_ALLOW = ("_scripts/_tools/build_public_edition.py",)

SECRET_PATTERNS = (
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"\bsk-[A-Za-z0-9]{24,}\b",
    r"AIza[0-9A-Za-z_\-]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"DSH_SYNTHESIS_API_KEY\s*[:=]\s*\S",
    r"Authorization:\s*Bearer\s+\S",
)

TEXT_SUFFIX = (".md", ".py", ".js", ".json", ".yml", ".yaml", ".toml", ".sh", ".css",
               ".html", ".txt", ".jsonl", ".tsv", ".csv", ".command")

# 需要在公开版里**改写**的绝对路径（不泄露本机用户名/目录结构）
_U = "/" + "Users" + "/"          # 运行时拼接：本文件里不出现字面量绝对路径
PATH_REWRITES = (
    (re.compile(re.escape(VAULT)), "<REPO>"),
    (re.compile(_U + r"[^\s\"'`)\]]+"), "<HOME>"),
    (re.compile(r"~/Desktop/[^\s\"'`)\]]+"), "<HOME>"),
    (re.compile("创造" + "一切可能"), "<WORKSPACE>"),
)
SANITIZE_SKIP = ("_scripts/_tools/build_public_edition.py",)


def _denied(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in DENY_DIRS for p in parts):
        return True
    if rel.endswith(DENY_SUFFIX):
        return True
    return any(rx.match(rel) for rx in DENY_REL)


def _data_allowed(rel: str) -> bool:
    return any(rx.match(rel) for rx in DATA_ALLOW)


def _copy_tree(src, dst, rel, stats):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in DENY_DIRS and not d.startswith("__pycache__")]
        for fn in files:
            p = os.path.join(root, fn)
            r = os.path.relpath(p, VAULT)
            if _denied(r):
                stats["denied"] += 1
                continue
            if r.startswith("_data/") and not _data_allowed(r):
                stats["denied"] += 1
                continue
            out = os.path.join(dst, r)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(p, out)
            stats["copied"] += 1
            stats["bytes"] += os.path.getsize(out)


def _sanitize(dst, stats):
    """把本机绝对路径改写成占位符（公开仓库不该泄露用户名/私有目录）。"""
    for root, dirs, files in os.walk(dst):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            if not fn.endswith(TEXT_SUFFIX):
                continue
            p = os.path.join(root, fn)
            if os.path.relpath(p, dst) in SANITIZE_SKIP:
                continue
            try:
                with io.open(p, encoding="utf-8") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            new = text
            for rx, repl in PATH_REWRITES:
                new = rx.sub(repl, new)
            if new != text:
                with io.open(p, "w", encoding="utf-8") as fh:
                    fh.write(new)
                stats["sanitized"] += 1


def _iter_text(dst):
    for root, dirs, files in os.walk(dst):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            if fn.endswith(TEXT_SUFFIX):
                yield os.path.join(root, fn)


def _corpus_ngrams(n=6, size=60):
    """从私有语料里抽 N 段**高辨识度**文本（用于反查公开版是否泄漏）。"""
    picks = []
    sem = os.path.join(VAULT, "02_Lacan_Seminars")
    files = []
    for root, _d, fs in os.walk(sem):
        for fn in fs:
            if fn.endswith(".md"):
                files.append(os.path.join(root, fn))
    random.Random(20260930).shuffle(files)
    for p in files:
        try:
            with io.open(p, encoding="utf-8") as fh:
                body = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        body = re.sub(r"(?s)^---.*?---", "", body)          # 去掉 frontmatter
        body = re.sub(r"\s+", " ", body).strip()
        if len(body) > 400:
            start = len(body) // 3
            picks.append(body[start:start + size])
        if len(picks) >= n:
            break
    rl = os.path.join(VAULT, "_data", "passage_store", "passage_realizations.jsonl")
    if os.path.isfile(rl):
        with io.open(rl, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i % 40000 == 7:
                    try:
                        text = (json.loads(line) or {}).get("text") or ""
                    except ValueError:
                        continue
                    text = re.sub(r"\s+", " ", text).strip()
                    if len(text) > 400:
                        picks.append(text[100:100 + size])
                if len(picks) >= n * 2:
                    break
    return picks


def verify(dst, stats=None):
    problems, info = [], {}
    files = [os.path.join(r, f) for r, _d, fs in os.walk(dst) for f in fs]
    info["files"] = len(files)
    info["bytes"] = sum(os.path.getsize(p) for p in files)
    info["mb"] = round(info["bytes"] / 1048576, 1)
    # ① 路径黑名单
    bad_paths = [os.path.relpath(p, dst) for p in files
                 if _denied(os.path.relpath(p, dst))]
    if bad_paths:
        problems.append("denied paths present: %s" % bad_paths[:5])
    # ② 单文件体积
    big = [(os.path.relpath(p, dst), os.path.getsize(p)) for p in files
           if os.path.getsize(p) > 2 * 1024 * 1024]
    if big:
        problems.append("files > 2MB: %s" % big[:5])
    # ③ 语料 N-gram 反查
    leaks = []
    grams = _corpus_ngrams()
    info["ngram_probes"] = len(grams)
    for p in _iter_text(dst):
        try:
            with io.open(p, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for g in grams:
            if g and g in text:
                leaks.append((os.path.relpath(p, dst), g[:40]))
    if leaks:
        problems.append("corpus text leak: %s" % leaks[:3])
    # ④ 密钥扫描
    secret_hits = []
    for p in _iter_text(dst):
        try:
            with io.open(p, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        rel = os.path.relpath(p, dst)
        if rel in SECRET_ALLOW:
            continue
        for pat in SECRET_PATTERNS:
            m = re.search(pat, text)
            if m:
                secret_hits.append((rel, pat[:24]))
    if secret_hits:
        problems.append("possible secrets: %s" % secret_hits[:5])
    # ⑤ 绝对路径扫描
    path_hits = []
    for p in _iter_text(dst):
        try:
            with io.open(p, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        rel = os.path.relpath(p, dst)
        if rel in PATH_SCAN_ALLOW:
            continue
        if (_U in text) or ("创造" + "一切可能") in text:
            path_hits.append(rel)
    if path_hits:
        problems.append("local absolute paths: %s" % path_hits[:5])
    info["problems"] = problems
    info["ok"] = not problems
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description="build the public (corpus-free) edition")
    ap.add_argument("--out", default="/tmp/lacan-os-public")
    ap.add_argument("--verify-only", default=None)
    a = ap.parse_args(argv)
    if a.verify_only:
        info = verify(a.verify_only)
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 0 if info["ok"] else 1
    dst = a.out
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    stats = {"copied": 0, "denied": 0, "bytes": 0, "sanitized": 0}
    for d in INCLUDE_DIRS:
        src = os.path.join(VAULT, d)
        if os.path.isdir(src):
            _copy_tree(src, dst, d, stats)
    for fn in INCLUDE_ROOT_FILES:
        p = os.path.join(VAULT, fn)
        if os.path.isfile(p) and not _denied(fn):
            shutil.copy2(p, os.path.join(dst, fn))
            stats["copied"] += 1
    # 顶层文档：**白名单**（内部阶段报告/交付证据留在私有库：它们引用语料与私有运维细节）
    os.makedirs(os.path.join(dst, "docs"), exist_ok=True)
    for fn in DOCS_KEEP:
        src = os.path.join(VAULT, fn)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dst, "docs", fn))
            stats["copied"] += 1
        else:
            stats.setdefault("missing_docs", []).append(fn)
    # 公开版专属文件（README 六语种、LICENSE/NOTICE、DSH bundle…）由 _publish/ 覆盖层提供，
    # 这样"公开版"完全可由脚本复现，而不是在输出目录里手工维护。
    pub = os.path.join(VAULT, "_publish")
    if os.path.isdir(pub):
        for root, _d, files in os.walk(pub):
            for fn in files:
                src = os.path.join(root, fn)
                rel = os.path.relpath(src, pub)
                out = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(src, out)
                stats["published"] = stats.get("published", 0) + 1
    _sanitize(dst, stats)
    info = verify(dst, stats)
    info["stats"] = stats
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0 if info["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
