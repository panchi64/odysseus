# Odysseus
───────────────────────────────────────────────
 ⊹ ࣪ ˖ ૮( ˶ᵔ ᵕ ᵔ˶ )っ  Odysseus vers. 2.0
───────────────────────────────────────────────

A self-hosted AI workspace — the self-hosted version of the experience you get from ChatGPT and Claude, but on your own hardware, with your own data. Local-first, privacy-first, encrypted at rest, no trojan.

> **Status: under reconstruction.** 🛠️ Odysseus is being rebuilt from the ground up.
> The **frontend** (a SolidStart terminal-HUD SPA) is well underway and runs today on
> mock data; the **backend** is a fresh greenfield build on **Pydantic AI + FastAPI**,
> currently being implemented against the design in [`docs/`](docs/). Features below
> describe the **target** the build is driving toward, not a shipped product yet.
> The previous implementation was scorched-earth reset — this is a new voyage.

## The idea

**Pydantic AI is the engine; we are the chassis.** All agentic reasoning — the model call, tool selection, the tool→observe→continue loop, validation, fallback — runs through Pydantic AI. Everything that turns one model run into a durable, observable, resumable product — run lifecycle, the event stream, disconnect-survival, cancellation, persistence, access policy, the verifier meta-loop — is ours. One powerful local host, one operator, capable native-tool-calling models.

## Features (the target)

  - **Chat** — chat with any local model or API; adding them is super simple.<br>　<sub>vLLM · llama.cpp · Ollama · OpenAI-compatible · streaming</sub>
  - **Agent** — hand it tools and let it run the whole task itself, with approval gates on anything powerful.<br>　<sub>Pydantic AI · MCP · web · files · shell · skills · memory · sensitive-action approval</sub>
  - **Cookbook** — scans your hardware, recommends models, click to download and serve.<br>　<sub>VRAM-aware · GGUF / FP8 / AWQ · fit scoring · vLLM / llama.cpp serving</sub>
  - **Deep Research** — multi-step runs that gather, read, and synthesize sources into a visual report.<br>　<sub>plan → search → read → analyze → write · bounded by rounds + time</sub>
  - **Compare** — compare models side by side, blind, no bias.<br>　<sub>multi-model · blind test · synthesis</sub>
  - **Documents** — YOU write the text, AI assists — not the other way around.<br>　<sub>multi-tab editor · markdown · HTML · CSV · AI edits · suggestions</sub>
  - **Memory / Skills** — persistent memory and skills; your agent evolves as it understands you and your tasks.<br>　<sub>vector + keyword retrieval · sqlite-vec · import/export</sub>
  - **Email** — IMAP/SMTP inbox with AI triage: urgency, auto-tag, auto-summary, reply drafts, spam.<br>　<sub>IMAP · SMTP · per-account routing · CalDAV-aware</sub>
  - **Notes & Tasks** — quick notes with reminders, a todo list, and scheduled tasks the agent can act on.<br>　<sub>note pings · checklist · cron-style tasks · notification channels</sub>
  - **Calendar** — local-first calendar with CalDAV sync to Radicale / Nextcloud / Apple / Fastmail.<br>　<sub>CalDAV pull · .ics import/export · per-calendar colors · agent-aware</sub>
  - **Works on mobile** — looks and runs great on your phone, not just desktop.<br>　<sub>responsive · installable (PWA) · touch gestures</sub>
  - **Extras** — image editor · theme editor · file uploads (vision + PDF) · web search · presets · sessions · 2FA

The full required behavior is specified, black-box, in [`docs/spec/`](docs/spec/README.md).

## Architecture

Two halves, cleanly separated — see [`docs/architecture/`](docs/architecture/README.md) for the full design and [`docs/architecture/decisions.md`](docs/architecture/decisions.md) for every decision and its trade-offs.

```
frontend/     SolidJS / SolidStart SPA · TypeScript · Tailwind v4 · Vite
              terminal-HUD design system · mock-data seam (backend wiring is Phase 2)

backend/      Pydantic AI + FastAPI  (greenfield, in progress)
  app.py        FastAPI assembly: middleware, auth, router registration, run registry
  core/         config · db engine + schema/migrations · auth · crypto · exceptions
  models/       ORM entities + Pydantic schemas (the data contracts)
  runs/         the Run substrate: registry · broker · event buffer · event protocol · transports
  agent/        the engine: Agent assembly · RunDeps · meta-loop (verifier, loop-break) · event translation
  tools/        tool definitions by category — thin adapters over services/
  services/     capabilities: llm · embeddings · vectorstore · search · memory · tts · stt · serving · mail · dav
  research/     deep-research orchestrator on the Run substrate
  routes/       thin FastAPI routers, one per feature surface

docs/spec/          black-box spec — WHAT the system must do
docs/architecture/  backend design — HOW it's built, and the decisions behind it
```

A **Run** is the central abstraction: one server-side, background-executing unit of work for one request. Chat turns, agent tasks, and research jobs are all Runs — so continuity, resume, cancellation, timeouts, and metrics are written once and inherited by all of them. The backend is an **origin-agnostic API**: it makes no assumption about who serves the frontend.

## Running it

> Until the backend lands, only the frontend runs — on typed mock data behind a stable
> seam. Phase 2 swaps the mock fetches for real API/stream calls without touching screens.

**Frontend** (requires [bun](https://bun.sh)):
```bash
cd frontend
bun install
bun run dev         # http://localhost:5173
bun run typecheck   # tsc --noEmit (scoped to src/)
bun run lint        # eslint + prettier --check
bun run build       # static SPA build
```

**Backend** — being built. It will be a Python 3.11+ service managed with
[uv](https://docs.astral.sh/uv/), platform-agnostic (Linux / macOS / POSIX), with no
OS-specific dependency. The install/run flow will be documented here once it exists.

## Security & privacy

Odysseus is a self-hosted workspace with powerful local capabilities — shell access, code execution, file writes, model serving, email, web research. Treat it like an admin console. See [SECURITY.md](SECURITY.md).

- **Single operator.** All data and features belong to one operator. Authentication is enforced before any feature is reached.
- **Sensitive actions require approval.** The agent must pause and ask before anything powerful or hard to reverse (shell, code, file writes, sending email, serving models, configuration, vault) takes effect.
- **Encrypted at rest.** All user data is encrypted with confidentiality that holds against quantum-capable adversaries; auth secrets are one-way hashed. The key is derived from your password and lives only in memory — no OS keystore, nothing readable on disk.
- **Local-first.** Nothing leaves the machine unless you configure an external provider or integration.
- Serve plain HTTP only on `localhost`/trusted LAN; put a TLS-terminating reverse proxy (e.g. [Caddy](https://caddyserver.com/)) in front for anything reachable beyond your machine.

## Data

All user data lives under `data/` and is **gitignored** — databases, uploads, keys, generated media. Never commit anything from `data/`, `.env`, or `logs/`.

## Contributing

It's early and the foundation is still being poured, but help is welcome — frontend polish, the spec, the architecture, and (soon) the backend build-out. See [ROADMAP.md](ROADMAP.md).

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
