# 20 — Feature Inventory

Requirements for the rest of the system. Each feature lists its **purpose**, its **requirements**, and its **access** (who may use it). The agent and deep research have their own documents.

**Access vocabulary:** *open* means any authenticated user with no additional privilege required (it does not mean unauthenticated — when authentication is enabled, every request is still authenticated per `XC-SEC-1`); *per-user* means gated by a per-user privilege; *administrator* means restricted to admin users.

---

## A. Conversation

### Chat (`CHAT-*`)

**Purpose:** Hold a conversation with a model, optionally drawing on tools, attachments, and linked content.

- **CHAT-1 (MUST).** The user MUST be able to send a message containing text, links, and file attachments, and receive a streamed reply.
- **CHAT-2 (MUST).** Linked URLs and uploaded files MUST be made available to the model as context for the reply.
- **CHAT-3 (MUST).** The system MUST decide per message whether a direct answer suffices or the agent's tools are needed, and proceed accordingly.
- **CHAT-4 (SHOULD — performance).** When a conversation grows near the model's context limit, older history SHOULD be summarized to stay within budget without losing the thread; summarization MAY use a separate, configurable utility model.
- **CHAT-5 (MUST).** The user MUST be able to stop an in-progress reply, and a reply interrupted by a disconnect MUST be resumable.
- **CHAT-6 (SHOULD).** The user SHOULD be able to ask the AI to rewrite or rephrase an existing message in the conversation.
- **Access:** per-user.

---

## B. Knowledge & content

### Long-term memory (`MEM-*`)

**Purpose:** Remember facts and preferences across conversations and recall them when relevant.

- **MEM-1 (MUST).** The user MUST be able to store, view, edit, and delete memories, and to browse them in a chronological timeline.
- **MEM-2 (MUST).** Relevant memories MUST be recalled by meaning, with a keyword fallback when semantic search is unavailable.
- **MEM-3 (SHOULD).** On a user-triggered audit, near-duplicate and redundant memories SHOULD be detected and consolidated automatically.
- **MEM-4 (MAY).** Memories MAY be pinned to always be included, MAY be imported from uploaded files, and MAY be extracted from an existing conversation on request.
- **Access:** per-user privilege.

### Skills (`SKILL-*`)

**Purpose:** Capture reusable know-how the agent can accumulate and apply to future tasks.

- **SKILL-1 (MUST).** Skills MUST be creatable, viewable, editable, publishable, and deletable, each describing when to use it, how to do it, pitfalls, and how to verify success.
- **SKILL-2 (MUST).** The agent MUST be able to find and apply relevant published skills, with relevant skills surfaced to it automatically as guidance during a task.
- **SKILL-3 (SHOULD).** Edits SHOULD support small, surgical changes, not only full rewrites.
- **SKILL-4 (MAY).** Skills the system writes from its own successful recoveries MAY be auto-published when their measured confidence exceeds an operator-set threshold.
- **SKILL-5 (MAY).** Skills MAY be tested and automatically refined against a task benchmark.
- **SKILL-6 (MAY).** Administrators MAY override the guidance attached to built-in tools.
- **Access:** per-user; built-in-tool overrides restricted to administrators.

### Documents & editor (`DOC-*`)

**Purpose:** A library of editable documents with version history and AI assistance.

- **DOC-1 (MUST).** The user MUST be able to create, edit, archive, restore, and search documents; the document's type/language MUST be detected for appropriate display.
- **DOC-2 (MUST).** Every change MUST be versioned with its origin (user, AI, or extraction) and MUST be restorable to an earlier version.
- **DOC-3 (MUST).** The AI MUST be able to fully rewrite a document, make targeted edits, or propose suggestions, with edits streaming into view as produced. Suggestions MUST be reviewable change-by-change with accept/reject (and accept-all) controls before anything is applied.
- **DOC-4 (SHOULD).** The library SHOULD support multi-term search and sorting, de-duplication of near-identical documents, and removal of junk documents via both a fast heuristic pass and an AI-assisted review.
- **DOC-5 (SHOULD).** Documents SHOULD be exportable individually (including rendering filled PDF forms) and in bulk.
- **Access:** per-document owner.

