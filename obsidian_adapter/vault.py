#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
obsidian_adapter.vault — Vault 检测 + 路径策略 + 原子写入（§4/§5/§22/§23/§28）

路径策略（安全核心）
────────────────────
* 接口**不接受任意路径**：只接受 note_type/title/id，最终路径由 adapter 决定。
* 所有写入先 `resolve()`：拒绝绝对路径、`..`、空段；`realpath` 必须落在 vault 根内
  （同时防 symlink 逃逸）。
* 写入一律 temp + `os.replace`（原子）；事务提交失败即回滚。
"""
from __future__ import annotations

import json
import os
import shutil

from scholarly_api import policy as POL

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_VAULT = os.path.dirname(HERE)

# 产品工作区根的相对位置（在项目 vault 内；策略已登记为 USER_WORKSPACE）
DEFAULT_ROOT_REL = os.path.join("_workspace", "obsidian_vault")

LAYOUT = {
    "research": "Research",
    "passages": "Passages",
    "concepts": "Concepts",
    "seminars": "Seminars",
    "projects": "Projects",
    "sources": "Sources",
    "system": "_System",
}
CANONICAL_PARTITIONS = ["00_System", "01_Sources", "02_Lacan_Seminars", "03_Ecrits",
                        "04_Concepts", "05_Terminology", "06_Clinical", "07_Cases",
                        "08_Topology_Mathemes", "09_Philosophy", "10_Freud",
                        "11_Thinkers", "12_Schools_Debates", "13_Reading_Notes",
                        "14_Synthesis", "15_Questions", "16_Research_Projects"]


class VaultError(RuntimeError):
    pass


def detect(project_vault=PROJECT_VAULT):
    """→ 检测报告（不创建任何东西）。§4：先检测再决定。"""
    has_obsidian = os.path.isdir(os.path.join(project_vault, ".obsidian"))
    partitions = [d for d in CANONICAL_PARTITIONS
                  if os.path.isdir(os.path.join(project_vault, d))]
    return {
        "project_vault": project_vault,
        "is_obsidian_vault": has_obsidian,
        "canonical_partitions_present": partitions,
        "default_workspace_root": os.path.join(project_vault, DEFAULT_ROOT_REL),
        "default_workspace_root_exists": os.path.isdir(
            os.path.join(project_vault, DEFAULT_ROOT_REL)),
        "existing_workspace_dirs": sorted(
            d for d in ("Research", "Concepts", "Seminars", "Passages", "Projects",
                        "Sources", "_System")
            if os.path.isdir(os.path.join(project_vault, d))),
        "env_override": os.environ.get("OBSIDIAN_VAULT_PATH"),
    }


class Vault:
    """一个受管工作区 vault 根（默认 `<project>/_workspace/obsidian_vault`）。"""

    def __init__(self, root=None):
        env = os.environ.get("OBSIDIAN_VAULT_PATH")
        raw = root or env or os.path.join(PROJECT_VAULT, DEFAULT_ROOT_REL)
        raw = os.path.expanduser(str(raw))
        # ⚠️ 相对路径按 **PROJECT_VAULT** 解析（与 scholarly_api.policy 同一套规则），
        #    否则从别的 cwd 调用会落到 cwd 下、被闸门判为 UNKNOWN 而拒绝写入（实测踩过）。
        if not os.path.isabs(raw):
            raw = os.path.join(PROJECT_VAULT, raw)
        self.root = os.path.abspath(raw)
        self.is_project_default = os.path.abspath(self.root) == os.path.abspath(
            os.path.join(PROJECT_VAULT, DEFAULT_ROOT_REL))

    # ── 路径
    def resolve(self, *parts):
        """→ 绝对路径；越界/绝对/`..` 一律拒绝（§22/§23）。"""
        for p in parts:
            s = str(p or "")
            if not s:
                raise VaultError("empty path segment")
            if os.path.isabs(s) or s.startswith("~"):
                raise VaultError("absolute path not allowed: %r" % s)
            if ".." in s.replace("\\", "/").split("/"):
                raise VaultError("path traversal not allowed: %r" % s)
        target = os.path.abspath(os.path.join(self.root, *[str(p) for p in parts]))
        real_root = os.path.realpath(self.root)
        real_target = os.path.realpath(target)
        if real_target != real_root and not real_target.startswith(real_root + os.sep):
            raise VaultError("resolved path escapes vault root: %r" % target)
        return target

    def rel(self, abs_path):
        return os.path.relpath(abs_path, self.root).replace(os.sep, "/")

    # ── 读
    def exists(self, *parts):
        return os.path.isfile(self.resolve(*parts))

    def read(self, *parts):
        p = self.resolve(*parts)
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            return f.read()

    def list_rel(self, sub):
        d = self.resolve(sub)
        if not os.path.isdir(d):
            return []
        return sorted(self.rel(os.path.join(d, f)) for f in os.listdir(d)
                      if f.endswith(".md"))

    # ── 写（闸门 + 原子）
    def write(self, rel_path, text, atomic=True):
        """经 `scholarly_api.policy` 闸门后原子写入。"""
        target = self.resolve(rel_path)
        POL.assert_writable(target)                 # 只允许 USER_WORKSPACE
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if atomic:
            tmp = target + ".tmp-%d" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, target)
        else:
            with open(target, "w", encoding="utf-8") as f:
                f.write(text)
        return target

    def write_raw(self, rel_path, text):
        """底层原子写入（**绕过闸门**）：仅供回滚使用 —— 路径在 stage 时已预检过。
        回滚必须能在「写入器本身正在失败」的情况下工作，所以不能递归调用 write()。"""
        target = self.resolve(rel_path)
        tmp = target + ".tmp-rollback-%d" % os.getpid()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, target)
        return target

    def remove(self, rel_path):
        p = self.resolve(rel_path)
        if os.path.isfile(p):
            os.remove(p)
            return True
        return False

    # ── 事务（§28）
    def transaction(self):
        return VaultTransaction(self)


class VaultTransaction:
    """预检 → 全部写 temp → 原子 rename；任一步失败则回滚已提交项。"""

    def __init__(self, vault):
        self.vault = vault
        self._staged = []
        self._committed = []
        self._backups = {}
        self.rollback_errors = []

    def stage(self, rel_path, text):
        target = self.vault.resolve(rel_path)        # 预检：越界立即失败
        POL.assert_writable(target)
        self._staged.append((rel_path, text))
        return rel_path

    def commit(self):
        try:
            for rel, text in self._staged:
                target = self.vault.resolve(rel)
                if os.path.isfile(target):
                    with open(target, encoding="utf-8") as f:
                        self._backups[rel] = f.read()
                else:
                    self._backups[rel] = None
                self.vault.write(rel, text)
                self._committed.append(rel)
            return [r for r, _ in self._staged]
        except Exception:
            self.rollback()
            raise

    def rollback(self):
        """尽力恢复；失败**必须记录**（不静默）。用 write_raw/remove 避免递归进失败的写入器。"""
        for rel in reversed(self._committed):
            prev = self._backups.get(rel)
            try:
                if prev is None:
                    self.vault.remove(rel)
                else:
                    self.vault.write_raw(rel, prev)
            except Exception as exc:                 # noqa: BLE001
                self.rollback_errors.append({"path": rel, "error": str(exc)[:200]})
        self._committed = []


def reset_workspace_root(vault=None):
    """测试/QA 用：清空并重建工作区根（**只在受管工作区内**）。"""
    v = vault or Vault()
    root = v.root
    if os.path.abspath(root) == os.path.abspath(PROJECT_VAULT):
        raise VaultError("refuse to reset the project vault root")
    if os.path.isdir(root):
        shutil.rmtree(root)
    return root


def read_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
