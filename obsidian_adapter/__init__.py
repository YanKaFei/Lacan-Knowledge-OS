#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
obsidian_adapter — Phase 4D.3：Obsidian 导出适配层（产品层）

    Frozen Scholarly Core → Validated Research Result → Research Workspace
        → obsidian_adapter → USER WORKSPACE / OBSIDIAN VAULT

硬边界
──────
* Obsidian ≠ Scholarly Core：**只写 USER_WORKSPACE**（`_workspace/**`），
  绝不写 corpus / passage store / ontology / Gold / Human Review / sealed runs / freeze 工件。
* Obsidian notes ≠ canonical ontology：研究回答只进 "Related Research"，
  **不自动写成 concept 定义**（§16）。
* user annotations ≠ validated evidence：用户区（`## My Notes`）永不被覆盖（§13/§14/§47）。
* Passage 默认 virtual；只在**实际被引用**时 materialize（§3/§10/§60）。
* 路径只由 adapter 决定；接口不接受任意路径（§23）。
"""
from .adapter import (                      # noqa: F401
    save_research, save_passage, ensure_concept_note, ensure_seminar_note,
    open_in_obsidian, verify_snapshot, list_saved_research, vault_status,
    save_project_note, project_note_map, research_links_for_project,
    unmap_project, remove_project_note,
    ADAPTER_VERSION,
)
__all__ = ["save_research", "save_passage", "ensure_concept_note",
           "ensure_seminar_note", "open_in_obsidian", "verify_snapshot",
           "list_saved_research", "vault_status", "save_project_note",
           "project_note_map", "research_links_for_project", "unmap_project", "remove_project_note",
           "ADAPTER_VERSION"]
