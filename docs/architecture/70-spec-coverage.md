# 70 — Spec Coverage Matrix

> **Traceability between the spec (`docs/spec/`) and the build (`backend/`).** Every black-box requirement, mapped to its implementation status, the code that realizes it, and the decision behind it. This is the "what's done vs. next" view for planning — kept current as slices land. The spec is the contract; this is the ledger against it.
>
> Status is judged against *backend* behavior. Frontend-only requirements (in-browser runners, rendering) are marked as such. When a status is anything but ✅, the **Notes** say what remains.

## How to read this

| Mark | Meaning |
|---|---|
| ✅ | **Built & tested** — implemented in `backend/`, with tests. |
| 🟢 | **Active slice** — being built right now (the current working set). |
| 🟡 | **Partial** — the foundation is in; a named piece remains. |
| 🔭 | **Deferred by decision** — design is settled (a D-number), build is deliberately held until its feature/seam is in scope. The seam is reserved; this is *not* an oversight. |
| ⬜ | **Pending** — capability/feature not yet started. |

**Rollup (≈153 requirements).** Foundation + first slices are in: the agent engine, run substrate, event protocol, approval, memory, auth, at-rest encryption, model registry, the code-execution sandbox (built — per-conversation live session, host-isolated, fail-closed), and the first surfaces on top of it — encrypted **artifacts** + live **previews** (token-gated reverse proxy) and a **conversation** read/manage layer. The long tail — most feature surfaces (mail, calendar, documents, research, model serving, uploads, …) — is pending, awaiting its `services/` capability. The pattern throughout: **the hard cross-cutting machinery is built once and inherited; each pending feature is now "add a capability + a thin tool + a route," not new infrastructure.**

---

## Cross-cutting — Security (`XC-SEC-*`)

| Req | Status | Realized by | Notes |
|---|---|---|---|
| XC-SEC-1 auth before any feature; locked-until-unlocked | ✅ | `core/auth` ASGI gate, `core/vault` | Global gate; restart re-locks. |
| XC-SEC-2 single operator, approval-gated | ✅ | D14 throughout | No tiers; sensitivity, not privilege. |
| XC-SEC-3 all data AES-256 at rest; password one-way hashed | ✅ | `core/crypto` (AES-256-GCM), `core/vault` (Argon2id verifier) | App-layer per-column AEAD (D17). |
| XC-SEC-4 password derives the at-rest key (login == unlock) | ✅ | `core/vault` (Argon2id KDF → memory-only DEK) | One event, no separate credential store. |
| XC-SEC-5 untrusted external content marked as data | 🟡 | `core/untrusted.py` (`wrap_untrusted`); applied in `services/search` to fetched pages + search snippets | Marking built and applied at the first ingester (web): sentinel-delimited block + standing "treat as data" instruction. `ReinjectSystemPrompt` (poisoned-history defense) still pending; extends to uploads/mail as they land. |
| XC-SEC-6 every record owner-stamped | ✅ | `owner_id` on every `models/` entity | Multi-user enforcement deferred (one human). |
| XC-SEC-7 agent code exec isolated from host; disabled if no sandbox | ✅ | `services/sandbox`, `tools/code.py` | Container backend; fail-closed (no runtime ⇒ capability absent), never host fallback (D23). Per-conversation live session, idle-reaped, vault-sealed workspace. |

## Cross-cutting — Config / Portability / Data (`XC-CFG-*`, `XC-PORT-*`, `XC-DATA-*`)

| Req | Status | Realized by | Notes |
|---|---|---|---|
| XC-CFG-1 deploy secrets before first start | ✅ | `core/config` (`.env`) | DB location, defaults, initial password. |
| XC-CFG-2 user settings runtime-mutable | 🟡 | `services/registry` (model roles/endpoints at `/models/*`) | Model config is runtime-mutable; a general settings store is not yet generalized. |
| XC-PORT-1 runs on Linux/macOS/POSIX, no OS-specific facility | ✅ | no OS keystore (D17), `pathlib`, container sandbox | Crypto/storage on cross-platform wheels. |
| XC-DATA-1 data stored locally, not transmitted | ✅ | SQLite under `data/` | Nothing external except configured integrations. |
| XC-DATA-2 schema auto-upgrades on startup | ✅ | `core/db` + `migrations/` (Alembic, auto-upgrade to head) | No manual step (D7). |

