#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.bundle — Research Bundle 构建与校验（4D.6 §12–§16/§47/§48/§65）

结构（§13）：
    bundle/
        README.md
        manifest.json
        research/<run_id>.md | .json
        claims/claims.json
        citations/citations.json
        passages/<passage_id>.json
        provenance/provenance.json
        project/project.json
        bibliography/bibliography.json

硬门禁：
    * **不得 materialize 全库**（§14）：只导出被引用 / 被保存 / 显式选择的 passage；
    * 流程固定（§47）：build temp → validate → hash → manifest → verify → atomic finalize；
      失败不留半成品；
    * ZIP 在目录 bundle **verify 之后**才压缩，且防 zip slip（§48）。
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile

from . import json_export, manifest as MF, markdown as MD, policy as POL
from .model import ExportError, sha256_bytes, sha256_file

MAX_PASSAGES = 500          # 显式上限：一次导出最多 materialize 这么多 passage（§14）
MAX_CONTEXT = 5


def _passage_payload(passage_id, *, include_context=0):
    import browse_api as B                                                # noqa: PLC0415
    p = B.get_passage_view(passage_id)
    if p is None:
        raise ExportError("BROKEN_REFERENCE", "passage not found: %s" % passage_id,
                          {"passage_id": passage_id})
    out = {
        "passage_id": p.get("passage_id"), "text": p.get("text"),
        "seminar": p.get("seminar"), "session": p.get("session"),
        "language": p.get("language"), "source_layer": p.get("source_layer"),
        "witness": p.get("witness"), "provenance_status": p.get("provenance_status"),
        "canonical_store": "passage store (read-only reference)",
    }
    if include_context:
        ctx = B.context(passage_id, include_context, include_context) or {}
        out["context"] = [{"passage_id": c.get("passage_id"), "text": c.get("text"),
                           "is_target": c.get("is_target")}
                          for c in ctx.get("items") or []]
        out["context_window"] = include_context
    return out


def collect_passage_ids(doc):
    """只收集：citation 指向的 + doc.passage + project 显式保存的（§14）。"""
    ids = []
    for rec in doc.get("citations") or []:
        pid = rec.get("passage_id")
        if pid and pid not in ids:
            ids.append(pid)
    p = doc.get("passage") or {}
    if p.get("passage_id") and p["passage_id"] not in ids:
        ids.append(p["passage_id"])
    proj = doc.get("project") or {}
    for pid in proj.get("saved_passages") or []:
        if pid not in ids:
            ids.append(pid)
    return ids


