#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch-corpus.py — 校验并安装一个语料包（corpus pack）。

与 `pack-corpus.py` 配对：语料以**一个可分发的包**流转（私有仓库 Release 资产、
自己的服务器、U 盘…），接收方用本脚本**逐文件校验哈希**后还原到仓库布局，
缺一个文件、错一个字节都拒绝安装（fail closed）。

用法：
    # A. 从本地文件
    python3 tools/fetch-corpus.py --pack corpus-pack-v1.tar.gz \\
        --manifest corpus-pack-v1.manifest.json --into .

    # B. 从 URL（私有仓库 Release 资产的直链、你自己的服务器…）
    python3 tools/fetch-corpus.py --url https://…/corpus-pack-v1.tar.gz \\
        --manifest corpus-pack-v1.manifest.json --into .

    # C. 只检查，不写入
    python3 tools/fetch-corpus.py --pack corpus-pack-v1.tar.gz --manifest … --check

安装后自检：
    python3 _scripts/_tools/core_freeze.py --verify
    python3 _scripts/tools/../inventory_corpus.py --help
    python3 -m workspace_ui.server.cli --port 3090      # → /help 与 /research 可用
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request

SECRET_STOP = ("/etc/", "/usr/", "/System/", "/Library/")
SAFE_PREFIX = ("02_Lacan_Seminars/", "_data/", "_index/")


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


class _KeepAuthRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub 私有资产会 302 到 objects.githubusercontent.com。

    urllib 默认**不**把 Authorization 带到跨主机重定向 —— 实测结果是 404。
    这里显式保留该头，同时仍然只允许 http(s) 目标。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if not newurl.lower().startswith(("http://", "https://")):
            raise SystemExit("refusing redirect to %r" % newurl)
        auth = req.get_header("Authorization")
        if auth:
            new.add_unredirected_header("Authorization", auth)
        return new


def download(url, dest, token=None):
    print("downloading %s" % url)
    req = urllib.request.Request(url)
    # 私有 release 资产走 API 端点 + octet-stream 最稳（浏览器直链在私有库下会 404）
    req.add_header("Accept", "application/octet-stream")
    if token:
        req.add_header("Authorization", "Bearer %s" % token)
    opener = urllib.request.build_opener(_KeepAuthRedirect)
    with opener.open(req, timeout=300) as r, open(dest, "wb") as out:
        total = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            total += len(chunk)
            if total % (25 << 20) < (1 << 20):
                print("  … %.0f MB" % (total / 1048576))
    print("  done: %.1f MB" % (os.path.getsize(dest) / 1048576))


