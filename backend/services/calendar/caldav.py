"""CalDAV sync — reconciling a local calendar with a remote collection (`CAL-2`).

A CalDAV object *is* an ICS document, so this module owns none of the parsing: it moves
bytes between the server and `ics.py`, and every merge decision is the same ``UID`` match
an ICS import already makes.

Three things shape the implementation:

- **The `caldav` package is synchronous.** Every call is a blocking HTTP round-trip, so the
  whole remote conversation runs inside ``anyio.to_thread`` — and in as few hops as
  possible (one thread for the pull, one for the push) rather than a hop per request.
- **The server URL is operator-supplied and therefore untrusted.** It is SSRF-checked
  (`core/ssrf`) before every sync, on the same principle as web fetch: a URL the system
  will connect to on someone's behalf is re-validated at use time, not trusted from when
  it was saved.
- **Credentials never leave the vault in the clear.** They are decrypted into locals for
  the duration of one sync and are never logged, never returned, and never written back.

**Scope.** Sync is *pull-authoritative with a first-time push*: remote changes win on
conflict (the server is the shared copy), local events that have never been pushed are
uploaded, and an event the server no longer has is removed locally. A local **deletion** is
not propagated — knowing a row was deleted rather than never created needs a tombstone the
schema doesn't carry, and inventing a heuristic here would silently delete the operator's
data off a server shared with other clients.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import anyio.to_thread

from core.ssrf import assert_public_url
from services.calendar.ics import export_ics, parse_ics
from services.calendar.service import CalendarService, EventView

logger = logging.getLogger(__name__)

# The remote is not asked for an unbounded object list in one breath; a collection larger
# than this is truncated with a log line rather than held whole in memory.
MAX_REMOTE_OBJECTS = 5000


class RemoteObject(Protocol):
    """The shape this module needs from a `caldav` calendar object — its ICS bytes, where
    it lives, and the server's version stamp."""

    @property
    def data(self) -> str: ...
    @property
    def url(self) -> object: ...
    @property
    def etag(self) -> str | None: ...


class RemoteCalendar(Protocol):
    """The shape this module needs from a `caldav` collection. Narrow on purpose: it is
    what lets a test drive the whole reconcile without a server (and what keeps the
    third-party client from leaking into the merge logic)."""

    def events(self) -> Sequence[RemoteObject]: ...
    def save_event(self, ical: str) -> RemoteObject: ...


Connector = Callable[[str, str | None, str | None], RemoteCalendar]


@dataclass(frozen=True)
class SyncResult:
    """What one reconcile did, in the operator's terms."""

    pulled_created: int = 0
    pulled_updated: int = 0
    pushed: int = 0
    removed_locally: int = 0
    skipped: int = 0


def connect(url: str, username: str | None, password: str | None) -> RemoteCalendar:
    """Open the remote collection. Blocking — always called through a worker thread.

    Imported lazily: ``caldav`` pulls a full HTTP stack, and a system whose operator has no
    remote calendar shouldn't pay for it at boot.
    """
    import caldav

    client = caldav.DAVClient(url=url, username=username, password=password)
    return client.calendar(url=url)  # type: ignore[return-value]


