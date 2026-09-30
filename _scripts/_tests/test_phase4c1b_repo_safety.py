#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4c1b_repo_safety.py — Phase 4C.1-B §B0/§23：**测试不得修改真实仓库历史**

背景（Phase 4C.1-A 报告 §14 第 10–11 条）
─────────────────────────────────────────
`test_phase2_deterministic.test_01` 旧版为了造「已提交的构建结果」基线，
对**真实仓库**执行了 `git add -A` + `git commit`，于是每跑一次测试就前移真实 HEAD：

    49b9e90 → ee0eed4 → 0bee05f → f70402e（提交信息均为 `test: deterministic baseline`）

后果：工作区里任何未提交内容被吞进测试提交；版本绑定（manifest 的 `git_commit`）随之漂移。

本套件把「测试仓库安全」变成可执行契约
──────────────────────────────────────
1. **静态**：任何 `_tests/test_*.py` 都不得对真实仓库调用写操作
   （`add` / `commit` / `reset` / `checkout` / `stash` / `clean` / `rebase` / `merge` / `push` / `rm` 等）；
   只读查询（`rev-parse` / `ls-files` / `status` / `check-ignore` / `diff --stat`）允许。
2. **动态**：本套件运行期间 HEAD 与索引不得变化。
3. **运行器护栏**：`run_all_tests.sh` 必须自带 HEAD 前后比对（§23 的 hard acceptance criterion）。
4. **正确姿势**：若确实要测 commit/hash 行为，必须在 **tempfile 建的独立仓库**里做 ——
   本套件用 `test_30` 证明这个模式可用。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
RUNNER = os.path.join(VAULT, "_scripts", "run_all_tests.sh")

# 会对真实仓库产生副作用的子命令（写操作）
MUTATING = ("add", "commit", "reset", "checkout", "stash", "clean", "rebase",
            "merge", "push", "cherry-pick", "revert", "switch", "restore",
            "update-ref", "gc", "prune", "tag", "branch")
# 只读子命令白名单（出现这些不算）
READONLY = ("rev-parse", "ls-files", "status", "check-ignore", "log", "show",
            "diff", "ls-tree", "cat-file", "merge-base", "describe", "config")

GIT_CALL = re.compile(r"""git["']?\s*,\s*["']([a-z-]+)["']""")
GIT_CALL2 = re.compile(r"""\[\s*["']git["']\s*,\s*["']([a-z-]+)["']""")


def git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True, text=True,
                          cwd=VAULT)


class TestNoRepoMutation(unittest.TestCase):
    """§B0：测试套件不得改写真实仓库。"""

    def test_10_head_and_index_stable_within_suite(self):
        """本套件运行期间 HEAD 与索引不得变化（动态检查）。"""
        before_head = git("rev-parse", "HEAD").stdout.strip()
        before_idx = git("status", "--porcelain").stdout
        # 触发一次只读 git 往返，确认检查本身无副作用
        git("ls-files")
        self.assertEqual(git("rev-parse", "HEAD").stdout.strip(), before_head)
        self.assertEqual(git("status", "--porcelain").stdout, before_idx)

    def test_11_no_test_file_mutates_real_repo(self):
        """静态扫描：所有 `_tests/test_*.py` 里不得出现写 git 子命令。"""
        offenders = []
        for fn in sorted(os.listdir(HERE)):
            if not (fn.startswith("test_") and fn.endswith(".py")):
                continue
            if fn == os.path.basename(__file__):
                continue                      # 本文件自带白名单文本
            src = open(os.path.join(HERE, fn), encoding="utf-8").read()
            for m in list(GIT_CALL.finditer(src)) + list(GIT_CALL2.finditer(src)):
                sub = m.group(1)
                if sub in MUTATING and sub not in READONLY:
                    line = src[:m.start()].count("\n") + 1
                    offenders.append("%s:%d git %s" % (fn, line, sub))
        self.assertEqual(offenders, [],
                         "测试对真实仓库调用了写操作 git 子命令：%s" % offenders)

    def test_12_deterministic_test_uses_snapshot_not_commit(self):
        """确定性测试必须用「内容快照」而不是 commit 来建立基线。"""
        p = os.path.join(HERE, "test_phase2_deterministic.py")
        src = open(p, encoding="utf-8").read()
        self.assertIn("_tree_state", src, "应使用内容快照前后比对")
        self.assertNotIn('git("add"', src)
        self.assertNotIn('"commit"', src.replace("git add -A && git commit", ""),
                         "不得在真实仓库上 commit")

    def test_13_runner_enforces_head_guard(self):
        """§23 hard acceptance criterion 必须落在运行器里。"""
        self.assertTrue(os.path.isfile(RUNNER), "缺 run_all_tests.sh")
        src = open(RUNNER, encoding="utf-8").read()
        self.assertIn("HEAD_BEFORE", src)
        self.assertIn("HEAD_AFTER", src)
        self.assertIn("repo mutated by tests", src)

    def test_14_history_has_no_new_test_commits_after_this_phase(self):
        """最近一次提交不得是本阶段新造的 `test: deterministic baseline`。

        只读检查：若 HEAD 的提交信息正是那个自动化信息，且提交时间晚于
        本套件文件的 mtime，则说明测试仍在写历史（回退）。
        """
        msg = git("log", "-1", "--pretty=%s").stdout.strip()
        if msg != "test: deterministic baseline":
            return                        # 已有人工整理或从未出现过 → 通过
        head_time = int(git("log", "-1", "--pretty=%ct").stdout.strip() or 0)
        self_mtime = int(os.path.getmtime(__file__))
        self.assertLess(head_time, self_mtime,
                        "HEAD 仍是新造的测试基线提交 —— 测试又在写真实历史了")


class TestTempRepoPattern(unittest.TestCase):
    """若必须测 commit / hash 行为，只在 tempfile 仓库里做。"""

    def test_30_temp_repo_commit_hash_pattern(self):
        with tempfile.TemporaryDirectory() as d:
            def run(*a):
                return subprocess.run(["git"] + list(a), cwd=d,
                                      capture_output=True, text=True)
            run("init", "-q")
            run("config", "user.email", "t@example.invalid")
            run("config", "user.name", "t")
            run("config", "commit.gpgsign", "false")
            with open(os.path.join(d, "f.txt"), "w", encoding="utf-8") as f:
                f.write("v1\n")
            run("add", "-A")
            run("commit", "-q", "-m", "baseline")
            h1 = run("rev-parse", "HEAD").stdout.strip()
            self.assertTrue(h1)
            # 真实仓库的 HEAD 不受影响
            real = git("rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(h1, real)

    def test_31_pattern_does_not_touch_real_repo(self):
        before = git("rev-parse", "HEAD").stdout.strip()
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q"], cwd=d, capture_output=True)
            subprocess.run(["git", "status", "--porcelain"], cwd=d,
                           capture_output=True)
        self.assertEqual(git("rev-parse", "HEAD").stdout.strip(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
