# 00 — Overview & System-Wide Requirements

## What Odysseus is

A **self-hosted AI workspace**: a single application that provides chat, an autonomous agent, deep research, a model manager, persistent memory, email, calendar, documents, notes, tasks, and related features — running on the operator's own hardware against their own data.

## Principles

1. **Local-first / privacy-first.** User data stays on the operator's machine. Nothing leaves the system unless the operator configures an external provider or integration.
2. **Admin-console posture.** The system exposes powerful capabilities (shell, code execution, model serving, configuration). It is operated by its owner; access is authenticated and privileged actions are gated.
3. **Self-contained but degradable.** Optional capabilities (vector search, web search, email, push notifications) may be unavailable; the system reduces functionality gracefully rather than failing.
4. **Configure in-app.** Most configuration is changeable at runtime through the UI; only deployment-level secrets are supplied before first start.
5. **Capable models.** The agent targets models that support native tool-calling.

---

## System-wide requirements

### Security (`XC-SEC-*`)

- **XC-SEC-1 (MUST).** When authentication is enabled, every request MUST be authenticated before any feature is reached.
- **XC-SEC-2 (MUST).** Privileged operations MUST be restricted to administrators; all other features MUST be governed by per-user privileges.
- **XC-SEC-3 (MUST).** Secrets at rest MUST be protected: reusable secrets (stored credentials, API keys, integration secrets, vault contents) MUST be encrypted, and authentication secrets (login passwords, two-factor seeds, backup codes) MUST be one-way hashed rather than recoverable.
- **XC-SEC-4 (MUST).** Authentication MUST support password login and optional time-based two-factor (TOTP) with recoverable backup codes.
- **XC-SEC-5 (MUST).** Untrusted external content (web pages, fetched URLs, emails, uploaded files, retrieved documents, transcripts, and the active editor document) included in a model prompt MUST be marked as untrusted so the model treats it as data, not instructions.
- **XC-SEC-6 (MUST).** Each user MUST only be able to read or modify their own data; ownership checks MUST deny access to other users' records rather than silently succeeding.

### Configuration (`XC-CFG-*`)

- **XC-CFG-1 (MUST).** Deployment-level secrets and defaults (authentication toggle, database location, default model host, service endpoints, initial admin password) MUST be configurable before first start.
- **XC-CFG-2 (SHOULD).** User-facing settings SHOULD be changeable at runtime without restarting the application, and MAY be overridable per user for a defined set of preferences.

### Data (`XC-DATA-*`)

- **XC-DATA-1 (MUST).** All user data MUST be stored locally under the application's data area and MUST NOT be transmitted externally except through operator-configured integrations.
- **XC-DATA-2 (MUST).** Schema changes MUST be applied automatically on startup so an existing installation upgrades in place without manual migration steps.

### Availability & degradation (`XC-DEG-*`)

- **XC-DEG-1 (SHOULD).** If vector search is unavailable, features that rely on it (memory recall, semantic retrieval) SHOULD fall back to keyword behavior rather than erroring.
- **XC-DEG-2 (SHOULD).** If web search is unavailable, dependent features SHOULD report a clear unavailable state and MUST NOT hang or loop indefinitely.
- **XC-DEG-3 (SHOULD).** The health of external services (vector store, web search, email, push, model endpoints) SHOULD be observable to the operator.

### Performance & responsiveness (`XC-PERF-*`)

- **XC-PERF-1 (MUST).** A request that hangs MUST be terminated by a server-side timeout rather than holding a connection open indefinitely.
- **XC-PERF-2 (MUST).** A stalled or runaway model response MUST be cut off by both an inactivity timeout and an overall wall-clock limit.
- **XC-PERF-3 (SHOULD).** Model-generated output that is shown to the user SHOULD stream incrementally as it is produced, rather than appearing only when complete.
- **XC-PERF-4 (SHOULD).** Frequently repeated, expensive lookups (search results, synthesized audio, inbox listings) SHOULD be cached with an appropriate freshness window.
