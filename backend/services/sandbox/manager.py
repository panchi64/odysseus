"""The set of live sandboxes — who owns one, how many may exist, and when each goes.

One :class:`~services.sandbox.session.SandboxSession` is a single conversation's
container and workspace, and knows nothing about the others. Everything that is a
*policy over the set* lives here instead: mapping a conversation to its session,
the live-session cap, the idle reaper, the preview token index, purging a deleted
conversation, adopting the plaintext workspaces an unclean shutdown stranded, and
forking a session for a delegated agent (the copy and the merge themselves are
:mod:`services.sandbox.fork`'s; which key is the parent is a fact about the set).

The split follows the lock. A session's lock spans one call on one container; this
manager's lock guards the maps that decide which session a key even names, and the
tombstone protocol (``_tearing_down``) that keeps a second session from being minted
onto a workspace a seal is still reading. Two locks with two jobs, and neither file
has a reason to change when the other's job does.

What is deliberately *not* here is boot cleanup: the containers and networks a
previous process left running are collected by :mod:`services.sandbox.reconcile`,
which needs none of this manager's state. The plaintext workspaces that same crash
stranded are collected here instead, by the idle sweep (:meth:`_seal_orphans`),
since sealing them needs a vault that is still locked at boot.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import time
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from core.concurrency import gather_bounded
from core.fork import MergeReport
from core.vault import Vault

from .base import SandboxError, safe_key
from .container import ContainerSandbox, ensure_image
from .fork import fork_marker
from .preview import PreviewHandle
from .reconcile import reconcile as reconcile_leftovers
from .seal import partial_marker
from .session import LiveWork, SandboxSession
from .warmup import ImageWarmup

if TYPE_CHECKING:  # `services.egress` reads `safe_key` from this package — importing it
    # for real here would close the loop, and the type is all this module needs.
    from services.egress import EgressPolicy

logger = logging.getLogger(__name__)

# How many reaped sessions are sealed concurrently (tar+gzip+AEAD is CPU/IO work
# off-thread) — bounded so a mass reap doesn't itself thrash the host, but no longer
# serial, so unrelated conversations aren't stalled behind one another. Shared by both
# reasons a session is reaped: the idle sweep, and a new session displacing an old one
# at the live-session cap.
_SEAL_CONCURRENCY = 3

# How many stranded plaintext workspaces one sweep adopts. Every key in a batch is
# tombstoned for the whole batch, and an `acquire()` that lands on a tombstone waits
# with nothing to show the operator — so the batch is kept to a couple of seal rounds
# rather than however many a crashed process happened to leave. The next sweep takes
# the next slice, which is soon enough for directories that have already sat in the
# clear since the crash.
_ORPHAN_SEALS_PER_SWEEP = 2 * _SEAL_CONCURRENCY


#: A session taken out of the live map and awaiting its seal, with the event that
#: releases whoever is waiting on *that* key's teardown. See ``_detach``.
type _Detached = tuple[str, SandboxSession, asyncio.Event]


class SandboxSessionManager:
    """Maps a conversation to its live :class:`SandboxSession`, reaping idle ones —
    idle for too long, or least-recently-used once there are too many.

    Built only when a container runtime is present (fail-closed detection lives in
    ``detect``), so its existence means code execution is available."""

    # How long a reaped/purged preview's token stays a recognized "stopped" tombstone
    # (`preview_status`) before it's pruned as stale — long enough for an operator who left
    # the tab open across the idle window to still get a legible answer, short enough that
    # an abandoned conversation's tokens don't accumulate forever in memory.
    _STOPPED_TOKEN_TTL_S = 3600.0

    def __init__(
        self,
        backend: ContainerSandbox,
        vault: Vault,
        *,
        egress: EgressPolicy,
        data_dir: Path,
        idle_ttl_s: float,
        reap_interval_s: float,
        excludes: Iterable[str],
        proxy_image: str = "python:alpine",
        preview_startup_timeout_s: float = 20.0,
        max_sessions: int = 8,
    ) -> None:
        self._backend = backend
        self._vault = vault
        # What each workspace may reach. The manager holds it (rather than each session)
        # because writing the file the fence reads is a *per-key* act that has to happen
        # before that key's first container exists — see `acquire`.
        self._egress = egress
        self._proxy_image = proxy_image
        self._work_root = data_dir / "sandbox" / "work"
        self._sealed_root = data_dir / "sandbox" / "sealed"
        self._idle_ttl = idle_ttl_s
        self._reap_interval = reap_interval_s
        self._excludes = tuple(excludes)
        self._preview_startup_timeout_s = preview_startup_timeout_s
        # How many conversations may hold a live container at once. The idle TTL bounds a
        # session in *time*; this bounds the set in *count*, which the TTL alone never does
        # — a dozen threads worked on in rotation all stay inside the window. See
        # `_over_cap`.
        self._max_sessions = max(1, max_sessions)
        self._sessions: dict[str, SandboxSession] = {}
        # token → safe session key, so the proxy route resolves a preview in O(1).
        self._previews: dict[str, str] = {}
        # token → monotonic time it was torn down *without* an explicit `view_close`
        # (idle-reaped or purged) — lets `preview_status` tell the frontend "this server
        # was killed out from under you" instead of a bare, indistinguishable 404. Explicit
        # closes need no tombstone: `view_close` already emits `view.live.stopped`.
        self._stopped_tokens: dict[str, float] = {}
        # safe key → set once its (former) session's teardown (a sweep's seal, or
        # a purge) is in flight. A concurrent acquire()/purge() for THIS key waits
        # on it; every other key is unaffected (sandbox-02).
        self._tearing_down: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None
        self._warm: asyncio.Task | None = None
        self._image_warmup = ImageWarmup()
        # Seals in flight, owned by the manager rather than by whoever triggered them —
        # see `_tear_down`. Held so they are not garbage-collected mid-archive and so
        # `stop` can drain them.
        self._teardowns: set[asyncio.Task] = set()

    @property
    def image_warmup_pending(self) -> bool:
        """Whether the boot-time image pull is still in flight — lets a caller
        (e.g. the ``code_execute`` tool) distinguish an ordinary cold start from
        one that's actually waiting on a still-downloading image."""
        return self._image_warmup.pending

    def existing(self, key: str) -> SandboxSession | None:
        """The live session for a conversation if one exists, **without creating** it,
        so a turn that never touched the sandbox triggers no workspace/history work."""
        return self._sessions.get(safe_key(key))

    async def acquire(self, key: str, *, holder: LiveWork | None = None) -> SandboxSession:
        """The session for a conversation, created (object only) on first use. If this
        key is mid-teardown from a concurrent sweep/purge, waits for THAT teardown
        specifically rather than racing a second session onto the same workspace
        path; every other key proceeds immediately (sandbox-02).

        ``holder`` is the run asking, and claiming it here is what makes the cap safe:
        without it the only "in use" signal is the exec lock, which is held for one call
        out of the dozens a turn makes. See :attr:`SandboxSession.is_claimed`. Optional
        because not every caller is a turn — a proxy request resolving a preview, a route,
        a test — and those genuinely have no lifetime to tie a container to.

        Admitting a new session is also where the **cap** is applied (:meth:`_over_cap`):
        a new arrival reaps the least-recently-used idle sessions back down to the ceiling
        before it returns, which makes the ceiling a policy instead of an accident. Nothing
        is lost by the reap: a reaped session's files are sealed and restored the next time
        that conversation runs code, exactly as after an idle reap."""
        safe = safe_key(key)
        evicted: list[_Detached] = []
        while True:
            async with self._lock:
                session = self._sessions.get(safe)
                if session is None:
                    other = self._tearing_down.get(safe)
                    if other is None:
                        session = self._new_session(safe, self._egress.allow_dir(key))
                        self._sessions[safe] = session
                        # Only a *new* arrival applies the cap: finding a session already
                        # live is the steady state, and re-reaping on every tool call
                        # would make the cap a per-call sweep.
                        evicted = self._detach(self._over_cap(keep={safe}))
                if session is not None:
                    session.touch()
                    session.hold(holder)
                    break
            await other.wait()
        if not session.is_warm:
            # The fence's allowlist has to be on disk before the sidecar mounts the
            # directory it lives in — a cold session's bring-up is the next thing that
            # happens, and a fence that came up over an empty directory would refuse
            # everything the operator has already allowed. A warm one already has it, and
            # every later grant rewrites the file under the running proxy.
            await self._egress.materialise(key)
        # Awaited rather than backgrounded, because the caller is about to start a
        # container: returning before the ones it displaced are actually gone would leave
        # the host over the cap at exactly the moment the cap matters. On a task of the
        # manager's own, because those sessions are *other* conversations' — `_tear_down`.
        await self._tear_down(evicted)
        return session

    def _over_cap(self, *, keep: Collection[str]) -> list[str]:
        """The session keys to reap so the live set fits under the cap, longest-idle
        first. Called under the manager lock.

        ``keep`` is what the admission is *about* and must survive it: the arriving
        session, and — for a fork — the parent it was copied from, mid-work by the very
        fact that it has just delegated. Beyond those, only a session nobody is using is a
        candidate — see :attr:`SandboxSession.is_displaceable` for the three ways that is
        decided. The cap is a resource ceiling, not a deadline: if everything live is in use
        the set simply runs over and the idle sweep collects the overflow once the work
        finishes — the same choice ``ConversationStore._trim_cache`` makes for pinned trees.

        Reaping also *seals*, so it needs the vault key. With the vault locked there is
        nothing to do but run over the cap: tearing a container down without sealing would
        strand the agent's plaintext files on disk, which is a worse answer than a
        container too many."""
        if not self._vault.is_unlocked:
            return []
        overflow = len(self._sessions) - self._max_sessions
        if overflow <= 0:
            return []
        now = time.monotonic()
        idle = sorted(
            (
                (session.idle_seconds(now), key)
                for key, session in self._sessions.items()
                if key not in keep and session.is_displaceable
            ),
            reverse=True,
        )
        return [key for _, key in idle[:overflow]]

    def _detach(self, keys: Iterable[str]) -> list[_Detached]:
        """Take sessions out of the live map, leaving a per-key teardown tombstone
        behind. Called under the manager lock, by both reasons a session is reaped: the
        idle sweep and the live-session cap.

        Detaching and sealing are separate halves on purpose. The map mutation has to be
        atomic against a concurrent ``acquire()``/``purge()`` — otherwise a second session
        is minted onto a workspace mid-teardown — while the seal itself is slow and must
        not hold the lock for the sum of every teardown (sandbox-02). The returned events
        are what the *same* key's acquire/purge waits on; every other key proceeds."""
        detached: list[_Detached] = []
        for key in keys:
            session = self._sessions.pop(key, None)
            if session is None:
                continue
            self._mark_preview_stopped(session)
            self._drop_preview_tokens(key)
            event = asyncio.Event()
            self._tearing_down[key] = event
            detached.append((key, session, event))
        return detached

    async def _reattach(self, detached: list[_Detached]) -> None:
        """Undo a :meth:`_detach` whose teardown must not happen after all — a seal that
        failed, a merge that reported nothing. Dropped there instead, a session is lost
        where neither sweep nor purge can find it: a container in nobody's map over a
        plaintext workspace, behind a tombstone every later ``acquire()`` for that key
        waits on forever. Nothing can have taken the key meanwhile — holding acquire and
        purge off is what that tombstone is for."""
        async with self._lock:
            for key, session, _event in detached:
                self._sessions.setdefault(key, session)
                self._tearing_down.pop(key, None)
        for _key, _session, event in detached:
            event.set()

    async def _tear_down(self, detached: list[_Detached]) -> None:
        """Seal detached sessions on a task the *manager* owns, and wait for it.

        The waiting is the caller's; the sealing is not. Both reasons a session is
        detached tear down somebody else's conversation — the cap seals whoever was
        least-recently-used, the sweep seals whoever went idle — and neither should die
        because the task that happened to trigger it was cancelled. Sealing is seconds of
        tar+gzip+AEAD, so the window is wide: the operator presses Stop, the acquiring
        task unwinds, and an unrelated conversation is left with a plaintext workspace,
        no archive, and a live container no sweep can reach.

        ``shield`` is what separates the two: a cancelled caller stops waiting, and the
        seal it started finishes regardless. :meth:`stop` drains what is still in flight
        rather than cancelling it — a half-written archive is the one outcome worse than
        a slow shutdown."""
        if not detached:
            return
        task = asyncio.create_task(self._seal_detached(detached))
        self._teardowns.add(task)
        task.add_done_callback(self._teardowns.discard)
        await asyncio.shield(task)

    async def _seal_detached(self, detached: list[_Detached]) -> None:
        """Seal and tear down detached sessions off the manager lock, a few at a time,
        then release each one's tombstone. One failed teardown must not strand the others
        — or, worse, leave a tombstone set forever and hang every later acquire for that
        conversation — so each leg isolates its own failure and releases in a ``finally``."""

        async def seal(key: str, session: SandboxSession, event: asyncio.Event) -> None:
            sealed = False
            try:
                await session.shutdown()
                sealed = True
            except Exception:  # noqa: BLE001 — one bad teardown must not stall the rest
                logger.warning(
                    "sandbox %s: teardown failed; leaving the session live for the sweep",
                    key,
                    exc_info=True,
                )
            finally:
                if sealed:
                    async with self._lock:
                        self._tearing_down.pop(key, None)
                    event.set()
                else:
                    # A seal that did not happen must not lose the session with it — put
                    # it back and let the next idle sweep try again.
                    await self._reattach([(key, session, event)])

        await gather_bounded([seal(*item) for item in detached], _SEAL_CONCURRENCY)

    def _new_session(
        self, safe: str, egress_dir: Path, *, ephemeral: bool = False
    ) -> SandboxSession:
        return SandboxSession(
            safe,
            workspace=self._work_root / safe,
            sealed=self._sealed_root / f"{safe}.tar.enc.gz",
            egress_dir=egress_dir,
            backend=self._backend,
            vault=self._vault,
            excludes=self._excludes,
            proxy_image=self._proxy_image,
            warmup=self._image_warmup,
            ephemeral=ephemeral,
        )

    async def fork(
        self, parent_key: str, child_key: str, *, holder: LiveWork | None = None
    ) -> SandboxSession:
        """A delegated agent's own session, over a copy of ``parent_key``'s workspace.

        The child is a full session — its own network, sidecar and container — over a warm
        copy of the parent's files and behind the *parent's* allowlist: a delegated agent
        reaches what the conversation that delegated to it reaches, and a grant approved for
        one is not a second thing to approve for the other. ``holder`` is the child's run,
        and passing it keeps the fork out of the cap's reach — displacing one means
        discarding it, nothing here being sealed — and claims the *parent*, mid-work
        by the very fact that it has just delegated."""
        parent = await self.acquire(parent_key, holder=holder)
        safe = safe_key(child_key)
        async with self._lock:
            if safe in self._sessions or safe in self._tearing_down:
                raise SandboxError(f"a workspace already exists for {child_key!r}")
            child = self._new_session(safe, self._egress.allow_dir(parent_key), ephemeral=True)
            self._sessions[safe] = child
            child.hold(holder)
            evicted = self._detach(self._over_cap(keep={safe, parent.key}))
        # Both halves have to agree on the key — a grant written under the child's own would
        # materialise an unmounted file. After the map, so a refusal above leaves no alias.
        self._egress.share(child_key, parent_key)
        # Before the copy, not after: what this displaced is already out of the live map
        # behind a tombstone, and a failed copy would strand its acquires on an unset event.
        await self._tear_down(evicted)
        try:
            # The parent's own call: the copy must hold the lock a seal takes — `clone_into`.
            child.fork_manifest = await asyncio.to_thread(parent.clone_into, child.workspace)
        except BaseException:
            # A fork with no copy is a session nobody can use, and reap-bait left in the map
            # over a *plaintext* copy nothing seals — and a Stop into the copy, the longest
            # await here, is not an `Exception`. `purge` takes the alias down with it.
            await asyncio.shield(self.purge(child_key))
            raise
        return child

    async def merge_back(self, child_key: str, parent_key: str) -> MergeReport:
        """Land what a forked workspace changed back in its parent, then delete the fork.

        Deleted whichever way the merge *went*: a report of conflicts has already told the
        caller which paths did not come across, and keeping a second copy of the parent's
        files in the hope someone revisits them is how disks fill up. A merge that produced
        no report at all — a vault re-locked mid-delegation, a Stop mid-walk — is the other
        case: the fork is put back, being the only copy of that agent's work with nothing
        reported for anyone to act on. Only a *fork* may be the child, precisely because
        deleting it is the last thing this does: an ordinary conversation's key, from a
        caller with its arguments the wrong way round, would land everything that
        conversation holds in another's workspace and then go with its archive; one key
        twice would wait out the teardown it is itself holding."""
        safe = safe_key(child_key)
        async with self._lock:
            child = self._sessions.get(safe)
            if child is None or not child.ephemeral or safe == safe_key(parent_key):
                raise SandboxError(f"there is no forked workspace for {child_key!r}")
            # Out of the live map for the whole merge: a fork displaced meanwhile is
            # *deleted*, leaving this walk an empty directory to report as a clean landing.
            detached = self._detach([safe])
        try:
            # Every box comes down before the walk, for the reason `shutdown` drops them
            # before an archive: they hold this workspace at /work, so a walk under a live
            # mount copies half-written files — and a box brought up after it writes onto
            # host files the walk has already judged.
            await child.discard()
            parent = await self.acquire(parent_key)
            work = child.ensure_workspace()
            report = await asyncio.to_thread(parent.merge_fork, work, child.fork_manifest)
        except BaseException:
            # Shielded, like the teardown it replaces: a cancellation delivered here too
            # would leave the fork in no map, behind a tombstone nothing ever releases.
            await asyncio.shield(self._reattach(detached))
            raise
        await self._tear_down(detached)
        return report

    async def start_preview(self, key: str, command: list[str], port: int) -> PreviewHandle:
        """Start (or replace) the conversation's live preview and index its token."""
        session = await self.acquire(key)
        safe = safe_key(key)
        token = secrets.token_urlsafe(32)
        # Launch outside the manager lock — the readiness wait must not stall other
        # conversations; the session's own lock marks it busy so the reaper defers.
        handle = await session.start_preview(
            command, port, token=token, startup_timeout_s=self._preview_startup_timeout_s
        )
        async with self._lock:
            self._drop_preview_tokens(safe)  # one preview per conversation
            self._previews[token] = safe
        return handle

    def resolve_preview(self, token: str) -> PreviewHandle | None:
        """The running preview a proxy request names, or None. Touches the session
        so active viewing keeps it warm (the idle reaper won't evict it). Sync (no
        await) so it reads the maps atomically against the reaper."""
        safe = self._previews.get(token)
        if safe is None:
            return None
        session = self._sessions.get(safe)
        if session is None or session.preview is None or session.preview.token != token:
            return None
        session.touch()
        return session.preview

    def preview_status(self, token: str) -> str:
        """Whether a `view.live` token still names a running preview, was torn down
        without an explicit stop (idle-reaped or the conversation was purged), or is
        unrecognized. Read-only — unlike `resolve_preview`, a status check must not
        itself keep an otherwise-idle preview warm. Lets the frontend tell "the
        sandbox went idle and killed it" apart from a merely-still-loading iframe."""
        safe = self._previews.get(token)
        if safe is not None:
            session = self._sessions.get(safe)
            if session is not None and session.preview is not None:
                if session.preview.token == token:
                    return "running"
        return "stopped" if token in self._stopped_tokens else "unknown"

    def _mark_preview_stopped(self, session: SandboxSession) -> None:
        """Tombstone a session's preview token as stopped-without-a-signal (idle
        reap or purge) and prune stale tombstones. Call *before* the session's
        preview is torn down."""
        now = time.monotonic()
        cutoff = now - self._STOPPED_TOKEN_TTL_S
        self._stopped_tokens = {t: ts for t, ts in self._stopped_tokens.items() if ts > cutoff}
        if session.preview is not None:
            self._stopped_tokens[session.preview.token] = now

    async def stop_preview(self, key: str) -> None:
        """Tear down the conversation's preview, leaving the exec session intact."""
        safe = safe_key(key)
        async with self._lock:
            session = self._sessions.get(safe)
            self._drop_preview_tokens(safe)
            if session is not None:
                await session.stop_preview()

    def _drop_preview_tokens(self, safe: str) -> None:
        self._previews = {t: k for t, k in self._previews.items() if k != safe}

    async def purge(self, key: str) -> None:
        """Delete a conversation's sandbox outright — stop any live session and
        remove its workspace **and** sealed archive from disk. Called when the
        conversation is deleted, so nothing is kept. Idempotent and safe for a cold
        conversation (no live session, only a sealed archive on disk), and works
        while the vault is locked (it only destroys).

        Registers itself in ``_tearing_down`` (the same gate a sweep's seal uses)
        for the duration of its own teardown+delete: if a sweep is already mid-seal
        for this key we wait for that first, and a concurrent ``acquire()`` for
        this key waits for us in turn — so nothing ever recreates a session onto
        files we're in the middle of removing (sandbox-02)."""
        safe = safe_key(key)
        my_event = asyncio.Event()
        session: SandboxSession | None = None
        while True:
            async with self._lock:
                other = self._tearing_down.get(safe)
                if other is None:
                    session = self._sessions.pop(safe, None)
                    if session is not None:
                        self._mark_preview_stopped(session)
                        self._drop_preview_tokens(safe)
                    self._tearing_down[safe] = my_event
                    break
            await other.wait()
        try:
            if session is not None:
                await session.discard()
            await asyncio.to_thread(self._purge_disk, safe)
        finally:
            # A fork's allowlist alias ends with the workspace it named — nothing ever
            # looks that key up again. An ordinary conversation never has one.
            self._egress.unshare(key)
            async with self._lock:
                self._tearing_down.pop(safe, None)
            my_event.set()

    def _purge_disk(self, safe: str) -> None:
        workspace = self._work_root / safe
        shutil.rmtree(workspace, ignore_errors=True)
        partial_marker(workspace).unlink(missing_ok=True)
        fork_marker(workspace).unlink(missing_ok=True)
        (self._sealed_root / f"{safe}.tar.enc.gz").unlink(missing_ok=True)

    async def reconcile(self) -> None:
        """Clear what the previous process left behind — see
        :mod:`services.sandbox.reconcile`, which owns the whole of it because it needs
        none of this manager's state."""
        await reconcile_leftovers(self._backend.runtime, self._work_root)

    async def start(self) -> None:
        """Reconcile what the last process left behind, then launch the idle reaper
        and warm the shared container image in the background. A boot status line for
        code execution and previews is logged here (both share this manager's runtime
        + image); the image pull runs off the critical path so app startup is never
        blocked, then logs when ready."""
        await self.reconcile()
        self._reaper = asyncio.create_task(self._reaper_loop())
        runtime = self._backend.runtime
        image = self._backend.image
        logger.info("sandbox: code execution ready (runtime=%s) — warming image %s", runtime, image)
        logger.info("preview: ready (runtime=%s) — shares the sandbox image %s", runtime, image)
        self._warm = asyncio.create_task(self._warm_image())

    async def _warm_image(self) -> None:
        """Pull the latest container image so the first code run / preview doesn't
        pay the pull cost. Best-effort: a failure leaves the image to be pulled
        lazily on first use rather than blocking or crashing startup. Resolves
        ``_image_warmup`` either way, so a session waiting on it (sandbox-01)
        unblocks instead of hanging on a pull that has already finished."""
        self._image_warmup.start_pulling()
        runtime = self._backend.runtime
        if runtime is None:  # disappeared since detection — nothing to warm
            self._image_warmup.mark_done(False)
            return
        image = self._backend.image
        try:
            ready = await ensure_image(runtime, image)
            # The proxy sidecar comes up on the same cold path and is the *first* box a
            # session starts, so an unpulled image there would spend a session's whole
            # bring-up budget on a download. Not part of `ready`: it is a small image, and
            # a failure here is better reported by the create that actually needs it than
            # as "the sandbox image is still downloading".
            await ensure_image(runtime, self._proxy_image)
        except Exception:  # noqa: BLE001 — warming must never crash the background task
            logger.exception("sandbox: image warm-up failed unexpectedly")
            self._image_warmup.mark_done(False)
            return
        if ready:
            logger.info("sandbox: image %s ready", image)
            logger.info("preview: image %s ready", image)
        else:
            logger.warning(
                "sandbox/preview: image %s unavailable — first run will pull it on demand",
                image,
            )
        self._image_warmup.mark_done(ready)

    async def stop(self) -> None:
        for task in (self._reaper, self._warm):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._reaper = None
        self._warm = None
        # Drained, never cancelled: a seal interrupted mid-archive leaves a workspace
        # neither sealed nor plaintext-free. Drained *before* taking the lock, which is
        # what each of them needs to release its own tombstone.
        if self._teardowns:
            await asyncio.gather(*self._teardowns, return_exceptions=True)
        async with self._lock:
            for session in list(self._sessions.values()):
                try:
                    await session.shutdown()
                except Exception:  # noqa: BLE001 — tear the rest down regardless
                    pass
            self._sessions.clear()
            self._previews.clear()

    async def _reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reap_interval)
            try:
                await self._sweep()
            except Exception:  # noqa: BLE001 — the reaper must survive a bad sweep
                pass

    async def _sweep(self) -> None:
        # Reaping seals the workspace; without the vault key we can't seal, and
        # killing the container would strand plaintext on disk. So defer all
        # reaping until the vault is unlocked rather than break encryption-at-rest.
        if not self._vault.is_unlocked:
            return
        now = time.monotonic()
        async with self._lock:
            # A claimed fork is the one thing time may not collect. Reaping an ordinary
            # session is lossless — it seals, the next run restores — which is why the
            # sweep otherwise ignores who holds what, down to a run parked on an
            # unanswered approval. A fork has no archive: reaping one deletes the work.
            stale = [
                key
                for key, s in self._sessions.items()
                if not s.is_busy
                and s.idle_seconds(now) >= self._idle_ttl
                and not (s.ephemeral and s.is_claimed)
            ]
            # Snapshot + detach under the lock (so a concurrent acquire() can't
            # mint a second session onto the same workspace mid-teardown), but the
            # seal itself (tar+gzip+AEAD, potentially slow) runs OUTSIDE the lock,
            # a few at a time — a mass reap must not stall unrelated conversations'
            # acquire()/start_preview()/purge() for the sum of every seal (sandbox-02).
            # A per-key tombstone in `_tearing_down` lets that *same* key's acquire/
            # purge wait for its own teardown specifically, never anyone else's.
            detached = self._detach(stale)

        await self._tear_down(detached)
        await self._seal_orphans()

    async def _seal_orphans(self) -> None:
        """Seal cold plaintext workspaces that belong to no session.

        A workspace directory with no live session and no teardown in flight is the
        residue of a process that died before its own seal ran — and every moment it sits
        there in the clear is a moment the vault's at-rest promise is not being kept.
        This is the only thing that keeps that promise for such a directory: boot cannot,
        the vault being locked then, so the sweep picks it up at the first unlock instead
        (:meth:`_sweep`, which is also why the vault is unlocked here).

        The seal goes through a throwaway session and the ordinary detach path rather
        than a direct :func:`~services.sandbox.seal.seal_workspace` call, so it inherits
        every protection that path carries: the tombstone protocol, so an ``acquire()``
        for that key arriving mid-archive waits instead of minting a session onto the
        directory being read out from under it; that same tombstone's release in a
        ``finally``, whatever the seal does or how it is cancelled;
        :meth:`SandboxSession._seal_and_clear`'s refusal to let a fragment overwrite the
        archive it came from; and the dead process's containers coming off the directory
        (:meth:`SandboxSession._release_mounts`).

        A directory name is all this path has, and the conversation key it was derived
        from cannot be recovered from it — so these sessions get the allowlist directory
        that *name* maps to (``dir_for``, not ``allow_dir``, which would encode an
        already-encoded name). Nothing reads it: an allowlist is mounted by a container,
        and this path starts none. One kind of stranded directory is discarded instead of
        sealed — a fork taken for a delegated agent
        (:func:`~services.sandbox.fork.fork_marker`), whose files copy a parent workspace
        that has its own archive, under a key no conversation will ever open again — and
        it goes through this same leg regardless, because its containers may well still
        be holding the mount."""
        orphans: list[_Detached] = []
        async with self._lock:
            for safe in self._orphan_keys()[:_ORPHAN_SEALS_PER_SWEEP]:
                event = asyncio.Event()
                self._tearing_down[safe] = event
                fork = fork_marker(self._work_root / safe).exists()
                session = self._new_session(safe, self._egress.dir_for(safe), ephemeral=fork)
                orphans.append((safe, session, event))
        if not orphans:
            return
        logger.info(
            "sandbox: collecting %d workspace(s) left behind by an unclean shutdown",
            len(orphans),
        )
        await self._tear_down(orphans)

    def _orphan_keys(self) -> list[str]:
        """Workspace dirs under ``_work_root`` that no session and no teardown owns.
        Called under the manager lock — one directory listing, so the two maps it
        reads cannot shift underneath the answer."""
        if not self._work_root.exists():
            return []
        return [
            path.name
            for path in sorted(self._work_root.iterdir())
            if path.is_dir()
            and path.name.startswith("s")  # `safe_key`'s prefix — never a scratch dir
            and path.name not in self._sessions
            and path.name not in self._tearing_down
        ]