def build_files(doc, *, include_context=0):
    """→ (files: [(relpath, bytes)], counts)。"""
    files = []
    run_id = doc.get("source_id") or "export"
    md = MD.render(doc)
    js = json_export.render(doc)
    files.append(("README.md", _readme(doc).encode("utf-8")))
    files.append(("research/%s.md" % POL.safe_name(run_id), md.encode("utf-8")))
    files.append(("research/%s.json" % POL.safe_name(run_id), js.encode("utf-8")))
    files.append(("claims/claims.json", json.dumps(
        {"schema_version": "bundle_claims_v1", "source_id": doc.get("source_id"),
         "claims": doc.get("claims") or [],
         "claim_bindings": doc.get("claim_bindings") or {}},
        ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")))
    files.append(("citations/citations.json", json.dumps(
        {"schema_version": "bundle_citations_v1", "source_id": doc.get("source_id"),
         "citations": doc.get("citations") or []},
        ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")))
    files.append(("provenance/provenance.json", json.dumps(
        {"schema_version": "bundle_provenance_v1",
         "provenance": doc.get("provenance") or {},
         "bibliographic_metadata": doc.get("bibliographic_metadata") or {}},
        ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")))
    if doc.get("project"):
        files.append(("project/project.json", json.dumps(
            {"schema_version": "bundle_project_v1", "project": doc["project"],
             "user_blocks": doc.get("user_blocks") or {}},
            ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")))
    ub = doc.get("user_blocks") or {}
    if ub.get("bibliography"):
        files.append(("bibliography/bibliography.json", json.dumps(
            {"schema_version": "bundle_bibliography_v1",
             "label": "Project Bibliography (user references, not corpus provenance)",
             "entries": ub["bibliography"]},
            ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")))

    ids = collect_passage_ids(doc)
    if len(ids) > MAX_PASSAGES:
        raise ExportError("EXPORT_POLICY_DENIED",
                          "refusing to materialise %d passages (max %d)"
                          % (len(ids), MAX_PASSAGES),
                          {"passage_ids": len(ids), "max": MAX_PASSAGES})
    for pid in ids:
        payload = _passage_payload(pid, include_context=include_context)
        files.append(("passages/%s.json" % POL.safe_name(pid.replace(".", "-")),
                      json.dumps(payload, ensure_ascii=False, indent=2,
                                 sort_keys=True).encode("utf-8")))
    return files, {"citations": len(doc.get("citations") or []),
                   "passages": len(ids)}


def _readme(doc):
    prov = doc.get("provenance") or {}
    return "\n".join([
        "# Research Bundle — %s" % (doc.get("title") or ""),
        "",
        "- export_id: `%s`" % doc.get("export_id"),
        "- schema: `%s` · exporter: `%s`"
        % (doc.get("schema_version"), doc.get("exporter_version")),
        "- source: `%s` / `%s`" % (doc.get("source_type"), doc.get("source_id")),
        "- answer_state: `%s`" % (doc.get("answer_state") or "—"),
        "- evidence_role: `%s`" % doc.get("evidence_role"),
        "- core_freeze_version: `%s`" % (doc.get("core_freeze_version") or "—"),
        "- source_answer_hash: `%s`" % (doc.get("source_answer_hash") or "—"),
        "- export_payload_hash: `%s`" % doc.get("export_payload_hash"),
        "- source_trace_incomplete: %s"
        % ("yes" if prov.get("source_trace_incomplete") else "no"),
        "",
        "## Contents",
        "",
        "- `research/<id>.md` — human-readable export (verbatim scholarly payload)",
        "- `research/<id>.json` — machine-readable `export_document_v1`",
        "- `claims/claims.json` — validated claims + claim→citation bindings",
        "- `citations/citations.json` — citation records (internal styles, capabilities)",
        "- `passages/<passage_id>.json` — **only** referenced/saved passages",
        "- `provenance/provenance.json` — provenance summary (witnesses, layers, trace)",
        "- `project/project.json` — project metadata and user blocks (if any)",
        "- `bibliography/bibliography.json` — user bibliography refs (not CorpusSource)",
        "",
        "> This bundle is a USER_WORKSPACE export. It is **not** evidence by itself:",
        "> every scholarly claim must be re-derived from the corpus by a research call.",
        "> The corpus is not copied into the bundle — only the referenced passages.",
        "",
        "Verify with `export_system.manifest.verify_bundle(path)`.",
        "",
    ])


def build_bundle(doc, *, include_context=0, root="default", make_zip=True,
                 include_audit=False, audit=None):
    """构建目录 bundle → verify → 原子 finalize（可选 zip）。"""
    include_context = int(include_context or 0)
    if include_context not in (0, 2, 5):
        raise ExportError("EXPORT_POLICY_DENIED",
                          "include_context must be 0, 2 or 5",
                          {"include_context": include_context})
    if (doc.get("snapshot_integrity") or "VERIFIED") == "MODIFIED" \
            and not (doc.get("export_options") or {}).get("allow_modified"):
        raise ExportError("BUNDLE_VERIFICATION_FAILED",
                          "refusing to bundle a MODIFIED snapshot without explicit opt-in")
    files, counts = build_files(doc, include_context=include_context)
    # ★ Phase 5A §46：Audit Bundle —— 把校验器诊断/验证轨迹作为**独立**审计文件随包，
    #   标准导出正文不含它们。审计文件同样进入 manifest 与 bundle_hash（可验证、可篡改检测）。
    if include_audit:
        audit = dict(audit or {})
        audit.setdefault("schema_version", "answer-audit/v1")
        audit["presentation_taxonomy_version"] = "presentation-taxonomy/v1"
        files.append(("audit/answer_audit_diagnostics.json",
                      json.dumps(audit, ensure_ascii=False, indent=2,
                                 sort_keys=True).encode("utf-8")))
        files.append(("audit/rejected_claims.json",
                      json.dumps(audit.get("rejected") or [], ensure_ascii=False,
                                 indent=2, sort_keys=True).encode("utf-8")))
        files.append(("audit/validation_trace.json",
                      json.dumps({"repaired": audit.get("repaired") or [],
                                  "prevalidation_dropped":
                                      audit.get("prevalidation_dropped") or [],
                                  "c_stage_dropped": audit.get("c_stage_dropped") or [],
                                  "quote_fixes": audit.get("quote_fixes") or [],
                                  "brief_answer_verbatim":
                                      audit.get("brief_answer_verbatim"),
                                  "routed_sections": audit.get("routed_sections") or [],
                                  "derived_from_legacy":
                                      audit.get("derived_from_legacy")},
                                 ensure_ascii=False, indent=2,
                                 sort_keys=True).encode("utf-8")))
    created = POL.now_iso()
    man = MF.build_manifest(doc, files, created_at=created,
                            citations=counts["citations"], passages=counts["passages"])
    # §28：context 选项必须写进 manifest（否则收件人无法知道 bundle 里带了什么）
    opts = dict(doc.get("export_options") or {})
    opts["include_context"] = include_context
    opts["include_audit"] = bool(include_audit)
    man["export_options"] = opts
    man["bundle_hash"] = MF.bundle_hash(man)
    files_all = files + [(MF.MANIFEST_NAME,
                          json.dumps(man, ensure_ascii=False, indent=2,
                                     sort_keys=True).encode("utf-8"))]

    root_dir = POL.export_root(root)
    final_dir = os.path.join(root_dir, POL.export_dir_name(doc.get("export_id")))
    temp_dir = POL.temp_dir_for(final_dir)
    try:
        os.makedirs(temp_dir, exist_ok=True)
        for rel, blob in files_all:
            p = os.path.join(temp_dir, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(blob)
        check = MF.verify_bundle(temp_dir, expect_source_id=doc.get("source_id"))
        if check["status"] != "VERIFIED":
            raise ExportError("BUNDLE_VERIFICATION_FAILED",
                              "bundle failed self-verification",
                              {"problems": check["problems"][:8],
                               "status": check["status"]})
        zip_name = None
        if make_zip:
            zip_name = "%s.zip" % POL.export_dir_name(doc.get("export_id"))
            zip_path = os.path.join(temp_dir, zip_name)
            _zip_dir(temp_dir, zip_path, skip={zip_name})
            man["zip"] = zip_name
            man["bundle_hash"] = MF.bundle_hash(man)
            with open(os.path.join(temp_dir, MF.MANIFEST_NAME), "w",
                      encoding="utf-8") as f:
                json.dump(man, f, ensure_ascii=False, indent=2, sort_keys=True)
        POL.atomic_finalize(temp_dir, final_dir)
    except Exception as exc:                                              # noqa: BLE001
        shutil.rmtree(temp_dir, ignore_errors=True)
        if isinstance(exc, ExportError):
            raise
        raise ExportError("EXPORT_WRITE_FAILED", str(exc)[:200])
    final = MF.verify_bundle(final_dir, expect_source_id=doc.get("source_id"))
    POL.audit({"export_id": doc.get("export_id"), "source_type": doc.get("source_type"),
               "source_id": doc.get("source_id"), "format": "bundle", "success": True,
               "file_count": man["file_count"], "bundle_hash": man["bundle_hash"],
               "export_root": root})
    return {"ok": True, "format": "bundle", "dir": final_dir,
            "rel_dir": os.path.relpath(final_dir, POL.VAULT),
            "zip": (os.path.relpath(os.path.join(final_dir, zip_name), POL.VAULT)
                    if zip_name else None),
            "manifest": man, "verify": final, "counts": counts,
            "export_payload_hash": doc.get("export_payload_hash")}


def _zip_dir(src_dir, zip_path, skip=()):
    """ZIP 目录；entry 名经过安全化，防 zip slip（§48）。"""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src_dir):
            for fn in sorted(files):
                p = os.path.join(root, fn)
                rel = os.path.relpath(p, src_dir).replace(os.sep, "/")
                if rel in skip or rel.endswith(".zip"):
                    continue
                if rel.startswith("/") or ".." in rel.split("/"):
                    continue                     # 绝不写入越界 entry
                z.write(p, POL.safe_name(rel.replace("/", "-")) if False else rel)
    return zip_path


def extract_zip(zip_path, dest_dir):
    """安全解压（防 zip slip）：任何越界 entry 直接拒绝。"""
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith("/") or "\\" in name or ".." in name.split("/"):
                raise ExportError("EXPORT_POLICY_DENIED",
                                  "refusing unsafe zip entry: %r" % name)
            target = os.path.abspath(os.path.join(dest_dir, name))
            if not target.startswith(os.path.abspath(dest_dir) + os.sep):
                raise ExportError("EXPORT_POLICY_DENIED",
                                  "zip entry escapes destination: %r" % name)
        z.extractall(dest_dir)
    return dest_dir
