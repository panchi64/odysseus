"""A workspace's network edge: one internal network, and the proxy that is its only exit.

The fence a workspace runs behind is two runtime objects rather than a flag. The network
is ``--internal``, so nothing attached to it has a route off the host — not the exec
container, not a preview, not anything the agent starts inside them. The sidecar is the
single container with a second leg on ``bridge``, and it forwards only what that
workspace's allowlist names (:mod:`services.sandbox.egress_proxy`).

Why a proxy rather than firewall rules: the agent must be able to install packages, clone
repositories and burn CPU without any of it feeling dangerous, and the thing actually
worth stopping is bytes leaving for somewhere nobody approved. A name-based allowlist is
the only form of that an operator can read and answer — an IP set is not something anyone
approves, and it is stale the moment a CDN moves.

The sidecar is also the workspace's way *in*. A container on an internal network cannot
publish a port at all (the runtime accepts ``--publish`` and maps nothing), and the
sidecar's mapping only materialises once its bridge leg is attached — so the live preview
is published here and relayed inward, and the preview container itself stays unpublished
on the internal network with everything else.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import SandboxError
from .container import (
    await_log_marker,
    detached_run_argv,
    force_remove_container,
    run_subprocess,
)
from .egress_proxy import FORWARD_FILE, FORWARD_PORT
from .names import ContainerNames

logger = logging.getLogger(__name__)

#: The port the sidecar's proxy listens on, and the one ``proxy_env`` points at.
PROXY_PORT = 3128

#: Mounted read-only into a stock python image — see the script's own module docstring.
PROXY_SCRIPT = Path(__file__).with_name("egress_proxy.py").resolve()

# Where the two mounts land inside the sidecar. Both read-only: the sidecar is the one
# container in a workspace that the agent's code never runs in, and it stays that way.
_SCRIPT_PATH = "/proxy.py"
_ALLOW_PATH = "/allow"

# Long enough for an implicit pull of the (small) proxy image on a cold host, since a
# workspace that cannot raise its fence does not start at all.
_CREATE_TIMEOUT_S = 180.0
_READY_TIMEOUT_S = 30.0


def proxy_env(names: ContainerNames, key: str) -> dict[str, str]:
    """The proxy environment every container on a workspace network is started with.

    Both cases, because the ecosystem is split down the middle and neither half is
    optional here: curl reads the lowercase names only, while pip, uv, npm, cargo, go and
    git read the uppercase pair. ``NO_PROXY`` keeps loopback and the sidecar itself direct
    — a client that proxied its own connection to the proxy would loop."""
    sidecar = names.sidecar(key)
    url = f"http://{sidecar}:{PROXY_PORT}"
    direct = f"localhost,127.0.0.1,{sidecar}"
    return {
        "HTTP_PROXY": url,
        "HTTPS_PROXY": url,
        "http_proxy": url,
        "https_proxy": url,
        "NO_PROXY": direct,
        "no_proxy": direct,
    }


async def create_internal_network(runtime: str, name: str) -> str:
    """Create this workspace's ``--internal`` network and return its subnet.

    An existing one of the same name is a success, not a conflict: the previous process
    may have left it (boot reconciliation clears those, but only when the runtime was up),
    and a network is stateless — joining the old one is joining the same wall.

    The subnet is what the sidecar refuses connections from outside of. It has to be read
    back rather than chosen, because the runtime allocates it."""
    _timed_out, code, _out, err = await run_subprocess(
        [runtime, "network", "create", "--internal", name], timeout_s=60.0
    )
    if code != 0 and b"already exists" not in err.lower():
        raise SandboxError(
            f"could not create the workspace network: {err.decode('utf-8', 'replace').strip()}"
        )
    _timed_out, code, out, err = await run_subprocess(
        [
            runtime,
            "network",
            "inspect",
            "--format",
            "{{range .IPAM.Config}}{{.Subnet}} {{end}}",
            name,
        ],
        timeout_s=30.0,
    )
    if code != 0:
        raise SandboxError(
            f"could not read the workspace network: {err.decode('utf-8', 'replace').strip()}"
        )
    subnet = " ".join(out.decode("utf-8", "replace").split())
    if not subnet:
        # A runtime whose inspect schema this template does not fit prints nothing and
        # exits 0. Refuse to come up rather than hand the proxy an empty peer check: the
        # sidecar would start, the fence would look raised, and the one control stopping
        # a bridge-side container from borrowing this allowlist would silently be off.
        raise SandboxError(f"the workspace network {name} reported no subnet")
    return subnet


async def remove_network(runtime: str, name: str, *, timeout_s: float = 30.0) -> None:
    """Best-effort ``network rm``. One still holding a container we failed to remove is
    left for the next boot's reconciliation rather than made anyone's error."""
    if timeout_s <= 0:
        return
    try:
        await run_subprocess([runtime, "network", "rm", name], timeout_s=timeout_s)
    except SandboxError:
        logger.info("sandbox: could not remove network %s", name, exc_info=True)


async def start_egress_sidecar(
    runtime: str,
    *,
    name: str,
    network: str,
    subnet: str,
    allow_dir: Path,
    image: str,
    script_path: Path = PROXY_SCRIPT,
) -> None:
    """Bring up a workspace's proxy sidecar, or raise.

    Fail-closed by construction: every caller starts workspace containers immediately
    after, and a workspace whose fence never came up would otherwise run with no exit
    policy at all rather than with none of its exits.

    The bridge leg is attached *after* creation rather than at ``run`` time because a
    container can only be created on one network — and it is what both gives the proxy a
    route to the open web and brings the published forward port up (a container created
    on an internal network publishes nothing until it has a routable leg)."""
    await force_remove_container(runtime, name)  # a leftover of this name blocks the create
    allow_dir.mkdir(parents=True, exist_ok=True)
    argv = detached_run_argv(
        runtime,
        name,
        _sidecar_flags(network=network, subnet=subnet, allow_dir=allow_dir, script=script_path),
        image,
        ["python", _SCRIPT_PATH, str(PROXY_PORT), _ALLOW_PATH],
    )
    _timed_out, code, _out, err = await run_subprocess(argv, timeout_s=_CREATE_TIMEOUT_S)
    if code != 0:
        raise SandboxError(
            f"could not start the egress proxy: {err.decode('utf-8', 'replace').strip()}"
        )
    _timed_out, code, _out, err = await run_subprocess(
        [runtime, "network", "connect", "bridge", name], timeout_s=30.0
    )
    if code != 0:
        await stop_egress_sidecar(runtime, name)
        raise SandboxError(
            f"could not connect the egress proxy to the network: "
            f"{err.decode('utf-8', 'replace').strip()}"
        )
    if not await await_log_marker(runtime, name, b"PROXY-READY", timeout_s=_READY_TIMEOUT_S):
        await stop_egress_sidecar(runtime, name)
        raise SandboxError("the egress proxy did not come up")


def _sidecar_flags(*, network: str, subnet: str, allow_dir: Path, script: Path) -> list[str]:
    """The sidecar's own hardening — deliberately not ``hardened_flags``.

    That function describes a *workspace* box: a writable bind mount, generous caps, and
    the install redirects the agent's code needs. This container runs one stdlib script
    over two read-only mounts and never runs anything the agent wrote, so it gets the
    strictest shape we have instead: immutable root, a scrap of tmpfs, and caps small
    enough that a runaway proxy costs nothing.

    The log cap belongs with those: every refusal prints a line, and what drives refusals
    is code the agent wrote. Unrotated, a loop over an unlisted host fills the operator's
    disk at loopback speed — a denial has to stay legible without being a write channel."""
    return [
        "--network",
        network,
        "--log-opt",
        "max-size=1m",
        "--log-opt",
        "max-file=1",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--memory",
        "256m",
        "--pids-limit",
        "256",
        "--publish",
        f"127.0.0.1:0:{FORWARD_PORT}",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONUNBUFFERED=1",
        "--env",
        f"EGRESS_CLIENT_SUBNET={subnet}",
        "--volume",
        f"{script}:{_SCRIPT_PATH}:ro",
        "--volume",
        f"{allow_dir}:{_ALLOW_PATH}:ro",
    ]


async def stop_egress_sidecar(runtime: str, name: str, *, timeout_s: float = 30.0) -> None:
    """Tear the sidecar down — the same best-effort removal every other box gets."""
    await force_remove_container(runtime, name, timeout_s=timeout_s)


def point_forwarder(allow_dir: Path, target: str) -> None:
    """Aim the sidecar's published port at ``host:port``, for the workspace's live preview.

    Written into the same directory the allowlist lives in because that directory is
    already mounted into the sidecar, and a second mount would be a second thing to keep
    in step for one line of text. Synchronous: it is one small write, and the caller is
    about to spend seconds starting a container."""
    allow_dir.mkdir(parents=True, exist_ok=True)
    (allow_dir / FORWARD_FILE).write_text(f"{target}\n", encoding="utf-8")
