#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ocr_pipeline.py — OCR pipeline interface + provenance schema（Phase 2 §十二）

本阶段**刻意不执行 OCR**
────────────────────────
原因（写进 `not_executed_reason`，可机械查询）：

1. **工具链未装**。本机没有 `ocrmypdf` / `tesseract`（Phase 1 环境勘察已确认）。
   §十二 明确要求：「如果工具链尚未安装，不要为了完成任务临时采用不可复现的 OCR 方法。」
2. **Passage Schema 刚刚稳定**。OCR 的产物必须能落进 `page → passage` 映射，
   否则会造出一批无法定位到段的文本 —— 那正好违反本库的根本目标。
3. **S7 那份是唯一 S7 中文底本**，一旦用不可复现的方法处理，
   会污染唯一的一手材料。宁可先不处理。

所以本脚本只提供**接口与 schema**：让 OCR 可以安全地接进来，
且每一步都有出处、可复核、可回滚。真正执行 OCR 是后续阶段的事。

设计要点
────────
* `page → passage` 可追踪：OCR 以**页**为单位产出，映射到该页所属的 session，
  并预留 `passage_id` 填写位（Passage 化在正文解析之后）。
* provenance 必须记录：源文件 sha256、页码、引擎与版本、语言包、DPI、
  每页置信度、是否有文字层、是否做过图像预处理。
* **原始 OCR 输出与人工校正分开存**：`raw_ocr_text` 永不覆盖，
  校正写进 `corrections` 列表 —— 与 §三 witness 分层同理。

用法
────
    python3 ocr_pipeline.py --print-schema     # 打印 JSON schema（机器可读）
    python3 ocr_pipeline.py --check-tools      # 检查工具链是否可用
    python3 ocr_pipeline.py --plan             # 列出 inventory 里 NEEDS_OCR 的文件
    python3 ocr_pipeline.py --run <file>       # 真正执行（工具链缺失时明确报错，不降级）
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))

# 执行 OCR 所需的外部工具（本机当前均缺失）
REQUIRED_TOOLS = {
    "ocrmypdf": "把文字层写回 PDF（保留原图，可复现）",
    "tesseract": "OCR 引擎本体",
}
REQUIRED_LANGS = ["chi_sim", "fra", "eng"]

# 为什么本阶段不执行 —— 机器可查
NOT_EXECUTED_REASON = [
    "工具链未安装（ocrmypdf / tesseract 均缺）——§十二 禁止用不可复现的临时方法代替",
    "Passage schema 刚冻结，OCR 产物必须先能落进 page → passage 映射，否则会产生无法定位的文本",
    "S7《精神分析的伦理学》是当前唯一 S7 中文底本，不可用不可复现的方法处理",
]

# 每个 OCR 页码记录的 provenance 字段
PROVENANCE_FIELDS = {
    "source_document_id": "逻辑文档 id（对应 Phase 1 inventory 的 document_id）",
    "physical_file": "物理文件相对路径",
    "physical_sha256": "源文件 sha256（防篡改锚点）",
    "page_number": "PDF 页码（1-based）",
    "page_image_sha256": "该页渲染图的 sha256",
    "text_layer_present_before": "OCR 前是否已有文字层",
    "engine": "OCR 引擎名",
    "engine_version": "引擎版本（可复现性前提）",
    "language_packs": "使用的语言包及版本",
    "dpi": "渲染 DPI",
    "preprocessing_ops": "图像预处理操作列表（每步可解释）",
    "page_confidence": "该页平均置信度",
    "ocr_performed_at": "执行时间（唯一允许的墙上时钟字段，因为它是事件时间）",
    "ocr_run_id": "本次运行的确定性 id（由输入 + 引擎版本推导）",
}

PAGE_TO_PASSAGE = {
    "page": "页码",
    "session_id": "该页所属 session（由课次解析确定；未知则为 session.S<NN>.unknown）",
    "passage_id": "该页文本被切成的 Passage（Passage 化之后填写；填写前为 null）",
    "structure_path": "该页在 Document→Seminar→Session→Section→Paragraph 中的路径",
    "mapping_status": "COMPLETE | SOURCE_TRACE_INCOMPLETE（缺 Passage 化时为后者）",
}


