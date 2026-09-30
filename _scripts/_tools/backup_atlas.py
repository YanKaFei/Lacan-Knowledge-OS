#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_atlas.py — P0：为 `.lacan-build/atlas/` 建立可验证的独立备份（Phase 2）

为什么这是 Phase 2 的第一件事
──────────────────────────────
`atlas/segments.jsonl` 里的 82,578 段中译，其**上游源目录已经消失**
（`<HOME>`）。也就是说这个文件是那批中译的
**唯一幸存副本**，而它从未被备份过。在动任何 corpus 转换之前必须先保住它 ——
转换可以重做，数据丢了不可逆。

本脚本做什么
────────────
1. 只读扫描 atlas/，为每个文件记录 path / sha256 / size / mtime
2. 复制出一份**独立本机备份**（不在源目录内部）
3. 生成一份**压缩 archive**（tar.gz）
4. 写出 `_data/BACKUP_MANIFEST.json`
5. 统计并记录 segment_count / language_count（zh / fr / total）
6. 全程不修改源目录

校验
────
`--verify` 会独立证明三件事，任何一项不符即非零退出：
  * 中文 segment 数 = 82,578
  * 法文 segment 数 = 166,527
  * 总数          = 249,105
若与基线不一致：**停止后续 ingest 并报告**（退出码 2）。

用法
────
    python3 backup_atlas.py                 # 建立备份 + manifest
    python3 backup_atlas.py --verify        # 只校验已有备份
    python3 backup_atlas.py --verify --json
    python3 backup_atlas.py --dest <DIR>    # 指定备份根目录
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
from datetime import datetime, timezone

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SRC = os.path.expanduser("<HOME>")
DEFAULT_DEST = os.path.expanduser("~/Lacan-OS-Backups")
MANIFEST_PATH = os.path.join(VAULT, "_data", "BACKUP_MANIFEST.json")

SCHEMA = "backup-manifest/v1"
CHUNK = 1 << 20

# 用户给定的权威基线。不一致 → 停止 ingest 并报告。
ZH_BASELINE = 82578
FR_BASELINE = 166527
TOTAL_BASELINE = 249105

ZH_FILE = "segments.jsonl"
FR_FILE = "french_staferla.jsonl"


# ------------------------------------------------------------------ 工具
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def count_jsonl(path, expect_field=None):
    """逐行统计 jsonl 的记录数与坏行数（只读）。"""
    n = 0
    bad = 0
    if not os.path.isfile(path):
        return n, bad
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
                n += 1
            except Exception:
                bad += 1
    return n, bad


def freeze_mtimes(src):
    """在任何读取之前把 mtime 固定下来，用于证明备份过程没改动源。"""
    out = {}
    for fn in sorted(os.listdir(src)):
        p = os.path.join(src, fn)
        if os.path.isfile(p):
            st = os.stat(p)
            out[fn] = {"mtime": st.st_mtime, "size": st.st_size}
    return out


