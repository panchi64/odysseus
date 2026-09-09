"""The command surface — what a session actually types.

Written for a reader that arrives with no context and one turn to spend. Two rules
follow from that, and they are why this module exists rather than a handful of scripts:

**Every command takes ``--json``.** A session that has to parse prose to learn a port
number will eventually parse it wrong, and be confidently wrong afterwards. The human
form is a convenience over the machine form, never the only form.

**Output ends with the next action, spelled out.** Knowing the state and knowing what to
do about it are different things, and a message that reports only the first leaves the
reader to guess the second.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from devkit import launch, ports, processes
from devkit.instance import DevInstance, resolve
from devkit.processes import Supervisor


def _service_states(instance: DevInstance) -> dict[str, bool]:
    """Which of the three services are listening. A port that will not bind is one
    something already holds — this instance's own service, in the ordinary case."""
    return {
        "backend": not ports.is_free(instance.backend_port),
        "frontend": not ports.is_free(instance.frontend_port),
        "stub": not ports.is_free(instance.stub_port),
    }


def status_payload(instance: DevInstance) -> dict[str, Any]:
    """Everything about an instance, in the shape ``--json`` prints.

    The single source for ports: the skill tells a session to read them from here rather
    than assume slot 0's, because a parallel worktree is on a different slot and a
    hardcoded 5273 would quietly drive the wrong instance.
    """
    running = _service_states(instance)
    return {
        "name": instance.name,
        "slot": instance.slot,
        "root": str(instance.root),
        "data_dir": str(instance.data_dir),
        "urls": {
            "frontend": instance.frontend_url,
            "backend": instance.backend_url,
            "stub": instance.stub_url,
        },
        "ports": {
            "frontend": instance.frontend_port,
            "backend": instance.backend_port,
            "stub": instance.stub_port,
        },
        "running": running,
        "ready": all(running.values()),
        "seeded": instance.seeded or None,
        "auth": instance.auth,
        "containers": instance.containers,
        "container_prefix": instance.container_prefix,
        # Printed because with auth off nobody is asked for it and it would otherwise
        # look like a secret that had gone missing when someone turns auth on.
        "password": instance.password,
    }


def _print_status(payload: dict[str, Any]) -> None:
    running = payload["running"]
    mark = {True: "up", False: "down"}
    print(f"dev instance '{payload['name']}'  (slot {payload['slot']})")
    print(f"  data      {payload['data_dir']}")
    for service in ("frontend", "backend", "stub"):
        print(f"  {service:<9} {payload['urls'][service]:<28} {mark[running[service]]}")
    print(f"  seeded    {payload['seeded'] or 'not yet'}")
    print(f"  auth      {'on — password below' if payload['auth'] else 'off — no login screen'}")
    print(f"  password  {payload['password']}")
    if not payload["ready"]:
        print("\nnext: uv run python dev_instance.py up")


def _cmd_status(args: argparse.Namespace) -> int:
    instance = resolve()
    payload = status_payload(instance)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_status(payload)
    return 0


def _print_ready(payload: dict[str, Any], outcomes: dict[str, str], *, detached: bool) -> None:
    """The block a session reads after ``up``. Ends with the next action, spelled out —
    knowing the state and knowing what to do about it are different things."""
    print(f"\ndev instance '{payload['name']}' ready  (slot {payload['slot']})\n")
    for service in ("frontend", "backend", "stub"):
        print(f"  {service:<9} {payload['urls'][service]:<28} {outcomes.get(service, '')}")
    print(f"  data      {payload['data_dir']}")
    print(f"  logs      {payload['root']}/logs")
    if payload["auth"]:
        print(f"  password  {payload['password']}")
    else:
        print("  login     none — auth is off, the app opens straight up")
    print(f"\nnext: preview_start '{launch.LAUNCH_CONFIG}'")
    print(f"      or open {payload['urls']['frontend']}")
    print("      ports differ per worktree — read them from `dev_instance.py status --json`")
    print(
        "\nrunning in the background; stop it with `dev_instance.py stop`"
        if detached
        else "\nCtrl-C stops the services this command started."
    )


def _cmd_up(args: argparse.Namespace) -> int:
    instance = resolve(auth=args.auth or None, containers=args.with_containers or None)
    supervisor = Supervisor()
    try:
        outcomes = launch.bring_up(instance, supervisor)
    except launch.LaunchError as failure:
        supervisor.stop_all()
        print(f"error: {failure}", file=sys.stderr)
        return 1

    supervisor.record(instance.root)
    payload = status_payload(instance)
    if args.json:
        print(json.dumps({**payload, "outcomes": outcomes, "detached": args.detach}, indent=2))
    else:
        _print_ready(payload, outcomes, detached=args.detach)

    if args.detach:
        # Each child has its own process group, so they outlive this command. `stop`
        # reads the pidfile just recorded and signals those groups.
        return 0
    try:
        launch.wait_for_signal()
    finally:
        supervisor.stop_all()
        (instance.root / processes.PIDFILE).unlink(missing_ok=True)
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    instance = resolve()
    stopped = processes.stop_recorded(instance.root)
    if args.json:
        print(json.dumps({"stopped": stopped}))
    elif stopped:
        print(f"stopped: {', '.join(stopped)}")
    else:
        print("nothing recorded as running for this worktree's instance")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev_instance",
        description=(
            "Run an isolated Odysseus for development — its own data, ports and "
            "containers, seeded and safe to break."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    up = subcommands.add_parser(
        "up",
        help="bring the instance up (safe to run twice — it fills in what is missing)",
    )
    up.add_argument(
        "--detach",
        action="store_true",
        help="return once everything is up, leaving it running; stop it with `stop`",
    )
    up.add_argument(
        "--auth",
        action="store_true",
        help="put the real login screen in front of the app (off by default)",
    )
    up.add_argument(
        "--with-containers",
        action="store_true",
        help="also run the sandbox, SearXNG and web-fetch containers",
    )
    up.set_defaults(handler=_cmd_up)

    status = subcommands.add_parser(
        "status", help="what this worktree's instance is and whether it is running"
    )
    status.set_defaults(handler=_cmd_status)

    stop = subcommands.add_parser("stop", help="stop the services a previous `up` started")
    stop.set_defaults(handler=_cmd_stop)

    for sub in subcommands.choices.values():
        sub.add_argument(
            "--json", action="store_true", help="machine-readable output (prefer this)"
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
