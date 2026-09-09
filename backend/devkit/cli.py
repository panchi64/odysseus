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

from devkit import ports
from devkit.instance import DevInstance, resolve


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev_instance",
        description=(
            "Run an isolated Odysseus for development — its own data, ports and "
            "containers, seeded and safe to break."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    status = subcommands.add_parser(
        "status", help="what this worktree's instance is and whether it is running"
    )
    status.set_defaults(handler=_cmd_status)

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