## Cross-cutting — Degradation / Performance (`XC-DEG-*`, `XC-PERF-*`)

| Req | Status | Realized by | Notes |
|---|---|---|---|
| XC-DEG-1 vector search → keyword fallback | ✅ | `services/memory` (hybrid, RRF; degrades to keyword) | Honored end to end (D18-as-built). |
| XC-DEG-2 web search unavailable → clear state, no hang | ✅ | `services/search` (`DegradedCapabilityError`), `tools/search.py`, `routes/overview` | No enabled provider ⇒ tools return "unavailable" and overview warns; an empty result set is a valid answer. No hang or loop. |
| XC-DEG-3 external-service health observable | 🟡 | `routes/overview.py` (`GET /overview`: per-capability health for main model / embeddings / sandbox — backend-decided status + remediation) + `/health` (liveness) | The home page renders these. Capabilities not yet built (web search, email, push, vector store) are deferred — they grow rows here as they land. |
| XC-PERF-1 hung request killed by server-side timeout | ✅ | `runs/registry` (wall-clock bound) | |
| XC-PERF-2 stalled model cut by inactivity + wall-clock | ✅ | `runs/registry` (`RunTimeout` kinds: `inactivity`, `wall_clock`) | Watchdog on `Run.touch()`. |
| XC-PERF-3 output streams incrementally | ✅ | `runs/transport` (SSE), `answer.delta` | |
| XC-PERF-4 expensive lookups cached | ⬜ | — | Search/audio/inbox caching — those features unbuilt. |

---

## Agent engine (`AE-*`)

| Req | Status | Realized by | Notes |
|---|---|---|---|
| AE-1.1 multi-step tool→observe→continue | ✅ | `agent/engine` via `agent.iter()` | Pydantic AI loop, observed per node. |
| AE-1.2 deterministic terminal outcome (done/blocked/pause/bound/cancel) | ✅ | `runs/run` `RunStatus`; `agent/engine` | No silent/indeterminate end. |
| AE-1.3 agent acts on tool results | ✅ | Pydantic AI loop | |
| AE-1.4 in-turn self-check of deliverables | ✅ | system prompt + the `AE-5.2` verifier | Systemic counterpart below. |
| AE-1.5 max-step bound, report on hit | ✅ | engine step ceiling | |
| AE-1.6 optional per-turn tool-call ceiling | 🟡 | run bounds | SHOULD; ceiling seam present, not fully wired. |
| AE-2 tool categories | 🟡 | `tools/` (`builtin`, `memory`, `code`, `preview`) | 4 of ~14 categories built; rest land with their capability. See [`40-tools-and-toolsets.md`](./40-tools-and-toolsets.md). |
| AE-2.1 typed params + arg validation | ✅ | Pydantic AI tool schemas | |
| AE-2.2 tool always returns actionable result; failure ≠ abort | ✅ | tools return error payloads, not raises | memory/code tools model this. |
| AE-3.1 sensitive set requires explicit approval | ✅ | D20 deferred-tool pause; `tools/code.py` host tool | Mechanism built; expands as sensitive tools land. |
| AE-3.2 approval channel per run; pause unattended | 🟡 | inline approval + `/runs/{id}/approve` | Interactive path ✅; unattended push/email channel ⬜. |
| AE-3.3 operator can disable individual tools | ✅ | `tools/toolsets` `_enabled_gate` | |
| AE-3.4 host-exec approval carries plain-language explanation | ✅ | `tools/code.py` `run_host_command(explanation=…)` | Explanation surfaced on `approval.required` (D23). |
| AE-3.5 scheduled-task pre-authorization (scoped standing grant) | 🔭 | — | Designed (D24); lands with `TASK-*`. |
| AE-3.6 external tools sensitive-by-default + trusted opt-out | 🔭 | — | Designed (D25); lands with `MCP-*`/`INTEG-*`. |
| AE-4.1 lean catalog, no runtime relevance filter | ✅ | `tools/toolsets` (no `.prepared()` step) | By design (D3); seam reserved. |
| AE-4.2 every permitted tool available whole turn | ✅ | full gated catalog always offered | Doc-tools-when-open holds once docs land. |
| AE-5.1 no infinite loop / no-progress stop | ✅ | `agent/meta` loop-breaker | Always-on. |
| AE-5.2 post-turn verifier + bounded corrective re-attempt | ✅ | `agent/meta` + `agent/engine` | Opt-in, capped (D4). |
| AE-5.3 prioritized endpoints, fall back on failure | ✅ | `services/llm` `FallbackModel` chain | Pre-stream only. |
| AE-5.4 context reduction near limit | 🔭 | — | Decided (D6: history-processor hybrid); impl deferred. Ties `CHAT-4`. |
| AE-6.1 stream activity (text, tools, steps, metrics, errors, end) | ✅ | `runs/events` (frozen v1), `agent/translate` | |
| AE-6.2 document content streams into a version | 🔭 | — | Deferred (D21); with `DOC-*`. |
| AE-6.3 reasoning distinguishable from answer | ✅ | `thinking.delta` vs `answer.delta` | |
| AE-6.4 auto-promote inline blocks to documents | 🔭 | — | Deferred (D21). |
| AE-7.1 run survives disconnect; reconnect replays missed | ✅ | `runs/stream` (buffer + broker + `Last-Event-ID`), `runs/registry` | Not required across server restart. |
| AE-8.1 native tool-calling models only | ✅ | model registry; owner profile | Out-of-scope models excluded by design. |