### Uploads & PDFs (`UP-*`)

**Purpose:** Accept files and make their contents usable, including scanned and fillable PDFs.

- **UP-1 (MUST).** The user MUST be able to upload files; duplicate uploads MUST be recognized per user.
- **UP-2 (MUST).** Text MUST be extracted from PDFs, including image-only/scanned PDFs via vision when needed; extracted text SHOULD be retained per upload and be correctable by the user afterward.
- **UP-3 (SHOULD).** Fillable PDF forms SHOULD be detected and their fields made editable; one user's signature/form data MUST NOT be exposed to another user.
- **UP-4 (MUST — performance).** Uploads MUST be rate-limited to protect the service.
- **Access:** per-user.

### Gallery & image editing (`GAL-*`)

**Purpose:** An image/video library with AI-assisted editing.

- **GAL-1 (MUST).** The user MUST be able to upload, browse, favorite, delete, and export images and videos; capture metadata (dimensions, camera, location, date) SHOULD be retained.
- **GAL-2 (SHOULD).** The user SHOULD be able to organize media into named albums and to tag items, with manually-added tags kept distinct from automatically-generated ones.
- **GAL-3 (SHOULD).** Items SHOULD be taggable automatically by the AI, individually or in batches.
- **GAL-4 (SHOULD).** The user SHOULD be able to apply AI image edits — upscale, remove background, inpaint, sharpen, denoise, enhance faces, and apply a reference style — with results saved back to their own library.
- **Access:** per-user.

### Web search (`SEARCH-*`)

**Purpose:** Search the web and retrieve page content for the user and the agent.

- **SEARCH-1 (MUST).** The system MUST search the web through a configurable provider, with fallback to alternates when one returns nothing.
- **SEARCH-2 (MUST).** It MUST be able to fetch and extract the readable content of result pages.
- **SEARCH-3 (SHOULD).** Results SHOULD be ranked for relevance, and SHOULD be cached with a freshness window appropriate to the query.
- **Access:** open.

### Personal knowledge base (`RAG-*`)

**Purpose:** Index a folder of the user's own documents so the agent can retrieve from them by meaning.

- **RAG-1 (MUST).** The user MUST be able to point the system at a local document collection and have it indexed for semantic retrieval, separate from chat uploads and the document editor.
- **RAG-2 (MUST).** Indexed content MUST be retrievable by meaning during chat and agent tasks, and the index MUST be re-buildable as the source files change.
- **RAG-3 (SHOULD).** The user SHOULD be able to see what is indexed and its status, and remove items from the index.
- **Access:** per-user.

### Signatures (`SIG-*`)

**Purpose:** Save reusable handwritten signatures for documents and mail.

- **SIG-1 (MUST).** The user MUST be able to draw, save, and reuse signatures, and apply one to a PDF form field or an outgoing email.
- **SIG-2 (MUST).** One user's saved signatures MUST NOT be visible to another user.
- **Access:** per-user.

### Code runner (`RUN-*`)

**Purpose:** Run small code snippets directly in the browser.

- **RUN-1 (SHOULD).** The user SHOULD be able to execute Python, JavaScript, and HTML snippets in-app and see their output, without those snippets running on the host machine.
- **Access:** per-user.

---

## C. Communication & personal information

### Email (`EMAIL-*`)

**Purpose:** A mail client with AI triage.

- **EMAIL-1 (MUST).** The user MUST be able to list, read, send, and reply to email across one or more accounts.
- **EMAIL-2 (MUST).** Incoming mail MUST be triaged automatically: summarized, tagged by category, assessed for urgency, and flagged as spam, with alerts for urgent messages.
- **EMAIL-3 (SHOULD).** Reply drafts SHOULD be pre-generated using prior context with the sender and the user's writing style. The system SHOULD be able to learn that writing style from the user's sent mail into a profile the user can view and edit.
- **EMAIL-4 (SHOULD).** Calendar events implied by email SHOULD be surfaced; quoted text and signatures SHOULD be separable for clean display.
- **EMAIL-5 (SHOULD — performance).** Inbox listings SHOULD be cached briefly for responsiveness.
- **Access:** per-user account ownership.

