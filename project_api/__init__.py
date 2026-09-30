#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_api — Phase 4D.5 **Research Project** 工作区产品层（§64/§65）

    Research Chat / Explorer / Obsidian Workspace
                    ↓
             Research Project Layer          ← 本模块
                    ↓
              USER_WORKSPACE（_workspace/projects/**）

边界（§2/§3/§65）：
    * Project 只做 organize / reference / annotate / group / bookmark / plan；
    * **永不** promote 用户笔记为 canonical claim、永不改 ontology / passage / evidence、
      永不覆盖 abstention；
    * 本模块可以调用 `scholarly_api` / `browse_api` / `obsidian_adapter` 的**稳定产品接口**，
      但**不得** import synthesis / validator / retrieval internals（契约自检守）。
    * Project 内容不是 evidence（§74）：`context_for_agent()` 明确标 `NOT_EVIDENCE`。
"""
from __future__ import annotations

from .items import (add_bibliography_ref, add_hypothesis, add_note, add_open_question,
                    hypothesis_research_request, open_questions_from_run,
                    record_hypothesis_test, remove_bibliography_ref, remove_note,
                    search_project, timeline, update_note)
from .projects import (add_question, add_reference, archive_project, check_referent,
                       create_project, enrich, get_project, list_projects,
                       remove_reference, restore_project, set_question_status,
                       summary, update_project)
from .runs import (add_research_run, answer_hash, compare_runs, context_for_agent,
                   get_run, list_runs, verify_project_runs)
from .store import (Conflict, Invalid, NotFound, PROJECT_API_VERSION,
                    PROJECT_SCHEMA_VERSION, PROJECTS_DIR, PROJECTS_REL, ProjectError,
                    new_project_id, project_dir, read_audit, read_project)

__all__ = [
    "PROJECT_API_VERSION", "PROJECT_SCHEMA_VERSION", "PROJECTS_DIR", "PROJECTS_REL",
    "ProjectError", "NotFound", "Invalid", "Conflict", "new_project_id", "project_dir",
    "read_project", "read_audit",
    "create_project", "get_project", "list_projects", "update_project", "archive_project",
    "restore_project", "add_question", "set_question_status", "add_reference",
    "remove_reference", "check_referent", "enrich", "summary",
    "add_research_run", "get_run", "list_runs", "compare_runs", "verify_project_runs",
    "answer_hash", "context_for_agent",
    "add_open_question", "open_questions_from_run", "add_hypothesis",
    "record_hypothesis_test", "hypothesis_research_request", "add_note", "update_note",
    "remove_note", "add_bibliography_ref", "remove_bibliography_ref", "search_project",
    "timeline",
]
