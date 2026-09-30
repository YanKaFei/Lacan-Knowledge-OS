# SECURITY.md

## Reporting a vulnerability

Open a **private** security advisory on GitHub (Security → Advisories → *Report a vulnerability*),
or contact the maintainer through the repository profile.

Please include: what you found, how to reproduce it, the impact you believe it has, and whether
you need credit. Do not open a public issue for an exploitable problem before a fix is available.

---

## Credential discipline (the part that matters here)

This project talks to real LLM endpoints, so credentials are a first-class concern. The rules
below are enforced by tests, not by convention.

| Rule | Enforcement |
|---|---|
| Credentials never pass **through the product API** | `workspace_ui/server/provider_view.py` accepts only `model` and `base_url`; no key field exists |
| Credentials are never **echoed** | The connection self-test reports status, latency, model name and error *type* only |
| Credentials are never **logged** | The acceptance suite scans run artifacts and application logs for key-like patterns (`F14` gate item, 0 findings required) |
| Credentials are read from **environment or `~/.dsh/.credentials.yaml`** | Both are read at call time by the provider adapter, never cached into product state |
| Persisted settings contain **no secrets** | `_workspace/settings/provider.json` holds `model` / `base_url` only |

If you find any path that prints, stores or transmits a credential, that is a security bug —
report it as such.

---

## Threat model

**In scope**

- A malicious or compromised **model endpoint** returning hostile content (the system treats all
  model output as untrusted and validates every claim against the corpus).
- Malicious **corpus text** attempting to inject markup or scripts into the UI (the frontend
  never uses `innerHTML`; all rendering goes through a DOM builder with `textContent`).
- A hostile **MCP client** sending malformed tool arguments (strict schemas, fail-closed).
- **Local file exfiltration** attempts through the product's write paths (writes are confined to
  the user workspace; the corpus layer is read-only in the product).

**Out of scope**

- Physical access to the machine, or a compromised local user account.
- The rights and licensing status of any corpus *you* ingest (see [CORPUS.md](CORPUS.md)).
- Model providers' own data handling. When you configure a real provider, prompts leave your
  machine by design. Offline / Mock mode never makes a network call.

---

## Defence in depth in this codebase

| Layer | Measure |
|---|---|
| Front end | No `innerHTML`, no `eval`; all user/corpus text is rendered as text nodes |
| Scheduling | Research requests are length-checked and **never silently truncated** |
| API | Per-route payload limits; unknown routes return a structured error, not a stack trace |
| Boundary | The frozen core is hash-verified at startup; a mismatch disables research and says why |
| Secrets | Product API has no credential input path; run artifacts are scanned for key patterns |
| Supply chain | Core path is Python standard library only; optional extras are opt-in and documented |

## Supported versions

The `main` branch is the supported line. Frozen scholarly components are versioned by freeze
segment, not by release branch — a security fix that would change scholarly semantics still
requires a Core Change Request (see [CONTRIBUTING.md](CONTRIBUTING.md)).
