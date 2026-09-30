#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase2_backup.py — P0：唯一副本备份完整性（Phase 2）

这是 Phase 2 最优先的一条。`.lacan-build/atlas/segments.jsonl` 是 82,578 段中译的
**唯一幸存副本**（上游源目录已消失）。在动任何 corpus 转换之前，必须有可验证的备份。

先写测试、看它红，再写 backup_atlas.py 让它绿。
"""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(VAULT, "_scripts", "_tools", "backup_atlas.py")
BACKUP_ROOT = os.path.expanduser("~/Lacan-OS-Backups")
MANIFEST = os.path.join(VAULT, "_data", "BACKUP_MANIFEST.json")
ATLAS = os.path.expanduser("<HOME>")

# 用户给定的权威基线 —— 不一致就必须停下来报告，不得继续 ingest
ZH_BASELINE = 82578
FR_BASELINE = 166527
TOTAL_BASELINE = 249105


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class BackupIntegrity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(ATLAS):
            cls.skip_all = True
            return
        cls.skip_all = False
        # 执行备份校验模式（只校验已有备份，不重新备份）
        cls.proc = subprocess.run(
            [sys.executable, SCRIPT, "--verify"],
            capture_output=True, text=True, cwd=VAULT)

    def setUp(self):
        if getattr(self, "skip_all", False):
            self.skipTest(f"atlas 不在（{ATLAS}）")

    # ---- 1 备份脚本存在且可运行
    def test_00_backup_script_runs(self):
        self.assertTrue(os.path.isfile(SCRIPT), f"缺 {SCRIPT}")
        self.assertEqual(self.proc.returncode, 0,
                         f"备份校验失败:\n{self.proc.stdout[-800:]}\n{self.proc.stderr[-800:]}")

    # ---- 2 manifest 存在且结构完整
    def test_01_manifest_exists_with_required_fields(self):
        self.assertTrue(os.path.isfile(MANIFEST), f"缺 {MANIFEST}")
        with open(MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        for k in ("backup_created_at", "source_root", "backup_copies",
                  "totals", "files"):
            with self.subTest(field=k):
                self.assertIn(k, m, f"manifest 缺字段 {k}")
        # 每个文件条目必须含 path/sha256/size/mtime
        for fe in m["files"]:
            for k in ("path", "sha256", "size", "mtime"):
                with self.subTest(file=fe.get("path"), field=k):
                    self.assertIn(k, fe)
        # 必须有 segment_count 与 language_count
        self.assertIn("segment_count", m["totals"])
        self.assertIn("language_count", m["totals"])

    # ---- 3 备份副本存在且为独立目录
    def test_02_independent_copy_exists(self):
        with open(MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        copies = m["backup_copies"]
        self.assertTrue(copies, "manifest 未记录任何备份副本")
        for c in copies:
            with self.subTest(copy=c.get("path")):
                self.assertIn("path", c)
                self.assertTrue(os.path.exists(c["path"]),
                                f"备份副本不存在: {c['path']}")
                real_src = os.path.realpath(ATLAS)
                real_bak = os.path.realpath(c["path"])
                self.assertNotEqual(real_src, real_bak, "备份不能是源目录本身")
                self.assertFalse(real_bak.startswith(real_src + os.sep),
                                 "备份不能位于源目录内部")
                # 必须是独立的本机备份（可跨设备，但必须是另一个路径）
                self.assertTrue(c.get("independent") is True,
                                "备份条目必须声明 independent=true")

    # ---- 4 压缩 archive 存在且可打开
    def test_03_compressed_archive_valid(self):
        with open(MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        arch = m.get("archive") or {}
        self.assertIn("path", arch, "manifest 未记录压缩 archive")
        self.assertTrue(os.path.isfile(arch["path"]),
                        f"archive 不存在: {arch.get('path')}")
        self.assertTrue(tarfile.is_tarfile(arch["path"]),
                        "archive 不是合法 tar")
        with tarfile.open(arch["path"]) as tf:
            names = tf.getnames()
        self.assertTrue(any("segments.jsonl" in n for n in names),
                        "archive 里没有 segments.jsonl")
        self.assertTrue(any("french_staferla.jsonl" in n for n in names),
                        "archive 里没有 french_staferla.jsonl")

    # ---- 5 备份内容 sha256 与 manifest 一致（核心：备份真的等于源）
    def test_04_backup_hashes_match_manifest(self):
        with open(MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        copies = [c["path"] for c in m["backup_copies"]]
        for fe in m["files"]:
            rel = fe["path"]
            with self.subTest(file=rel):
                src = os.path.join(ATLAS, rel)
                self.assertTrue(os.path.isfile(src), f"源文件缺失: {rel}")
                self.assertEqual(sha256_file(src), fe["sha256"],
                                 f"{rel} 的源 sha256 与 manifest 不符")
                # 至少一个副本里该文件必须存在且 hash 相同
                found = False
                for cp in copies:
                    cand = os.path.join(cp, rel)
                    if os.path.isfile(cand):
                        self.assertEqual(sha256_file(cand), fe["sha256"],
                                         f"备份副本里的 {rel} 与 manifest 不符")
                        found = True
                        break
                self.assertTrue(found, f"{rel} 在任何备份副本里都找不到")

    # ---- 6 段数三项基线（用户给定；不符必须失败）
    def test_05_segment_counts_match_baseline(self):
        with open(MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        sc = m["totals"]["segment_count"]
        # 允许键名略有差异，但必须能取到 zh / fr / total
        zh = sc.get("zh") or sc.get("zh_translation")
        fr = sc.get("fr") or sc.get("fr_transcription")
        total = sc.get("total")
        self.assertEqual(zh, ZH_BASELINE, f"中文段数 {zh} != {ZH_BASELINE}")
        self.assertEqual(fr, FR_BASELINE, f"法文段数 {fr} != {FR_BASELINE}")
        self.assertEqual(total, TOTAL_BASELINE, f"总数 {total} != {TOTAL_BASELINE}")
        self.assertEqual(zh + fr, total, "zh + fr 必须等于 total")

    # ---- 7 源目录未被修改
    def test_06_source_untouched_during_backup(self):
        with open(MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        for fe in m["files"]:
            src = os.path.join(ATLAS, fe["path"])
            with self.subTest(file=fe["path"]):
                self.assertEqual(int(os.stat(src).st_mtime),
                                 int(float(fe["mtime"])) if not isinstance(fe["mtime"], (int, float))
                                 else int(fe["mtime"]),
                                 f"{fe['path']} 的 mtime 变了 —— 备份过程不得修改源")

    # ---- 8 备份校验命令能独立证明三项数字
    def test_07_verify_command_proves_counts(self):
        out = self.proc.stdout + self.proc.stderr
        for needle in ("82578", "166527", "249105"):
            with self.subTest(needle=needle):
                self.assertIn(needle, out.replace(",", ""),
                              f"校验输出未证明数字 {needle}")

    # ---- 9 源目录所有文件都必须进 manifest（不能只备份两个大文件）
    def test_08_manifest_covers_all_atlas_files(self):
        actual = sorted(
            f for f in os.listdir(ATLAS)
            if os.path.isfile(os.path.join(ATLAS, f))
        )
        with open(MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        listed = sorted(fe["path"] for fe in m["files"])
        self.assertEqual(listed, actual,
                         "manifest 的文件清单与 atlas 实际内容不一致")


if __name__ == "__main__":
    unittest.main(verbosity=2)