# ------------------------------------------------------------------ 建立
def create_backup(src, dest, stamp=None):
    if not os.path.isdir(src):
        print(f"[FATAL] 源目录不存在: {src}", file=sys.stderr)
        return None

    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    copy_dir = os.path.join(dest, "atlas-copy-" + stamp)
    archive_path = os.path.join(dest, "atlas-" + stamp + ".tar.gz")

    os.makedirs(dest, exist_ok=True)

    # ① 先冻结 mtime（在复制/读取之前）
    frozen = freeze_mtimes(src)

    # ② 复制出独立副本
    if os.path.exists(copy_dir):
        print(f"[warn] 副本目录已存在，复用: {copy_dir}", file=sys.stderr)
    else:
        shutil.copytree(src, copy_dir)
    print(f"[backup] 独立副本 -> {copy_dir}", file=sys.stderr)

    # ③ 压缩 archive
    with tarfile.open(archive_path, "w:gz") as tf:
        for fn in sorted(os.listdir(copy_dir)):
            p = os.path.join(copy_dir, fn)
            if os.path.isfile(p):
                tf.add(p, arcname=os.path.join("atlas", fn))
    print(f"[backup] 压缩 archive -> {archive_path}", file=sys.stderr)

    # ④ 逐文件 sha256（对**源**计算，并确认副本一致）
    files = []
    for fn in sorted(os.listdir(src)):
        p = os.path.join(src, fn)
        if not os.path.isfile(p):
            continue
        h_src = sha256_file(p)
        h_copy = sha256_file(os.path.join(copy_dir, fn))
        h_arch = None
        if h_src != h_copy:
            print(f"[FATAL] 副本与源不一致: {fn}", file=sys.stderr)
            return None
        files.append({
            "path": fn,
            "sha256": h_src,
            "size": frozen[fn]["size"],
            "mtime": frozen[fn]["mtime"],
            "copy_sha256_matches": True,
        })

    # ⑤ 段数统计
    zh, zh_bad = count_jsonl(os.path.join(src, ZH_FILE))
    fr, fr_bad = count_jsonl(os.path.join(src, FR_FILE))
    total = zh + fr

    counts = {"zh": zh, "fr": fr, "total": total}
    baseline_ok = (zh == ZH_BASELINE and fr == FR_BASELINE and total == TOTAL_BASELINE)

    manifest = {
        "schema": SCHEMA,
        "backup_created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_root": src,
        "source_read_only": True,
        "source_untouched": True,
        "source_frozen_mtimes": {k: v["mtime"] for k, v in frozen.items()},
        "backup_copies": [{
            "path": copy_dir,
            "kind": "directory",
            "independent": True,
            "sha256_verified": True,
        }],
        "archive": {
            "path": archive_path,
            "kind": "tar.gz",
            "sha256": sha256_file(archive_path),
            "size": os.path.getsize(archive_path),
        },
        "files": files,
        "totals": {
            "file_count": len(files),
            "bytes": sum(f["size"] for f in files),
            "segment_count": counts,
            "language_count": {"zh": zh, "fr": fr, "languages": 2},
            "malformed_lines": {"zh": zh_bad, "fr": fr_bad},
        },
        "baseline": {
            "zh": ZH_BASELINE,
            "fr": FR_BASELINE,
            "total": TOTAL_BASELINE,
            "matches": baseline_ok,
        },
    }

    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[backup] manifest -> {MANIFEST_PATH}", file=sys.stderr)

    return manifest


