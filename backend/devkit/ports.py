"""Which ports a dev instance gets, and why it gets the same ones tomorrow.

Ports are allocated in **slots** rather than one at a time: a slot is a whole triple
(backend, frontend, stub) at the same offset, so an instance's three services are always
a fixed distance apart and one number identifies the lot. That is worth more than the
packing it wastes — the number appears in a URL the operator reads, in a CORS origin, in
a generated launch config, and in whatever a future session is about to be told, and a
triple that could drift apart is three things to keep in step instead of one.

The bases sit clear of 8000 and 5173, which is where the operator's own instance lives.
That separation is structural rather than checked-for: no slot can reach those numbers,
so there is no arithmetic to get wrong and no conflict to detect.

Allocation happens **once**, when an instance is first created, and is then recorded.
A later run reads the recorded slot back rather than re-deriving it, because by then the
instance's own services are usually listening on those ports and a fresh probe would
read its own backend as a conflict and move it — renaming URLs out from under whoever
was using them.
"""

from __future__ import annotations

import socket

#: The first port of each service's range. Chosen well above the operator's 8000/5173.
BACKEND_BASE = 8200
FRONTEND_BASE = 5273
STUB_BASE = 8300

#: How many parallel dev instances one host will hand out slots for. A ceiling rather
#: than a limit anyone should reach: it exists so a bug that fails to find a free slot
#: says so instead of scanning ports forever.
MAX_SLOTS = 20


class NoFreeSlot(RuntimeError):
    """Every slot is taken. Carries the remedy, because the caller prints it verbatim."""


def slot_ports(slot: int) -> tuple[int, int, int]:
    """The (backend, frontend, stub) triple for a slot."""
    return BACKEND_BASE + slot, FRONTEND_BASE + slot, STUB_BASE + slot


def is_free(port: int) -> bool:
    """Whether nothing is listening on this loopback port.

    Deliberately without ``SO_REUSEADDR``: the question is "can a server take this
    port", not "can I momentarily bind it", and the reuse flag would answer yes over a
    socket another process is still holding.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def allocate(taken: set[int]) -> int:
    """The lowest slot that neither another instance has claimed nor the host is using.

    ``taken`` is what the other instances on this host have recorded — checked first and
    on its own, because a slot belonging to an instance that simply is not running right
    now would otherwise look free and be handed out twice.
    """
    for slot in range(MAX_SLOTS):
        if slot in taken:
            continue
        if all(is_free(port) for port in slot_ports(slot)):
            return slot
    raise NoFreeSlot(
        f"all {MAX_SLOTS} dev-instance slots are claimed or in use. "
        "Remove an instance you no longer need from ~/.odysseus/dev/, "
        "or stop whatever is holding ports "
        f"{BACKEND_BASE}-{BACKEND_BASE + MAX_SLOTS - 1}."
    )
