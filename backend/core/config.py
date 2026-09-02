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

    # Where code mode's git worktrees are checked out. **Deliberately outside
    # `data_dir`**: an approved host command is fenced by `services/sandbox/host.py`,
    # which denies reads of the whole data directory (the vault, the sealed workspaces
    # and the DB live there). A worktree under `data_dir` would therefore be unreadable
    # by the very shell that has to build and test it. The tradeoff this accepts is that
    # a worktree is plaintext on disk — it is a checkout of the operator's own already
    # plaintext repository, so it exposes nothing that was not already exposed.
    worktrees_dir: Path = Path("~/.odysseus/worktrees")

    @field_validator("worktrees_dir")
    @classmethod
    def _absolute_worktrees_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    # DB connection. None ⇒ a file under data_dir; tests pass an in-memory URL.
    db_url: str | None = None
    # Unlock passphrase for the at-rest encryption vault. When set, the vault is
    # set up (first run) or unlocked at boot without a login — the auth-disabled
    # path. With auth enabled the operator unlocks via login instead.
    unlock_passphrase: str | None = None

    # Run substrate bounds. Timeouts are seconds; None disables.
    #
    # Concurrency is carved into **lanes** (`runs/lanes.py`) rather than shared blindly:
    # the operator's own turn must not queue behind a scheduled task or behind threads the
    # agent opened for itself. `run_max_concurrency` keeps its name, its number and its
    # meaning — the host ceiling, across every lane; the two unattended lanes are capped
    # well below it on purpose, because nobody is waiting on them and their failure mode
    # is volume, and slots they can never hold are slots the operator always can.
    run_max_concurrency: int = 8
    run_background_concurrency: int = 2
    run_linked_concurrency: int = 3
    # Off by default: a turn is already bounded by `agent_request_limit` (it cannot loop
    # forever), so a wall clock mostly fires on a run that is legitimately slow — a local
    # model, a long sandboxed tool call — which is precisely the run we want to let
    # finish. It stays available as an opt-in lever for the gap neither other bound
    # covers: the inactivity watchdog reads activity off the event stream, so a run that
    # keeps *emitting* — a tool streaming progress, a model streaming tokens — refreshes
    # the clock on every frame and never trips it, while spending no extra model requests.
    run_wall_clock_timeout_s: float | None = None
    run_inactivity_timeout_s: float | None = 120.0

    # Model resolution is the DB-backed registry's job (services/registry.py) —
    # named roles bound to ordered endpoint chains, the single source of truth,
    # populated by manual config (the /models surface) today and the automatic
    # setup later. There is deliberately no env model seam.

    # Agent bounds: max model requests per turn and optional per-turn
    # tool-call cap. None disables the tool cap.
    agent_request_limit: int = 25
    agent_tool_calls_limit: int | None = None

    # How long a research thread the *agent* opened may run before the substrate ends it.
    # The one place a wall clock is on by default, because it is the one turn nobody is
    # sitting in front of: the inactivity watchdog cannot end it (a model streaming tokens
    # refreshes that clock on every frame), the request limit only bounds round trips, and
    # the linked lane is `run_linked_concurrency` wide — so unbounded threads would block
    # every later `research_start` for as long as they cared to run. Eighteen minutes: a
    # thorough read of a dozen sources fits comfortably, a stuck one does not.
    research_wall_clock_timeout_s: float | None = 1080.0

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
    # How much of a file one `files_read_file` call returns. Paging exists (the tool takes
    # an offset), so this bounds a single call rather than what the agent can ultimately
    # read — set to keep one oversized file from crowding out the rest of the turn.
    sandbox_files_max_read_lines: int = 2_000
    # Per-conversation live sandbox: a container lazily spun up on the first code
    # execution and kept warm so the agent can iterate (fix an error, reuse an
    # installed dependency) without rebuilding. Idle sessions are reaped to free
    # resources; the workspace (the agent's files) is preserved across reaps,
    # sealed with the vault while dormant. `idle_ttl` is how long a session may sit
    # unused before it is killed; `reap_interval` is how often the reaper sweeps.
    sandbox_session_idle_ttl_s: float = 1800.0
    sandbox_session_reap_interval_s: float = 60.0
    # And how many conversations may hold one at once. The TTL bounds a session in time;
    # without a count, threads worked on in rotation all stay inside the window and every
    # one of them keeps a container. Past the cap, the least-recently-used idle session is
    # sealed to make room — the same reap the TTL performs, triggered by pressure instead
    # of by the clock, and just as invisible to the conversation it hits.
    sandbox_max_sessions: int = 8
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

    # The approved host-command escape hatch, confined. Approval is consent to the
    # command the operator read, not to whatever it might reach afterwards, so the
    # process is additionally fenced at the OS level (seatbelt on macOS, bubblewrap on
    # Linux). Unlike the sandbox proper this degrades rather than fails closed: the
    # operator explicitly approved *this* command, and refusing to run it because a
    # platform primitive is missing would break the one case the tool exists for.
    host_command_sandbox_enabled: bool = True
    # Egress allowlist for those commands. Empty means no network at all — widen it
    # deliberately, per domain, rather than reaching for the disable switch above.
    host_command_allowed_domains: tuple[str, ...] = ()
    # Read-denied even under approval. The data directory is added to this at runtime
    # because it holds the vault, the sealed workspaces and the database: the agent must
    # never read its own encrypted store from the host, whatever it was approved to do.
    host_command_deny_read: tuple[str, ...] = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gh")
    # Writes are **deny-by-default** under the confinement, so this list is what makes the
    # tool usable at all — an approved "change my host" command that cannot write anything
    # would fail confusingly rather than safely. Kept broad on purpose (the operator read
    # and approved this specific command); the fence's value is in the read denials and the
    # egress allowlist, which are the exfiltration paths. The credential paths above are
    # additionally write-denied, so a confined command can neither read nor clobber them.
    host_command_allow_write: tuple[str, ...] = ("~", "/tmp", "/var/tmp")

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

    # Auto review (`services/permissions`). At the Auto level a deferred call is settled
    # by a deterministic shell judge and then, if that declines, by one structured call on
    # the utility model. `review_timeout_s` bounds that call — it runs inside a live turn
    # with the operator watching, so a stuck reviewer would hold the run open on a call
    # nobody has been asked about, which is worse than the park it was avoiding. A timeout
    # therefore parks, like every other way the review can fail. `review_max_tokens` is
    # the output cap, sized like the title call's: reasoning is requested off, but a
    # runtime that ignores the lever reasons anyway and the cap has to leave room for a
    # think block plus three short fields. `review_transcript_messages` is how much of the
    # thread the reviewer reads, counted from the end.
    review_timeout_s: float = 30.0
    review_max_tokens: int = 2048
    review_transcript_messages: int = 12

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
    # An image the answer embeds, fetched by us so the operator's browser never
    # contacts the remote host (`services.webimage`). Its own budget, not the page
    # fetch's: no browser to start, so a slow image is a slow socket and nothing more,
    # and the cap is larger because a photograph is legitimately bigger than a page's
    # extracted text.
    web_image_timeout_s: float = 10.0
    web_image_max_bytes: int = 10_000_000
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

    # Browser control — the agent drives a real page (click, type, submit) rather than
    # only reading one. It attaches to the *same* containerized Chromium web fetch
    # renders in, so there is one browser process, one SSRF proxy, and one thing offline
    # mode has to bring down. There is no separate on/off switch: `web_fetch_enabled`
    # decides whether a browser exists, and with none there is nothing to attach to.
    #
    # A session is conversation-scoped, not per-turn: a login or a half-filled form in
    # one turn must still be there in the next, which is the whole point of controlling a
    # browser rather than fetching pages. `idle_ttl_s` is how long one may sit unused
    # before it is reaped, `reap_interval_s` how often the sweep runs, and `max_live`
    # caps how many conversations hold one at once — each costs a Playwright driver
    # process, so this is deliberately small.
    browser_control_idle_ttl_s: float = 900.0
    browser_control_reap_interval_s: float = 60.0
    browser_control_max_live: int = 3
    # What the operator watches in the Browser panel: a CDP screencast of the live page,
    # JPEG frames bounded to the same 1280×800 viewport the stealth context options use.
    # `quality` trades bytes for fidelity on a stream nobody reads text off — the model
    # reads the page through `snapshot`/`get_text`, not through this.
    browser_control_frame_quality: int = 60
    browser_control_frame_width: int = 1280
    browser_control_frame_height: int = 800

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

    # Conversation auto-compaction — the **only** context reduction that fires on measured
    # pressure rather than unconditionally. Once a thread's *projected* footprint (what is
    # already in the replay plus the prompt and context about to be added) reaches
    # `auto_compact_threshold` of the model's context window, everything older than the last
    # `auto_compact_keep_turns` exchanges is summarized by the utility model into one
    # checkpoint, and the thread carries on from that summary plus the retained turns.
    # The threshold is 0.80, not the old 0.95: at 95% the fold leaves no room for the turn
    # that triggered it, so the very next request overflows anyway. `auto_compact_keep_turns`
    # is 3, not 0 — a summary is lossy about the exchange in flight, and the last few turns
    # verbatim are what keeps a fold from derailing the work the operator is mid-way through.
    # Nothing is deleted: the operator's transcript keeps every turn, and only what is
    # re-sent to the model shrinks. It fires **between** turns, in the orchestrator prelude,
    # so it can never disturb reasoning already in flight — with one exception: a provider
    # context-overflow inside a turn folds once and retries the failed request.
    # `auto_compact_input_max_tokens` bounds the transcript handed to the summarizer, which
    # by definition is folding most of the *main* model's window into a utility model that
    # may be smaller; a transcript over the bound is summarized in chunks rather than
    # elided, so the ceiling buys throughput rather than fidelity. `auto_compact_max_tokens`
    # is the summary's own output budget, sized (like the titler's) to leave room for a
    # `<think>` block on a runtime that ignores the reasoning-off lever.
    # `auto_compact_timeout_s` sits *below* `run_inactivity_timeout_s` (120s) on purpose:
    # a summarizer allowed to run as long as the watchdog would let the watchdog kill the
    # run it was trying to save. Enabled/threshold/keep-turns are the *defaults* — the
    # operator overrides them at runtime via `PUT /chat/settings`, and enablement per thread
    # via `/conversations/{id}`.
    auto_compact_enabled: bool = True
    auto_compact_threshold: float = 0.80
    auto_compact_keep_turns: int = 3
    auto_compact_input_max_tokens: int = 32000
    auto_compact_max_tokens: int = 4096
    auto_compact_timeout_s: float = 100.0

    # What the footprint estimator assumes the per-turn overhead costs — instructions,
    # system prompt and tool schemas — when a thread carries no measured `TurnOverhead`
    # record (every turn taken before the record existed, and the first turn of a fresh
    # thread). The assembled catalog measures at ~14k tokens, so the alternative default,
    # zero, would tell the compaction trigger a nearly-full thread had room to spare.
    # Deliberately under the measured figure: the estimate is a fallback, and it should
    # nudge the trigger early without folding a thread that was never under pressure.
    context_overhead_fallback_tokens: int = 12000

    # Anthropic prompt caching (services/providers/anthropic.py): the TTL requested on the
    # cache breakpoints the adapter sets over the instructions and the tool definitions —
    # the two prefix segments that are byte-identical across every turn of a thread. "5m"
    # is Anthropic's standard tier and covers back-to-back turns; "1h" costs more to write
    # and pays off only when the operator returns to a thread after a long pause.
    # "off" sends no breakpoints at all — the escape hatch for an Anthropic-compatible
    # proxy that rejects `cache_control` outright, where the choice is between paying full
    # price for every prefix and not reaching the endpoint at all.
    anthropic_cache_ttl: Literal["5m", "1h", "off"] = "5m"


@lru_cache
def get_settings() -> Settings:
    return Settings()
