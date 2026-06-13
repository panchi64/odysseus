# 20 — Feature Inventory

Requirements for the rest of the system. Each feature lists its **purpose** and its **requirements**. The agent and deep research have their own documents.

**Access model.** Odysseus has a **single operator** (`XC-SEC-2`): every feature belongs to that operator, every request is authenticated (`XC-SEC-1`), and every record is owner-stamped against the future multi-user seam (`XC-SEC-6`). There are no privilege tiers. The only access distinction that carries weight is **sensitivity**: powerful or hard-to-reverse capabilities — running code or commands **on the host**, host filesystem writes, sending email, model serving/management, configuration, vault access, and externally-registered tools (`AE-3.6`) — are **approval-gated** when the *agent* invokes them (`AE-3`); the operator performs them directly. (Sandboxed code execution is *not* sensitive — it is isolated from the host, `XC-SEC-7`.) Features below flag this where it applies — as a **Sensitive** note or an explicit requirement — in place of an access tier.

---

## A. Conversation

### Chat (`CHAT-*`)

**Purpose:** Hold a conversation with a model, optionally drawing on tools, attachments, and linked content.

- **CHAT-1 (MUST).** The user MUST be able to send a message containing text, links, and file attachments, and receive a streamed reply.
- **CHAT-2 (MUST).** Linked URLs and uploaded files MUST be made available to the model as context for the reply.
- **CHAT-3 (MUST).** Every message runs through the agent path: the full set of permitted tools is offered and the model itself decides whether to call any — including none, for a message that needs only a direct answer. There is no separate pre-classification step that routes a message away from the agent.
- **CHAT-4 (SHOULD — performance).** When a conversation grows near the model's context limit, older history SHOULD be summarized to stay within budget without losing the thread; summarization MAY use a separate, configurable utility model.
- **CHAT-5 (MUST).** The user MUST be able to stop an in-progress reply, and a reply interrupted by a disconnect MUST be resumable.
- **CHAT-6 (SHOULD).** The user SHOULD be able to ask the AI to rewrite or rephrase an existing message in the conversation.

---

## B. Knowledge & content

### Long-term memory (`MEM-*`)

**Purpose:** Remember facts and preferences across conversations and recall them when relevant.

- **MEM-1 (MUST).** The user MUST be able to store, view, edit, and delete memories, and to browse them in a chronological timeline.
- **MEM-2 (MUST).** Relevant memories MUST be recalled by meaning, with a keyword fallback when semantic search is unavailable.
- **MEM-3 (SHOULD).** On a user-triggered audit, near-duplicate and redundant memories SHOULD be detected and consolidated automatically.
- **MEM-4 (MAY).** Memories MAY be pinned to always be included, MAY be imported from uploaded files, and MAY be extracted from an existing conversation on request.

### Skills (`SKILL-*`)

**Purpose:** Capture reusable know-how the agent can accumulate and apply to future tasks.

- **SKILL-1 (MUST).** Skills MUST be creatable, viewable, editable, publishable, and deletable, each describing when to use it, how to do it, pitfalls, and how to verify success.
- **SKILL-2 (MUST).** The agent MUST be able to find and apply relevant published skills, with relevant skills surfaced to it automatically as guidance during a task.
- **SKILL-3 (SHOULD).** Edits SHOULD support small, surgical changes, not only full rewrites.
- **SKILL-4 (MAY).** Skills the system writes from its own successful recoveries MAY be auto-published when their measured confidence exceeds an operator-set threshold.
- **SKILL-5 (MAY).** Skills MAY be tested and automatically refined against a task benchmark.
- **SKILL-6 (MAY).** The operator MAY override the guidance attached to built-in tools.

### Documents & editor (`DOC-*`)

**Purpose:** A library of editable documents with version history and AI assistance.

