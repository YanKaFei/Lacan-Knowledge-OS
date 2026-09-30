#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.markdown — ExportDocument → Markdown（4D.6 §34）

面向 Obsidian / Git / 纯文本归档的**可移植**产物。
⚠️ 与 4D.3 的 Obsidian Save 是两件事（§34）：这里是 portable export，
不是 workspace-integrated note —— 因此**不写 managed block**、不改 vault 里的任何东西。

纪律：
    * 用户内容（notes / hypotheses / open questions / bibliography）**分区**显示（§39/§40/§41/§42）；
    * `SOURCE_TRACE_INCOMPLETE` 必须出现（§29）；
    * Markdown frontmatter 用受控 YAML 序列化（防 frontmatter 注入，§69）。
"""
from __future__ import annotations

from obsidian_adapter.frontmatter import dump_frontmatter

from . import citations as C
from .model import ABSTENTION_TITLE, USER_BLOCK_LABELS


def _frontmatter(doc):
    fm = {
        "type": "lacan-export",
        "export_schema": doc.get("schema_version"),
        "export_id": doc.get("export_id"),
        "source_type": doc.get("source_type"),
        "source_id": doc.get("source_id"),
        "answer_state": doc.get("answer_state"),
        "created": (doc.get("created_at") or "")[:19],
        "source_answer_hash": doc.get("source_answer_hash"),
        "export_payload_hash": doc.get("export_payload_hash"),
        "evidence_role": doc.get("evidence_role"),
        "core_freeze_version": doc.get("core_freeze_version"),
        "exporter_version": doc.get("exporter_version"),
    }
    if doc.get("snapshot_integrity"):
        fm["snapshot_integrity"] = doc["snapshot_integrity"]
    return dump_frontmatter({k: v for k, v in fm.items() if v is not None})


def _state_line(doc):
    st = doc.get("answer_state") or "—"
    label = doc.get("answer_state_label")
    if st == "VALIDATED_WITH_QUALIFICATIONS":
        return "`%s` — **Qualified answer** (qualifications and limitations are kept below)" % st
    if st == "ABSTAINED":
        return "`%s` — the corpus cannot support a reliable answer" % st
    if st == "PARTIALLY_SUPPORTED":
        return "`%s` — partially supported; NOT a fully validated answer" % st
    if st == "VALIDATION_FAILED":
        return ("`%s` — the core could NOT validate this answer; "
                "treat it as a failed research call, not as a result" % st)
    if st == "INSUFFICIENT_EVIDENCE":
        return "`%s` — the corpus does not provide sufficient evidence" % st
    return "`%s`%s" % (st, (" — %s" % label) if label else "")


def render(doc, *, include_rendered_at=True):
    out = [_frontmatter(doc).rstrip("\n"), "", "# %s" % (doc.get("title") or "Export"), ""]
    out += ["> **Evidence role**: `%s` — exported scholarly content is copied verbatim "
            "from the stored validated output; nothing is re-summarised."
            % doc.get("evidence_role"), ""]
    if doc.get("question"):
        out += ["## Research question", "", doc["question"], ""]
    out += ["## Research metadata", "",
            "- Answer state: %s" % _state_line(doc),
            "- Task type: `%s`" % (doc.get("task_type") or "—"),
            "- Source: `%s` / `%s`" % (doc.get("source_type"), doc.get("source_id")),
            "- Created: %s" % (doc.get("created_at") or "—"),
            "- Core freeze: `%s`" % (doc.get("core_freeze_version") or "—"),
            "- Source answer hash: `%s`" % (doc.get("source_answer_hash") or "—"),
            "- Export payload hash: `%s`" % (doc.get("export_payload_hash") or "—"),
            "- Exporter: `%s`" % doc.get("exporter_version"), ""]
    if doc.get("snapshot_integrity"):
        out += ["> Snapshot integrity: **%s**" % doc["snapshot_integrity"], ""]

    # 答案正文（逐字）
    ab = doc.get("abstention")
    if ab:
        out += ["## %s" % (ab.get("title") or ABSTENTION_TITLE), ""]
        for title, key in (("Why this cannot be answered", "categories"),
                           ("Missing information", "missing_information"),
                           ("Available partial information",
                            "available_partial_information"),
                           ("Sources needed", "required_sources")):
            items = ab.get(key) or []
            if not items:
                continue
            out += ["### %s" % title, ""] + ["- %s" % x for x in items] + [""]
    if doc.get("sections"):
        out += ["## Scholarly answer", ""]
        for s in doc["sections"]:
            out += ["### %s%s" % (s.get("label") or "",
                                  " (internal)" if s.get("internal") else ""), "",
                    str(s.get("text") or ""), ""]
    if doc.get("claims"):
        out += ["## Validated claims", ""]
        for c in doc["claims"]:
            out += ["### Claim `%s`" % (c.get("claim_id") or "—"), "",
                    str(c.get("claim_text") or ""), "",
                    "Epistemic status: `%s` · type: `%s`"
                    % (c.get("epistemic_label") or c.get("epistemic_status") or "—",
                       c.get("claim_type") or "—"), ""]
            ids = [b for b in (doc.get("claim_bindings") or {}).get("bindings", [])
                   if b.get("claim_id") == c.get("claim_id")]
            if ids and ids[0].get("citation_ids"):
                out += ["Evidence:", ""] + ["- %s" % C.short_citation(pid)
                                            for pid in ids[0]["citation_ids"]] + [""]
    if doc.get("citations"):
        out += ["## Citations", ""]
        for rec in doc["citations"]:
            out += ["- `%s` — %s" % (rec["passage_id"], rec["internal_full"])]
            out += ["  - provenance: %s" % rec["provenance"]]
            if rec.get("quoted_span"):
                out += ["  - quoted span: %s" % _quote(rec["quoted_span"])]
            if rec.get("provenance_status") == "SOURCE_TRACE_INCOMPLETE":
                out += ["  - **SOURCE_TRACE_INCOMPLETE** — 来源链未闭合到原始物理文件；"
                        "该限制随导出保留。"]
            if rec.get("witness") is None:
                out += ["  - witness: `null`（系统未记录 witness；**不是**省略）"]
        out += [""]
    if doc.get("limitations"):
        out += ["## Source limitations", ""] + ["- %s" % x for x in doc["limitations"]] + [""]
    if doc.get("warnings"):
        out += ["## Warnings", ""] + ["- %s" % _warn(w) for w in doc["warnings"]] + [""]

    # passage 对象
    p = doc.get("passage")
    if p:
        out += ["## Passage", "", "```text", str(p.get("text") or ""), "```", "",
                "- Seminar: `%s`" % (p.get("seminar") or "—"),
                "- Session: `%s`" % (p.get("session") or "—"),
                "- Language: `%s`" % (p.get("language") or "—"),
                "- Source layer: `%s`" % (p.get("source_layer") or "—"),
                "- Witness: `%s`" % (p.get("witness") if p.get("witness") else "null"),
                "- Provenance: `%s`" % (p.get("provenance_status") or "—"), ""]
        if p.get("trace_incomplete"):
            out += ["<div class=\"export-warning\">SOURCE_TRACE_INCOMPLETE — %s</div>"
                    % (p.get("witness_note") or "来源链未闭合"), ""]
        if p.get("context"):
            out += ["### Context (±%d)" % len(p["context"]), ""]
            for c in p["context"]:
                out += ["- `%s`%s %s" % (c["passage_id"],
                                         " **←**" if c.get("is_target") else "",
                                         (c.get("text") or "")[:400])]
            out += [""]

    # 项目对象
    proj = doc.get("project")
    if proj:
        out += ["## Project", "",
                "- Project id: `%s`" % proj.get("project_id"),
                "- Status: `%s`" % proj.get("status"),
                "- Revision: %s" % proj.get("revision"),
                "- Created: %s" % proj.get("created_at"),
                "- Updated: %s" % proj.get("updated_at"),
                "- Tags: %s" % (", ".join(proj.get("tags") or []) or "—"),
                "- Snapshot verification: `%s`" % proj.get("snapshot_verification"),
                "- Evidence role: `%s`" % proj.get("evidence_role"), ""]
        if proj.get("description"):
            out += [proj["description"], ""]
        if proj.get("research_questions"):
            out += ["### Research questions", ""] + [
                "- [%s] %s" % (q.get("status"), q.get("text"))
                for q in proj["research_questions"]] + [""]
        if proj.get("runs_index"):
            out += ["### Research runs index", ""]
            for r in proj["runs_index"]:
                out += ["- `%s` · %s · %s citations" % (r["answer_state"], r["question"],
                                                        r["citations"])]
            out += [""]
        for key in ("saved_concepts", "saved_seminars", "saved_passages", "saved_terms"):
            vals = proj.get(key) or []
            if vals:
                out += ["### %s" % key.replace("saved_", "").title(), ""] + [
                    "- `%s`" % v for v in vals] + [""]
        if proj.get("broken_references"):
            out += ["> **BROKEN_REFERENCE**: %s（保留，不静默删除）"
                    % ", ".join(proj["broken_references"]), ""]

    # 用户区块（分区，§39–§42）
    ub = doc.get("user_blocks") or {}
    if ub.get("user_hypotheses"):
        out += ["## %s" % USER_BLOCK_LABELS["user_hypotheses"], ""]
        out += ["**USER HYPOTHESIS — NOT VALIDATED BY THE SCHOLARLY CORE**", ""]
        for h in ub["user_hypotheses"]:
            out += ["- %s" % h.get("text")]
        out += [""]
    if ub.get("open_questions"):
        out += ["## %s" % USER_BLOCK_LABELS["open_questions"], ""]
        for q in ub["open_questions"]:
            out += ["- %s _(origin: %s%s)_" % (q.get("text"), q.get("origin"),
                                               (", run %s" % q["run_id"])
                                               if q.get("run_id") else "")]
        out += [""]
    if ub.get("user_notes"):
        out += ["## %s" % USER_BLOCK_LABELS["user_notes"], ""]
        for n in ub["user_notes"]:
            out += ["### %s" % (n.get("title") or n.get("id")), "", str(n.get("text") or ""), ""]
    if ub.get("bibliography"):
        out += ["## %s" % USER_BLOCK_LABELS["bibliography"], ""]
        out += ["> `BibliographyRef` 是用户引用管理对象，**不是** `CorpusSource`。", ""]
        for b in ub["bibliography"]:
            bits = [str(b.get("title") or "—")]
            if b.get("author"):
                bits.append(str(b["author"]))
            if b.get("year"):
                bits.append(str(b["year"]))
            line = " · ".join(bits)
            if b.get("missing_fields"):
                line += " _(missing: %s)_" % ", ".join(b["missing_fields"])
            out += ["- %s" % line]
        out += [""]

    # provenance 摘要
    prov = doc.get("provenance") or {}
    if prov:
        out += ["## Provenance summary", "",
                "- Citation source layers: %s"
                % (", ".join("%s ×%d" % (k, v)
                             for k, v in sorted((prov.get("citation_layers") or {}).items()))
                   or "—"),
                "- Witnesses: %s" % (", ".join(prov.get("witnesses") or []) or "—"),
                "- Passages without witness: %s"
                % (", ".join(prov.get("passages_without_witness") or []) or "—"),
                "- Source trace incomplete: %s" % ("yes" if prov.get(
                    "source_trace_incomplete") else "no"), ""]
        if prov.get("source_trace", {}).get("chain"):
            out += ["### Source trace", ""]
            for s in prov["source_trace"]["chain"]:
                out += ["- %s `%s`%s" % (s.get("step"), s.get("id") or "—",
                                         "" if s.get("present") else "  ← **break**")]
            out += [""]

    out += ["---", "",
            "Exported by `%s` · schema `%s` · payload hash `%s`"
            % (doc.get("exporter_version"), doc.get("schema_version"),
               (doc.get("export_payload_hash") or "")[:16]), ""]
    return "\n".join(out)


def _quote(text):
    t = str(text or "").replace("\n", " ").strip()
    return "`%s`" % (t[:200] + ("…" if len(t) > 200 else ""))


def _warn(w):
    if isinstance(w, dict):
        return "%s — %s" % (w.get("code") or "warning", w.get("message") or "")
    return str(w)
