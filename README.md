# Odysseus
───────────────────────────────────────────────
 ⊹ ࣪ ˖ ૮( ˶ᵔ ᵕ ᵔ˶ )っ  Odysseus vers. 2.0
───────────────────────────────────────────────

A self-hosted AI workspace that runs on your own hardware against your own data. Local-first, encrypted at rest, built for personal use (1 user).

![Odysseus — the agent working through a task, with its work log, tool calls, and a published artifact inline](md-assets/odysseus-screenshot.png)

I rebuilt the entire platform on top of **Pydantic AI + FastAPI**, and it's still in progress. The core is done, though: you can chat, and the full agent loop is implemented — tools, sandboxed code, web search, memory, approval gates, resumable runs, and encryption at rest. The rest of the nice-to-have features (research, email, calendar, the model Cookbook, documents, and more) are specified but not built yet. The sections below separate what runs today from what's planned.

## The idea

**Pydantic AI is the engine; the code I wrote around it is the chassis.** All agentic reasoning — the model call, tool selection, typed-arg validation, the within-turn tool→observe→continue loop, retries, fallback, output validation, history processing — runs *through* Pydantic AI. Everything that turns one model run into a durable, observable, resumable product — run lifecycle, the event stream, disconnect-survival and resume, cancellation, timeouts, persistence, access policy, the verifier/loop-break meta-loop — is what I built. Like I said up top, Odysseus assumes one powerful local host, a single operator, and models capable of native tool calling.

## What runs today

Here's what already works, built and tested in `backend/`:

- **Chat.** Every message runs the full agent path rather than a pre-classified route: the model sees the whole permitted tool catalog and decides what to call. Replies stream incrementally, survive a disconnect, and resume on reconnect. Conversations branch through regenerate, edit, and rewind. Works against local models and API providers (vLLM, llama.cpp, Ollama, OpenAI-compatible).
- **The agent engine.** A Pydantic AI `Agent` driven node by node, wrapped in a meta-loop — an always-on no-progress guard plus an opt-in post-turn verifier — with first-turn auto-titling.
- **Sensitive-action approval.** A powerful tool call parks the run and asks before it executes; approving or denying resumes it.
- **Sandboxed code, artifacts, and previews.** The agent runs code in a host-isolated, per-conversation container that fails closed and never touches the host, publishes artifacts into an encrypted store, and serves live previews through a token-gated reverse proxy.
- **Web search and fetch.** A managed SearXNG instance with no operator setup, SSRF-guarded page fetch, and untrusted content marked as data.
- **Long-term memory.** Store, view, edit, and delete entries, with hybrid semantic-plus-keyword recall that degrades to keyword-only when the vector store is unavailable.
- **Model registry.** Named roles (`main`, `utility`, `embedding`) map to ordered fallback chains; endpoints discover their served models at runtime; conversations can override the model; API keys are encrypted at rest.
- **Embeddings.** Selectable model behind semantic search and recall.
- **Health.** Per-capability status for the operator covering model, embeddings, sandbox, and search.
- **Auth and at-rest encryption.** A global auth gate (cookie or bearer); all user data AES-256 encrypted under a password-derived, memory-only, lock-until-unlocked key.

The spec-to-build ledger is in [`docs/architecture/70-spec-coverage.md`](docs/architecture/70-spec-coverage.md).

## What's planned

These are all specified in [`docs/spec/`](docs/spec/README.md), and they reuse the same run substrate that already powers chat:

- **Deep Research** — multi-round runs that plan, search, read, analyze, and write a cited report, bounded by rounds and time, reusing the run substrate.
- **Documents** — a multi-tab editor where you write and the agent assists with rewrites, targeted edits, reviewable suggestions, and versioning.
- **Skills** — reusable know-how the agent accumulates and applies to later tasks.
- **Gallery** — an image and video library with AI editing (upscale, background removal, inpaint, restyle).
- **Uploads** — files as context, including text extraction from scanned and fillable PDFs.
- **Knowledge Base** — point it at a folder of your own documents and retrieve from them by meaning (RAG).
- **Code Runner** — run Python, JS, and HTML snippets in the browser, never on the host.
- **Email** — IMAP/SMTP across accounts with AI triage: urgency, tagging, summaries, reply drafts, spam handling.
- **Calendar** — a local-first calendar with CalDAV sync and `.ics` import/export.
- **Tasks** — scheduled and event-triggered jobs the agent runs unattended within a pre-authorized scope.
- **Cookbook** — scans your hardware, recommends models that fit, then downloads and serves them (VRAM-aware; GGUF, FP8, AWQ; vLLM and llama.cpp; diffusion models too).
- **Compare** — send one prompt to several models, judge them blind, then reveal.
- **MCP** — register external tool servers; their tools are sensitive by default until you trust them.
- **Integrations** — preset connectors to third-party HTTP services, with encrypted credentials.
- **API tokens** — scoped tokens and inbound webhooks for programmatic access.
- **Vault** — a password manager layered on the at-rest encryption; agent access is approval-gated.
- **Host shell** — the operator's own terminal behind a re-authenticated host mode, never reachable by the agent.
- **Backup and restore** — encrypted export under a separate backup secret, with merge-import that avoids duplicates.

## Architecture

