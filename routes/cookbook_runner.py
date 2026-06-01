"""cookbook_runner.py — the single source of truth for the shell fragments that
Cookbook bakes into its generated runner scripts (model download / serve) and
the remote server-setup command.

Why this module exists
-----------------------
Cookbook builds bash scripts on the fly and runs them in detached tmux sessions
(locally or over SSH). Those scripts have to install Python dependencies, and
that install logic used to be hand-written — copied a dozen times across
`cookbook_routes.py` with slightly different flags each time. The copies drifted
(lost flag-separating spaces, `--system` vs `--python`, missing fallbacks), and
each drift was its own production bug ("No module named pip", silent pip
fallbacks, installs into the wrong interpreter).

The fix is to own each *concern* in exactly one place here, so a runner is
assembled from these building blocks instead of bespoke strings:

- `user_shell_path_bootstrap()` — recover the user's interactive PATH inside a
  minimal non-interactive tmux shell.
- `venv_scrub_lines()` — drop any inherited (pip-less) virtualenv so `python3`
  resolves to the real system interpreter. (Odysseus runs under its own uv
  venv; runners must not leak it.)
- `ensure_uv_lines()` — define + call a single idempotent `_ody_ensure_uv`
  shell function that makes uv available on the host, lazily and once.
- `pip_install()` — the ONE canonical, uv-first install command. Every install
  site calls this; there are no hand-written `uv pip install … || pip …`
  chains anywhere else.

These are pure string/​list builders (no FastAPI, no I/O) so they're trivially
unit-testable and reusable from any runner-building branch.

The contract every bash runner follows
---------------------------------------
1. `#!/bin/bash`
2. `user_shell_path_bootstrap()`            — fix PATH
3. (no user-selected env only) `venv_scrub_lines()`  — drop inherited venv
   OR a user `env_prefix` (activate their venv/conda) — never both
4. `ensure_uv_lines(local_uv=…)`            — make uv available, once
5. any number of `pip_install([...])`       — installs resolve uv via PATH

Steps 2–4 run before any `pip_install()` so that, by the time we install,
`command -v uv` succeeds and `$(command -v python3)` is the intended
interpreter (the activated venv, or the scrubbed system python).
"""

import shlex
import sys


def server_interpreter() -> str:
    """Absolute path to the interpreter the Odysseus server runs under.

    THE single source of truth for "where do LOCAL Cookbook dependencies live".
    Two sites must agree on this answer or the "Installed" badge silently lies:

      - the INSTALL site — `pip_install(..., python=server_interpreter())` for a
        local dep — puts the package into this interpreter's environment, and
      - the PROBE site — `/api/cookbook/packages` — decides "Installed" with an
        in-process `importlib` call, which by definition inspects THIS
        interpreter.

    The original bug: the serve runner scrubbed Odysseus's own uv venv and
    installed into the system python instead, so installs succeeded (exit 0)
    but the in-process probe, looking inside the venv, never saw them. Anchoring
    both sides to this one value is what prevents that drift from coming back —
    a new install path should pin to `server_interpreter()`, never re-derive an
    interpreter of its own."""
    return sys.executable


# Official uv installer. Kept as a module constant so the URL lives in one place
# (and is easy to audit / pin). The installer drops the `uv` binary into
# ~/.local/bin by default, which is what makes `ensure_uv` self-caching.
_UV_INSTALL_URL = "https://astral.sh/uv/install.sh"


# Prints a one-line, token-masked status so a gated-model "not authorized"
# failure can be told apart from a simply-missing HF token in the run log.
HF_TOKEN_STATUS_SNIPPET = (
    'if [ -n "$HF_TOKEN" ]; then '
    'echo "[odysseus] HF token: applied"; '
    'else '
    'echo "[odysseus] HF token: NOT SET — gated/private models will be denied. '
    'Add one in Odysseus Settings -> Cookbook -> HuggingFace Token."; '
    'fi'
)


def user_shell_path_bootstrap() -> list[str]:
    """Recover the user's *interactive* PATH inside the runner.

    Detached tmux runners start from a minimal non-interactive environment that
    often omits ~/.local/bin, Homebrew, pyenv shims, etc. Source the user's
    login/interactive shell once to capture its PATH and prepend it, so tools
    the user has installed (uv, hf, conda, …) are findable."""
    return [
        'ODYSSEUS_USER_SHELL="${SHELL:-}"',
        'if [ -n "$ODYSSEUS_USER_SHELL" ] && [ -x "$ODYSSEUS_USER_SHELL" ]; then',
        '  ODYSSEUS_USER_PATH="$("$ODYSSEUS_USER_SHELL" -ic \'printf "__ODYSSEUS_PATH__%s\\n" "$PATH"\' 2>/dev/null | sed -n \'s/^__ODYSSEUS_PATH__//p\' | tail -n 1 || true)"',
        '  if [ -n "$ODYSSEUS_USER_PATH" ]; then export PATH="$ODYSSEUS_USER_PATH:$PATH"; fi',
        'fi',
    ]