# ------------------------------------------------------------------ 校验
def verify(manifest_path=MANIFEST_PATH, as_json=False):
    problems = []
    if not os.path.isfile(manifest_path):
        problems.append(f"缺 manifest: {manifest_path}")
        return problems, None
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)

    src = m["source_root"]

    # 1) 源文件 sha256 与 manifest 一致
    for fe in m["files"]:
        p = os.path.join(src, fe["path"])
        if not os.path.isfile(p):
            problems.append(f"源文件缺失: {fe['path']}")
            continue
        if sha256_file(p) != fe["sha256"]:
            problems.append(f"源文件 sha256 变化: {fe['path']}")

    # 2) 每个备份副本都存在且内容一致
    copies = m.get("backup_copies") or []
    if not copies:
        problems.append("manifest 未记录备份副本")
    for c in copies:
        cp = c["path"]
        if not os.path.isdir(cp):
            problems.append(f"备份副本不存在: {cp}")
            continue
        real_src, real_cp = os.path.realpath(src), os.path.realpath(cp)
        if real_cp == real_src or real_cp.startswith(real_src + os.sep):
            problems.append(f"备份副本位于源目录内部: {cp}")
        for fe in m["files"]:
            cand = os.path.join(cp, fe["path"])
            if not os.path.isfile(cand):
                problems.append(f"备份副本缺文件: {fe['path']}")
            elif sha256_file(cand) != fe["sha256"]:
                problems.append(f"备份副本 sha256 不符: {fe['path']}")

    # 3) 压缩 archive 可打开且含关键文件
    arch = m.get("archive") or {}
    ap = arch.get("path")
    if not ap or not os.path.isfile(ap):
        problems.append(f"压缩 archive 不存在: {ap}")
    else:
        try:
            with tarfile.open(ap) as tf:
                names = tf.getnames()
            for need in (ZH_FILE, FR_FILE):
                if not any(n.endswith(need) for n in names):
                    problems.append(f"archive 缺 {need}")
        except Exception as e:
            problems.append(f"archive 无法打开: {type(e).__name__}: {e}")
        if arch.get("sha256") and sha256_file(ap) != arch["sha256"]:
            problems.append("archive sha256 与 manifest 不符")

    # 4) 段数三项基线（核心）
    sc = (m.get("totals") or {}).get("segment_count") or {}
    zh, fr, total = sc.get("zh"), sc.get("fr"), sc.get("total")
    if zh != ZH_BASELINE:
        problems.append(f"中文 segment 数 {zh} != {ZH_BASELINE}")
    if fr != FR_BASELINE:
        problems.append(f"法文 segment 数 {fr} != {FR_BASELINE}")
    if total != TOTAL_BASELINE:
        problems.append(f"总 segment 数 {total} != {TOTAL_BASELINE}")
    if isinstance(zh, int) and isinstance(fr, int) and zh + fr != (total or 0):
        problems.append(f"zh + fr != total ({zh} + {fr} != {total})")

    # 5) 源目录未被修改
    for fe in m["files"]:
        p = os.path.join(src, fe["path"])
        if os.path.isfile(p):
            got = os.stat(p).st_mtime
            if abs(got - float(fe["mtime"])) > 1e-6:
                problems.append(f"源文件 mtime 被改动: {fe['path']}")

    result = {
        "schema": "backup-verify/v1",
        "manifest": manifest_path,
        "source_root": src,
        "segment_count": {"zh": zh, "fr": fr, "total": total},
        "baseline": {"zh": ZH_BASELINE, "fr": FR_BASELINE, "total": TOTAL_BASELINE},
        "copies": [c["path"] for c in copies],
        "archive": ap,
        "problems": problems,
        "ok": not problems,
    }
    return problems, result


def main():
    ap = argparse.ArgumentParser(description="atlas 唯一副本备份与校验（Phase 2 P0）")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--verify", action="store_true", help="只校验已有备份")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stamp", default=None, help="备份时间戳（默认当前 UTC）")
    args = ap.parse_args()

    if args.verify:
        problems, result = verify(as_json=args.json)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            sc = result["segment_count"] if result else {}
            print("=" * 66)
            print("备份校验（atlas 唯一副本）")
            print("=" * 66)
            print(f"源目录:   {result['source_root'] if result else args.src}")
            print(f"备份副本: {result['copies'] if result else '—'}")
            print(f"archive:  {result['archive'] if result else '—'}")
            print()
            print("段数证明:")
            for k, label, base in (("zh", "中文", ZH_BASELINE),
                                   ("fr", "法文", FR_BASELINE),
                                   ("total", "合计", TOTAL_BASELINE)):
                got = (sc or {}).get(k)
                mark = "✓" if got == base else "✗"
                print(f"  {mark} {label}: {got}  (基线 {base})")
            print()
            if problems:
                print(f"发现 {len(problems)} 个问题:")
                for p in problems:
                    print(f"  ✗ {p}")
                print()
                print("结论: 备份不可信 —— 停止后续 ingest 并报告")
            else:
                print("结论: 备份可验证，三项段数全部吻合")
        if problems:
            # 与基线不符 → 退出码 2（明确区别于一般失败）
            sc = (result or {}).get("segment_count") or {}
            if (sc.get("zh") != ZH_BASELINE or sc.get("fr") != FR_BASELINE
                    or sc.get("total") != TOTAL_BASELINE):
                return 2
            return 1
        return 0

    m = create_backup(args.src, args.dest, args.stamp)
    if m is None:
        return 1
    print()
    problems, _ = verify()
    if problems:
        print(f"[FATAL] 备份建好后自校验失败:", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1
    print("[backup] 完成并自校验通过", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
