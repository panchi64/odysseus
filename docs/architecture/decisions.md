# Architecture Decisions — open register

Decisions with genuine trade-offs. Each is **OPEN** until you weigh in; recommendations are starting points, not commitments. Referenced inline from the docs as **⟦OPEN: Dn⟧**.

Status legend: 🔵 open · 🟢 decided · ⚪ deferred (revisit when the area is built).

---

### D1 — Run streaming transport 🟢 DECIDED: SSE + POST control
**Question.** How does the server push the run event stream to the client?

- **SSE (server→client) + plain POST for control.** Native `Last-Event-ID` replay (matches `AE-7` "receive the output it missed" with zero custom catch-up logic); trivial to proxy; text-only is fine for our events. Cost: one-directional (control like *stop* is a separate POST — which we want anyway), and HTTP/1.1 per-origin connection caps (a non-issue over HTTP/2).
- **WebSocket (bidirectional).** One socket for stream + control; binary-capable. Cost: resume/catch-up is *manual* (we'd rebuild what SSE gives free), reconnection and proxying are fussier.
- **Both.** More surface to maintain for little gain at our scale.

**Decision:** **SSE + POST control.** It makes `AE-7` continuity nearly free, and we never need client→server streaming. Revisit only if a feature genuinely needs duplex.

---

### D2 — Concurrency / run-execution model 🟢 DECIDED: in-process asyncio
**Question.** Where do Runs actually execute?

- **In-process asyncio tasks + in-memory registry/broker.** Fits the single-operator, single-host profile. Model inference is an HTTP call to a local OpenAI-compatible server, so it never blocks the loop. `AE-7`'s "continuity need not survive a server restart" *explicitly licenses* in-memory state. Simplest possible thing that satisfies the spec.
- **External queue + worker (Redis/Celery/RQ).** Survives restarts, scales horizontally — neither of which the spec requires, and both add operational weight against the local-first principle.

**Decision:** **In-process.** A `RunRegistry` of asyncio tasks with a bounded global concurrency limit (Pydantic AI's own `ConcurrencyLimit` can cap concurrent agent runs; a small queue absorbs bursts — also satisfies `TASK-5` "no overlapping overload"). Keep the broker abstraction clean so an external backend is a later swap, not a rewrite.

**Parallelism (single host, many things at once).** The app runs as a **single main process** — required, because the Run registry, event broker, and resume buffers are **in-memory** (`AE-7`); multiple uvicorn workers would fragment that state and break continuity. We parallelize *within* the process: **asyncio** for massive I/O concurrency (concurrent Runs, parallel tool calls, concurrent search/read per `DR-3.4`, all background workers); a **ThreadPoolExecutor** for GIL-releasing native CPU work (crypto, SQLCipher, numpy/embeddings) — genuinely parallel; a **ProcessPoolExecutor** for heavy pure-Python CPU (parsing/extraction) for true multi-core. **Honest bottleneck:** concurrent *LLM* calls serialize on the model server's batching — one big local model won't run N turns truly in parallel; the separate role-endpoints (D16, e.g. `utility` on a smaller server) let tiers run concurrently without contending. We max out I/O + CPU parallelism; model throughput is bounded by what's served.

---

### D3 — Tool-relevance mechanism (`AE-4`) 🟢 DECIDED: no relevance layer — the model discerns
**Question.** How do we pick "only the tools relevant to this request" while always keeping a core set?

**Decision:** **Don't pre-filter at all.** Present the full (access-gated) catalog and let the model — a capable native-tool-calling model (`AE-8.1`) on one powerful host — discern what to invoke. `AE-4.1` is a *SHOULD-performance*, explicitly waivable with reason; the reason is our deployment profile, and the directive to not overcomplicate. We avoid the latency, infra, and misroute-failure modes of a selection layer entirely.

Consequences:
- The toolset stack drops its `.prepared(relevance_select)` step; only the **access gates** remain (privilege → enabled → naming).
- `AE-4.2` ("doc tools available when a document is open") is **trivially satisfied** — every tool is always present.
- The seam stays open: if the catalog ever grows large enough that the full tool list hurts accuracy or token cost, a `.prepared()` relevance step can be slotted in later **without touching anything else** in the stack. Candidate mechanisms if that day comes: embedding similarity (reuses our embedding capability) or a cheap classifier.

Rejected for now (kept for the record): embedding similarity · LLM classifier/router · static category routing · hybrid — all add cost/complexity the profile doesn't require.

**The honest nuance.** This is sound *provided the catalog stays lean*. Token cost and latency are neutralized by prompt-caching the (static) tool-definition prefix; the only real risk is **selection accuracy, which scales with total tool count** (capable models stay sharp to ~20–40 tools, degrade past ~50–80). The correct lever is therefore **tool design, not filtering**: coarse, action-parameterized tools (one `document` tool with an `action` field, not five) keep the catalog in the safe zone by construction. Viewed this way, `AE-4` is plausibly an **artifact** of the suboptimal original — a relevance index bolted on to cope with a sprawling, un-consolidated catalog. We avoid the cause instead of patching the symptom. **Watch item:** total tool count and observed selection accuracy on the actual local model; the `.prepared()` seam is insurance if a future catalog genuinely outgrows the model.

---

### D4 — Verifier / corrective meta-loop policy (`AE-5.2`, `AE-5.5`) 🟢 DECIDED: heuristic, configurable, capped
**Question.** After a turn, do we judge success and retry?

- **Always-on.** Highest reliability; every turn pays a judge round-trip and possibly a re-attempt.
- **Operator-configurable, default off (or on only for tool-producing turns).** The spec marks this SHOULD/MAY and says it MUST be bounded and MAY be operator-configurable — so config is sanctioned. Pay the cost only where it earns its keep.
- **Heuristic trigger.** Verify only when the turn produced a checkable artifact (a file, a document, a deliverable the user named).

**Recommendation:** **operator-configurable, default to the heuristic trigger**, with a hard cap on corrective attempts (e.g. 1). Judge model is the configurable "utility" model, separate from the main one. The no-progress **loop-breaker** (`AE-5.1`) is *always on* and independent of this — it inspects the running message history / tool-call signature and aborts on repetition.

---

### D5 — Chat-vs-agent routing (`CHAT-3`) 🟢 DECIDED: single always-agent path
**Question.** "Decide per message whether a direct answer suffices or tools are needed."

- **Single always-agent path.** Tools are always *offered* (relevance-narrowed), the model simply may call none. One code path; relevance selection naturally collapses to "core tools only" for chitchat. Slightly more prompt overhead on trivial messages.
- **Pre-classifier fast path.** A cheap check routes trivial messages to a tool-less, cheaper config. Lower latency/cost on small talk; a second path to maintain and a misroute risk.

**Recommendation:** **single always-agent path** to start (simplest, no misroute failure mode); the relevance scorer (D3) already does the practical work of not burdening trivial turns with the full catalog. Add a fast-path later if latency data justifies it.

---

### D6 — Context reduction near the limit (`AE-5.4`, `CHAT-4`) 🟢 DECIDED (impl deferred)
**Question.** How do we stay within the model's context window?

- **Pydantic AI history processor** that trims oldest turns when token budget is tight — cheapest, lossy.
- **Summarize-and-replace** older turns via the configurable utility model — preserves the thread, costs a call.
- **Hybrid:** keep a pinned head (system + active task + open document, which `AE-5.4` says MUST survive) + summarize the middle + keep recent verbatim.

**Recommendation (defer):** implement as a history processor so the mechanism is swappable; start with **hybrid** (pin the active task + open doc, summarize the middle with the utility model). Revisit when we measure real conversations.

---

### D7 — Schema migration strategy (`XC-DATA-2`) 🟢 DECIDED: Alembic from day one
**Question.** How does an existing install upgrade its schema on startup with no manual step?

- **Inline idempotent migration functions** run from DB init. Dead simple, zero deps, total control; you hand-write each change. Fine for a single-DB, single-operator app.
- **Alembic.** Industry-standard, autogenerate + downgrade, version table. Heavier; more ceremony than a local-first single-user DB usually warrants.

**Decision:** **Alembic from day one.** Versioned migrations with autogenerate + downgrade; the upgrade is **auto-invoked on startup** so `XC-DATA-2` ("applied automatically… upgrades in place," no manual step) still holds. Chosen over inline because schema churn is expected and **SQLCipher complicates in-place `ALTER`s** (some need table-rebuild/copy dances) — better handled by explicit, reviewable migration scripts than ad-hoc introspection guards.

**As built.** Alembic lives at `backend/migrations/` with the initial revision capturing the current schema (conversations, messages, model_endpoints, model_roles). `core.db.init_db` runs `command.upgrade(cfg, "head")` on every boot, handing Alembic the **live engine** via `config.attributes['connection']` rather than letting `env.py` build its own — this is what lets the in-memory test DBs (schema on one shared connection) migrate at all. `render_as_batch=True` is on so SQLite `ALTER`s use the table-rebuild dance (anticipating the SQLCipher note in D17). The CLI path (`alembic revision --autogenerate`, `alembic check`) builds its own engine from `sqlalchemy.url` / `ODYSSEUS_DB_URL`. The Mako template imports `sqlmodel` so autogenerated `sqlmodel.sql.sqltypes` references resolve.

---

### D8 — Conversation-history persistence 🟢 DECIDED: in-memory working set + write-behind queue
**Question.** What is the source of truth for a conversation, and how does it reach the DB?

**Decision:** **Write-behind hybrid.** While a user is engaged, Pydantic AI's in-memory `ModelMessage` history is the **live working set** (a pseudo-cache) — runs read/continue from it with zero DB round-trips on the hot path. As each message completes, it is **copied onto a persistence queue** that drains to the DB asynchronously, off the critical path. The DB is the **durable** record (survives restart, serves history/search/metrics); memory is the **fast** record (serves the active turn).

Mechanics:
- Persistence is a **queue consumer on the run substrate** — the same place run events flow. Message-completion enqueues a write job; a background drainer batches them to the DB. Backpressure-bounded; failures retry without stalling the run.
- The durable form is the serialized `ModelMessage` (via `ModelMessagesTypeAdapter`/`to_jsonable_python`) for **resume fidelity**, alongside a thin derived projection (role, text, timestamps, run id, token counts) for **listing/search/metrics**. The projection is derived, never authoritative.
- On resuming a cold session, the blob rehydrates the in-memory working set; from there it's memory-speed again.

This is the concrete instance of "we own the queues": the write-behind drainer is one of a small family of background workers (persistence, scheduling, notifications) on the in-process substrate.

---

### D9 — Auth credential transport 🟢 DECIDED: dual (httpOnly cookie + bearer)
**Question.** Bearer token vs cookie session.

- **Bearer token** in `Authorization`. Works identically same-origin or split-origin; aligns with `AUTH-4` scoped API tokens (same verification path for humans and programmatic callers). No CSRF surface.
- **Cookie session.** Smoother for a pure same-origin browser app; CSRF + `SameSite` to manage; awkward across origins.

**Decision:** **Dual.** Browser sessions use an **httpOnly, `SameSite` cookie** (not XSS-exfiltratable — important for an admin console holding shell/vault); programmatic/API clients (`AUTH-4`) use **bearer tokens**. The server accepts either credential on a request. Cost: standard CSRF protection on the cookie path (SameSite + CSRF token).

---

### D10 — Repo package granularity 🟢 DECIDED: fine split
**Question.** How finely to split the backend.

- **Fine split** (`runs/ agent/ tools/ services/ research/ routes/ models/ core/`). Each concern is findable; matches the layer map; more top-level packages.
- **Fewer packages** (e.g. one `src/` with sub-modules). Less navigation, but the agent engine is the heart of this project and benefits from breathing room.

**Recommendation:** **fine split.** The Run substrate, the engine, the tools, and the capabilities are genuinely different concerns with different change-rates; keeping them as siblings makes the dependency direction visible and enforces "tools are thin."

---

### D11 — Untrusted-content marking technique (`XC-SEC-5`) 🟢 DECIDED (technique deferred)
**Question.** How to mark web pages, emails, uploads, retrieved docs, and the open editor doc as *data, not instructions*.

- **Delimiter/sentinel wrapping** in the prompt text (clear, model-agnostic, slightly hacky).
- **Distinct structured content parts** (cleaner; depends on model/part support).
- **A dedicated "untrusted context" section** with an explicit standing instruction to treat it as data.

**Decision (technique deferred):** the marking is **ours** — Pydantic AI has **no built-in "treat-as-data" primitive** (confirmed: it offers only adjacent pieces — `ReinjectSystemPrompt(replace_existing=True)` to keep our system prompt authoritative over untrusted history, a **Hooks** capability to intercept tool/model calls, and `PrepareTools` for tool filtering). So `XC-SEC-5` is met by a single `wrap_untrusted()` helper used by every context-builder and content-returning tool — sentinel-delimited blocks + a standing "treat as data" instruction to start, upgrading to structured parts where supported. We **compose** it with `ReinjectSystemPrompt` (defend against poisoned history) and optionally a **Hook** running an injection classifier over tool outputs / retrieved content. Centralized = one place to harden.

---

### D12 — ORM choice 🟢 DECIDED: SQLModel, sync DB in threadpool
- **SQLAlchemy (async)** — most capable, most ubiquitous, verbose.
- **SQLModel** — Pydantic-native (pairs with FastAPI + Pydantic AI), thinner, younger.
- **Tortoise / others** — Django-like; less synergy here.

**Decision:** **SQLModel**, with the **DB layer run synchronously in a threadpool executor.** D17's SQLCipher driver is a *sync* DBAPI, so a fully-async ORM stack doesn't pair cleanly; blocking SQLCipher calls go in a threadpool to keep the event loop free while retaining SQLModel's Pydantic-native ergonomics. Drop to raw SQLAlchemy Core only where SQLModel is too thin. (SQLCipher releases the GIL during I/O, so threadpool DB calls genuinely parallelize — ties into D2.)

---

### D13 — Scheduling / event triggers (`TASK-*`) 🟢 DECIDED: in-process, lock-aware
**Question.** What drives recurring/cron/event/webhook tasks?

- **In-process async scheduler** (a tick loop or APScheduler) firing tasks as Runs. Fits the in-process model (D2); dies with the process (tasks reschedule on boot from the DB).
- **External scheduler.** Survives restarts independently; more moving parts against local-first.

**Recommendation (defer):** **in-process scheduler** that materializes due tasks as Runs on the same substrate, with the schedule persisted so boot rehydrates it. Inbound webhooks (`AUTH-5`) are just authenticated endpoints that enqueue a Run.

---

## Newly identified — not yet scheduled

Surfaced while surveying the whole spec; captured here so they aren't lost. One-liners now; each gets a full angle write-up when we pick it up. Ordered roughly by how foundational it is.

- **D14 — User model 🟢 DECIDED: single-operator, ownership seam only (C1) + capability gating by approval.** The spec's "privilege" conflates three independent axes; we separate them:
  - **Axis A — Authentication.** Kept fully — the app is a networked admin console and must authenticate even for one person (`XC-SEC-1`, `AUTH-1/2/4`).
  - **Axis B — Capability sensitivity.** *Reframed* from the spec's user-centric "admin-only tools" (vacuous with one admin) to **capability-centric**: certain tools are *sensitive* (shell, Python, filesystem-write, email-send, vault, config) and a sensitive call **requires explicit user approval before it executes** (see **D20**). This is what actually constrains the *autonomous agent*, which is the real threat surface here — not other humans.
  - **Axis C — Multi-tenancy.** **C1 (seam only):** every record carries an `owner_id` defaulting to the single operator, but **no ownership-enforcement checks and no per-user privilege/management UI are built yet.** Rationale: the one expensive, regret-prone future migration is retrofitting an owner column onto a populated schema and finding every query site — so we *pre-pay* that with a free column now and defer the enforcement (and `AUTH-3` user management, per-user setting overrides) until a second human actually exists. C0 (no column) saves a triviality at the price of that retrofit; C2 (full enforcement now) builds a multi-tenant fortress for a population of one, mostly unexercisable.

  Net posture: **authenticate fully · gate sensitive capabilities by approval · attribute data to an owner but don't enforce isolation yet.** Spec edited in place to match (`AE-3`, `XC-SEC-2/6`), keeping the spec black-box (no mention of the approval *mechanism*).

- **D15 — The concrete event protocol (`AE-6`) 🟢 DECIDED (v1 frozen).** The backend↔frontend streaming contract.
  - **Framing.** SSE; each frame's `id:` = a **per-run monotonic `seq`**, `data:` = a typed JSON envelope `{type, seq, ts, …payload}`. **One channel**, type lives in the JSON (not SSE's `event:` field) — simplest for our own client. Strict ordering by `seq` within a run; deltas are append-only.
  - **Resume (`AE-7`).** On reconnect the client sends `Last-Event-ID` = last `seq` seen; the server replays every buffered event with `seq >` that, then goes live. The per-run event buffer lives in memory for the run's lifetime.
  - **Versioning.** Protocol version announced in `run.started`; additive events/fields don't bump it, breaking changes do.
  - **Naming convention.** `entity.event`, **dot.lowercase**. Discrete (it *happened*) → past-tense verb (`started`, `committed`, `failed`); streaming increments → `delta`/`progress`.
  - **v1 event set:**
    - **Run:** `run.started` · `run.metrics` · `run.ended` · `run.error`
    - **Step:** `step.started` · `step.completed`
    - **Content:** `thinking.delta` · `answer.delta` (the `AE-6.3` reasoning/answer split)
    - **Tools:** `tool.started` · `tool.progress` (elapsed + partial, for slow tools) · `tool.completed` · `tool.failed`
    - **Documents:** `document.created` · `document.delta` · `document.committed` (`AE-6.2`)
    - **Notices:** `citation.added` · `approval.required` (D20) · `limit.notice`
  - **Deltas are coalesced server-side** (batched by time/punctuation, not one frame per token) for smoother render and lower frame overhead.
  - **Tool payloads are full inline** (complete args + results on the stream), not summaries — for user transparency; the client compacts them in an expandable view. (Full history is also persisted.)
  - These events are produced by translating Pydantic AI's native stream (`PartStartEvent`/`PartDeltaEvent` for thinking/answer parts, tool-call/return events, `FinalResultEvent`) and by emitting the ones the library doesn't know about (step boundaries, document lifecycle, citations, approvals, limit notices, run metrics, end).

- **D16 — Model/endpoint configuration & the utility model 🟢 DECIDED: named roles → endpoint/fallback-chain; single global utility.**
  - **Roles.** Fixed named roles the engine consumes: **`main`** (agent/chat), **`utility`** (cheap background work), **`embedding`** (recall), and later **`vision`** (scanned-PDF extraction) and **`image-gen`** (diffusion). Each role binds to **an endpoint or an ordered fallback chain** of endpoints.
  - **`main` is overridable per conversation** (the chat model picker); all other roles are **global settings**.
  - **`utility` is a single global role** used by summarization (`CHAT-4`), verification (`AE-5.2`), email triage (`EMAIL-2`), NL parsing (`TASK-4`/`CAL-3`), titles, and memory extraction. **If unset it falls back to `main`.** Seam exists to split per-feature later, but we don't start there.
  - **Endpoints** are provider-agnostic: OpenAI-compatible `base_url` + model name + optional key + metadata — **context window** (feeds context reduction `AE-5.4`), and **capability flags** (native tool-calling is required `AE-8.1`; vision; thinking). Local (llama.cpp/Ollama/MLX/vLLM) or remote, per the local-first-but-configurable principle.
  - **Registry & resolution.** The endpoint registry lives in the **encrypted** settings, populated by manual config **and** the Cookbook (`COOK-4`) when it serves a model. At run start the orchestrator resolves the model from the role (with the per-session override for `main`) and builds the Pydantic AI model — wrapping the role's chain in **`FallbackModel`** (`AE-5.3`). The *"don't switch endpoints once answer text has streamed"* rule (`AE-5.3`) is enforced by **our** orchestrator, not the library: fallback is only allowed before the first `answer.delta`.
  - **Ripple → D18 / `EMB-2`:** the `embedding` role couples to the vector store; changing it must not lose existing recall, so each stored vector records which embedding model/dimension produced it (re-embed or segregate on change).
  - **As built.** The registry is the **single source of truth** for model resolution — there is no `.env` model seam and no runtime fallback to one (an unconfigured role is a degraded capability, surfaced as a clear "configure a model" error). It is realized as structured tables (`model_endpoints` + `model_roles`) rather than a generic encrypted-settings KV; only the **API key field is application-layer AEAD-encrypted** (the at-rest posture after whole-DB SQLCipher was ruled out — see D17), while base_url/model/flags stay indexable in the clear. The operator manages it through `/models/*`; the automatic-setup/Cookbook (`COOK-4`) populates it through the **same** `create_endpoint` + `set_role` write path. Roles resolve through `services.registry.ModelRegistry.resolve`; `services.llm` owns only the spec→model builders and the `FallbackModel` chain wrap.

- **D17 — At-rest encryption & key management (`XC-SEC-3`) 🟢 DECIDED.** All user data at rest is encrypted; the system is a vault that must be unlocked each boot.
  - **Cipher (settled by cryptography, not preference):** symmetric **AES-256-GCM** (or XChaCha20-Poly1305) *is* the post-quantum-safe choice — AES-256 retains ~128-bit strength under Grover; NIST excludes symmetric crypto from PQC transition. There is no PQ bulk cipher to adopt. PQC (hybrid X25519+ML-KEM) is reserved for *asymmetric key wrapping* (portable backups, future multi-device) — a deferred seam, not a dependency.
  - **Granularity — DECIDED: whole-DB + encrypted files.** SQLCipher encrypts the entire SQLite file (rows, indexes, FTS, embedded vectors — transparent to queries); large files (uploads/docs/gallery/personal-docs) are per-file AEAD blobs under the same key hierarchy. The vault keeps its own extra layer on top.
  - **As built — application-layer AEAD, not whole-DB SQLCipher (revised).** Whole-DB SQLCipher needs a SQLCipher-linked `sqlite3` driver, and there are **no portable wheels for our runtime (Python 3.14)** — adopting it would mean building from source / pinning Python, which breaks `XC-PORT-1` (must run with no OS-specific build dance across Linux/macOS/Windows). So at-rest encryption is **application-layer AES-256-GCM** under the *same* password-derived, memory-only DEK and key hierarchy described below — only the *granularity* changes: instead of the whole file being opaque, **each sensitive value is sealed in its column** (conversation message text + serialized `ModelMessage` blob; model-endpoint API keys), while structural metadata that must be indexed/ordered (ids, owner, timestamps, seq, kind, base_url, model name, capability flags) stays in the clear. Encryption happens on the **lock-aware** side of the write-behind queue, so a mid-turn lock parks the write rather than losing it. The cipher, key custody, lock lifecycle, and PQ posture are **unchanged** — only the boundary moves from "the file" to "the sensitive fields." **Trade-off accepted:** indexes/FTS over plaintext columns are not encrypted (acceptable — they hold structural keys, not content), and remembering to seal each new sensitive column is now a design responsibility (the model registry's `api_key` is the first to follow it). **The whole-DB design stays the target seam:** if portable SQLCipher wheels appear, or the data model grows enough that field-level coverage becomes error-prone, the `core.db` engine factory is the single swap-in point (Alembic already runs with `render_as_batch=True` for the `ALTER` constraints SQLCipher would impose). Large-file per-file AEAD (uploads/docs/gallery) is unaffected and lands with those features.
  - **Key custody — DECIDED: password-derived, lock-until-unlocked.** The operator's **login password is the key material**. Two-tier hierarchy: password → **KEK** via **Argon2id** (dedicated salt) → unwraps a random **DEK** (so a password change only re-wraps the DEK, never re-encrypts data). Auth-verifier and KEK are **domain-separated** (independent HKDF labels / salts) so the stored login hash is useless for decryption. The **DEK lives only in process memory** after unlock — never written to disk and never to any OS keystore (no Keychain / DPAPI / `libsecret` dependency), which also makes this the **most platform-agnostic** custody option: byte-for-byte identical behavior on Linux, macOS, and Windows. **Auth secrets stay hashed** (Argon2id), never encrypted (`XC-SEC-4`).
  - **Lock lifecycle:** on boot/restart the app is **locked** (encrypted data inaccessible); first successful login derives the KEK and unwraps the DEK into memory, **unlocking** it for the process lifetime. An explicit *lock* control (and optionally an idle timeout) wipes the DEK from memory, requiring re-unlock. Restart ⇒ re-unlock.
  - **Consequence — background work is lock-aware (ripple → D13).** The scheduler, email triage, reminder dispatch, webhook handlers, and the write-behind persistence drainer all touch encrypted data, so they **only run while unlocked**. While locked they **park gracefully** (persist intent, surface a "locked" status) rather than erroring or dropping events; on unlock they catch up a bounded backlog. After a restart, unattended features stay paused until the operator logs in — an accepted trade for maximum confidentiality.
  - **Consequence — app "locked" state surfaces to the client.** The shell needs a locked/unlocked indicator and an unlock prompt; health/connection status reflects it.
  - **Edge — `AUTH_ENABLED=false`.** At-rest encryption needs an unlock secret even when network auth is off. Resolution (provisional): the **unlock passphrase is conceptually separate from login** — disabling auth disables the *login gate*, not the *unlock*; the operator still supplies a passphrase to derive the key. (Equivalently, at-rest encryption makes an unlock step effectively mandatory.) Confirm when we build auth.
  - **Ripple → D18:** pushes the vector store toward **embedded (sqlite-vec inside the encrypted DB)** so embeddings are encrypted for free; an external Chroma would be a separate plaintext store needing its own encryption.
  - **Ripple → `BACKUP-*`:** a backup must be decryptable on another host, so export re-wraps the DEK under a **separate backup secret** (recovery key / passphrase) — the natural home for an optional PQ-hybrid (X25519+ML-KEM) key-wrap later. A forgotten password with no recovery key = unrecoverable data (accepted for a single operator; recovery key is the mitigation).

- **D18 — Vector store (`XC-DEG-1`, `MEM-2`, `RAG-2`, `EMB-*`) 🟢 DECIDED: pluggable interface, `sqlite-vec` default.** Vectors live in **`sqlite-vec` inside the encrypted DB** (D17) — one encrypted store, no extra service; brute-force KNN is fine at single-operator volumes. The pluggable interface keeps the seam to slot an external store (Chroma, etc.) if volume outgrows brute-force. Degrades to **keyword search** when vector search is unavailable (`XC-DEG-1`). Each vector records its embedding model/dimension so an `embedding`-role change (D16, `EMB-2`) re-embeds or segregates rather than corrupting recall.
  - **As built — brute-force hybrid in Python, *no* `sqlite-vec` (revised).** `sqlite-vec`'s whole justification was that whole-DB SQLCipher would encrypt its vectors "for free" (this entry's own phrasing). D17 moved to **app-layer per-column AEAD** (no portable SQLCipher wheels), and that premise is gone: `sqlite-vec` does KNN over **plaintext** vectors, which under per-column encryption would leave embeddings of private memories unencrypted at rest — and embeddings are invertible enough to leak their source text, contradicting `XC-SEC-3`. (FTS5 keyword indexing has the same plaintext-index problem.) So at single-operator volumes the store is **brute-force-in-Python over the decrypted working set**: vectors are AEAD-sealed in their column, and recall loads the owner's memories, decrypts, and scores each both ways — **dense** (cosine over embeddings, "by meaning") and **sparse** (token overlap, the keyword path) — fusing the two with **Reciprocal Rank Fusion**. This satisfies `MEM-2` (meaning + keyword fallback) in one pass, keeps every vector encrypted, needs **no native extension** (better for `XC-PORT-1`), and is microseconds at this scale. `EMB-2` is honored: dense comparison is gated to the same embedding model/dim, so a model change degrades to sparse rather than comparing across spaces. **The pluggable seam stands** — an ANN store (`sqlite-vec`/external) can slot back in when *volume*, not confidentiality, becomes the constraint, which is an explicit trade then (and would pair with whole-DB encryption if it returns). First realized for `MEM-*`; `RAG-*` reuses the same store.

- **D19 — Deep-research build approach (`DR-*`) 🟢 DECIDED: hybrid.** A **hand-coded outer pipeline** owns the deterministic concerns — rounds + time bounds (`DR-3.1`), source/query dedup (`DR-1.4`), per-round concurrency and source caps (`DR-3.4`), stop-when-comprehensive (`DR-3.2`), and the phase progress events (`DR-5.1`). Inside each round, a **Pydantic AI agent** handles the judgement-heavy step: analyze gathered evidence, refine the evolving answer, and identify remaining gaps to investigate next (`DR-1.2`). Both ride the **Run substrate** and reuse the **search + LLM capabilities** directly. This keeps the bounds explicit and testable while letting the model do the open-ended synthesis. Cost: two paradigms in one feature — kept clean by the pipeline owning control flow and the agent owning only the in-round reasoning.

- **D20 — Sensitive-capability gating 🟢 DECIDED: approval via Pydantic AI deferred tools.** Sensitive tools (Axis B in D14) are gated by **explicit user approval**, implemented with Pydantic AI's human-in-the-loop deferred-tools mechanism:
  - A sensitive tool is marked `requires_approval=True` (or raises `ApprovalRequired` for runtime-conditional sensitivity — e.g. a write to a protected path).
  - The agent run ends with a `DeferredToolRequests` output whose `approvals` list holds each pending `ToolCallPart` (tool name + **validated args** + `tool_call_id`). Pydantic AI has done the agentic work; it has *not* executed the call.
  - **We own the pause/resume lifecycle:** the Run enters an `awaiting_input` state; we emit an `approval_required` event (carrying the human-readable action + args) over the stream; we notify on the appropriate channel (inline for an interactive Run; push/email for an unattended/scheduled Run); we hold the serialized message history.
  - The user decides via a `POST /runs/{id}/approve` control endpoint. We resume the agent with `deferred_tool_results=DeferredToolResults(approvals={tool_call_id: ToolApproved() | ToolDenied(message=…)})`. `ToolApproved` may carry `override_args`; `ToolDenied`'s message is shown to the model so it can adapt.
  - Because the parked state is just serialized history + pending requests, an approval pause **naturally survives client disconnect** (`AE-7`) and can outlive it entirely for unattended runs.

  This unifies interactive and unattended gating under one mechanism (only the notification channel and latency differ) and keeps the clean split: Pydantic AI decides *what* needs approval and *exactly what it would do*; we own *parking, notifying, waiting, and resuming*.

- **D21 — Document streaming & auto-promotion (`AE-6.2`, `AE-6.4`, `DOC-3`).** How AI-authored document content streams into a version and commits, and how a substantial inline code/doc block gets *promoted* into a real document automatically. Detection heuristic + event shape. **Defer until the document feature is in scope.**

- **D22 — Attachment / upload ingestion pipeline (`CHAT-2`, `UP-*`).** How links and uploaded files become model context: fetch+extract inline vs a pre-ingest step feeding RAG; PDF/vision extraction path. **Defer until uploads are in scope.**

- **D23 — Code-execution isolation (`XC-SEC-7`, `AE-2`, `AE-3`) 🟢 DECIDED: sandboxed by default, host only via explained approval.** Approval (D20) is *consent, not containment* — a misjudged click, a destructive command dressed up as benign, or injection that manufactures a plausible approval request all land on the real host. So code execution gets a structural boundary *underneath* the gate, not just the gate.
  - **Invariant.** All agent-invoked code and shell execution runs in an environment **isolated from the host**, operating only on **copies** of the files explicitly handed to it. It cannot read or modify the host filesystem, processes, or environment. Outputs return to the user/app explicitly; any write-back to real data is an ordinary, separately-gated action — nothing escapes the box as a side effect.
  - **Two paths, cleanly split.** (a) **Sandboxed execution** is the default and is *not* approval-gated — being contained, it carries no host-level risk, so the agent computes freely in the box (and routine code-exec loses its approval friction entirely). (b) **Host execution** is a distinct, **approval-gated deferred tool** (reusing D20's mechanism) for the legitimate case where the user genuinely needs the host itself changed; its approval request MUST carry a **plain-language explanation** of what the code does and its effect, not just the raw command (`AE-3.4`).
  - **Operator's own terminal stays.** The manual Host Shell (`SHELL-*`) is operator-initiated — the operator deliberately operating their own machine — and is unchanged by this; the agent can never reach it. The agent's only path to the host is the explained-approval tool above.
  - **Mechanism — pluggable, container default.** An **execution-sandbox capability** in `services/` with a pluggable backend; default is a **container runtime** (Docker/Podman) providing filesystem/process/network isolation and copy-in/copy-out of files. Provider-agnostic like the vector store (D18); the container runtime is the portable default that satisfies `XC-PORT-1` (works across Linux/macOS/Windows, no OS-specific facility).
  - **Degradation — fail closed, never to host.** If no sandbox runtime is available, the code-execution capability is **disabled** and the agent is told so (`XC-DEG-*`); it MUST NOT silently fall back to running on the host. Network egress from the sandbox is off/controlled by default so copied data can't leak; tighten per config.
  - **Ripples.** The `approval.required` event gains an optional explanation field for the host-exec case (additive to the frozen v1 protocol, D15 — no version bump). `RUN-1`'s in-browser snippet runner already honors the spirit (never on host) and is unaffected. `SHELL-*` is reframed to the operator's own deliberate terminal — agent-unreachable, opened only through a re-authenticated **host mode** (`SHELL-3`).

- **D24 — Pre-authorized scheduled tasks (`AE-3.5`, `TASK-*`) 🟢 DECIDED: approval moves to scheduling time as a scoped standing grant.** Strict per-run approval (`AE-3.2`) makes a recurring task that touches a sensitive action **park every run** — defeating the point of unattended automation. Resolution: **the scheduling tool is itself a deferred/approval tool** (D20). When the agent schedules a task, the Run parks and surfaces the task to the operator — its trigger, intended actions, and the specific **sensitive actions** it would perform — and approval grants a **scoped pre-authorization** stored with the task.
  - **At each unattended run.** A sensitive action **within** the pre-authorized scope is auto-satisfied (the deferred result is supplied as approved) without re-parking; a sensitive action **outside** the scope falls back to `AE-3.2` (pause + notify). The standing-trust surface is bounded to exactly what the operator reviewed.
  - **Scope, not a blank cheque.** The pre-authorization is over a **declared scope** (e.g. 'may send email to these recipients', 'may run sandboxed code', 'may not run host code'), checked at runtime — not an unconditional pass. For free-form agent tasks whose exact calls aren't known at scheduling time, the operator approves the *bounds* and runtime actions are matched against them; an out-of-bounds action pauses.
  - **Revocable & visible.** The operator can review and revoke any task's pre-authorization at any time; revocation returns the task to strict per-run approval. Ties D13 (the scheduler materializes tasks as Runs) to D20 (the deferred-tool approval mechanism), reusing both rather than adding new machinery.

- **D25 — External-tool gating (`AE-3.6`, `MCP-*`, `INTEG-*`) 🟢 DECIDED: sensitive by default, operator trust opt-out.** The `AE-3` sensitivity model rests on a *known* list (shell, email, vault…); tools from registered MCP servers and configured third-party integrations are the **unknown** case it can't enumerate — arbitrary, possibly externally-visible effects. So they are **approval-gated by default**, and the operator opts specific tools into **trusted** (auto-approve) status. Consistent with the rest of the posture (sandbox-by-default, explain-before-host): unknowns are contained until the operator deliberately relaxes them, per tool, never the agent.
  - **Mechanism.** In the toolset stack, external tools carry a default *sensitive* marking and ride the same deferred-tool approval path as D20; a **trusted-tool allowlist** (operator-managed, persisted in encrypted settings) flips specific tools to auto-approve. Enable/disable (`AE-3.3`) is orthogonal and still applies.
  - **Scope.** Trust is **per tool, not per server**, so registering/enabling a server doesn't blanket-trust everything it exposes. Revocable at any time.
