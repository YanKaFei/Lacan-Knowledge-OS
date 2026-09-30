#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_docs_update.py — Phase 4E §69：按最终判定更新用户/开发文档 + 记录。

READY 情形：
  * `USER_GUIDE.md` §6 从「真实 provider 当前不可用（CCR-0001）」改为「READY」，
    并写清凭据配置、失败语义、延迟预期、no-fallback 政策；
  * §9 的对应限制条目改写（不再是"不可用"，而是"需要凭据 / 延迟由 provider 侧决定"）；
  * `DEVELOPER_AUDIT_GUIDE.md` §8 把 CCR-0001 标为 RESOLVED 并写修复摘要，
    新增 real-provider wiring 纪律，工具清单补 4E 工具。

BLOCKED 情形：文档**保持** BLOCKED 描述，只追加一句「Phase 4E 未通过，见报告」。

用法：
    python3 _scripts/_tools/phase4e_docs_update.py --decision PHASE_4E_COMPLETE \
        [--acc-run 4e_acceptance_...]
"""
from __future__ import annotations

import argparse
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
UG = os.path.join(VAULT, "USER_GUIDE.md")
DG = os.path.join(VAULT, "DEVELOPER_AUDIT_GUIDE.md")
OUT = os.path.join(VAULT, "_data", "phase4e", "docs_update.json")

UG_PROVIDER_OLD = """**当前状态（诚实告知）**：真实 LLM 研究路径在**冻结核心**里存在一个缺陷
（`CCR-0001`：核心把低层 completion provider 当成 synthesis adapter 使用），
因此即使配了凭据，真实 provider 研究也会失败。产品层的处理是**如实报错**："""

UG_PROVIDER_NEW = """**状态**：真实 LLM 研究路径**可用**（`CCR-0001` 已在 Phase 4E 修复：
产品边界现在经既有工厂 `make_adapter` 把 completion provider **包进**
`ScholarlySynthesisAdapter`，与 4C.1-D/D2 验证过的结构一致；详见
`PHASE4E_REAL_PROVIDER_REMEDIATION_REPORT.md`）。

* **延迟预期**：单题真实研究会调用 provider 多次（综合 + 逐条蕴含裁判），
  实测约 **几十秒到数分钟**（本机 14 题中位约 3–4 分钟/题）。
* **凭据缺失 / provider 故障**时**如实报错**，绝不 fallback："""

UG_LIMIT_OLD = "8. **真实 LLM provider 当前不可用**（`CCR-0001`）；离线/mock 完全可用。"
UG_LIMIT_NEW = ("8. **真实 LLM provider 需要显式凭据**（`DSH_SYNTHESIS_API_KEY` 或 "
                "`~/.dsh/.credentials.yaml`）；离线 / mock 无需凭据且完全可用。"
                "真实 provider 的延迟与配额由 provider 侧决定。")

DG_CCR_OLD = """* `CCR-0001`（`S1_CORRECTNESS`，OPEN）：`provider=llm` 时核心把低层
  completion provider（`OpenAICompatibleProvider.complete`）当成 synthesis adapter
  使用（`scholarly_api/core.py:412/446/457`），必然抛
  `AttributeError: … has no attribute 'synthesize'` → `PROVIDER_CALL_FAILED`。
  真实 LLM 研究因此**不可用**。
  产品层**没有**改核心，只做了两件事：
  1. 错误码诚实映射（`workspace_ui/server/api.py::_is_provider_failure`
     → `PROVIDER_UNAVAILABLE`，且**不** fallback、**不**补答）；
  2. 凭据探测与核心 `load_dsh_key()` 对齐（原实现探测核心根本不读的
     `DEEPSEEK_API_KEY/OPENAI_API_KEY/ANTHROPIC_API_KEY` 环境变量 → 假阴性，
     用户按核心机制配好凭据也会被拒答）。"""

DG_CCR_NEW = """* `CCR-0001`（`S1_CORRECTNESS`，**RESOLVED**，resolution_phase = Phase 4E）：
  `provider=llm` 时产品门面把低层 completion provider（只有 `complete()`）当成
  synthesis adapter 使用，必然抛 `AttributeError: … has no attribute 'synthesize'`。
  **修复方式 = reuse 既有实现**：`scholarly_api/core.py` 的 llm/mock 分支改经
  `synthesis_adapters.make_adapter()` 选择 adapter（真 provider 被**包进**
  `ScholarlySynthesisAdapter`）；provider 失败的错误翻译 + 内部子分类 + 凭据脱敏；
  冻结的 D2 验证 engine（`synthesis_adapters.py` / `synthesis_contract.py` …）
  **逐字节未改**。冻结谱系新增第 5 段（`phase=4E, ccr=CCR-0001`），
  39 个组件里只有 `scholarly_api_core_hash` 变化（产品边界）。

### 8.1 real provider wiring 纪律（Phase 4E 之后）

1. **completion provider ≠ synthesis adapter**：只有 `complete(system, user, schema)`
   的对象**不能**交给 synthesis boundary；必须经 `make_adapter(name, provider)`
   得到 `synthesize()` + `.provider` 都齐的 adapter。
2. 选择点只有一个：`synthesis_adapters.make_adapter()`。禁止在别处 `if provider:`
   直接构造并调用。