- **DOC-1 (MUST).** The user MUST be able to create, edit, archive, restore, and search documents; the document's type/language MUST be detected for appropriate display.
- **DOC-2 (MUST).** Every change MUST be versioned with its origin (user, AI, or extraction) and MUST be restorable to an earlier version.
- **DOC-3 (MUST).** The AI MUST be able to fully rewrite a document, make targeted edits, or propose suggestions, with edits streaming into view as produced. Suggestions MUST be reviewable change-by-change with accept/reject (and accept-all) controls before anything is applied.
- **DOC-4 (SHOULD).** The library SHOULD support multi-term search and sorting, de-duplication of near-identical documents, and removal of junk documents via both a fast heuristic pass and an AI-assisted review.
- **DOC-5 (SHOULD).** Documents SHOULD be exportable individually (including rendering filled PDF forms) and in bulk.
- **DOC-6 (SHOULD).** Documents SHOULD support lightweight note-keeping: checklist items within a document, and organization of the library by labels and pinning.

### Uploads & PDFs (`UP-*`)

**Purpose:** Accept files and make their contents usable, including scanned and fillable PDFs.

- **UP-1 (MUST).** The user MUST be able to upload files; duplicate uploads MUST be recognized.
- **UP-2 (MUST).** Text MUST be extracted from PDFs, including image-only/scanned PDFs via vision when needed; extracted text SHOULD be retained per upload and be correctable by the user afterward.
- **UP-3 (SHOULD).** Fillable PDF forms SHOULD be detected and their fields made editable.
- **UP-4 (MUST — performance).** Uploads MUST be rate-limited to protect the service.

### Gallery & image editing (`GAL-*`)

**Purpose:** An image/video library with AI-assisted editing.

- **GAL-1 (MUST).** The user MUST be able to upload, browse, favorite, delete, and export images and videos; capture metadata (dimensions, camera, location, date) SHOULD be retained.
- **GAL-2 (SHOULD).** The user SHOULD be able to organize media into named albums and to tag items, with manually-added tags kept distinct from automatically-generated ones.
- **GAL-3 (SHOULD).** Items SHOULD be taggable automatically by the AI, individually or in batches.
- **GAL-4 (SHOULD).** The user SHOULD be able to apply AI image edits — upscale, remove background, inpaint, sharpen, denoise, enhance faces, and apply a reference style — with results saved back to their own library.

### Web search (`SEARCH-*`)

**Purpose:** Search the web and retrieve page content for the user and the agent.

- **SEARCH-1 (MUST).** The system MUST search the web through a configurable provider, with fallback to alternates when one returns nothing.
- **SEARCH-2 (MUST).** It MUST be able to fetch and extract the readable content of result pages.
- **SEARCH-3 (SHOULD).** Results SHOULD be ranked for relevance, and SHOULD be cached with a freshness window appropriate to the query.

### Personal knowledge base (`RAG-*`)

**Purpose:** Index a folder of the user's own documents so the agent can retrieve from them by meaning.

- **RAG-1 (MUST).** The user MUST be able to point the system at a local document collection and have it indexed for semantic retrieval, separate from chat uploads and the document editor.
- **RAG-2 (MUST).** Indexed content MUST be retrievable by meaning during chat and agent tasks, and the index MUST be re-buildable as the source files change.
- **RAG-3 (SHOULD).** The user SHOULD be able to see what is indexed and its status, and remove items from the index.

### Code runner (`RUN-*`)

**Purpose:** Run small code snippets directly in the browser.

- **RUN-1 (SHOULD).** The user SHOULD be able to execute Python, JavaScript, and HTML snippets in-app and see their output, without those snippets running on the host machine.

---

## C. Communication & personal information

### Email (`EMAIL-*`)

**Purpose:** A mail client with AI triage.

- **EMAIL-1 (MUST).** The user MUST be able to list, read, send, and reply to email across one or more accounts.
- **EMAIL-2 (MUST).** Incoming mail MUST be triaged automatically: summarized, tagged by category, assessed for urgency, and flagged as spam, with alerts for urgent messages.
- **EMAIL-3 (SHOULD).** Reply drafts SHOULD be pre-generated using prior context with the sender and the user's writing style. The system SHOULD be able to learn that writing style from the user's sent mail into a profile the user can view and edit.
- **EMAIL-4 (SHOULD).** Calendar events implied by email SHOULD be surfaced; quoted text and signatures SHOULD be separable for clean display.
- **EMAIL-5 (SHOULD — performance).** Inbox listings SHOULD be cached briefly for responsiveness.
- **Sensitive:** the agent sending or replying to email is approval-gated (`AE-3.1`).