def venv_scrub_lines() -> list[str]:
    """Drop any inherited Python virtualenv from a runner's environment.

    Odysseus runs under `uv run`, which exports VIRTUAL_ENV and prepends its
    .venv/bin to PATH; detached tmux runners inherit both. That uv-created venv
    ships NO pip, so a no-env `python3 -m pip install` resolves to it and dies
    with "No module named pip". A bare `deactivate` can't undo this — it's only
    defined inside an already-activated shell, so in a fresh non-interactive
    bash it's a no-op while VIRTUAL_ENV/PATH stay polluted. Strip the venv
    explicitly so python3/uv resolve to the real system interpreter.

    Only the no-env-prefix branches use this; when the user picks a venv/conda
    env we activate that instead and must NOT scrub."""
    return [
        'if [ -n "$VIRTUAL_ENV" ]; then',
        '  # Drop the inherited (pip-less) uv venv so python3 finds the system pip.',
        '  _ody_path=""',
        '  IFS=":" read -ra _ody_parts <<< "$PATH"',
        '  for _ody_p in "${_ody_parts[@]}"; do',
        '    [ "$_ody_p" = "$VIRTUAL_ENV/bin" ] && continue',
        '    _ody_path="${_ody_path:+$_ody_path:}$_ody_p"',
        '  done',
        '  export PATH="$_ody_path"',
        '  unset VIRTUAL_ENV',
        'fi',
        'deactivate 2>/dev/null; hash -r',
    ]


def ensure_uv_lines(local_uv: str | None = None) -> list[str]:
    """Define and invoke `_ody_ensure_uv`: make uv available on the host, once.

    This is the *single surface* for getting uv onto a machine — not prepended
    to every install command, and not a separate setup step the user must
    remember. It resolves uv in cheap-to-expensive order and stops at the first
    hit:

      1. `command -v uv`            — already on PATH (the common case)
      2. `local_uv` (if given)      — the absolute path uv resolved to on the
                                      Odysseus server; covers the minimal-PATH
                                      LOCAL tmux shell without any network call
      3. ~/.local/bin/uv            — uv's canonical install dir (covers both a
                                      prior install and the remote case)
      4. one-time network install   — `curl|sh` (or `wget|sh`) from the official
                                      installer, landing in ~/.local/bin

    Because step 4 installs into ~/.local/bin, step 1/3 succeed on every
    subsequent run on that host: the network install fires at most ONCE per
    machine, ever, with no state to track. If even the install fails (offline
    host), `pip_install()`'s pip fallback still carries the install through.

    `local_uv` should be the server-resolved `shutil.which("uv")` for LOCAL
    runners and None for remote runners (a local path is meaningless there)."""
    seed: list[str] = []
    if local_uv:
        q = shlex.quote(local_uv)
        seed = [f'  if [ -x {q} ]; then export PATH="$(dirname {q}):$PATH"; return 0; fi']
    install_url = shlex.quote(_UV_INSTALL_URL)
    return [
        '_ody_ensure_uv() {',
        '  if command -v uv >/dev/null 2>&1; then return 0; fi',
        '  if [ -x "$HOME/.local/bin/uv" ]; then export PATH="$HOME/.local/bin:$PATH"; return 0; fi',
        *seed,
        f'  if command -v curl >/dev/null 2>&1; then curl -LsSf {install_url} | sh >/dev/null 2>&1; '
        f'elif command -v wget >/dev/null 2>&1; then wget -qO- {install_url} | sh >/dev/null 2>&1; fi',
        '  export PATH="$HOME/.local/bin:$PATH"',
        '  if command -v uv >/dev/null 2>&1; then return 0; fi',
        # Make the fall-through visible: on an offline/locked host the network
        # install above is silenced, so without this line a user only sees the
        # (slower) pip path with no clue why uv never engaged. Printed to stdout
        # so it lands in the runner's captured log.
        '  echo "[odysseus] uv unavailable (not installed and network install failed) — using pip; installs may be slower."',
        '  return 1',
        '}',
        # `|| true`: a failed ensure must not abort the runner — pip_install's
        # pip fallback can still succeed on hosts where uv won't install. The
        # 2>/dev/null mutes the probe noise but keeps the stdout notice above.
        '_ody_ensure_uv 2>/dev/null || true',
    ]


