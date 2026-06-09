# Roadmap / Help Wanted

Odysseus is on a voyage, and right now we're rebuilding the ship's hull. The backend was scorched-earth reset and is being rebuilt greenfield on **Pydantic AI + FastAPI**; the frontend is a SolidStart SPA running on mock data. Feedback and help appreciated (I half-know what I'm doing, hlep).

If you see weird CSS, strange layout behavior, or a suspiciously murky corner, you're probably right to stay away — for now.

## Where things stand

- ✅ **Spec** — black-box requirements written (`docs/spec/`).
- ✅ **Architecture** — engine/chassis design + every foundational decision settled (`docs/architecture/`).
- 🛠️ **Frontend** — SolidStart terminal-HUD SPA, built against typed mock data behind a stable seam.
- ⏳ **Backend** — greenfield build-out starting now, against the architecture docs.

## Now — foundational build-out

Scaffold and stand up `backend/` against `docs/architecture/`, pillar by pillar:

- The **Run substrate** — registry, in-process broker, event buffer, lifecycle state machine, resume/cancel/timeout.
- The **event protocol** — the frozen v1 typed event union that is the backend↔frontend contract.
- The **agent engine** — Pydantic AI `Agent` assembly, the toolset-stack access policy, the verifier/loop-break meta-loop.
- **Persistence & crypto** — encrypted-at-rest SQLite, write-behind history, the password-derived lock-until-unlocked key.
- **Auth & transport** — global auth middleware, dual cookie + bearer, origin-agnostic API + SSE.

## Next — wire the frontend

- Swap each feature's mock `data.ts` for real `~/lib/api` / `~/lib/stream` calls — return types unchanged, so screens don't move.
- Stream chat/agent/research over the event protocol end to end.

## Later — feature breadth & hardening

- Cookbook reliability across machines, GPUs, drivers, and Python environments.
- Deep research depth, source handling, and report quality.
- Email/calendar integrations: confirm what works, document setup, hide or remove what doesn't.
- Better degraded-state reporting for vector store, web search, email, push, and provider probes.
- Provider setup/probing across Anthropic, Gemini, Groq, xAI, OpenRouter, OpenAI, DeepSeek.
- Fresh-install smoke tests on Linux and macOS.
- A self-host troubleshooting cookbook for the weird 30-second fixes that otherwise eat 30 minutes.

## Frontend polish (ongoing)

- Accessibility: keyboard navigation, focus states, contrast, reduced motion.
- Empty states and error messages on fresh installs.
- Tighten first-run setup, hints, and tours so they don't repeat or fight each other.
- Mobile gallery/editor polish; popover/dropdown placement inside transformed modals.
- `Esc` should close every dismissible surface, consistently.
- Vendor CDN assets eventually for a fully self-hosted/offline mode.