---

## Feature inventory — A. Conversation

| Req | Status | Realized by | Notes |
|---|---|---|---|
| CHAT-1 send text/links/files, streamed reply | 🟡 | `routes/chat`, run substrate, `services/conversations` | Text+stream+persistence ✅; attachments/links ⬜ (D22). |
| CHAT-2 links/files as model context | 🔭 | — | Deferred (D22, ingestion pipeline). |
| CHAT-3 every message runs the agent path | ✅ | `agent/engine` single path | No pre-classification (D5). |
| CHAT-4 summarize near context limit (utility model) | 🔭 | — | With `AE-5.4` (D6). Utility role already exists in the registry. |
| CHAT-5 stop in-progress; resume after disconnect | ✅ | `/runs/{id}/cancel`, `runs/stream` | |
| CHAT-6 ask AI to rewrite/rephrase a message | ⬜ | — | SHOULD; not built. |

> **Supporting infra, not a named spec feature:** a **conversation read/manage surface** (`services/conversations` write-behind store, `services/conversation_view` projection, `/conversations/*`) backs the chat features — list summaries, read render-ready history projected from full-fidelity `ModelMessage` blobs, rename, delete. Conversation content is encrypted at rest (`XC-SEC-3`). A "supporting utility" per spec §inventory-tail.
>
> **Supporting infra, on top of the sandbox:** **artifacts + previews** (`services/artifacts`, `tools/preview`, `/artifacts/*`, `/previews/{token}/*`). `publish_artifact` captures a sandbox file into an encrypted store and serves it back inert (sandboxing CSP + `nosniff`); `start_preview`/`stop_preview` run a live server in the sandbox, reverse-proxied over a token-gated subtree (HTTP + WebSocket) into an opaque-origin iframe. Not a named spec feature; it is the agent's render surface for sandboxed output and a building block toward `DOC-*`/`RUN-1`-class display. Distinct from `RUN-1` (which is an in-browser, host-free snippet runner — still ⬜).

## Feature inventory — B. Knowledge & content