class CalDavSync:
    """Reconciles one calendar against its remote collection.

    ``connector`` is injected so the reconcile logic is testable without a server — the
    default opens a real `caldav` client.
    """

    def __init__(self, calendars: CalendarService, *, connector: Connector = connect) -> None:
        self._calendars = calendars
        self._connector = connector

    async def sync(self, owner_id: str, calendar_id: str) -> SyncResult:
        """Pull the remote collection into the local calendar, then push anything local
        that has never been uploaded. Raises :class:`ValueError` when the calendar isn't
        bound to a server and :class:`core.exceptions.SSRFError` when its URL resolves
        somewhere the system refuses to reach."""
        calendar = await self._calendars.get_calendar(owner_id, calendar_id)
        url, username, password = await self._calendars.caldav_credentials(owner_id, calendar_id)
        await assert_public_url(url)

        remote = await anyio.to_thread.run_sync(self._read_remote, url, username, password)
        result = await self._apply_remote(owner_id, calendar_id, remote)

        if not calendar.read_only:
            result = await self._push_local(owner_id, calendar_id, url, username, password, result)

        await self._calendars.mark_synced(owner_id, calendar_id)
        return result

    # --- the remote conversation (blocking; runs in a worker thread) --------

    def _read_remote(
        self, url: str, username: str | None, password: str | None
    ) -> list[tuple[str, str | None, str | None]]:
        """Every object on the collection as ``(ics, href, etag)``. One thread hop covers
        connect *and* list, because each is its own blocking round-trip."""
        collection = self._connector(url, username, password)
        objects: list[tuple[str, str | None, str | None]] = []
        for index, obj in enumerate(collection.events()):
            if index >= MAX_REMOTE_OBJECTS:
                logger.warning(
                    "calendar: remote collection exceeds %d objects; truncating the sync",
                    MAX_REMOTE_OBJECTS,
                )
                break
            objects.append((_data(obj), _href(obj), _etag(obj)))
        return objects

    def _write_remote(
        self,
        url: str,
        username: str | None,
        password: str | None,
        documents: Sequence[tuple[str, str]],
    ) -> list[tuple[str, str | None, str | None]]:
        """Upload ``(event id, ics)`` pairs, returning ``(event id, href, etag)`` for the
        ones the server accepted. A single refused upload is logged and skipped — one
        event the server dislikes must not abort the rest of the push."""
        collection = self._connector(url, username, password)
        stamped: list[tuple[str, str | None, str | None]] = []
        for event_id, document in documents:
            try:
                saved = collection.save_event(document)
            except Exception:  # noqa: BLE001 — any server-side refusal is per-event
                logger.warning("calendar: remote refused an event during push", exc_info=True)
                continue
            stamped.append((event_id, _href(saved), _etag(saved)))
        return stamped

    # --- merge (async; owns the DB) ----------------------------------------

    async def _apply_remote(
        self,
        owner_id: str,
        calendar_id: str,
        remote: Sequence[tuple[str, str | None, str | None]],
    ) -> SyncResult:
        """Merge the server's objects in, then drop local events the server no longer has.

        An object whose ``etag`` matches what we already recorded is **not re-parsed** —
        that is the whole point of an etag, and it keeps a routine sync over a large
        calendar close to free.
        """
        created = updated = skipped = 0
        seen_uids: set[str] = set()

        for document, href, etag in remote:
            for entry in parse_ics(document):
                if entry.uid is None:
                    skipped += 1
                    continue
                seen_uids.add(entry.uid)
                existing = await self._calendars.find_by_uid(owner_id, calendar_id, entry.uid)
                if existing is not None and etag is not None and existing.remote_etag == etag:
                    continue
                try:
                    if existing is None:
                        await self._calendars.create_event(
                            owner_id,
                            calendar_id,
                            title=entry.title,
                            starts_at=entry.starts_at,
                            ends_at=entry.ends_at,
                            timezone=entry.timezone,
                            all_day=entry.all_day,
                            description=entry.description,
                            location=entry.location,
                            rrule=entry.rrule,
                            uid=entry.uid,
                            remote_href=href,
                            remote_etag=etag,
                        )
                        created += 1
                    else:
                        await self._calendars.update_event(
                            owner_id,
                            existing.id,
                            title=entry.title,
                            starts_at=entry.starts_at,
                            ends_at=entry.ends_at,
                            timezone=entry.timezone,
                            all_day=entry.all_day,
                            description=entry.description or "",
                            location=entry.location or "",
                            rrule=entry.rrule,
                            clear_rrule=entry.rrule is None,
                            remote_href=href,
                            remote_etag=etag,
                        )
                        updated += 1
                except ValueError:
                    logger.warning("calendar: remote event rejected locally", exc_info=True)
                    skipped += 1

        removed = await self._remove_vanished(owner_id, calendar_id, seen_uids)
        return SyncResult(
            pulled_created=created,
            pulled_updated=updated,
            removed_locally=removed,
            skipped=skipped,
        )

    async def _remove_vanished(
        self, owner_id: str, calendar_id: str, seen_uids: set[str]
    ) -> int:
        """Delete local events that **came from** this server and are no longer on it. An
        event with no ``remote_href`` has never been pushed, so its absence upstream says
        nothing about it — it is left alone."""
        removed = 0
        for event in await self._calendars.list_events(owner_id, calendar_id):
            if event.remote_href and event.uid not in seen_uids:
                await self._calendars.delete_event(owner_id, event.id)
                removed += 1
        return removed

    async def _push_local(
        self,
        owner_id: str,
        calendar_id: str,
        url: str,
        username: str | None,
        password: str | None,
        result: SyncResult,
    ) -> SyncResult:
        """Upload local events the server has never seen, and record where they landed so
        the next sync recognizes them as remote-backed rather than pushing them twice."""
        pending: list[tuple[str, EventView]] = [
            (event.id, event)
            for event in await self._calendars.list_events(owner_id, calendar_id)
            if not event.remote_href
        ]
        if not pending:
            return result

        documents = [
            (event_id, export_ics([event]).decode()) for event_id, event in pending
        ]
        stamped = await anyio.to_thread.run_sync(
            self._write_remote, url, username, password, documents
        )
        for event_id, href, etag in stamped:
            if href is None and etag is None:
                continue  # nothing to record — `None` already means "leave it alone"
            await self._calendars.update_event(
                owner_id, event_id, remote_href=href, remote_etag=etag
            )
        return SyncResult(
            pulled_created=result.pulled_created,
            pulled_updated=result.pulled_updated,
            pushed=len(stamped),
            removed_locally=result.removed_locally,
            skipped=result.skipped,
        )


def _data(obj: RemoteObject) -> str:
    raw = obj.data
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def _href(obj: RemoteObject) -> str | None:
    url = getattr(obj, "url", None)
    return str(url) if url else None


def _etag(obj: RemoteObject) -> str | None:
    try:
        etag = obj.etag
    except Exception:  # noqa: BLE001 — some servers omit it; sync must not depend on it
        return None
    return str(etag) if etag else None