### Calendar (`CAL-*`)

**Purpose:** A calendar that can sync from remote CalDAV sources.

- **CAL-1 (MUST).** The user MUST be able to create, view, edit, and delete events, including all-day and recurring events, with correct time-zone handling.
- **CAL-2 (SHOULD).** Remote calendars SHOULD be syncable into the local calendar; import and export via standard calendar files MUST be supported.
- **CAL-3 (SHOULD).** Natural-language event entry (e.g. "lunch Friday 1pm") SHOULD be parsed into a structured event.
- **Access:** per-user.

### Contacts (`CONTACT-*`)

**Purpose:** A contact directory, optionally backed by CardDAV.

- **CONTACT-1 (MUST).** The user MUST be able to create, view, edit, delete, and search contacts with multiple emails and phone numbers each.
- **CONTACT-2 (SHOULD).** Contacts SHOULD be backed by a remote CardDAV directory when configured, falling back to local storage otherwise; they SHOULD be importable/exportable in standard formats, and the agent SHOULD be able to resolve a name to a contact.
- **Access:** administrator.

### Notes (`NOTE-*`)

**Purpose:** Quick notes and checklists with reminders.

- **NOTE-1 (MUST).** The user MUST be able to create notes with labels, color, pinning, archiving, due dates, repetition, and checklist items.
- **NOTE-2 (MUST).** Reminders MUST fire on the due date through the user's chosen channels (in-app, email, push) and MUST NOT deliver duplicates for the same reminder.
- **NOTE-3 (MAY).** Reminder messages MAY be phrased by the AI for context rather than sent verbatim.
- **Access:** per-user.

### Tasks & scheduling (`TASK-*`)

**Purpose:** Recurring automated jobs the agent or built-in actions perform.

- **TASK-1 (MUST).** The user MUST be able to define scheduled tasks (recurring or one-off, including cron-style) and tasks triggered by events or inbound webhooks.
- **TASK-2 (MUST).** A task's output MUST be deliverable to a chat session, a notification, or email; each run MUST record its outcome.
- **TASK-3 (SHOULD).** Tasks MAY invoke predefined automation actions (e.g. email triage, housekeeping) in addition to free-form agent work, and MAY chain to a follow-up task on success.
- **TASK-4 (SHOULD).** Natural-language task descriptions SHOULD be parseable into a structured schedule.
- **TASK-5 (MUST).** Tasks MUST run without overlapping in a way that overloads the system.
- **Access:** per-user; system-level actions (running local commands or scripts) restricted to administrators.

---

## D. Models & infrastructure

### Model Cookbook (`COOK-*`)

**Purpose:** Match models to the operator's hardware, download them, and serve them.

- **COOK-1 (MUST).** The system MUST detect the host's hardware (accelerators, memory, compute backend) and recommend models that fit, ranked by suitability.
- **COOK-2 (SHOULD).** The operator SHOULD be able to simulate other hardware to see what would fit.
- **COOK-3 (MUST).** The operator MUST be able to download a model with visible progress and have failed downloads retried.
- **COOK-4 (MUST).** The operator MUST be able to start and stop a model server, on the local host or a remote one, with startup errors surfaced; served models MUST become usable endpoints.
- **COOK-5 (SHOULD).** The Cookbook SHOULD cover image-generation (diffusion) models as well as language models — recommending ones that fit, serving them, and registering them as usable image endpoints.
- **Access:** administrator.

### Embedding models (`EMB-*`)

**Purpose:** Choose and manage the model that powers semantic search and recall.

- **EMB-1 (MUST).** The operator MUST be able to select the embedding model used for semantic retrieval, including downloading a local model or pointing at a custom endpoint.
- **EMB-2 (SHOULD).** A change of embedding model SHOULD take effect without losing the ability to retrieve existing content.
- **Access:** administrator.