| Req | Status | Realized by | Notes |
|---|---|---|---|
| MEM-1 store/view/edit/delete/timeline | ✅ | `services/memory`, `/memory/*`, `models/memory` | First end-to-end slice. |
| MEM-2 recall by meaning, keyword fallback | ✅ | `services/memory` hybrid (dense+sparse, RRF) | |
| MEM-3 audit: detect & consolidate near-duplicates | ⬜ | — | SHOULD; not built. |
| MEM-4 pin / import / extract from conversation | ⬜ | — | MAY. |
| SKILL-1…6 reusable skills | ⬜ | — | Not started. |
| DOC-1…6 document library + editor + AI assist | ⬜ | — | Streaming/auto-promote deferred (D21). `DOC-6` (checklists + label/pin organization) folds in the former Notes surface. |
| UP-1…4 uploads & PDFs | 🔭 | — | Ingestion deferred (D22). |
| GAL-1…4 gallery & image editing | ⬜ | — | |
| SEARCH-1…3 web search | ✅ | `services/search`, `tools/search.py`, `routes/search`, `models/search` | SearXNG-backed `search` + SSRF-guarded `fetch_url` (trafilatura → Markdown) as agent tools; provider CRUD surface; results untrusted-wrapped. Backs the agent's web tools and unblocks deep research. |
| RAG-1…3 personal knowledge base | ⬜ | — | Reuses the `services/memory` store/seam (D18). |
| RUN-1 in-browser snippet runner | ⬜ | frontend | Never on host (honors `XC-SEC-7` spirit). |

## Feature inventory — C. Communication & personal info

| Req | Status | Notes |
|---|---|---|
| EMAIL-1…5 | ⬜ | Agent send/reply is approval-gated when built (`AE-3.1`). |
| CAL-1…3 | ⬜ | CalDAV sync. |
| TASK-1…6 | ⬜ | Scheduler designed (D13); scheduling pre-auth designed (D24, `AE-3.5`). `TASK-6` (reminders via in-app/email/push, no duplicates, optional AI phrasing) absorbs the former Notes reminders. |

## Feature inventory — D. Models & infrastructure

| Req | Status | Realized by | Notes |
|---|---|---|---|
| COOK-1…5 model download/serve/manage | ⬜ | — | Registry handles *endpoint* config, not local serving. Agent serve/stop is approval-gated when built. |
| EMB-1 choose/manage embedding model | ✅ | `services/registry` `embedding` role, `services/embeddings` | Surfaced in the Cookbook UI (EMBEDDING tab). |
| EMB-2 model change re-embeds/segregates | ✅ | `services/memory` (dense gated to model/dim) | Degrades to sparse across spaces (D16/D18). |
| CMP-1…3 blind model compare | ⬜ | — | Surfaced in the Cookbook UI (COMPARE tab). |
| MCP-1…3 external tool servers | ⬜ | — | Gating designed (D25, `AE-3.6`). |
| INTEG-1…3 third-party integrations | ⬜ | — | Gating designed (D25). |

> **Supporting infra, not a spec feature:** the **model role→endpoint registry** (`services/registry`, `models/registry`, `/models/*`) is the single source of truth for model resolution — named roles (`main`/`utility`/`embedding`) → ordered `FallbackModel` chains, per-conversation `main` override (a provider **and** a model on it), API keys encrypted at rest. An **endpoint is a provider connection** (model optional); its served models are **discovered at runtime** from the provider's models API (`GET /models/endpoints/{id}/models`, parsed across OpenAI/Gemini/Ollama-style shapes), so the chat model is chosen from a top-bar picker rather than baked per endpoint. It realizes **D16** and directly backs `AE-5.3`, `CHAT-4`, and `EMB-*`.

## Feature inventory — E. Security & operations