def schema():
    return {
        "schema": "ocr-pipeline/v1",
        "page_to_passage": PAGE_TO_PASSAGE,
        "provenance_fields": PROVENANCE_FIELDS,
        "engine_requirements": {
            "tools": REQUIRED_TOOLS,
            "language_packs": REQUIRED_LANGS,
            "reproducibility": ("必须记录 engine_version 与 language_packs 版本；"
                                "不同版本产出的文本视为不同 witness"),
        },
        "not_executed_reason": NOT_EXECUTED_REASON,
        "raw_vs_corrected": {
            "raw_ocr_text": "引擎原始输出，**永不覆盖**",
            "corrections": "人工校正列表（每条含 before/after/reason/reviewer）",
            "rule": "校正不改 raw_ocr_text —— 与 §三 witness 分层同构",
        },
        "witness_policy": ("OCR 产物是**新的 witness**（witness_kind=ocr），"
                           "不替换既有 witness；`status=recovered`, `canonical=false`"),
    }


def check_tools():
    out = {}
    for t in REQUIRED_TOOLS:
        out[t] = shutil.which(t)
    langs = {}
    if out.get("tesseract"):
        try:
            import subprocess
            r = subprocess.run([out["tesseract"], "--list-langs"],
                               capture_output=True, text=True)
            have = {l.strip() for l in r.stdout.splitlines()[1:] if l.strip()}
            for l in REQUIRED_LANGS:
                langs[l] = l in have
        except Exception as e:
            langs["error"] = str(e)[:120]
    return {"tools": out, "language_packs": langs,
            "ready": all(out.values()) and all(langs.get(l) for l in REQUIRED_LANGS)}


def plan():
    """列出 inventory 里解析状态为 NEEDS_OCR 的文件（只读）。"""
    p = os.path.join(VAULT, "_data", "corpus_inventory.json")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        inv = json.load(f)
    rows = []
    for r in inv["records"]:
        if r.get("parse_status") == "NEEDS_OCR":
            rows.append({
                "document_id": r.get("document_id"),
                "physical_file": r["rel_path"],
                "physical_sha256": r.get("sha256"),
                "page_count": r.get("page_count"),
                "size": r.get("size"),
                "language_guess": r.get("estimated_language"),
                "priority": ("highest" if r.get("seminar_number") == 7
                             or "研讨班七" in r["rel_path"] else "normal"),
            })
    rows.sort(key=lambda x: (x["priority"] != "highest", -(x["size"] or 0)))
    return rows


def run_one(path, dry_run=False):
    tools = check_tools()
    if not tools["ready"]:
        return {
            "executed": False,
            "reason": NOT_EXECUTED_REASON[0],
            "tools": tools,
            "hint": ("安装后重试：brew install ocrmypdf tesseract tesseract-lang。"
                     "本脚本**不会**回退到不可复现的做法。"),
        }
    # 工具齐备时才走到这里。真实实现应：渲染页图 → OCR → 写 provenance →
    # 落 page→passage 映射 → 作为新 witness 登记。此处刻意留空，
    # 因为本阶段不允许执行（§十二）。
    return {"executed": False,
            "reason": "工具链虽已就绪，但本阶段按 §十二 不执行 OCR；"
                      "请在 Passage schema 稳定并通过审核后再启用。",
            "tools": tools}


def main():
    ap = argparse.ArgumentParser(description="OCR pipeline 接口（Phase 2 §十二）")
    ap.add_argument("--print-schema", action="store_true")
    ap.add_argument("--check-tools", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run", default=None, metavar="FILE")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.print_schema:
        print(json.dumps(schema(), ensure_ascii=False, indent=2))
        return 0
    if args.check_tools:
        r = check_tools()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    if args.plan:
        rows = plan()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print("=" * 68)
            print("待 OCR 文件（来自 _data/corpus_inventory.json）")
            print("=" * 68)
            for r in rows:
                print(f"  [{r['priority']:7s}] {r['physical_file'][:64]}")
                print(f"            {r['page_count']} 页 · "
                      f"{(r['size'] or 0)//1024} KB · {r['language_guess']}")
            print()
            print(f"共 {len(rows)} 个文件。**本阶段不执行 OCR** —— 原因：")
            for i, x in enumerate(NOT_EXECUTED_REASON, 1):
                print(f"  {i}. {x}")
        return 0
    if args.run:
        print(json.dumps(run_one(args.run), ensure_ascii=False, indent=2))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
