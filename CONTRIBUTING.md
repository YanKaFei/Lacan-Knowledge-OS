# CONTRIBUTING.md

Thank you for wanting to move this forward. This project is explicitly built to be
**forked and evolved** — but it has one non-negotiable rule, and it is worth understanding why.

---

## The rule

> **Do not change scholarly semantics without a Core Change Request (CCR).**

The system is split into two planes:

| Plane | Where | Can you change it freely? |
|---|---|---|
| **Product** | `workspace_ui/`, `browse_api/`, `project_api/`, `export_system/`, `bibliography/`, `obsidian_adapter/`, docs, tests, Help | **Yes.** |
| **Product boundary** | `scholarly_api/` (3 hashed components) | Only additively; report it. |
| **Frozen core** | retrieval semantics, evidence contract, sufficiency, synthesis boundary, citation rules, entailment, abstention policy | **No** — this requires a CCR and a new freeze segment. |

`python3 _scripts/_tools/core_freeze.py --verify` recomputes 39 component hashes.
`python3 _scripts/_tools/freeze_lineage.py --verify` proves zero semantic drift across phases.
If you change a frozen component, the launcher **refuses to start** — that is the feature.

### Opening a Core Change Request

```
_core_change_requests/          # schema + template + state machine live here
```

A CCR must state: what semantic behaviour changes, why the current behaviour is wrong,
what evidence supports it, and what the migration does to existing runs. Semantic changes are
recorded as a **new** lineage segment; they never rewrite an existing one.

---

## Development setup

```bash
git clone https://github.com/YanKaFei/Lacan-Knowledge-OS.git
cd Lacan-Knowledge-OS
python3 -m workspace_ui.server.cli --port 3090       # run the UI
```

No bundler, no build step: `workspace_ui/static/index.html` loads ES modules directly. Python
3.9+ with the standard library covers the core path.

### Before you open a pull request

```bash
python3 _scripts/_tools/core_freeze.py --verify      # frozen core intact
python3 _scripts/_tools/freeze_lineage.py --verify   # no semantic drift
python3 _scripts/_tools/build_i18n.py --check        # UI copy ↔ dictionary ↔ call sites
python3 _scripts/_tools/build_help.py --check        # Help links/anchors, 0 fiction
bash _scripts/run_all_tests.sh                       # full regression (needs a corpus)
```

`failed=[]` **and** `skipped=[]` are both required. A skipped suite is not a passing suite.

---

## House rules that reviewers enforce

1. **Never fabricate.** No invented citations, dates, publishers, page numbers, translations or
   metadata. If data is missing, surface `Not linked` / `unavailable` / an explicit reason code.
2. **No silent repair.** If the system cannot do something, it says so — in the UI, in the API
   payload, and in Help. Do not make a limitation look like a success.
3. **AI output never auto-promotes.** Anything model-produced enters as a candidate or a
   proposal. Promotion to canonical is a human act, recorded.
4. **Derivatives stay regenerable.** New derived artifacts must document how to rebuild them;
   the canonical layer is the only source of truth.
5. **Do not weaken a test to make it pass.** Fix the code, or record the defect with evidence.
   Deleting or loosening an assertion is a review blocker.
6. **No documentation fiction.** If Help or the README describes a control, route, status or
   workflow, it must exist and be verifiable. `HELP_CLAIM_VERIFICATION.json` is machine-checked;
   a claim that cannot be verified is a bug in the claim.
7. **Credentials never pass through the product API.** Not as parameters, not in logs, not in
   error messages. See [SECURITY.md](SECURITY.md).
8. **Accessibility is not optional.** Every interactive control needs an accessible name;
   `_scripts/_tools/check_accessibility.py` is part of the gate.
9. **Keep the four-language discipline in UI copy.** New user-visible strings go through the
   i18n dictionary (`build_i18n.py --check` must stay clean). Source text is never translated.

---

## Where help is most welcome

| Area | Idea |
|---|---|
| **Corpus onboarding** | A worked example of ingesting a small public-domain corpus end to end |
| **Retrieval** | Better hybrid ranking; the vector path is optional today |
| **Evidence UI** | Richer context navigation, side-by-side passage comparison |
| **Export** | More internal citation styles, better Obsidian note templates |
| **i18n** | More interface locales (the dictionary pipeline already supports it) |
| **Testing** | Property tests for the passage store; fuzzing the MCP schemas |

## Commit style

Short imperative subject lines. If a change touches a frozen component, say so in the body and
link the CCR. If a change is product-only, say which module.

## License of contributions

By contributing you agree that your contribution is licensed under the Apache License 2.0,
and you confirm you have the right to submit it. **Never** submit third-party source text that
you are not entitled to redistribute — that is the fastest way to get a pull request closed.