| Req | Status | Realized by | Notes |
|---|---|---|---|
| AUTH-1 password login + rate-limit + first-run setup | ✅ | `core/auth`, `/setup`, `/auth/login` | Dual cookie+bearer (D9). |
| AUTH-3 user administration | 🔭 | `owner_id` seam | Deferred until a second human exists. |
| AUTH-4 API tokens | ⬜ | — | |
| AUTH-5 inbound webhooks | ⬜ | — | Ties the scheduler/triggers (D13). |
| VAULT-1 password vault (secrets manager) | ⬜ | — | Distinct from the at-rest encryption vault (`core/vault`, `XC-SEC-3`). |
| VAULT-2 agent vault access approval-gated | 🔭 | — | Rides D20 when the vault tool lands. |
| BACKUP-1…2 encrypted export / merge-import | ⬜ | — | Separate backup secret (`XC-SEC-3`). |
| SHELL-1…3 operator's own host terminal | ⬜ | — | Frontend + re-auth host mode. **Invariant already upheld:** the agent's only host path is the explained-approval `run_host_command`; the operator terminal is agent-unreachable by construction (`SHELL-2`, D23). |

---

## Deep research (`DR-*`)

The orchestrator (`research/`) is a stub; the build approach is decided (**D19** — hand-coded outer pipeline + in-round agent, on the Run substrate, reusing search + LLM capabilities). All `DR-*` are ⬜ **pending** — but their blocking dependency, the `search` capability, **now exists** (`services/search`, `SEARCH-*` ✅), so deep research is unblocked. Substrate-level pieces it will inherit *already exist*: the Run lifecycle, cancellation at step boundary (`DR-3.3` ↔ `CHAT-5`), bounds (`DR-3.1` ↔ `runs/registry`), phase/progress streaming (`DR-5.1` ↔ the event protocol), and graceful degradation (`DR-4.1` ↔ `XC-DEG-2`). So deep research is "write the pipeline orchestrator + wire search," not new chassis.

| Group | Status | Notes |
|---|---|---|
| DR-1 capability (iterative multi-source → cited report) | ⬜ | Needs `search` + the pipeline. |
| DR-2 output (long-form, structured, evidence, document) | ⬜ | Document render ties `DOC-*`. |
| DR-3 limits & control (rounds + time, early-stop, cancel, concurrency) | ⬜ | Bounds/cancel inherited from the substrate. |
| DR-4 robustness (search-unavailable, step-failure isolation, prune) | ⬜ | `DR-4.1` ties `XC-DEG-2`. |
| DR-5 progress (phase + counts; optional ETA) | ⬜ | Rides the event protocol. |
| DR-6 configuration (per-run limits, provider) | ⬜ | |
| DR-7 library (retain, list, search/sort, follow-up conversation) | ⬜ | |

---

## What this says about "next"

The code-execution sandbox is in (`XC-SEC-7`/`AE-3.4` ✅) with artifacts + previews on top, and **web search is now in** (`SEARCH-*`/`XC-DEG-2` ✅), which also stood up the first untrusted-content marking (`XC-SEC-5` 🟡). The cheapest, highest-leverage next slices are the ones whose **chassis already exists and only the capability is missing**:

1. **Deep research** (`DR-*` / D19) — now unblocked (its `search` dependency landed); it's "write the pipeline orchestrator + wire the existing search/fetch tools," reusing the Run substrate, bounds, cancellation, and progress streaming it already inherits.
2. **The scheduler** (`TASK-*` + D13) — turns `AE-3.5`/D24 pre-authorization from design into running unattended automation, reusing the approval mechanism already built.
3. **Uploads/attachments** (`UP-*` / D22) — unblocks `CHAT-1`/`CHAT-2` and feeds `RAG-*`, and is the next consumer of the `XC-SEC-5` untrusted-content marking (extending `wrap_untrusted` past the web ingester).

Each is additive over the foundation, not a rebuild — which is the whole point of having spent the early passes on the chassis.

→ see also: [`40-tools-and-toolsets.md`](./40-tools-and-toolsets.md) (gating detail), [`decisions.md`](./decisions.md) (the D-numbers cited here), and the per-area specs under [`../spec/`](../spec/).