3. 凭据只认核心读的那两处：`DSH_SYNTHESIS_API_KEY` 或
   `~/.dsh/.credentials.yaml` 的 `DEEPSEEK_API_KEY:` 行；不要臆测别的环境变量。
4. provider 失败**保持公开错误码稳定**（`PROVIDER_CALL_FAILED` /
   `PROVIDER_UNAVAILABLE`），子分类放内部 `detail.provider_diagnostic`
   （AUTH / RATE_LIMITED / TIMEOUT / BAD_RESPONSE / CONNECTION / ADAPTER_ERROR）。
5. 对外文本一律过 `_redact_secrets()`（key / `Authorization: Bearer` / `sk-…`）。
6. **拒绝 fallback**：无凭据或 provider 故障时返回错误，绝不用 mock 或模型知识补答。"""

DG_TOOLS_OLD = "| `summarize_regression_timing.py`（4D.7，**不进 Gate**） | 从完整回归日志确定性还原逐套件耗时 |"
DG_TOOLS_NEW = """| `summarize_regression_timing.py`（4D.7，**不进 Gate**） | 从完整回归日志确定性还原逐套件耗时 |
| `phase4e_real_provider_run.py` | 14 题真实 provider 回归（sealed；Gate20/21 复算、D2 对照） |
| `phase4e_product_delta.py` | 真实 provider 的产品 delta 验证（A/D/F + 四格式 + Project + Obsidian） |
| `phase4e_freeze_record.py` | 冻结修复记录（父/新 hash、变化组件、语义影响、CCR） |
| `phase4e_acceptance.py` | Phase 4E Remediation Gate v1 的冻结与判定（E1–E17） |
| `phase4e_secret_audit.py` | 运行工件凭据泄漏审计（§68） |
| `phase4e_regression.py` | 全量回归 + `_data/phase4e/regression.json` |
| `phase4e_spot_review_packet.py` | 人工抽查的输入材料（只读，不评分） |"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E docs update")
    ap.add_argument("--decision", required=True)
    ap.add_argument("--acc-run", default=None)
    a = ap.parse_args(argv)
    ready = a.decision == "PHASE_4E_COMPLETE"
    ug = open(UG, encoding="utf-8").read()
    dg = open(DG, encoding="utf-8").read()
    applied = []

    if ready:
        assert UG_PROVIDER_OLD in ug, "USER_GUIDE §6 锚点未找到"
        ug = ug.replace(UG_PROVIDER_OLD, UG_PROVIDER_NEW)
        applied.append("USER_GUIDE §6：真实 provider 状态 BLOCKED → READY（含凭据/失败/延迟/无兜底）")
        assert UG_LIMIT_OLD in ug, "USER_GUIDE §9 限制条目锚点未找到"
        ug = ug.replace(UG_LIMIT_OLD, UG_LIMIT_NEW)
        applied.append("USER_GUIDE §9：限制条目改为「需要凭据 + 延迟由 provider 侧决定」")
        assert DG_CCR_OLD in dg, "DEVELOPER_AUDIT_GUIDE §8 锚点未找到"
        dg = dg.replace(DG_CCR_OLD, DG_CCR_NEW)
        applied.append("DEVELOPER_AUDIT_GUIDE §8：CCR-0001 OPEN → RESOLVED + 修复摘要 + §8.1 wiring 纪律")
        if DG_TOOLS_OLD in dg:
            dg = dg.replace(DG_TOOLS_OLD, DG_TOOLS_NEW)
            applied.append("DEVELOPER_AUDIT_GUIDE §4.2：工具清单补 4E 工具")
    else:
        ug += ("\n\n> **Phase 4E 未通过**：`CCR-0001` 仍未 RESOLVED，真实 LLM 研究仍不可用；"
               "详见 `PHASE4E_REAL_PROVIDER_REMEDIATION_REPORT.md`。\n")
        applied.append("USER_GUIDE：追加「Phase 4E 未通过」说明（保持 BLOCKED 描述）")

    open(UG, "w", encoding="utf-8").write(ug)
    open(DG, "w", encoding="utf-8").write(dg)
    doc = {"schema_version": "phase4e-docs-update/v1",
           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "decision": a.decision, "acceptance_run": a.acc_run,
           "applied": applied,
           "summary": ("`USER_GUIDE.md`：真实 LLM 研究 BLOCKED → **READY**，写明凭据配置、"
                       "provider 失败语义（PROVIDER_UNAVAILABLE、不 fallback）、"
                       "延迟预期（单题数十秒到数分钟）与 no-fallback 政策；"
                       "`DEVELOPER_AUDIT_GUIDE.md`：`CCR-0001` 标为 **RESOLVED**（Phase 4E），"
                       "新增 real-provider wiring 纪律（make_adapter 是唯一选择点、"
                       "凭据来源、错误码稳定 + 内部子分类、脱敏、禁止 fallback），"
                       "工具清单补 7 个 4E 工具。")
           if ready else "Phase 4E 未通过：文档保持 BLOCKED 描述并追加说明。"}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    for x in applied:
        print("  + %s" % x)
    print("-> %s" % os.path.relpath(OUT, VAULT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
