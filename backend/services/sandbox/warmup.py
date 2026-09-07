"""When the shared container image is ready — the one fact the manager and every
session have to agree on.

Its own module because it belongs to neither: the manager is the only thing that
*pulls* the image, a session is the only thing that *waits* for it, and putting the
handshake in either file gives that file a second reason to change.
"""

from __future__ import annotations

import asyncio


class ImageWarmup:
    """Coordinates the background image pull (the manager's ``_warm_image``)
    with a session's first container create, so a cold ``_ensure_up``/
    ``start_preview`` never races an implicit ``docker run`` pull against its own
    short create-timeout (sandbox-01). One instance per manager, shared by every
    session it mints; a bare :class:`~services.sandbox.session.SandboxSession` used
    without one (e.g. direct unit construction) simply skips the coordination — see
    ``warmup=None``.

    Defaults to "nothing to wait for" (``ready``, not ``pending``) until
    :meth:`start_pulling` says otherwise — so a manager that's never actually
    started warming (e.g. most unit tests, which construct one without calling
    :meth:`~services.sandbox.manager.SandboxSessionManager.start`) behaves exactly as
    it did before this coordination existed, rather than waiting on a pull that will
    never run."""

    def __init__(self) -> None:
        self._done = asyncio.Event()
        self._done.set()
        self.ready = True

    @property
    def pending(self) -> bool:
        """True only while a background pull is actually in flight."""
        return not self._done.is_set()

    def start_pulling(self) -> None:
        """Call right before kicking off the background pull — flips to
        pending so a concurrent create knows to wait rather than assume
        readiness."""
        self.ready = False
        self._done.clear()

    def mark_done(self, ready: bool) -> None:
        self.ready = ready
        self._done.set()

    async def wait(self, timeout_s: float) -> bool:
        """Wait up to ``timeout_s`` for the pull to resolve. Returns whether the
        image is now known ready. A caller that times out here still sees
        ``pending`` True afterwards, distinguishing "still pulling" (worth a
        clear retry message) from "resolved and confirmed missing" (let the
        ordinary create attempt run and report its own real error)."""
        if not self.pending:
            return self.ready
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout_s)
        except TimeoutError:
            return False
        return self.ready
