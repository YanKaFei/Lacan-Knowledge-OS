#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_system.html — ExportDocument → standalone HTML（4D.6 §32/§33）

要求：
    * **standalone**：单文件、无 CDN、无远程 JS、无外部字体；
    * **printable**：一份打印样式；
    * **safe**：question / user note / corpus text / metadata **全部 escape**；
      禁止 raw HTML、`<script>`、`javascript:` URL。

实现上只用 `html.escape` + 纯 CSS，不引入任何模板引擎。
"""
from __future__ import annotations

from html import escape

from . import citations as C
from .model import ABSTENTION_TITLE, USER_BLOCK_LABELS

_CSS = """
:root { --bg:#f7f6f3; --panel:#fff; --ink:#1c1b19; --ink2:#43403b; --ink3:#6f6a62;
        --line:#ded9d1; --accent:#6b4c2f; --soft:#f0e7dc; --warn:#8a6d1f; --warnbg:#fbf3dd;
        --ok:#3f6b4a; --err:#8c3b32; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif; }
main { max-width:900px; margin:0 auto; padding:32px 28px 64px; background:var(--panel);
       box-shadow:0 1px 2px rgba(28,27,25,.05),0 6px 20px rgba(28,27,25,.04); }
h1,h2,h3 { font-family:"Iowan Old Style",Palatino,Georgia,"Songti SC",serif; line-height:1.3; }
h1 { font-size:26px; margin:0 0 6px; } h2 { font-size:19px; margin:26px 0 8px;
     border-bottom:1px solid var(--line); padding-bottom:5px; }
h3 { font-size:16px; margin:18px 0 6px; }
.meta { color:var(--ink3); font-size:13px; }
.kv { display:grid; grid-template-columns:200px 1fr; gap:3px 14px; margin:10px 0 0; }
.kv dt { color:var(--ink3); } .kv dd { margin:0; font-family:ui-monospace,Menlo,monospace;
  font-size:13px; word-break:break-all; }
blockquote { border-left:3px solid var(--soft); margin:12px 0; padding:8px 0 8px 14px;
  font-family:"Iowan Old Style",Georgia,serif; font-size:18px; white-space:pre-wrap; }
.tag { display:inline-block; background:var(--soft); border:1px solid #e4d5c2;
  border-radius:3px; padding:0 6px; font-size:11px; color:var(--accent); margin-right:5px; }
.tag.warn { background:var(--warnbg); border-color:#ecdcae; color:var(--warn); }
.tag.ok { background:#e8f1ea; border-color:#cde0d2; color:var(--ok); }
.warnbox { background:var(--warnbg); border:1px solid #ecdcae; color:var(--warn);
  padding:8px 12px; border-radius:5px; font-size:13px; margin:10px 0; }
.userblock { border-left:3px solid var(--line); padding-left:12px; margin:16px 0;
  background:#fbfaf8; }
.userblock h2 { border:0; }
.scholarly { border-left:3px solid var(--accent); padding-left:12px; }
pre { background:#f4f2ee; padding:10px 12px; border-radius:5px; overflow-x:auto;
  font-size:13px; white-space:pre-wrap; }
code { font-family:ui-monospace,Menlo,monospace; font-size:13px; }
footer { border-top:1px solid var(--line); margin-top:28px; padding-top:10px;
  color:var(--ink3); font-size:12px; }
@media print { body{background:#fff;} main{box-shadow:none;max-width:none;padding:0;} }
"""


def _esc(value):
    return escape(str(value if value is not None else ""), quote=True)


def _kv(rows):
    items = []
    for k, v in rows:
        if v in (None, "", []):
            continue
        items.append("<dt>%s</dt><dd>%s</dd>" % (_esc(k), _esc(v)))
    return "<dl class=\"kv\">%s</dl>" % "".join(items) if items else ""


def _state_badge(doc):
    st = doc.get("answer_state") or "—"
    cls = "warn" if st in ("ABSTAINED", "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE",
                           "PARTIALLY_SUPPORTED") else (
        "ok" if st == "VALIDATED" else "")
    extra = ""
    if st == "VALIDATED_WITH_QUALIFICATIONS":
        extra = " <span class=\"tag\">Qualified answer</span>"
    elif st == "PARTIALLY_SUPPORTED":
        extra = " <span class=\"tag warn\">Partially supported — not fully validated</span>"
    elif st == "VALIDATION_FAILED":
        extra = " <span class=\"tag warn\">Validation failed — not a result</span>"
    elif st == "INSUFFICIENT_EVIDENCE":
        extra = " <span class=\"tag warn\">Insufficient evidence</span>"
    return "<span class=\"tag %s\">%s</span>%s" % (cls, _esc(st), extra)


def render(doc, *, title=None):
    h = ["<!DOCTYPE html>", "<html lang=\"zh\"><head><meta charset=\"utf-8\">",
         "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
         "<title>%s</title>" % _esc(title or doc.get("title") or "Export"),
         "<style>%s</style>" % _CSS, "</head><body><main>"]
    h.append("<h1>%s</h1>" % _esc(doc.get("title")))
    h.append("<p class=\"meta\">%s · evidence role <code>%s</code></p>"
             % (_state_badge(doc), _esc(doc.get("evidence_role"))))
    if doc.get("question"):
        h.append("<h2>Research question</h2><p>%s</p>" % _esc(doc["question"]))
    h.append("<h2>Research metadata</h2>")
    h.append(_kv([("Task type", doc.get("task_type")),
                  ("Source", "%s / %s" % (doc.get("source_type"), doc.get("source_id"))),
                  ("Created", doc.get("created_at")),
                  ("Core freeze", doc.get("core_freeze_version")),
                  ("Source answer hash", doc.get("source_answer_hash")),
                  ("Export payload hash", doc.get("export_payload_hash")),
                  ("Exporter", doc.get("exporter_version")),
                  ("Snapshot integrity", doc.get("snapshot_integrity"))]))
    if doc.get("snapshot_integrity") == "MODIFIED":
        h.append("<div class=\"warnbox\">Snapshot integrity: <strong>MODIFIED</strong> — "
                 "this workspace snapshot no longer matches its stored hash.</div>")

    ab = doc.get("abstention")
    if ab:
        h.append("<div class=\"scholarly\"><h2>%s</h2>"
                 % _esc(ab.get("title") or ABSTENTION_TITLE))
        for label, key in (("Why this cannot be answered", "categories"),
                           ("Missing information", "missing_information"),
                           ("Available partial information",
                            "available_partial_information"),
                           ("Sources needed", "required_sources")):
            items = ab.get(key) or []
            if not items:
                continue
            h.append("<h3>%s</h3><ul>%s</ul>"
                     % (_esc(label), "".join("<li>%s</li>" % _esc(x) for x in items)))
        h.append("</div>")
    if doc.get("sections"):
        h.append("<div class=\"scholarly\"><h2>Scholarly answer</h2>")
        for s in doc["sections"]:
            h.append("<h3>%s%s</h3><p>%s</p>"
                     % (_esc(s.get("label")),
                        " <span class=\"tag\">internal</span>" if s.get("internal") else "",
                        _esc(s.get("text"))))
        h.append("</div>")
    if doc.get("claims"):
        h.append("<h2>Validated claims</h2>")
        for c in doc["claims"]:
            h.append("<h3>Claim <code>%s</code></h3><p>%s</p><p class=\"meta\">%s</p>"
                     % (_esc(c.get("claim_id")), _esc(c.get("claim_text")),
                        _esc(" · ".join(x for x in (c.get("epistemic_label"),
                                                    c.get("claim_type")) if x))))
            b = [x for x in (doc.get("claim_bindings") or {}).get("bindings", [])
                 if x.get("claim_id") == c.get("claim_id")]
            if b and b[0].get("citation_ids"):
                h.append("<p class=\"meta\">Evidence: %s</p>"
                         % _esc(", ".join(C.short_citation(p)
                                          for p in b[0]["citation_ids"])))
    if doc.get("citations"):
        h.append("<h2>Citations</h2><ul>")
        for rec in doc["citations"]:
            h.append("<li><code>%s</code> — %s<br><span class=\"meta\">%s</span>"
                     % (_esc(rec["passage_id"]), _esc(rec["internal_full"]),
                        _esc(rec["provenance"])))
            if rec.get("quoted_span"):
                h.append("<br><span class=\"meta\">quoted span: %s</span>"
                         % _esc(rec["quoted_span"][:200]))
            if rec.get("provenance_status") == "SOURCE_TRACE_INCOMPLETE":
                h.append("<br><span class=\"tag warn\">SOURCE_TRACE_INCOMPLETE</span>")
            if rec.get("witness") is None:
                h.append("<br><span class=\"meta\">witness: <code>null</code></span>")
            h.append("</li>")
        h.append("</ul>")
    if doc.get("limitations"):
        h.append("<h2>Source limitations</h2><ul>%s</ul>"
                 % "".join("<li>%s</li>" % _esc(x) for x in doc["limitations"]))
    if doc.get("warnings"):
        h.append("<h2>Warnings</h2><ul>%s</ul>" % "".join(
            "<li>%s</li>" % _esc(w if not isinstance(w, dict)
                                 else "%s — %s" % (w.get("code"), w.get("message")))
            for w in doc["warnings"]))

    p = doc.get("passage")
    if p:
        h.append("<h2>Passage</h2><blockquote>%s</blockquote>" % _esc(p.get("text")))
        h.append(_kv([("Seminar", p.get("seminar")), ("Session", p.get("session")),
                      ("Language", p.get("language")),
                      ("Source layer", p.get("source_layer")),
                      ("Witness", p.get("witness") if p.get("witness") else "null"),
                      ("Provenance", p.get("provenance_status"))]))
        if p.get("trace_incomplete"):
            h.append("<div class=\"warnbox\">SOURCE_TRACE_INCOMPLETE — %s</div>"
                     % _esc(p.get("witness_note") or "来源链未闭合"))
        if p.get("context"):
            h.append("<h3>Context (±%d)</h3><ul>%s</ul>"
                     % (len(p["context"]),
                        "".join("<li><code>%s</code> %s</li>"
                                % (_esc(c["passage_id"]), _esc((c.get("text") or "")[:400]))
                                for c in p["context"])))

    proj = doc.get("project")
    if proj:
        h.append("<h2>Project</h2>")
        h.append(_kv([("Project id", proj.get("project_id")),
                      ("Status", proj.get("status")), ("Revision", proj.get("revision")),
                      ("Created", proj.get("created_at")), ("Updated", proj.get("updated_at")),
                      ("Tags", ", ".join(proj.get("tags") or []) or "—"),
                      ("Snapshot verification", proj.get("snapshot_verification")),
                      ("Evidence role", proj.get("evidence_role"))]))
        if proj.get("description"):
            h.append("<p>%s</p>" % _esc(proj["description"]))
        if proj.get("research_questions"):
            h.append("<h3>Research questions</h3><ul>%s</ul>" % "".join(
                "<li>[%s] %s</li>" % (_esc(q.get("status")), _esc(q.get("text")))
                for q in proj["research_questions"]))
        if proj.get("runs_index"):
            h.append("<h3>Research runs index</h3><ul>%s</ul>" % "".join(
                "<li><code>%s</code> · %s · %s citations</li>"
                % (_esc(r["answer_state"]), _esc(r["question"]), r["citations"])
                for r in proj["runs_index"]))
        for key in ("saved_concepts", "saved_seminars", "saved_passages", "saved_terms"):
            vals = proj.get(key) or []
            if vals:
                h.append("<h3>%s</h3><ul>%s</ul>"
                         % (_esc(key.replace("saved_", "").title()),
                            "".join("<li><code>%s</code></li>" % _esc(v) for v in vals)))
        if proj.get("broken_references"):
            h.append("<div class=\"warnbox\">BROKEN_REFERENCE: %s</div>"
                     % _esc(", ".join(proj["broken_references"])))

    ub = doc.get("user_blocks") or {}
    if ub.get("user_hypotheses"):
        h.append("<div class=\"userblock\"><h2>%s</h2><div class=\"warnbox\">"
                 "USER HYPOTHESIS — NOT VALIDATED BY THE SCHOLARLY CORE</div><ul>%s</ul></div>"
                 % (_esc(USER_BLOCK_LABELS["user_hypotheses"]),
                    "".join("<li>%s</li>" % _esc(x.get("text"))
                            for x in ub["user_hypotheses"])))
    if ub.get("open_questions"):
        h.append("<div class=\"userblock\"><h2>%s</h2><ul>%s</ul></div>"
                 % (_esc(USER_BLOCK_LABELS["open_questions"]),
                    "".join("<li>%s <span class=\"meta\">(origin: %s)</span></li>"
                            % (_esc(q.get("text")), _esc(q.get("origin")))
                            for q in ub["open_questions"])))
    if ub.get("user_notes"):
        h.append("<div class=\"userblock\"><h2>%s</h2>%s</div>"
                 % (_esc(USER_BLOCK_LABELS["user_notes"]),
                    "".join("<h3>%s</h3><p>%s</p>" % (_esc(n.get("title") or n.get("id")),
                                                      _esc(n.get("text")))
                            for n in ub["user_notes"])))
    if ub.get("bibliography"):
        h.append("<div class=\"userblock\"><h2>%s</h2><p class=\"meta\">A BibliographyRef "
                 "is not a CorpusSource.</p><ul>%s</ul></div>"
                 % (_esc(USER_BLOCK_LABELS["bibliography"]),
                    "".join("<li>%s%s</li>" % (_esc(b.get("title")),
                                              (" _(missing: %s)_"
                                               % _esc(", ".join(b["missing_fields"])))
                                              if b.get("missing_fields") else "")
                            for b in ub["bibliography"])))

    prov = doc.get("provenance") or {}
    if prov:
        h.append("<h2>Provenance summary</h2>")
        h.append(_kv([("Citation source layers",
                       ", ".join("%s ×%d" % (k, v) for k, v in
                                 sorted((prov.get("citation_layers") or {}).items())) or "—"),
                      ("Witnesses", ", ".join(prov.get("witnesses") or []) or "—"),
                      ("Passages without witness",
                       ", ".join(prov.get("passages_without_witness") or []) or "—"),
                      ("Source trace incomplete",
                       "yes" if prov.get("source_trace_incomplete") else "no")]))
        chain = (prov.get("source_trace") or {}).get("chain")
        if chain:
            h.append("<h3>Source trace</h3><ul>%s</ul>" % "".join(
                "<li>%s <code>%s</code>%s</li>"
                % (_esc(s.get("step")), _esc(s.get("id") or "—"),
                   "" if s.get("present") else " ← <strong>break</strong>")
                for s in chain))

    h.append("<footer>Exported by <code>%s</code> · schema <code>%s</code> · "
             "payload hash <code>%s</code></footer>"
             % (_esc(doc.get("exporter_version")), _esc(doc.get("schema_version")),
                _esc((doc.get("export_payload_hash") or "")[:16])))
    h.append("</main></body></html>")
    return "\n".join(h)