### Calendar (`CAL-*`)

**Purpose:** A calendar that can sync from remote CalDAV sources.

- **CAL-1 (MUST).** The user MUST be able to create, view, edit, and delete events, including all-day and recurring events, with correct time-zone handling.
- **CAL-2 (SHOULD).** Remote calendars SHOULD be syncable into the local calendar; import and export via standard calendar files MUST be supported.
- **CAL-3 (SHOULD).** Natural-language event entry (e.g. "lunch Friday 1pm") SHOULD be parsed into a structured event.

### Tasks & scheduling (`TASK-*`)

**Purpose:** Recurring automated jobs and reminders the agent or built-in actions perform.

- **TASK-1 (MUST).** The user MUST be able to define scheduled tasks (recurring or one-off, including cron-style) and tasks triggered by events or inbound webhooks.
- **TASK-2 (MUST).** A task's output MUST be deliverable to a chat session, a notification, or email; each run MUST record its outcome.
- **TASK-3 (SHOULD).** Tasks MAY invoke predefined automation actions (e.g. email triage, housekeeping) in addition to free-form agent work, and MAY chain to a follow-up task on success.
- **TASK-4 (SHOULD).** Natural-language task descriptions SHOULD be parseable into a structured schedule.
- **TASK-5 (MUST).** Tasks MUST run without overlapping in a way that overloads the system.
- **TASK-6 (MUST).** Reminders MUST fire on their scheduled date through the user's chosen channels — in-app, email, and push — and MUST NOT deliver duplicates for the same reminder; reminder messages MAY be phrased by the AI for context rather than sent verbatim.
- **Sensitive:** scheduling a task is itself approval-gated — the operator reviews it and **pre-authorizes** the sensitive actions it may perform unattended (`AE-3.5`); within that scope its runs proceed without re-prompting, and anything outside it falls back to pause-and-notify (`AE-3.2`). Code a task runs still follows the code-execution rules (sandboxed by default; host execution approval-gated — `XC-SEC-7`, `AE-3.4`).

---

## D. Models & infrastructure

### Model Cookbook (`COOK-*`)

**Purpose:** Match models to the operator's hardware, download them, and serve them.

- **COOK-1 (MUST).** The system MUST detect the host's hardware (accelerators, memory, compute backend) and recommend models that fit, ranked by suitability.
- **COOK-2 (SHOULD).** The operator SHOULD be able to simulate other hardware to see what would fit.
- **COOK-3 (MUST).** The operator MUST be able to download a model with visible progress and have failed downloads retried.
- **COOK-4 (MUST).** The operator MUST be able to start and stop a model server, on the local host or a remote one, with startup errors surfaced; served models MUST become usable endpoints.
- **COOK-5 (SHOULD).** The Cookbook SHOULD cover image-generation (diffusion) models as well as language models — recommending ones that fit, serving them, and registering them as usable image endpoints.
- **Sensitive:** the agent downloading, serving, or stopping a model is approval-gated (`AE-3.1`); the operator manages models directly.

### Embedding models (`EMB-*`)

**Purpose:** Choose and manage the model that powers semantic search and recall.

- **EMB-1 (MUST).** The operator MUST be able to select the embedding model used for semantic retrieval, including downloading a local model or pointing at a custom endpoint.
- **EMB-2 (SHOULD).** A change of embedding model SHOULD take effect without losing the ability to retrieve existing content.

### Compare (`CMP-*`)

**Purpose:** Compare models side by side, blind, then reveal.

- **CMP-1 (MUST).** The user MUST be able to send the same prompt to two or more models and see their responses side by side without knowing which is which.
- **CMP-2 (MUST).** The user MUST be able to vote for a winner; only after voting are the model identities revealed.
- **CMP-3 (SHOULD).** Past comparisons SHOULD be viewable and deletable.

### External tools (MCP) (`MCP-*`)

**Purpose:** Extend the agent with external tool servers.

