#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase2_deterministic.py — P0.1 确定性构建（Phase 2）

要求：
  * 默认 `build` **不得**仅因运行时间不同而产生 git diff。
  * 只有显式 `--stamp` 才能刷新 generated_at。
  * 连续执行相同 build 两次，第二次 git diff 必须为空。
  * **不得**简单把核心 evidence artifacts 加进 .gitignore 了事。

做法：默认模式下 generated_at 由**内容哈希**推导（确定性），
内容不变 → 时间戳不变 → 无 diff。`--stamp` 才写真实当前时间。
"""

import hashlib
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
BUILD = os.path.join(VAULT, "_scripts", "build.py")
# deterministic helper 住在 _scripts/_tools/，测试里要用到
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))

# 这些是核心 evidence artifacts，**必须入库**、不得靠 .gitignore 规避 diff
CORE_ARTIFACTS = [
    "_data/corpus_inventory.json",
    "_data/corpus_report.md",
    "_data/corpus_inventory.csv",
    "_data/recoverable_corpus.json",
    "_index/Reports/validation-report.json",
    "_index/Reports/validation-report.md",
]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=VAULT, **kw)


def git(*args):
    return run(["git"] + list(args))


class DeterministicBuild(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.in_repo = git("rev-parse", "--is-inside-work-tree").stdout.strip() == "true"

    def setUp(self):
        if not self.in_repo:
            self.skipTest("不是 git 仓库，无法验证 diff")

    # ---- 1 构建编排入口存在
    def test_00_build_entrypoint_exists(self):
        self.assertTrue(os.path.isfile(BUILD), f"缺 {BUILD}")

    # ---- 2 默认 build 幂等：跑一次不得产生任何内容 diff
    def test_01_rebuild_produces_no_diff(self):
        """核心契约：在**当前树**上跑一次默认 build → 任何被它触碰的文件都不得变内容。

        ⚠️ 为什么不再 `git add -A && git commit`（Phase 4C.1-B §B0）
        ────────────────────────────────────────────────────────────
        旧版为了造一个「已提交的构建结果」基线，直接对**真实仓库**做了
        `git add -A` + `git commit`。后果是每次跑测试都会移动真实 HEAD
        （实测 `49b9e90 → ee0eed4 → 0bee05f → f70402e`），并把工作区里
        任何未提交内容吞进一个名为 `test: deterministic baseline` 的提交。
        **测试不得修改真实仓库历史**（Phase 4C.1-B hard acceptance criterion）。

        新做法（等价，且不改 git 历史）：**连续两次 build 的快照比对**。
          ① 先跑一次 build（让树到达不动点 —— 其它套件可能刚改写过派生文件）
          ② 记录 `git status --porcelain`（只读）+「可能被 build 触碰」文件的 sha256
          ③ 再跑一次同样的 build
          ④ 断言 ② 与 ③ 完全一致（这正是文件开头写的「连跑两次，第二次不得有 diff」）

        这个不变式比「已提交后无 diff」更强：它不要求工作树干净，
        直接证明 **build 是其自身输出的不动点**（内容确定性）。
        `test_02` 另外用导出函数逐字比对时间戳，`test_03` 证明默认模式不取墙上时钟。

        ⚠️ **跑套件期间不得在仓库根目录新建 / 改名 / 删除 `.md`**（实测事故）
        ────────────────────────────────────────────────────────────────
        根目录的 `.md` 是 `root-doc`，会被 `validate_vault.py` 记进
        `validation-report.json` 的 **skipped 清单**。于是「在两次 build 之间
        新建或改名一份根目录报告」= 真实改变了 build 输出 → 本测试红，
        而失败信息若只说「报告文件变了」会非常难定位。
        复现证据（已实测）：根目录加一个 `.md`，报告 sha256
        `ca64808e… → ab1f82ab…`；删掉后逐字节回到 `ca64808e…`。
        现在失败信息会打印**字段级差异**（含 skipped 的增删条目），
        直接指出是哪个根目录文档被动了。跑验收套件时请把手交给脚本：
        期间只读、不写仓库根目录。

        ⚠️ 实测数字：完整 `build.py` 约 **66 秒**。Passage Store 有一条约定的快速路径
        （源 sha256 未变则直接返回已记录 meta，不重写 373MB），
        真实重派生的证据单独记在 `_data/index/FULL_REDERATION.json`。
        """
        # ① 先跑一次 build，让树到达**不动点**（其它套件可能刚改写过派生文件）
        r0 = run([sys.executable, BUILD])
        self.assertEqual(r0.returncode, 0,
                         f"build 失败:\n{r0.stdout[-800:]}\n{r0.stderr[-800:]}")
        # ② 快照 A
        before = self._tree_state()
        # ③ 再跑一次同样的 build
        r = run([sys.executable, BUILD])
        self.assertEqual(r.returncode, 0,
                         f"build 失败:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
        # ④ 快照 B；两次 build 之间不得有任何内容差异
        after = self._tree_state()
        if before != after:
            changed = sorted(set(before["hashes"]) | set(after["hashes"]))
            diff = [rel for rel in changed
                    if before["hashes"].get(rel) != after["hashes"].get(rel)]
            self.fail("连续两次 build 改变了文件内容 —— 构建非确定性:\n"
                      "  status 前: %s\n  status 后: %s\n  changed: %s\n"
                      "  字段级差异（before -> after）:\n%s"
                      % (before["status"][:400], after["status"][:400], diff[:20],
                         "\n".join(self._payload_diff(
                             before.get("payloads") or {}, after.get("payloads") or {}))))

    # 「可能被 build 触碰」的路径前缀（只读 git 查询，不做任何写操作）
    WATCH_PREFIXES = ("_data/", "_index/")

    def _tree_state(self):
        """→ {"status": <git status --porcelain 原文>, "hashes": {rel: sha256}}"""
        st = git("status", "--porcelain").stdout
        tracked = git("ls-files").stdout.split()
        untracked = git("ls-files", "--others", "--exclude-standard").stdout.split()
        rels = sorted({r for r in (tracked + untracked)
                       if r.startswith(self.WATCH_PREFIXES)}
                      | set(CORE_ARTIFACTS))
        hashes = {}
        for rel in rels:
            p = os.path.join(VAULT, rel)
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    hashes[rel] = hashlib.sha256(f.read()).hexdigest()
        # 报告类产物额外留一份**解析后的载荷**：一旦两次 build 的内容不一致，
        # 失败信息必须直接指出**是哪个字段变了**，而不是只报「这两个文件变了」。
        # （实测教训：曾在套件运行期间把一份根目录报告 `mv` 改名，根目录 .md 会进入
        #  validation-report 的 skipped 清单 → build 输出**真实**改变 → 本测试红。
        #  当时只看到「报告文件变了」，定位花了很久。）
        payloads = {}
        for rel in CORE_ARTIFACTS:
            if not hashes.get(rel):
                continue
            p = os.path.join(VAULT, rel)
            try:
                if rel.endswith(".json"):
                    with open(p, encoding="utf-8") as f:
                        payloads[rel] = json.load(f)
            except Exception:  # noqa: BLE001 —— 诊断信息不得让断言本身出错
                pass
        return {"status": st, "hashes": hashes, "payloads": payloads}

    @staticmethod
    def _payload_diff(before, after, limit=6):
        """→ 人类可读的「哪个字段变了」摘要（含 skipped 的增删条目）。"""
        lines = []
        for rel in sorted(set(before) | set(after)):
            b, a = before.get(rel), after.get(rel)
            if b == a:
                continue
            if isinstance(b, dict) and isinstance(a, dict):
                keys = sorted(set(b) | set(a))
                for k in keys:
                    if b.get(k) == a.get(k):
                        continue
                    if k == "skipped" and isinstance(b.get(k), list) \
                            and isinstance(a.get(k), list):
                        rb = {s.get("rel") for s in b[k]}
                        ra = {s.get("rel") for s in a[k]}
                        lines.append("  %s.%s: 新增 %s / 消失 %s"
                                     % (rel, k, sorted(ra - rb)[:limit],
                                        sorted(rb - ra)[:limit]))
                    else:
                        lines.append("  %s.%s: %r -> %r"
                                     % (rel, k,
                                        json.dumps(b.get(k), ensure_ascii=False)[:160],
                                        json.dumps(a.get(k), ensure_ascii=False)[:160]))
                    if len(lines) >= limit:
                        return lines
            else:
                lines.append("  %s: 载荷类型/内容不同" % rel)
        return lines or ["  （载荷相同：差异只在字节层，例如键序）"]

    # ---- 3 generated_at 在默认模式下必须是确定性的（内容哈希推导）
    def test_02_generated_at_is_content_derived(self):
        """同一内容重跑，generated_at 必须逐字相同。"""
        vals = []
        for _ in range(2):
            run([sys.executable, BUILD])
            for rel in ("_data/corpus_inventory.json",
                        "_data/recoverable_corpus.json",
                        "_index/Reports/validation-report.json"):
                p = os.path.join(VAULT, rel)
                with open(p, encoding="utf-8") as f:
                    vals.append((rel, json.load(f).get("generated_at")))
        first = vals[: len(vals) // 2]
        second = vals[len(vals) // 2:]
        self.assertEqual(first, second,
                         f"generated_at 不是内容推导的:\n{first}\n{second}")

    # ---- 4 generated_at 不得是「当前时间」（默认模式）
    def test_03_default_mode_not_wallclock(self):
        """默认生成的 generated_at 不应随墙上时钟变化（连续两次同值即证明）。"""
        run([sys.executable, BUILD])
        p = os.path.join(VAULT, "_data/corpus_inventory.json")
        with open(p, encoding="utf-8") as f:
            a = json.load(f)
        run([sys.executable, BUILD])
        with open(p, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(a["generated_at"], b["generated_at"])
        # 必须留下可审计的痕迹：说明时间戳是怎么来的
        self.assertIn("stamp_mode", a,
                      "产物必须记录 stamp_mode（deterministic / stamped）以便审计")
        self.assertEqual(a["stamp_mode"], "deterministic",
                         "默认模式应为 deterministic")

    # ---- 5 --stamp 才刷新真实时间
    def test_04_stamp_flag_refreshes_timestamp(self):
        run([sys.executable, BUILD])
        p = os.path.join(VAULT, "_data/corpus_inventory.json")
        with open(p, encoding="utf-8") as f:
            before = json.load(f)
        r = run([sys.executable, BUILD, "--stamp"])
        self.assertEqual(r.returncode, 0, f"--stamp 失败:\n{r.stderr[-600:]}")
        with open(p, encoding="utf-8") as f:
            after = json.load(f)
        self.assertEqual(after["stamp_mode"], "stamped",
                         "--stamp 后 stamp_mode 应为 stamped")
        self.assertNotEqual(before["generated_at"], after["generated_at"],
                            "--stamp 应刷新 generated_at")
        # 复原成确定性状态，避免污染后续测试
        run([sys.executable, BUILD])

    # ---- 6 核心 artifacts 不得被 .gitignore 掉（用户明确要求）
    def test_05_core_artifacts_are_tracked_not_ignored(self):
        for rel in CORE_ARTIFACTS:
            with self.subTest(path=rel):
                p = os.path.join(VAULT, rel)
                self.assertTrue(os.path.isfile(p), f"核心产物缺失: {rel}")
                # 必须能被 git 跟踪（未被 ignore）
                r = run(["git", "check-ignore", "-q", rel])
                self.assertNotEqual(r.returncode, 0,
                                    f"{rel} 被 .gitignore 忽略了 —— "
                                    f"用户要求不得靠 ignore 规避 diff")
                r2 = git("ls-files", "--error-unmatch", rel)
                self.assertEqual(r2.returncode, 0,
                                 f"{rel} 未被 git 跟踪")

    # ---- 7 内容变化时 generated_at 必须跟着变（否则就是「假确定性」）
    def test_06_generated_at_changes_with_content(self):
        """确定性 ≠ 冻结：内容变了，generated_at 必须变。"""
        from deterministic import content_timestamp
        a = content_timestamp({"x": 1})
        b = content_timestamp({"x": 2})
        self.assertNotEqual(a, b, "内容不同却得到相同时间戳 —— 实现有误")
        self.assertEqual(a, content_timestamp({"x": 1}),
                         "同内容必须得到同时间戳")


if __name__ == "__main__":
    unittest.main(verbosity=2)
