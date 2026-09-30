#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4e_project_state_vocabulary.py — Phase 4E delta 发现的产品缺陷回归

**缺陷**：`project_api.runs.RUN_STATE_OK` 只列 3 态
（VALIDATED / VALIDATED_WITH_QUALIFICATIONS / ABSTAINED），于是真实 provider 合法返回
`PARTIALLY_SUPPORTED` / `VALIDATION_FAILED` / `INSUFFICIENT_EVIDENCE` 时，
`add_research_run` 抛 `Invalid` —— 用户拿到真实答案却**无法加入 Research Project**。
4D.7 只修了导出层的同类问题；mock provider 在这条动线上从不产生这 3 态，所以没照到。

本测试是**确定性**的（不联网、不用真实 provider）：构造 6 个合法状态的答案视图，
逐个存进一个隔离的临时项目，断言：

1. 6 态全部可存（不再拒答）；
2. 存进去的 `answer_state` 原样保留（**不**把失败态美化成答案）；
3. `source_answer_hash` 与核心答案身份一致；
4. 视图层的状态文案对这 6 态都有定义（不能落到未翻译的裸值）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "lacan_mcp"))
sys.path.insert(0, VAULT)

import export_system as EX                        # noqa: E402
import project_api as PA                          # noqa: E402
from workspace_ui.server import viewmodel as VM   # noqa: E402

CORE_STATES = ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "PARTIALLY_SUPPORTED",
               "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "ABSTAINED")


def _view(state, i):
    return {
        "kind": "answer", "question": "state vocabulary probe %d" % i,
        "task_type": "concept_definition", "state": state,
        "state_label": VM.STATE_LABELS.get(state, state), "answer_permission": "FULL_SYNTHESIS",
        "sections": {"brief_answer": "（probe）"},
        "claims": ([{"claim_id": "c1", "claim_type": "DEFINITION",
                     "claim_text": "（probe claim）", "evidence_ids": ["passage.S11.unknown.P2253"],
                     "epistemic_status": "DIRECTLY_SUPPORTED"}] if state == "VALIDATED" else []),
        "citations": [], "limitations": [], "abstention": None, "warnings": [],
        "advanced": {"provider": "mock", "request_id": "probe-%d" % i,
                     "core_freeze_version": "scholarly_core_freeze_v1",
                     "api_version": "scholarly-api/v1", "mcp_version": "mcp/v1",
                     "answer_schema_version": "final-scholarly-answer/v1"},
    }


class TestProjectStateVocabulary(unittest.TestCase):

    def test_01_all_core_states_are_storable_and_preserved(self):
        # 必须落在 vault 内（`_workspace/**` 是 USER_WORKSPACE）——
        # 写到系统临时目录会被 policy 正确拒绝（未分类路径）。
        ws = os.path.join(VAULT, "_workspace")
        os.makedirs(ws, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ws, prefix="test_state_vocab_") as tmp:
            prev = PA.store.PROJECTS_DIR
            PA.store.PROJECTS_DIR = os.path.join(tmp, "projects")
            try:
                p = PA.create_project("状态词表探针", "phase4e")
                for i, st in enumerate(CORE_STATES):
                    view = _view(st, i)
                    p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
                    self.assertEqual(rec["answer_state"], st,
                                     "%s 被改写成了 %s" % (st, rec["answer_state"]))
                    self.assertEqual(rec["source_answer_hash"], EX.prov.answer_hash(view))
                got = PA.get_project(p["project_id"])
                self.assertEqual(len(got["research_runs"]), len(CORE_STATES))
                self.assertEqual(sorted(r["answer_state"] for r in got["research_runs"]),
                                 sorted(CORE_STATES))
            finally:
                PA.store.PROJECTS_DIR = prev

    def test_02_viewmodel_has_labels_for_all_core_states(self):
        missing = [s for s in CORE_STATES if s not in VM.STATE_LABELS]
        self.assertEqual(missing, [], "视图层缺这些状态的文案：%s" % missing)
        # 诚实性：未验证状态不得被说成「已验证」
        for st in ("VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "PARTIALLY_SUPPORTED"):
            label = VM.STATE_LABELS[st].lower()
            self.assertTrue("not" in label or "insufficient" in label
                            or "failed" in label or "partially" in label,
                            "%s 的文案不够诚实：%r" % (st, VM.STATE_LABELS[st]))

    def test_03_run_state_ok_matches_core_vocabulary(self):
        self.assertEqual(set(PA.runs.RUN_STATE_OK), set(CORE_STATES))


if __name__ == "__main__":
    unittest.main(verbosity=2)