def safe_members(tf):
    """只接受包内相对路径、且落在语料前缀里的成员（防目录穿越 / 防覆盖系统文件）。"""
    out = []
    for m in tf.getmembers():
        if not m.isfile():
            continue
        name = m.name.lstrip("./")
        if name.startswith("/") or ".." in name.split("/"):
            raise SystemExit("refusing unsafe path in pack: %r" % m.name)
        if not name.startswith(SAFE_PREFIX):
            raise SystemExit("refusing unexpected path in pack: %r" % m.name)
        if any(s in ("/" + name) for s in SECRET_STOP):
            raise SystemExit("refusing path: %r" % name)
        out.append((m, name))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify and install a Lacan Knowledge OS corpus pack")
    ap.add_argument("--pack", default=None, help="path to corpus-pack-*.tar.gz")
    ap.add_argument("--url", default=None, help="download the pack from this URL instead")
    ap.add_argument("--token-env", default=None,
                    help="environment variable holding a bearer token (for private releases)")
    ap.add_argument("--manifest", default=None, help="manifest json to verify against")
    ap.add_argument("--into", default=".", help="repository root to install into")
    ap.add_argument("--check", action="store_true", help="verify only, do not install")
    ap.add_argument("--force", action="store_true", help="install even if target files exist")
    a = ap.parse_args(argv)

    if not a.pack and not a.url:
        ap.error("give --pack or --url")

    tmp = None
    pack = a.pack
    if a.url:
        tmp = tempfile.mkdtemp(prefix="corpus-pack-")
        pack = os.path.join(tmp, os.path.basename(a.url.split("?")[0]) or "corpus-pack.tar.gz")
        token = os.environ.get(a.token_env) if a.token_env else None
        download(a.url, pack, token)

    manifest = None
    if a.manifest:
        with io.open(a.manifest, encoding="utf-8") as fh:
            manifest = json.load(fh)
        got = sha256(pack)
        want = (manifest.get("pack") or {}).get("sha256")
        if want and got != want:
            print("PACK_HASH_MISMATCH\n  expected %s\n  got      %s" % (want, got), file=sys.stderr)
            return 3
        print("pack sha256 ok: %s…" % got[:24])

    expect = {}
    if manifest:
        for f in manifest.get("files") or []:
            expect[f["path"]] = f["sha256"]

    root = os.path.abspath(a.into)
    print("installing into %s" % root)
    installed = verified = 0
    with tarfile.open(pack, "r:gz") as tf:
        members = safe_members(tf)
        if a.check:
            for m, name in members:
                src = tf.extractfile(m)
                h = hashlib.sha256()
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
                if expect and h.hexdigest() != expect.get(name):
                    print("HASH_MISMATCH %s" % name, file=sys.stderr)
                    return 3
                verified += 1
            print("checked %d files — all match the manifest" % verified)
            missing = sorted(set(expect) - {n for _m, n in members})
            if missing:
                print("manifest lists %d files missing from the pack: %s"
                      % (len(missing), missing[:5]), file=sys.stderr)
                return 3
            shutil.rmtree(tmp, ignore_errors=True) if tmp else None
            return 0
        # ① **先预检冲突，再写任何字节**：安装要么整体生效、要么整体不动。
        #    实测缺陷：旧实现边写边跳过已存在文件 → 干净副本（自带参考语料的
        #    INDEX_MANIFEST / _concept_meta / _build_meta）会装出"半个参考 + 半个 demo"
        #    的混合语料，冻结必然漂移且原因难查。
        conflicts, identical = [], []
        for m, name in members:
            dest = os.path.join(root, name)
            if not os.path.exists(dest) or a.force:
                continue
            if expect and sha256(dest) == expect.get(name):
                identical.append(name)
            else:
                conflicts.append(name)
        if conflicts:
            print("REFUSING TO MIX CORPUSES: %d file(s) already exist with different content:"
                  % len(conflicts), file=sys.stderr)
            for name in conflicts[:8]:
                print("  - %s" % name, file=sys.stderr)
            print("  这些文件属于**另一份语料**（或引擎随包分发的参考语料元数据）。"
                  "安装一个语料包要么整体生效、要么整体不动 —— 混合语料会让冻结漂移且原因难查。",
                  file=sys.stderr)
            print("  确认要覆盖它们时重跑并加 --force："
                  "python3 tools/fetch-corpus.py --pack … --manifest … --into . --force",
                  file=sys.stderr)
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            return 3
        for name in identical:
            verified += 1
            print("already installed (identical): %s" % name)
        # ② 安装
        for m, name in members:
            dest = os.path.join(root, name)
            if not a.force and os.path.exists(dest):
                continue          # 预检已判定与包内一致
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            src = tf.extractfile(m)
            h = hashlib.sha256()
            with open(dest, "wb") as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
                    out.write(chunk)
            if expect:
                if h.hexdigest() != expect.get(name):
                    os.unlink(dest)
                    print("HASH_MISMATCH %s (removed)" % name, file=sys.stderr)
                    return 3
                verified += 1
            installed += 1
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    print("installed %d files (%d hash-verified)" % (installed, verified))
    kind = (manifest or {}).get("pack_kind") or "reference"
    profile = (manifest or {}).get("corpus_profile") or "reference"
    if kind == "demo" or profile != "reference":
        print("corpus_profile = %s（%s）" % (profile, kind))
        print("  ⚠️ 该语料**没有人工验收证据**：冻结状态是 CORPUS_HUMAN_REVIEW_NOT_AVAILABLE，")
        print("     不是 SCHOLARLY_CORE_READY；答案不携带人工验收背书。")
        notice = (manifest or {}).get("rights_notice")
        if notice:
            print("  " + notice.replace("\n", "\n  "))
    print("\nnext:")
    print("  python3 _scripts/_tools/core_freeze.py --verify")
    print("  python3 tools/ensure_corpus.py --status")
    print("  python3 -m workspace_ui.server.cli --port 3090    # → http://127.0.0.1:3090/help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
