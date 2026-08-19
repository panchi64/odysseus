"""Application configuration.

Deploy-level secrets and defaults come from the environment / ``.env`` before
first boot. Runtime-mutable user settings live in the DB and are
not modeled here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ODYSSEUS_", env_file=".env", extra="ignore"
    )

    version: str = "0.1.0"
    environment: str = "development"

    host: str = "127.0.0.1"
    # 8000, not 7000: macOS AirPlay Receiver squats on :7000 (wildcard, both IP
    # stacks), shadowing an IPv4-only bind when localhost resolves to ::1.
    port: int = 8000

    # Origin-agnostic: the frontend origins allowed to call the API. Both localhost
    # and 127.0.0.1 are listed since browsers treat them as distinct origins.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    auth_enabled: bool = True

    # All user data lives under here — gitignored, encrypted at rest.
    data_dir: Path = Path("data")

    @field_validator("data_dir")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        # Anchor to an absolute host path once, here. Consumers bind-mount paths
        # beneath this (the sandbox workspace, the managed SearXNG config) into
        # containers, and a container bind mount needs an absolute source — a
        # relative one is read as a named volume, which forbids path separators.
        return value.expanduser().resolve()
    # DB connection. None ⇒ a file under data_dir; tests pass an in-memory URL.
    db_url: str | None = None
    # Unlock passphrase for the at-rest encryption vault. When set, the vault is
    # set up (first run) or unlocked at boot without a login — the auth-disabled
    # path. With auth enabled the operator unlocks via login instead.
    unlock_passphrase: str | None = None

    # Run substrate bounds. Timeouts are seconds; None disables.
    run_max_concurrency: int = 8
    run_wall_clock_timeout_s: float | None = 1800.0
    run_inactivity_timeout_s: float | None = 120.0

    # Model resolution is the DB-backed registry's job (services/registry.py) —
    # named roles bound to ordered endpoint chains, the single source of truth,
    # populated by manual config (the /models surface) today and the automatic
    # setup / Cookbook later. There is deliberately no env model seam.

    # Agent bounds: max model requests per turn and optional per-turn
    # tool-call cap. None disables the tool cap.
    agent_request_limit: int = 25
    agent_tool_calls_limit: int | None = None

    # Execution sandbox. Agent code/shell runs isolated from the host; when no
    # runtime is available the capability is disabled (fail closed — never a host
    # fallback). `sandbox_runtime` pins docker/podman; None auto-detects.
    sandbox_enabled: bool = True
    sandbox_runtime: str | None = None
    sandbox_image: str = "python:3.12-slim"
    sandbox_memory: str = "512m"
    sandbox_cpus: str = "1.0"
    # Max processes/threads a single execution may spawn — a crude fork-bomb guard.
    # Reported to the model alongside memory/cpus (`tools/code.py`) so a fork/thread
    # failure can be attributed to this cap instead of only "possibly OOM".
    sandbox_pids_limit: int = 256
    # code_execute's stdout+stderr budget shown to the model, split evenly per stream.
    # A runaway print must not flood the turn's context — current-turn tool results
    # aren't covered by prior-turn compaction (agent/compaction.py only condenses
    # already-persisted turns). Generous by design: a safety ceiling, not a normal-
    # output budget: an over-cap stream is truncated in the middle (head + tail kept,
    # since errors/final state usually live at the tail).
    sandbox_output_max_chars: int = 24_000
    # Per-conversation live sandbox: a container lazily spun up on the first code
    # execution and kept warm so the agent can iterate (fix an error, reuse an
    # installed dependency) without rebuilding. Idle sessions are reaped to free
    # resources; the workspace (the agent's files) is preserved across reaps,
    # sealed with the vault while dormant. `idle_ttl` is how long a session may sit
    # unused before it is killed; `reap_interval` is how often the reaper sweeps.
    sandbox_session_idle_ttl_s: float = 1800.0
    sandbox_session_reap_interval_s: float = 60.0
    # A small pool of idle, conversation-unattached containers pre-created off
    # the critical path (after boot image warm-up) so a conversation's first
    # code_execute claims one instead of paying the container-create round
    # trip. Reaped by the same idle sweep if a spare is never claimed; disable
    # for a host that would rather not keep any container running at rest.
    sandbox_spare_enabled: bool = True
    sandbox_spare_count: int = 1
    # Live preview: the agent runs a dev server in the sandbox and the backend
    # reverse-proxies it to the frontend. How long to wait for that server to start
    # listening before reporting the start as failed (back to the agent).
    sandbox_preview_startup_timeout_s: float = 20.0
    # What a reap preserves: the agent's own files and any output it produced.
    # These names/globs are dropped from the sealed copy — virtual environments
    # and language caches are bloat that is cheaper to rebuild than to store.
    sandbox_session_seal_excludes: tuple[str, ...] = (
        ".venv", "venv", "env", ".local", ".tmp", ".home", "__pycache__",
        "node_modules", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".cache", "dist", "build", "*.pyc", "*.pyo", "*.egg-info",
    )

    # Meta-loop. The no-progress guard trips after this many identical tool
    # calls in a turn. The verifier (a post-turn judge + one bounded corrective
    # re-attempt) is off by default.
    loop_repeat_threshold: int = 3
    verify_enabled: bool = False
    # When the verifier is on, only judge turns that produced a checkable
    # artifact (made a tool call) — chitchat that called no tools is skipped.
    # Set False to judge every answer.
    verify_heuristic: bool = True

    # Approval grants. When the operator approves a deferred tool call with the
    # "allow for this conversation" option, that tool auto-approves in that
    # conversation for this long before lapsing back to strict per-call approval.
    approval_grant_ttl_s: float = 86400.0

    # Web search. `web_search_result_limit` caps results from the SearXNG provider;
    # `web_search_timeout_s` bounds one query (its own budget, not the fetch timeout).
    web_search_result_limit: int = 10
    web_search_timeout_s: float = 15.0

    # Web fetch. The open web is treated as always-dynamic: every page is rendered in a
    # headless Chromium that runs in its own loopback-bound container (isolating untrusted
    # page JS from the host), driven over CDP; the rendered DOM is extracted to Markdown.
    # `image` tracks :latest (refreshed each boot, like SearXNG — CDP is version-tolerant);
    # `enabled` turns fetch off (degrades); `startup_timeout_s` bounds container bring-up;
    # `timeout_s` bounds navigation/render; `max_bytes` caps the rendered HTML/text handed
    # to the extractor; `wait_until` is Playwright's load milestone with `render_wait_ms`
    # an extra settle delay; `concurrency` bounds simultaneous contexts; `min_chars` is the
    # length below which extraction falls back to innerText. The browser is stealthed to
    # present as a normal user's Chrome (so sites return what a person would see):
    # `user_agent` empty ⇒ derive a realistic one from the engine version; `locale`/`timezone`
    # set the context. SSRF is enforced out-of-browser by a proxy sidecar (`proxy_image` —
    # a stock python image the SSRF script is mounted into; tracks :latest), so every request
    # is gated without the in-browser interception bot walls detect.
    # `cookie_ttl_s` (>0 enables) caches a site's cookies in-memory across fetches so a
    # solved JS/bot challenge's clearance carries forward, bounded by TTL + `cookie_max`;
    # `min_interval_s` (>0 enables) is the minimum gap between fetches to the same host
    # (politeness vs rate limits); `challenge_waits`/`challenge_wait_ms` let a render that
    # looks like a bot-wall interstitial settle and be re-snapshotted instead of returned.
    web_fetch_enabled: bool = True
    web_fetch_image: str = "chromedp/headless-shell:latest"
    web_fetch_proxy_image: str = "python:alpine"
    web_fetch_startup_timeout_s: float = 45.0
    web_fetch_timeout_s: float = 15.0
    web_fetch_max_bytes: int = 2_000_000
    web_fetch_wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = (
        "domcontentloaded"
    )
    web_fetch_render_wait_ms: int = 250
    web_fetch_concurrency: int = 4
    web_fetch_min_chars: int = 200
    web_fetch_user_agent: str = ""
    web_fetch_locale: str = "en-US"
    web_fetch_timezone: str = "America/New_York"
    web_fetch_cookie_ttl_s: float = 1800.0
    web_fetch_cookie_max: int = 2000
    web_fetch_min_interval_s: float = 1.0
    web_fetch_challenge_waits: int = 2
    web_fetch_challenge_wait_ms: int = 5000
    # A fetched page's body is capped to this token budget before it reaches the model, so a
    # long article can't blow a local model's context in one tool result. The rest is reachable
    # by calling fetch again with the `offset` the truncation notice reports (paging).
    web_fetch_output_max_tokens: int = 4000
    # A `.pdf` URL can't render in the browser (it starts a download); the fetcher instead
    # downloads the bytes and extracts their text layer. `pdf_max_bytes` caps the download;
    # `pdf_max_pages` bounds extraction cost (no vision OCR — a scanned PDF degrades).
    web_fetch_pdf_max_bytes: int = 25_000_000
    web_fetch_pdf_max_pages: int = 50
    # Adaptive settle: a JS-heavy page (SPA) can report its shell first and fill the real
    # content a beat later. After the first snapshot, re-snapshot up to `settle_checks` times
    # (waiting `settle_wait_ms` each) while the page is still thin (< `settle_min_chars`) or
    # visibly still growing. A page that is already rich and stable pays zero extra waits.
    web_fetch_settle_checks: int = 3
    web_fetch_settle_wait_ms: int = 750
    web_fetch_settle_min_chars: int = 1000
    # Goal-aware distillation: when the fetch tool is given a `goal` and the page body is over
    # the output cap, the utility model distills it down to the goal-relevant content (verbatim
    # figures/tables preserved) instead of truncating. `window_tokens` is the per-call excerpt
    # size; `max_windows` caps coverage (8×12k ≈ 96k tokens of page); `timeout_s` bounds the
    # whole distillation (on timeout/failure it falls back to truncation + offset paging).
    web_fetch_distill_enabled: bool = True
    web_fetch_distill_window_tokens: int = 12000
    web_fetch_distill_max_windows: int = 8
    web_fetch_distill_timeout_s: float = 90.0

    # Managed web search. So search "just works" with zero operator setup, the
    # backend runs its own SearXNG in a container (the same runtime the sandbox
    # uses), bound to loopback, and queries it automatically — the DB-backed
    # provider registry stays as an optional override for a custom/remote instance.
    # The image is always refreshed to the latest tag on boot. When no runtime is
    # present web search simply degrades (no host fallback). `searxng_base_url`
    # points at an already-running instance instead, so no container is managed.
    searxng_enabled: bool = True
    searxng_image: str = "searxng/searxng:latest"
    searxng_startup_timeout_s: float = 30.0
    searxng_base_url: str | None = None

    # Offline mode — when internet connectivity is lost the managed web containers
    # (SearXNG + the fetch browser/proxy) are torn down to save resources and the
    # web tools are hidden from the agent; both return automatically when
    # connectivity is back. The operator can also force offline manually. Boot is
    # probe-first / fail-closed: one check decides whether the heavy browser starts
    # at all. The monitor TCP-connects to these public anchors (direct IPs, no DNS,
    # no payload) on its interval; `fail_threshold` consecutive failures declare
    # offline, `recover_threshold` consecutive successes declare online (hysteresis
    # so the containers don't flap on a flaky link).
    # When False the monitor does no network probing and simply assumes online, so
    # auto-detection is off and only the manual switch can force offline (a host on a
    # known-always-online link, or tests that must not touch the network).
    offline_check_enabled: bool = True
    offline_auto_default: bool = True
    offline_check_interval_s: float = 30.0
    offline_check_timeout_s: float = 3.0
    offline_fail_threshold: int = 3
    offline_recover_threshold: int = 2
    offline_anchors: list[str] = ["1.1.1.1:443", "8.8.8.8:443", "9.9.9.9:443"]


    # Auto-titling: name a fresh thread from its first exchange (a best-effort
    # reasoning-off utility call). On by default; the operator can rename either way.
    # The title call is best-effort and bounded by `title_timeout_s` so a slow or
    # stuck utility model can't hold the run open. `title_max_tokens` is the output
    # cap: reasoning is requested off, but a runtime that ignores the lever (e.g.
    # LM Studio + Qwen) reasons anyway, so the cap must leave room for a `<think>`
    # block plus the title. The auto path runs concurrently and is awaited before the
    # run finalizes, so it stays tight; the manual re-title spans every operator turn
    # (a longer think block) and is a deliberate, awaited operator action, so it gets
    # a wider budget and its own longer timeout.
    title_enabled: bool = True
    title_timeout_s: float = 20.0
    title_max_tokens: int = 2048
    retitle_timeout_s: float = 60.0
    retitle_max_tokens: int = 4096

    # Uploads (UP-*). A file is accepted, stored encrypted at rest, and its text
    # extracted off the request path. `upload_max_bytes` caps a single file.
    # Uploads are rate-limited to protect the service (UP-4): a per-operator token
    # bucket holding `upload_rate_burst` tokens, refilling at `upload_rate_per_minute`.
    # `upload_extract_max_pages` bounds extraction cost — vision OCR is one model call
    # per scanned page — and pages beyond it are recorded as skipped, never dropped
    # silently. `upload_ocr_timeout_s` bounds a single page's vision call.
    upload_max_bytes: int = 50_000_000
    upload_rate_per_minute: float = 30.0
    upload_rate_burst: int = 10
    upload_extract_max_pages: int = 50
    upload_ocr_timeout_s: float = 120.0
    # Extraction engine. `auto` uses MinerU (high-fidelity Markdown — layout, tables,
    # formulas) when the `mineru` tool is detected on the host, falling back to the
    # zero-setup built-in (pypdfium2 text + vision OCR) otherwise; `mineru`/`basic`
    # pin one. MinerU is detected, not bundled (like the container runtime) and runs as
    # a transient subprocess, so its heavy models load per-extraction and free on exit.
    # `upload_mineru_timeout_s` bounds one MinerU run before degrading to the built-in.
    upload_extractor: Literal["auto", "mineru", "basic"] = "auto"
    upload_mineru_timeout_s: float = 300.0

    # Chat attachments. A file attached to a message stays inline in the conversation
    # so a follow-up "just works" — images always (their cost is bounded and there's no
    # way to re-see one on demand), and a non-image file's extracted text up to this
    # token budget. Past it, the text is cut off at the cap and a pointer to the
    # attachments/corpus tools is appended, so a large document can't grow context
    # without bound. This is the *default*; the operator overrides it at runtime via
    # `PUT /chat/settings` (stored owner-scoped in the settings store). 0 ⇒ never retain
    # non-image text inline (always cut to a pointer); images are unaffected either way.
    attachment_inline_max_tokens: int = 6000

    # Tool-result compaction. In a tool-heavy chat, large tool outputs from *earlier* turns
    # pile up and crowd the model's context. When enabled, the model re-reads a deterministic
    # digest of an old, oversized tool result instead of the whole thing — and can call
    # `expand_tool_result` to pull the full output back on demand. The operator always sees the
    # full output (it's persisted and streamed untouched); only the model's replayed view of
    # *prior* turns is condensed — the current turn is never compacted. `compaction_keep_recent`
    # is the rolling window (the K most-recent tool results always stay full);
    # `compaction_min_tokens` is the size floor (a result must exceed it to be worth digesting).
    # These are the *defaults*; the operator overrides them at runtime via `PUT /chat/settings`.
    compaction_enabled: bool = True
    compaction_keep_recent: int = 6
    compaction_min_tokens: int = 1000

    # Conversation auto-compaction — the other half of context reduction, and a different
    # thing from the tool-result compaction above: that one condenses individual tool
    # outputs, this one folds whole *turns*. Once a thread's measured footprint reaches
    # `auto_compact_threshold` of the model's context window, everything older than the
    # last `auto_compact_keep_turns` exchanges is summarized by the utility model into one
    # checkpoint, and the thread carries on from that summary plus the retained turns.
    # Nothing is deleted: the operator's transcript keeps every turn, and only what is
    # re-sent to the model shrinks. It fires **between** turns, in the orchestrator prelude,
    # so it can never disturb reasoning already in flight. It is also not a safety net — a
    # prompt that overruns the window anyway still stops the run with a context notice.
    # `auto_compact_input_max_tokens` bounds the transcript handed to the summarizer, which
    # by definition is folding most of the *main* model's window into a utility model that
    # may be smaller; `auto_compact_max_tokens` is the summary's own output budget, sized
    # (like the titler's) to leave room for a `<think>` block on a runtime that ignores the
    # reasoning-off lever. Enabled/threshold are the *defaults* — the operator overrides
    # them at runtime via `PUT /chat/settings`, and per thread via `/conversations/{id}`.
    auto_compact_enabled: bool = True
    auto_compact_threshold: float = 0.95
    auto_compact_keep_turns: int = 2
    auto_compact_input_max_tokens: int = 24000
    auto_compact_max_tokens: int = 4096
    auto_compact_timeout_s: float = 120.0

    # Deep research (DR-*): a run is a deterministic rounds loop with a dynamic
    # per-round fan-out of search/read workers, bounded by whichever of rounds or wall-
    # clock time comes first (DR-3.1). `research_max_concurrency` caps how many workers
    # run at once within a round (DR-3.4); `research_round_floor` is the minimum number
    # of rounds before the comprehensiveness judge is even consulted, so a run can't
    # declare victory after a single lucky round (DR-3.2). `research_empty_rounds_abort`
    # is how many consecutive rounds of zero usable search results it takes to conclude
    # search is unavailable and stop with a clear message rather than an empty or
    # fabricated report (DR-4.1). All operator-configurable (DR-6.1); these are the
    # defaults.
    research_max_rounds: int = 4
    research_time_limit_s: float = 900.0
    research_round_floor: int = 2
    research_max_concurrency: int = 4
    research_empty_rounds_abort: int = 2

    # Operator Shell (`SHELL-1..3`): a host PTY streamed to the browser over a
    # WebSocket, agent-unreachable by construction (no tool references it — see
    # `tests/test_shell_guard.py`). `shell_enabled` is the on/off switch;
    # `shell_idle_timeout_s` kills a session with no keystrokes for that long;
    # `shell_max_sessions` bounds concurrent live sessions (single operator, so a
    # small number is deliberate, not a scaling limit); `shell_host_token_ttl_s` is
    # how long a minted host-mode token stays redeemable before it must be
    # re-requested (it's single-use regardless, so this only bounds an unused
    # token's shelf life); `shell_auth_rate_per_minute`/`shell_auth_rate_burst`
    # throttle password attempts against `POST /shell/host-mode` the same way
    # uploads throttle theirs.
    shell_enabled: bool = True
    shell_idle_timeout_s: float = 900.0
    shell_max_sessions: int = 1
    shell_host_token_ttl_s: float = 60.0
    shell_auth_rate_per_minute: float = 5.0
    shell_auth_rate_burst: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
