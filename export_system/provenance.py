#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.provenance — Provenance 摘要（4D.6 §13/§29/§30/§31/§45）

* `provenance_summary(view, passage=None, trace=None, citations=None)`：
  汇总 source layer 分布、witness 集合、trace 状态、以及**核心答案的答案身份哈希**；
* **SOURCE_TRACE_INCOMPLETE 必须在所有格式里保留**（§29）——所以它进的是
  ExportDocument 的结构化字段，而不是某个 renderer 里的一句提示；
* witness 缺失写 `null`，不是省略（§31：不知道 ≠ 不存在）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def answer_hash(view):
    """与核心/4D.3/4D.5 一致：对 `raw.scholarly_payload` 规范化后取 sha256。"""
    payload = ((view or {}).get("raw") or {}).get("scholarly_payload")
    if payload is None:
        payload = ((view or {}).get("raw") or {})
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def source_layer_distribution(citations):
    out = {}
    for c in citations or []:
        code = c.get("source_layer") or "UNKNOWN"
        out[code] = out.get(code, 0) + 1
    return out


def provenance_summary(view, *, passage=None, trace=None, citations=None):
    citations = citations or []
    layers = source_layer_distribution(citations)
    witnesses = sorted({c.get("witness") for c in citations if c.get("witness")})
    missing_witness = [c.get("passage_id") for c in citations if not c.get("witness")]
    incomplete = [c.get("passage_id") for c in citations
                  if c.get("provenance_status") == "SOURCE_TRACE_INCOMPLETE"]
    out = {
        "generated_at": now_iso(),
        "source_answer_hash": answer_hash(view) if view else None,
        "core_freeze_version": ((view or {}).get("advanced") or {}).get(
            "core_freeze_version") if view else None,
        "task_type": (view or {}).get("task_type") if view else None,
        "answer_state": (view or {}).get("state") if view else None,
        "citation_layers": layers,
        "witnesses": witnesses,
        "passages_without_witness": missing_witness,
        "passages_trace_incomplete": incomplete,
        "source_trace_incomplete": bool(incomplete),
        "note": ("Provenance is copied from the canonical store; nothing is inferred. "
                 "A missing witness is reported as null/missing, not omitted."),
    }
    if passage:
        out["passage"] = {
            "passage_id": passage.get("passage_id"),
            "seminar": passage.get("seminar"), "session": passage.get("session"),
            "language": passage.get("language"),
            "source_layer": passage.get("source_layer"),
            "witness": passage.get("witness"),
            "provenance_status": passage.get("provenance_status"),
            "canonical_store": "passage store",
        }
    if trace:
        out["source_trace"] = {
            "chain": [{"step": s.get("step"), "id": s.get("id"),
                       "present": s.get("present"), "label": s.get("label")}
                      for s in (trace.get("chain") or [])],
            "broken_at": trace.get("broken_at") or [],
            "trace_status": trace.get("trace_status"),
            "trace_missing": trace.get("trace_missing") or [],
            "complete": trace.get("complete"),
            "witness_note": trace.get("witness_note"),
            "witness_note_source": trace.get("witness_note_source"),
            "source_state": trace.get("source_state"),
        }
    return out


def corpus_provenance_block(passage_meta):
    """§43：`Corpus Provenance` 区块（与 Project Bibliography 分开）。"""
    return {
        "label": "Corpus Provenance",
        "source": "passage store / corpus_sources / witnesses（系统 provenance）",
        "entries": passage_meta or [],
    }


def project_bibliography_block(refs):
    """§43：`Project Bibliography` 区块（用户引用管理对象，**不是** CorpusSource）。"""
    return {
        "label": "Project Bibliography",
        "source": "project_api bibliography_refs（用户提供的元数据，缺失就缺失）",
        "entries": [dict(r) for r in (refs or [])],
        "note": "A BibliographyRef is not a CorpusSource.",
    }