- **MCP-1 (MUST).** The operator MUST be able to register external tool servers, discover their tools, and enable or disable individual tools.
- **MCP-2 (MUST).** Registered external tools MUST become available to the agent, subject to the same enable/disable control as built-in tools (`AE-3.3`) and to the external-tool gating in `AE-3.6` (sensitive by default until the operator marks a tool trusted).
- **MCP-3 (SHOULD).** Connections SHOULD be manageable (reconnect, disable, remove), including those requiring third-party authorization.
- **Sensitive:** registering an external tool server is operator configuration; the tools it exposes are approval-gated by default until the operator marks them trusted (`AE-3.6`).

### Integrations (`INTEG-*`)

**Purpose:** Connect to third-party HTTP services through preset connectors.

- **INTEG-1 (MUST).** The operator MUST be able to configure connectors from presets, supplying credentials that are stored encrypted.
- **INTEG-2 (MUST).** The agent MUST be able to call a configured integration on the user's behalf, subject to the external-tool gating in `AE-3.6` (sensitive by default until the operator marks it trusted).
- **INTEG-3 (SHOULD).** The operator SHOULD be able to test a connector's credentials before relying on it.
- **Sensitive:** configuring a connector and its credentials is operator configuration; the agent calling a configured integration is approval-gated by default until the operator marks it trusted (`AE-3.6`).

---

## E. Security & operations

### Authentication & access (`AUTH-*`)

**Purpose:** Identity, API tokens, and inbound webhooks.

- **AUTH-1 (MUST).** The operator MUST be able to log in with a password — the same password that unlocks at-rest encryption (`XC-SEC-4`), chosen at first-run setup. Login attempts MUST be rate-limited to resist brute force.
- **AUTH-3 (deferred — multi-user seam).** With a single operator there is no user administration. Should multiple accounts ever be introduced, the operator MUST be able to manage users and their per-feature privileges; until a second human exists this is carried only by the `owner_id` seam (`XC-SEC-6`), with nothing to enforce.
- **AUTH-4 (MUST).** The operator MUST be able to issue and revoke scoped API tokens for programmatic access.
- **AUTH-5 (SHOULD).** Inbound webhooks SHOULD be able to trigger scheduled tasks.

### Password vault — secrets manager (`VAULT-*`)

**Purpose:** A password manager for the operator's stored credentials and secrets — an additional encrypted layer on top of at-rest encryption. Distinct from the system's **encryption vault** (the password-derived key custody that unlocks the app at login, `XC-SEC-3`); this `VAULT-*` feature is the user-facing place to keep secrets.

- **VAULT-1 (MUST).** The operator MUST be able to configure, unlock, lock, and log out of the password vault; its unlocked state MUST be held in memory only, never persisted.
- **VAULT-2 (MUST).** The agent accessing the password vault is a sensitive action and MUST be approval-gated (`AE-3.1`).

### Backup & restore (`BACKUP-*`)

**Purpose:** Export and re-import user data.

- **BACKUP-1 (MUST).** The operator MUST be able to export their data (memories, skills, presets, settings, and preferences) as a single file. The export MUST be encrypted under a separate backup secret (a recovery key or passphrase) so it carries no plainly-readable user data and can be decrypted on another host (`XC-SEC-3`).
- **BACKUP-2 (MUST).** Importing MUST merge data without creating duplicates, and MUST attribute imported records to the operator (the ownership seam, `XC-SEC-6`).

### Host shell (`SHELL-*`)

**Purpose:** The operator's own terminal for running commands directly on the host — deliberately gated, and never reachable by the agent.

- **SHELL-1 (MUST).** The operator MUST be able to run shell commands on the host directly and see their output streamed back — a deliberate, operator-driven terminal.
- **SHELL-2 (MUST).** This terminal is the operator's alone: it MUST NOT be exposed as, or reachable by, any agent tool. The agent's only path to host execution is the separate, explained, approval-gated tool (`AE-3.4`, `XC-SEC-7`).
- **SHELL-3 (MUST).** Opening the host terminal MUST require an explicit, freshly re-authenticated **host mode** — a deliberate confirmation step beyond ordinary login — before any direct host command can be run, so host access is never a single click away from a normal session.

---

> Supporting utilities (diagnostics, cleanup, history, preferences, presets, sessions, and similar) provide standard create/read/update/delete and status functions over the data above and follow the same access model. They can be promoted to full requirements here on request.