def pip_install(pkgs, *, upgrade: bool = False, no_deps: bool = False, quiet: bool = True, python: str | None = None) -> str:
    """The ONE canonical install command for a bash runner.

    uv-first, with a pip safety net. Assumes the runner already ran
    `ensure_uv_lines()` (so `command -v uv` works when uv is installable) and
    handled the interpreter target via `venv_scrub_lines()` or an `env_prefix`
    (so `$(command -v python3)` is the intended interpreter).

    `python` pins the install to an ABSOLUTE interpreter path instead of the
    runner's `$(command -v python3)`. This is required for a LOCAL Cookbook
    dependency install (rembg, diffusers, hf_transfer, …): those packages exist
    for the Odysseus server to `import`, and the "Installed" badge is a live
    in-process `importlib` probe running under the server's own interpreter
    (`sys.executable`). Without pinning, the runner scrubs the server's uv venv
    and installs into the system python — the install succeeds but the probe,
    looking inside the venv, never sees it. Pinning to `sys.executable` makes
    the install land exactly where the probe looks. uv installs into any target
    interpreter without needing pip there, so this works even though Odysseus's
    uv venv ships no pip.

    Resolution order in the emitted shell:
      1. uv → the pinned/active venv / scrubbed system python (`--python`,
         `--break-system-packages` for PEP-668 hosts)
      2. `python3 -m pip --user --break-system-packages` (PEP-668 systems
         without uv)
      3. `python3 -m pip` (inside a venv where --user is invalid)
      4. bare `pip` (last resort for the rare host whose `python3` is a
         pip-less interpreter but a usable `pip` is elsewhere on PATH)

    The pip fallbacks invoke `python3 -m pip`, NOT a bare `pip`/`pip3` command:
    that targets the same interpreter we install for and works regardless of
    whether the console script is named `pip` or `pip3` (common on Debian/Ubuntu
    where only `pip3` exists). All branches target the same package set, so
    whichever runs produces the same result. Returns a single shell statement
    safe to drop into a runner line or join into a `;`-separated setup command."""
    if isinstance(pkgs, str):
        pkgs = [pkgs]
    flags: list[str] = []
    if quiet:
        flags.append("-q")
    if upgrade:
        flags.append("-U")
    if no_deps:
        flags.append("--no-deps")
    flagstr = (" ".join(flags) + " ") if flags else ""
    spec = " ".join(shlex.quote(p) for p in pkgs)
    if python:
        # Pinned-interpreter install (local dependency for the Odysseus server).
        # uv targets the exact interpreter; the single pip fallback uses the same
        # absolute python so a host without uv still installs into the right env.
        # No --user (invalid inside a venv) and no PATH-relative `python3`.
        py = shlex.quote(python)
        return (
            f'{{ command -v uv >/dev/null 2>&1 && uv pip install --python {py} '
            f'{flagstr}{spec} 2>/dev/null; }} '
            f'|| {py} -m pip install {flagstr}{spec} 2>/dev/null'
        )
    return (
        f'{{ command -v uv >/dev/null 2>&1 && uv pip install --python "$(command -v python3)" '
        f'--break-system-packages {flagstr}{spec} 2>/dev/null; }} '
        f'|| python3 -m pip install --user --break-system-packages {flagstr}{spec} 2>/dev/null '
        f'|| python3 -m pip install {flagstr}{spec} 2>/dev/null '
        f'|| pip install {flagstr}{spec} 2>/dev/null'
    )


def ps_pip_install(pkgs, *, quiet: bool = True, suppress_errors: bool = False) -> str:
    """Canonical `python -m pip install` line for the Windows PowerShell runner
    branches — the counterpart to `pip_install()` for bash.

    Windows intentionally stays on `python -m pip` rather than the uv-first
    chain: uv's Windows bootstrap differs from the curl|sh installer and these
    hosts ship pip. The value of centralizing here is purely de-duplication —
    the four PS call sites used to hand-write this string, so a flag change had
    to be made in four places (and inevitably drifted). `suppress_errors` adds
    PowerShell's `2>$null`; package names are emitted bare to match the existing
    Windows behavior (our callers pass fixed, metacharacter-free specs)."""
    if isinstance(pkgs, str):
        pkgs = [pkgs]
    parts = ["python", "-m", "pip", "install"]
    if quiet:
        parts.append("-q")
    parts += pkgs
    cmd = " ".join(parts)
    if suppress_errors:
        cmd += " 2>$null"
    return cmd