### Compare (`CMP-*`)

**Purpose:** Compare models side by side, blind, then reveal.

- **CMP-1 (MUST).** The user MUST be able to send the same prompt to two or more models and see their responses side by side without knowing which is which.
- **CMP-2 (MUST).** The user MUST be able to vote for a winner; only after voting are the model identities revealed.
- **CMP-3 (SHOULD).** Past comparisons SHOULD be viewable and deletable.
- **Access:** per-user.

### External tools (MCP) (`MCP-*`)

**Purpose:** Extend the agent with external tool servers.

- **MCP-1 (MUST).** The operator MUST be able to register external tool servers, discover their tools, and enable or disable individual tools.
- **MCP-2 (MUST).** Registered external tools MUST become available to the agent, subject to access control.
- **MCP-3 (SHOULD).** Connections SHOULD be manageable (reconnect, disable, remove), including those requiring third-party authorization.
- **Access:** administrator.

### Integrations (`INTEG-*`)

**Purpose:** Connect to third-party HTTP services through preset connectors.

- **INTEG-1 (MUST).** The operator MUST be able to configure connectors from presets, supplying credentials that are stored encrypted.
- **INTEG-2 (MUST).** The agent MUST be able to call a configured integration on the user's behalf.
- **INTEG-3 (SHOULD).** The operator SHOULD be able to test a connector's credentials before relying on it.
- **Access:** administrator to configure.

### Speech (`AUDIO-*`)

**Purpose:** Text-to-speech and speech-to-text.

- **AUDIO-1 (MUST).** The system MUST synthesize speech from text and transcribe speech from audio, each through a selectable provider (including local and remote options) that can be changed without restart.
- **AUDIO-2 (SHOULD — performance).** Synthesized audio SHOULD be cached so identical requests are not re-computed.
- **Access:** open.

---

## E. Security & operations

### Authentication & access (`AUTH-*`)

**Purpose:** Identity, two-factor, API tokens, and inbound webhooks.

- **AUTH-1 (MUST).** Users MUST be able to log in with a password; sign-up and login MUST be rate-limited.
- **AUTH-2 (MUST).** Users MUST be able to enable two-factor authentication (TOTP) with backup codes, and disable it with password confirmation.
- **AUTH-3 (MUST).** Administrators MUST be able to manage users and their per-feature privileges.
- **AUTH-4 (MUST).** Users MUST be able to issue and revoke scoped API tokens for programmatic access.
- **AUTH-5 (SHOULD).** Inbound webhooks SHOULD be able to trigger scheduled tasks.
- **Access:** login/sign-up open; user and token administration restricted to administrators.

### Password vault (`VAULT-*`)

**Purpose:** Access an encrypted password vault.

- **VAULT-1 (MUST).** The operator MUST be able to configure, unlock, lock, and log out of a password vault; the vault session MUST be stored securely.
- **VAULT-2 (MUST).** Vault access through the agent MUST be restricted to administrators.
- **Access:** administrator.

### Backup & restore (`BACKUP-*`)

**Purpose:** Export and re-import user data.

- **BACKUP-1 (MUST).** The operator MUST be able to export memories, skills, presets, settings, and preferences as a single file.
- **BACKUP-2 (MUST).** Importing MUST merge data without creating duplicates and assign ownership appropriately.
- **Access:** administrator.

### Host shell (`SHELL-*`)

**Purpose:** Run commands on the host machine from the app.

- **SHELL-1 (MUST).** An administrator MUST be able to run shell commands on the host and see their output streamed back.
- **SHELL-2 (MUST).** Host shell access MUST be restricted to administrators and MUST NOT be reachable by non-administrator users or by per-user agent tools.
- **Access:** administrator.

---

> Supporting utilities (diagnostics, cleanup, history, preferences, presets, sessions, and similar) provide standard create/read/update/delete and status functions over the data above and follow the same access model. They can be promoted to full requirements here on request.
