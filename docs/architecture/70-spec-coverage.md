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
| XC-SEC-5 untrusted external content marked as data | 🟡 | `core/untrusted.py` (`wrap_untrusted`); applied in `services/webfetch` to fetched pages + `services/search` to search snippets | Marking built and applied at the first ingester (web): sentinel-delimited block + standing "treat as data" instruction. `ReinjectSystemPrompt` (poisoned-history defense) still pending; extends to uploads/mail as they land. |
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
| XC-DEG-2 web search unavailable → clear state, no hang | ✅ | `services/search` (`DegradedCapabilityError`), `services/searxng` (managed instance), `tools/search.py`, `routes/overview` | Managed SearXNG normally backs search with zero setup; no instance (no container runtime / not yet booted) and no configured provider ⇒ tools return "unavailable" and overview warns. An empty result set is a valid answer. No hang or loop. |
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
| AE-2 tool categories | 🟡 | `tools/` (`builtin`, `memory`, `conversations`, `code`, `preview`, `web`) | 6 of ~14 categories built; rest land with their capability. See [`40-tools-and-toolsets.md`](./40-tools-and-toolsets.md). |
| AE-2.1 typed params + arg validation | ✅ | Pydantic AI tool schemas | |
| AE-2.2 tool always returns actionable result; failure ≠ abort | ✅ | tools return error payloads, not raises | memory/code tools model this. |
| AE-3.1 sensitive set requires explicit approval | ✅ | D20 deferred-tool pause; `tools/code.py` host tool | Mechanism built; expands as sensitive tools land. Strict per-call default, with the `AE-3.7` conversation-grant exception (D28). |
| AE-3.2 approval channel per run; pause unattended | 🟡 | inline approval + `/runs/{id}/approve` | Interactive path ✅; unattended push/email channel ⬜. |
| AE-3.3 operator can disable individual tools | ✅ | `tools/toolsets` `_enabled_gate` | |
| AE-3.4 host-exec approval carries plain-language explanation | ✅ | `tools/code.py` `run_host_command(explanation=…)` | Explanation surfaced on `approval.required` (D23). |
| AE-3.5 scheduled-task pre-authorization (scoped standing grant) | 🔭 | — | Designed (D24); lands with `TASK-*`. |
| AE-3.6 external tools sensitive-by-default + trusted opt-out | 🔭 | — | Designed (D25); lands with `MCP-*`/`INTEG-*`. |
| AE-3.7 conversation-scoped auto-approval grant (opt-in, TTL'd, revocable) | ✅ | D28; `services/approval_grants`, `models/approval_grant`, engine auto-approve split, `ApprovalDecision.scope`, `GET`/`DELETE /conversations/{id}/grants` | Generic over any deferred tool; off by default; UI affordance on the shared `ApprovalCard` + revocable strip. |
| AE-3.8 global knowledge-base recall is approval-gated (context gate) | ✅ | D28; `tools/recall_gate.py` shared by `corpus.retrieve` (no `source_ids`), `memory.recall`, `conversations.search` — all raise `ApprovalRequired` on global recall | Conditional — explicit-id reads pass through (`corpus.retrieve` with `source_ids`, `conversations.read` by id); not in the `AE-3.1` sensitive set (read-only). |
| AE-4.1 lean catalog, no runtime relevance filter | ✅ | `tools/toolsets` (no `.prepared()` step) | By design (D3); seam reserved. |
| AE-4.2 every permitted tool available whole turn | ✅ | full gated catalog always offered | Doc-tools-when-open holds once docs land. |
| AE-5.1 no infinite loop / no-progress stop | ✅ | `agent/meta` loop-breaker | Always-on. |
| AE-5.2 post-turn verifier + bounded corrective re-attempt | ✅ | `agent/meta` + `agent/engine` | Opt-in, capped (D4). |
| AE-5.3 prioritized endpoints, fall back on failure | ✅ | `services/llm` `FallbackModel` chain | Pre-stream only. Resolution **skips disabled endpoints** (pre-emptive failover, atop the runtime `FallbackModel`). Endpoint health via `POST /models/endpoints/{id}/test` — backend-categorized (auth / rate-limited / timeout / unreachable / bad-response), plain-language detail rendered verbatim — plus disable-without-delete. |
| AE-5.4 context reduction near limit | 🔭 | — | Decided (D6: history-processor hybrid); impl deferred. Ties `CHAT-4`. |
| AE-6.1 stream activity (text, tools, steps, metrics, errors, end) | ✅ | `runs/events` (frozen v1), `agent/translate` | |
| AE-6.2 document content streams into a version | 🔭 | — | Deferred (D21); with `DOC-*`. |
| AE-6.3 reasoning distinguishable from answer | ✅ | `thinking.delta` vs `answer.delta` | |
| AE-6.4 auto-promote inline blocks to documents | 🔭 | — | Deferred (D21). |
| AE-7.1 run survives disconnect; reconnect replays missed | ✅ | `runs/stream` (buffer + broker + `Last-Event-ID`), `runs/registry`; SSE keepalive (`runs/transport`); client reattach on visibility/online + cold-read (`conversations.active_run` → frontend `createChatStream.reattachRun`) | Not required across server restart. End-to-end: in-app nav, backgrounded tab, and reload all resume the live turn. |
| AE-8.1 native tool-calling models only | ✅ | model registry; owner profile | Out-of-scope models excluded by design. |

---

## Feature inventory — A. Conversation

| Req | Status | Realized by | Notes |
|---|---|---|---|
| CHAT-1 send text/links/files, streamed reply | ✅ | `routes/chat`, `agent/attachments`, `agent/engine`, `services/uploads`, run substrate, `services/conversations` | Text+stream+persistence + **file attachments** (`attachment_ids` on the chat send; client uploads via `POST /uploads` first). Links are still plain text the agent fetches via the web tool. |
| CHAT-2 links/files as model context | ✅ | `agent/attachments`, `agent/engine`, `services/conversations`, `tools/attachments.py`, `services/sandbox`, `tools/corpus.py`, `routes/chat` | Attached files reach the model in full for the attach turn (image-as-pixels for a vision model, extracted text otherwise — `wrap_untrusted`, `XC-SEC-5`). Replayed history retains them **inline up to an operator token cap** (`chat.attachment_inline_max_tokens`, set via `GET/PUT /chat/settings`): images always; a document's text until it exceeds the cap, past which it's **cut off with a pointer to the tools** (`install_persisted_attachments`). Beyond the cap (and for any attachment's raw bytes), the agent reaches the file via `corpus.retrieve` (its text) or `attachments_provision` (stages the bytes into the sandbox `/work` for `code_execute`) — available-to-reference, not info-dumped. |
| CHAT-3 every message runs the agent path | ✅ | `agent/engine` single path | No pre-classification (D5). |
| CHAT-4 summarize near context limit (utility model) | 🔭 | — | With `AE-5.4` (D6). Utility role already exists in the registry. |
| CHAT-5 stop in-progress; resume after disconnect | ✅ | `/runs/{id}/cancel`, `runs/stream` | |
| CHAT-6 ask AI to rewrite/rephrase a message | ⬜ | — | SHOULD; not built. |
| CHAT-7 agent searches/reads the operator's other conversations | ✅ | `services/conversation_search` (hybrid recall + transcript read), `tools/conversations.py`, per-message embeddings in `services/conversations` drainer | Mirrors memory recall (dense+sparse, RRF; `XC-DEG-1` keyword fallback). Excludes the current + ephemeral threads; read-only, not approval-gated. |

> **Supporting infra, not a named spec feature:** a **conversation read/manage surface** (`services/conversations` write-behind store, `services/conversation_view` projection, `/conversations/*`) backs the chat features — list summaries, read render-ready history projected from full-fidelity `ModelMessage` blobs, rename, delete. Conversation content is encrypted at rest (`XC-SEC-3`). A "supporting utility" per spec §inventory-tail.
>
> **Supporting infra, on top of the sandbox:** the **View** — one versioned output surface per conversation (`services/artifacts` as the version store, `tools/view`, `/views/*`, `/previews/{token}/*`). The agent reaches it through one tool: `view_show(file=…)` captures a sandbox file as a static **version** into an encrypted store served back inert (sandboxing CSP + `nosniff`); `view_show(serve=…, port=…, path=…)` runs the live **head** in the sandbox, reverse-proxied over a token-gated subtree (HTTP + WebSocket) into an opaque-origin iframe with the entry `path` baked into the url; `view_close` tears it down. The frontend renders one viewport — the head on stage plus a version timeline to compare (D29). Not a named spec feature; it is the agent's render surface for sandboxed output and a building block toward `DOC-*`/`RUN-1`-class display. Distinct from `RUN-1` (which is an in-browser, host-free snippet runner — still ⬜).

## Feature inventory — B. Knowledge & content

| Req | Status | Realized by | Notes |
|---|---|---|---|
| MEM-1 store/view/edit/delete/timeline | ✅ | `services/memory`, `/memory/*`, `models/memory` | First end-to-end slice. |
| MEM-2 recall by meaning, keyword fallback | ✅ | `services/memory` hybrid (dense+sparse, RRF) | |
| MEM-3 audit: detect & consolidate near-duplicates | ⬜ | — | SHOULD; not built. |
| MEM-4 pin / import / extract from conversation | ⬜ | — | MAY. |
| SKILL-1…6 reusable skills | ⬜ | — | Not started. |
| DOC-1 create/edit/archive/restore/search + type detect | ✅ | `services/documents`, `services/corpus/documents`, `models/document`, `routes/documents` | CRUD over an at-rest-sealed store (title + body); coarse type heuristic + best-effort `langdetect`. Search flows through the corpus (the documents adapter), not a second scan. |
| DOC-2 versioned changes (origin) + restore | ✅ | `services/documents` (`DocumentVersion`) | Every change appends a full sealed snapshot stamped user/ai/extraction; restore-to-version copies a snapshot back and records it as a fresh version (append-only history). |
| DOC-3…6 AI assist, dedup, export, checklists/labels | ⬜ | — | Streaming/auto-promote deferred (D21). `DOC-6` (checklists + label/pin organization) folds in the former Notes surface. |
| UP-1 upload files + recognize duplicates | ✅ | `services/uploads`, `models/upload`, `routes/uploads` | Multipart upload stored sealed at rest (bytes + filename); content `sha256` is the dedup key — re-uploading identical bytes returns the existing upload (201 created vs 200 duplicate). |
| UP-2 extract PDF text (incl. scanned via vision), retain + correctable | ✅ | `services/upload_extraction`, `services/upload_mineru`, `agent/vision`, `services/corpus/uploads` | Extraction is a seam: the built-in path (pypdfium2 native text + per-page **vision OCR** for scanned pages, the codebase's first multimodal model call) is the zero-setup floor; **MinerU** (detected host tool, transient subprocess → clean Markdown with layout/tables/formulas) goes in front via `FallbackExtractor` when present, degrading to the built-in on any failure. Extracted text is retained per upload, operator-correctable, and indexed into the corpus; the producing extractor is recorded so built-in extractions can be re-run through MinerU later. Runs off the request path on a lock-aware worker. |
| UP-3 fillable PDF form detection | ⬜ | — | SHOULD; not built. |
| UP-4 upload rate-limiting | ✅ | `core/ratelimit`, `routes/uploads` | Per-operator token bucket on the upload endpoint → 429 + `Retry-After`. |
| GAL-1…4 gallery & image editing | 🚧 | `services/gallery`, `routes/gallery`, `models/gallery`, `services/uploads`, `services/conversations` | **Browse + albums landed; AI editing deferred.** The gallery is a presentation lens over the image uploads (`mime image/*`) — chat attachments and KB uploads are the *same* `Upload`, so it aggregates every uploaded image with **no separate store**. `GAL-1`: browse/favorite/delete/export via `GET /gallery/media` + the existing `/uploads` write paths (a per-image `favorite` flag, a WebP `thumbnail` endpoint + inline `content` serving). `GAL-2` named **albums** are real (`models/gallery` — vault-sealed album name + a many-to-many membership; plus system provenance buckets *chat attachments* vs *imported* derived at read time), with manual tagging deferred. Deleting a chat message/conversation that holds image attachments **prompts keep-or-delete**, and an image is purged only when nothing surviving still references it (`ConversationStore.orphaned_attachments_for_delete`). **`GAL-3` (AI auto-tagging) and `GAL-4` (AI image edits) deferred** (no AI-generated artifacts in v1); video has no ingestion pipeline yet. |
| SEARCH-1…3 web search + fetch | ✅ | `services/search`, `services/searxng`, `services/webfetch`, `tools/search.py`, `routes/search`, `models/search` | **Search:** the backend runs its **own** SearXNG in a container (same runtime as the sandbox, image refreshed to latest on boot, loopback-bound) and queries it automatically — **zero operator setup**; the provider CRUD surface (`routes/search`) is an optional override. **Fetch:** `services/webfetch` treats the web as always-dynamic — it renders each URL in a **containerized headless Chromium** (driven over CDP, stealthed to look like a normal browser so sites return what a person would see) and extracts the rendered DOM to Markdown with trafilatura, falling back to innerText. SSRF-guarded on **every** request (initial/redirect/subresource); results untrusted-wrapped. Backs the agent's web tools and unblocks deep research. |
| RAG-1…4 knowledge base (unified corpus) | 🚧 | `services/corpus/*`, `models/corpus`, `routes/corpus`, `tools/corpus.py` | **Foundation landed.** One `CorpusIndex` fans a query out to registered `SourceAdapter`s and RRF-fuses (the shared `services/ranking` primitives). Memory + cross-chat search enroll as wrapper adapters **untouched, zero migration**; chunked content lands in a generic `corpus_chunk` store (sealed text + vector, D18). The one concrete content source is `FolderAdapter` — a lock-aware crawl→chunk→embed (parks while the vault is locked). **Documents** and **Uploads** are enrolled for real (`services/corpus/documents` chunks each document body; `services/corpus/uploads` chunks each upload's extracted text — both replacing their stubs); **research** remains a **stub adapter** listed but empty until its pipeline lands. The **gallery is deliberately not a corpus source** — its images are uploads, already indexed under `surf-uploads`, so a separate gallery source would double-count the same chunks (it is a presentation lens over uploads, not a second source). Each upload carries a per-file **`kb_excluded`** flag (`RAG-4`): the operator can scope a file out of the knowledge base retroactively (`PATCH /uploads/{id}` `kbExcluded`), which restamps its chunks so `corpus.retrieve` drops it everywhere — reversibly, without deleting it. REST mirrors the `/rag` screen (camelCase `RagSource`/`RagIndexStats`); the agent reads the whole corpus via `corpus.retrieve` (folder/upload content untrusted-wrapped), and can scope a read to specific files via `source_ids` (how it reads a just-attached file). **Global recall is approval-gated** (`AE-3.8`, D28) so the operator can keep irrelevant KB content out of context; a `source_ids` read passes through ungated. |
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
| COOK-1 detect hardware + recommend fitting models | 🟡 | `services/cookbook` (`hardware`), `/models/cookbook/hardware*` | Hardware detection retained (degrade-safe psutil + gated subprocess probes). The hardware-fit **ranking** (catalog/sources/recommend/quality) was **removed** as structurally unfixable: the only free quality signal (LMArena) lags the frontier, so the suitability ranking surfaced *old* models on top by design — and download/serve (COOK-3…5) was never built, so the list was un-actionable. Discovering/evaluating new models is now **out of scope by design** — the operator researches externally and configures an endpoint (guided setup, below). The hardware package remains the foundation for fit+recency discovery if/when local serving lands. |
| COOK-2 simulate other hardware | ⬜ | — | Removed with the hardware-fit ranking (the what-if reused the same scorer). Returns alongside discovery if/when fit ranking is reintroduced on the surviving hardware probe. |
| COOK-3…5 download/serve/manage models | 🟡 | `services/serving` (engine recommend + repo-introspected quant discovery, lock-aware HF download manager, process supervisor, pluggable engine adapters, `ServingService` facade), `models/serving` (`ManagedModel`), `routes/serving` (`/models/serving/*`), Cookbook **LOCAL MODELS** + **GET STARTED → Run locally** + **EMBEDDING → serve locally** | The operator chooses the inference engine from a hardware-gated picker (recommended engine preselected; ones the host can't run shown disabled with the reason) and, for llama.cpp, a quantization discovered from the repo's own GGUF files (`GET /models/serving/repo-quants`, defaulting to Auto). They point at a HuggingFace repo and the platform downloads it (visible progress) and supervises an inference engine as a 127.0.0.1 endpoint, registered through the existing registry so it resolves with zero agent-engine changes. **llama.cpp** is the universal baseline (chat + embeddings, all platforms); **MLX** (`mlx-openai-server` in an isolated uv venv, Apple-Silicon chat speed) is present-but-unavailable off arm64 macOS. Operator-UI only in v1; the approval-gated **agent** serve/stop tool is the remaining COOK-5 slice. No Ollama. Restart-safe (lifespan reconcile clean-slates orphan engines; graceful shutdown stops them), and `serve()` runs a pre-flight headroom guard that refuses (naming what to stop) when a model won't fit alongside what's resident. |
| EMB-1 choose/manage embedding model | ✅ | `services/registry` `embedding` role (persisted model pick + bind-time `/embeddings` probe), `services/embeddings` (`probe_embedding`), `routes/models`, Settings ROLE BINDINGS (model picker + degraded badge); local serving via `services/serving` (Cookbook EMBEDDING → serve locally, bound to the `embedding` role) | The role pins an explicit model on its endpoint (its stand-in for `main`'s picker); a non-embeddings model is rejected at bind (422) instead of silently degrading recall. The operator can also download + serve a GGUF embedding model locally (llama.cpp) bound straight to the role, which triggers the EMB-2 reindex. |
| EMB-2 model change re-embeds/segregates | ✅ | `services/memory` (dense gated to model/dim; `reembed`), `services/conversations` (`reindex_embeddings`), `services/reindex` (background coordinator, auto-triggered on model change + `POST /models/embedding/reindex`), startup backfill in `app.py` | Stale-space vectors degrade to sparse, then the reindex heals them into the new model's space (D16/D18). |
| CMP-1…3 blind model compare | ⬜ | — | Surfaced in the Cookbook UI (COMPARE tab). |
| MCP-1…3 external tool servers | ⬜ | — | Gating designed (D25, `AE-3.6`). |
| INTEG-1…3 third-party integrations | ⬜ | — | Gating designed (D25). |

> **Supporting infra, not a spec feature:** the **model role→endpoint registry** (`services/registry`, `models/registry`, `/models/*`) is the single source of truth for model resolution — named roles (`main`/`utility`/`embedding`) → ordered `FallbackModel` chains, per-conversation `main` override (a provider **and** a model on it), API keys encrypted at rest. An **endpoint is a provider connection** (model optional); its served models are **discovered at runtime** from the provider's models API (`GET /models/endpoints/{id}/models`, parsed across OpenAI/Gemini/Ollama-style shapes), so the chat model is chosen from a top-bar picker rather than baked per endpoint. It realizes **D16** and directly backs `AE-5.3`, `CHAT-4`, and `EMB-*`. Two operator-facing surfaces ride this registry: **guided setup** (Cookbook → *Get Started*: pick a provider preset → paste a key → *Connect & use this* tests the endpoint and auto-selects a working model, so chat works without the operator choosing one) and **endpoint health & recovery** (per-endpoint connection test with backend-categorized errors, disable-without-delete). Both are UX over existing infra — no dedicated spec rows yet (candidate `COOK`/`XC` additions to surface).

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

The code-execution sandbox is in (`XC-SEC-7`/`AE-3.4` ✅) with the unified View (versions + live head) on top, and **web search is now in** (`SEARCH-*`/`XC-DEG-2` ✅), which also stood up the first untrusted-content marking (`XC-SEC-5` 🟡). The cheapest, highest-leverage next slices are the ones whose **chassis already exists and only the capability is missing**:

1. **Deep research** (`DR-*` / D19) — now unblocked (its `search` dependency landed); it's "write the pipeline orchestrator + wire the existing search/fetch tools," reusing the Run substrate, bounds, cancellation, and progress streaming it already inherits. Chat attachments enrolled at upload time are already corpus-reachable from a research run; the orchestrator references them via `corpus.retrieve` and the shared `agent/attachments` helper when built.
2. **The scheduler** (`TASK-*` + D13) — turns `AE-3.5`/D24 pre-authorization from design into running unattended automation, reusing the approval mechanism already built.

Each is additive over the foundation, not a rebuild — which is the whole point of having spent the early passes on the chassis.

→ see also: [`40-tools-and-toolsets.md`](./40-tools-and-toolsets.md) (gating detail), [`decisions.md`](./decisions.md) (the D-numbers cited here), and the per-area specs under [`../spec/`](../spec/).