There are two halves, kept cleanly separate: the frontend renders and captures intent, and **all the logic lives in the backend.** See [`docs/architecture/`](docs/architecture/README.md) for the full design, and [`docs/architecture/decisions.md`](docs/architecture/decisions.md) for every decision and its trade-offs.

```
frontend/     SolidJS / SolidStart SPA · TypeScript · Tailwind v4 · Vite
              terminal-HUD design system (Phosphor / Paper) · typed mock-data seam;
              home · chat · memory · settings wired to the real backend, the rest on mocks

backend/      Pydantic AI + FastAPI  (Python 3.14, uv-managed)
  app.py        FastAPI assembly: middleware, auth gate, router registration, shared singletons
  core/         foundation: config · db · crypto/vault (at-rest encryption) · auth · write-behind
                worker · untrusted-content marking · SSRF guard · exceptions
  models/       SQLModel entities + schema (owner seam · per-column encryption · branch tree)
  runs/         Pillars I+II — the Run substrate + the frozen v1 event protocol
  agent/        Pillar III — the engine: orchestrator · node→event translator · meta-loop · namer
  prompts/      the prompt library, split by durability (system_prompt vs instructions)
  tools/        Pillar III — the agent's tool catalog: namespacing + enable gate + thin adapters
  services/     capabilities: llm/registry · memory · conversations · sandbox · search · artifacts
  routes/       thin FastAPI routers, one per surface (overview is the home aggregate)
  research/     deep-research orchestrator on the Run substrate (stub)
  migrations/   Alembic — schema auto-upgraded to head on startup

docs/spec/          black-box spec — WHAT the system must do (based on PewDiePie's original idea, minus the vibe-coded features that seemed redundant or unnecessary)
docs/architecture/  backend design — HOW it's built, the decision register, the spec-coverage ledger
```

The central abstraction is a **Run**: one server-side, background-executing unit of work for a single request. Chat turns, agent tasks, and research jobs are all Runs, so I only have to write continuity, resume, cancellation, timeouts, and metrics **once** — everything inherits them. The backend is an **origin-agnostic API**: it makes no assumption about who serves the frontend. The whole thing rests on three pillars — the Run substrate, the event protocol, and the agent engine plus tools — detailed in [`docs/architecture/README.md`](docs/architecture/README.md).

## Running it

**Backend** (requires [uv](https://docs.astral.sh/uv/)) — platform-agnostic (Linux / macOS / POSIX), no OS-specific dependency:
```bash
cd backend
uv sync                                       # creates .venv (Python 3.14), installs deps
uv run uvicorn app:app --reload --port 8000   # http://localhost:8000  (/health to check)
uv run pytest                                 # the test suite
uv run ruff check .                           # lint
```
On first run, create the operator account via the frontend (the password you choose also derives the at-rest encryption key). A container runtime (Docker/Podman) is needed for the code sandbox and managed web search; without one, those capabilities report unavailable rather than falling back to the host.

**Frontend** (requires [bun](https://bun.sh)):
```bash
cd frontend
bun install
bun run dev         # http://localhost:5173
bun run typecheck   # tsc --noEmit (scoped to src/)
bun run lint        # eslint + prettier --check
bun run build       # static SPA build
```
Screens not yet wired to the backend render on typed mock data behind a stable seam; swapping in real calls doesn't move any logic into the frontend, because none lives there.

## Security & privacy

Odysseus can do powerful things on your machine — sandboxed and (with approval) host code execution, file writes, model serving, email, web research — so I don't treat security as an afterthought. The full details are in [SECURITY.md](SECURITY.md).

- **Single operator.** All data and features belong to *you* — the sole user. Every request is authenticated before any feature is reached; every record is owner-stamped against a future multi-user seam.
- **Sensitive actions require approval.** The agent pauses and asks before anything powerful or hard to reverse (host shell/code, file writes, sending email, serving models, configuration, vault) takes effect. Sandboxed code is *not* sensitive — it's isolated and containerized from the host.
- **Encrypted at rest.** All user data is AES-256 encrypted; auth secrets are one-way hashed. The key is derived from your password and lives only in memory — no OS keystore, nothing readable on disk, re-locked on restart.
- **Untrusted content is data, not instructions.** External content (web pages, fetched URLs, files) is wrapped and marked so the model treats it as data before it enters a prompt.
- **Local-first.** Nothing leaves the machine unless you configure an external provider or integration.
- Serve plain HTTP only on `localhost`/trusted LAN; put a TLS-terminating reverse proxy in front for anything reachable beyond your machine.

## Data

All user data lives under `data/` and is **gitignored** — databases, uploads, keys, generated media. Never commit anything from `data/`, `.env`, or `logs/`.

## Contributing

It's still early days, but help is more than welcome. There are exactly three authoritative inputs: the [spec](docs/spec/README.md) (the *what*), the [architecture & decisions](docs/architecture/README.md) (the *how*), and the capabilities of FastAPI + Pydantic AI. I don't use the deleted pre-reset code as a reference — PewDiePie's original was vibe-coded. The [spec-coverage matrix](docs/architecture/70-spec-coverage.md) is the live "what's done vs. next" view.

## License
MIT — see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).

```
                                  |
                                 |||
                                |||||
                  |    |    |   |||||||
                 )_)  )_)  )_)   ~|~
                )___))___))___)\  |
               )____)____)_____)\\|
             _____|____|____|_____\\\__
             \                       /
       ~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~
               ~^~  all aboard!  ~^~
       ~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~
```
