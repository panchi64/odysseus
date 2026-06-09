# 00 — Overview & System-Wide Requirements

## What Odysseus is

A **self-hosted AI workspace**: a single application that provides chat, an autonomous agent, deep research, a model manager, persistent memory, email, calendar, documents, notes, tasks, and related features — running on the operator's own hardware against their own data.

## Principles

1. **Local-first / privacy-first.** User data stays on the operator's machine. Nothing leaves the system unless the operator configures an external provider or integration.
2. **Admin-console posture.** The system exposes powerful capabilities (shell, code execution, model serving, configuration). It is operated by its owner; access is authenticated and privileged actions are gated.
3. **Self-contained but degradable.** Optional capabilities (vector search, web search, email, push notifications) may be unavailable; the system reduces functionality gracefully rather than failing.
4. **Configure in-app.** Most configuration is changeable at runtime through the UI; only deployment-level secrets are supplied before first start.
5. **Capable models.** The agent targets models that support native tool-calling.
6. **Platform-agnostic.** The system runs on common operator platforms (Linux, macOS, and other POSIX hosts) with no dependency on any single operating system's facilities.

---

## System-wide requirements

### Security (`XC-SEC-*`)

- **XC-SEC-1 (MUST).** When authentication is enabled, every request MUST be authenticated before any feature is reached.
- **XC-SEC-2 (MUST).** The system targets a **single operator**; all data and features belong to that operator. Sensitive or hard-to-reverse operations MUST require the operator's explicit approval before they take effect (see `AE-3`). Multi-user privilege separation is out of current scope and MAY be introduced later without changing this posture.
- **XC-SEC-3 (MUST).** All user data at rest MUST be encrypted, using encryption whose confidentiality remains secure against quantum-capable adversaries (resistant to known quantum attacks, not merely classical ones) — no user information may be stored in plainly-readable form. Reusable secrets (stored credentials, API keys, integration secrets, vault contents) MUST be encrypted. Authentication secrets (login passwords, two-factor seeds, backup codes) are the exception: they MUST be one-way hashed rather than encrypted, so they are never recoverable.
- **XC-SEC-4 (MUST).** Authentication MUST support password login and optional time-based two-factor (TOTP) with recoverable backup codes.
- **XC-SEC-5 (MUST).** Untrusted external content (web pages, fetched URLs, emails, uploaded files, retrieved documents, transcripts, and the active editor document) included in a model prompt MUST be marked as untrusted so the model treats it as data, not instructions.
- **XC-SEC-6 (MUST).** Every record MUST be attributed to an owner. With a single operator, all data belongs to that operator; should multiple accounts be introduced, a user MUST only be able to read or modify their own data, with ownership checks denying access to others' records rather than silently succeeding.

### Configuration (`XC-CFG-*`)

- **XC-CFG-1 (MUST).** Deployment-level secrets and defaults (authentication toggle, database location, default model host, service endpoints, initial admin password) MUST be configurable before first start.
- **XC-CFG-2 (SHOULD).** User-facing settings SHOULD be changeable at runtime without restarting the application, and MAY be overridable per user for a defined set of preferences.

### Portability (`XC-PORT-*`)

- **XC-PORT-1 (MUST).** The system MUST run on Linux, macOS, and other POSIX hosts without relying on any operating-system-specific facility for core function (storage, encryption, key custody, scheduling). Where a platform-specific capability is used, it MUST be optional and have a portable default.

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
