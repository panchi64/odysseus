"""Claim-level attribution: the sources a turn retained, and the triples read off them.

Three things live here, and they are together because each is only meaningful about the
next:

- :func:`sources_from_results` — the **inventory**: which sources a turn actually
  retained, read back off its persisted tool results. This is what makes the whole
  feature retroactive. Tool results are persisted structurally (``core/serde``), so the
  inventory of a thread that finished last month is the same inventory the live turn had.
- :class:`Claim` — one claim → source → passage triple, including the ones with no
  passage, which are the point rather than the failure.
- :class:`ConversationAttributions` — where a turn's triples are stored, sealed under the
  vault and keyed by the assistant turn's branch node.

The model call that produces the triples is **not** here: it is ``agent/attribution.py``,
one layer up, because composing a model call sits above the capability it reads from.

**Why the inventory reads structure rather than asking the result.** A live tool result
is a :class:`~core.citations.Citable` and can be asked what it cites; the same result
read back out of the database is the JSON that ``core.serde.jsonable`` wrote, and JSON
has no methods. Rather than keep two readers — one that asks and one that parses,
guaranteed to drift the day a producer changes — everything goes through ``jsonable``
first and one parser reads the structure both paths share. What that costs is a parser
that knows the *shape* of a citable batch; what it buys is that a cold read and a warm
one cannot disagree, which is the only property this feature's retroactivity rests on.
``tests/test_attribution_sources.py`` pins the parser against each producer's own
``citations()``, so a producer that changes shape fails there rather than quietly
returning fewer sources.

**The text matters as much as the citation.** A citation carries an identity and a
snippet; the extraction needs what the model actually *read*, which for a fetched page is
the page body and for a search hit is only ever the snippet. So a source record is a
citation plus its fullest retained text, unfenced — the untrusted markers are how the
*model* was handed the text, and the reader gets its own fence built fresh.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.citations import ENGAGEMENT_ORDER, Citation, Engagement
from core.db import in_session
from core.serde import as_utc, jsonable
from core.untrusted import unwrap_untrusted
from core.vault import Vault, VaultError, VaultLocked
from models._fields import new_id, utcnow
from models.attribution import MessageAttribution

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceRecord:
    """One source a turn retained, and the text it was retained as.

    ``citation`` is the identity the rest of the product already folds and renders by;
    ``text`` is what the model had in front of it from that source — a page body, a
    corpus passage, or (for a hit the model never opened) the search snippet and nothing
    more. The split matters: an extraction handed only snippets can ground almost
    nothing, and one handed only bodies loses every source that was merely listed.
    """

    citation: Citation
    text: str

    @property
    def key(self) -> str:
        return self.citation.key


def _text_of(value: Any) -> str:
    """One string field of a persisted result, unwrapped and stripped.

    ``unwrap_untrusted`` rather than ``unfence`` because the producers here are of both
    kinds: a fetched page carries its own preamble with its fence, a search snippet and a
    corpus passage share one preamble emitted at the top of their batch. The wider reader
    handles both and leaves text that was never wrapped alone.
    """
    return unwrap_untrusted(value).strip() if isinstance(value, str) else ""


def _search_hits(result: Mapping[str, Any]) -> list[SourceRecord]:
    """A web search batch — hits the model saw the title and snippet of, nothing more."""
    out: list[SourceRecord] = []
    for row in result.get("results") or []:
        if not isinstance(row, Mapping):
            continue
        url = row.get("url")
        if not isinstance(url, str) or not url:
            continue
        snippet = _text_of(row.get("snippet"))
        title = row.get("title")
        out.append(
            SourceRecord(
                citation=Citation(
                    url=url,
                    title=title if isinstance(title, str) else None,
                    snippet=snippet or None,
                    published=(
                        row.get("published") if isinstance(row.get("published"), str) else None
                    ),
                    engagement="listed",
                ),
                text=snippet,
            )
        )
    return out


def _corpus_passages(result: Mapping[str, Any]) -> list[SourceRecord]:
    """A corpus retrieve batch — the operator's own indexed knowledge. A passage's text
    *is* the result, so every one of these is ``read``."""
    out: list[SourceRecord] = []
    for row in result.get("passages") or []:
        if not isinstance(row, Mapping):
            continue
        source_id, ref = row.get("source"), row.get("ref")
        if not isinstance(ref, str) or not ref:
            # The locator is a corpus citation's whole identity; a hit without one is
            # dropped for the same reason `tools/corpus.py` drops it, and here rather
            # than at `Citation`, where the raise would cost the whole batch.
            continue
        text = _text_of(row.get("text"))
        out.append(
            SourceRecord(
                citation=Citation(
                    kind="corpus",
                    title=ref,
                    source_id=source_id if isinstance(source_id, str) else None,
                    ref=ref,
                    snippet=text or None,
                    engagement="read",
                ),
                text=text,
            )
        )
    return out


def _fetched_page(result: Mapping[str, Any]) -> list[SourceRecord]:
    """A rendered page — one source, and the one case where the retained text is the
    whole body rather than a snippet."""
    url = result.get("url")
    if not isinstance(url, str) or not url:
        return []
    title = result.get("title")
    return [
        SourceRecord(
            citation=Citation(
                url=url,
                title=title if isinstance(title, str) else None,
                engagement="read",
            ),
            text=_text_of(result.get("content")),
        )
    ]


def _records(result: Any) -> list[SourceRecord]:
    """The sources one tool result names, read off the structure it persists as.

    Batch shapes are tested before the single-page one because a batch is itself a
    mapping and would otherwise be read as a page with no url and dropped.
    """
    if not isinstance(result, Mapping):
        return []
    if isinstance(result.get("results"), list):
        return _search_hits(result)
    if isinstance(result.get("passages"), list):
        return _corpus_passages(result)
    if isinstance(result.get("content"), str):
        return _fetched_page(result)
    return []


def _stronger(left: SourceRecord, right: SourceRecord) -> SourceRecord:
    """The better of two sightings of one source: the higher rung on the engagement
    ladder, and within a tie the one that retained more text.

    A page a search listed and a fetch then opened is the case this exists for — keeping
    the snippet would hand the extraction 300 characters of a page it has the whole body
    of, and every claim from the second half of that page would come back ungrounded.
    """
    ranks = (
        ENGAGEMENT_ORDER.get(left.citation.engagement, 0),
        ENGAGEMENT_ORDER.get(right.citation.engagement, 0),
    )
    if ranks[1] != ranks[0]:
        return right if ranks[1] > ranks[0] else left
    return right if len(right.text) > len(left.text) else left


def sources_from_results(results: Iterable[Any]) -> list[SourceRecord]:
    """Every source a turn's tool results named, folded by identity, in first-seen order.

    ``results`` are tool results **already coerced by** :func:`core.serde.jsonable` — the
    shape they persist as, which is the shape the retroactive path reads back. A live
    caller coerces them the same way rather than passing the typed objects, so both paths
    run the one parser (see this module's docstring).

    Anything that names no source contributes nothing, which is most tool results: this
    is additive and never load-bearing, exactly as the citation stream is.
    """
    folded: dict[str, SourceRecord] = {}
    for result in results:
        for record in _records(jsonable(result)):
            key = record.key
            if not key:
                continue
            existing = folded.get(key)
            folded[key] = record if existing is None else _stronger(existing, record)
    return list(folded.values())


#: How sure the reader is that the passage says what the claim says. Ordered loosely, but
#: never compared — it is reported, not thresholded, because the operator is the one
#: deciding whether to go and look.
Confidence = ("high", "medium", "low")


@dataclass(frozen=True)
class Claim:
    """One claim the answer made, and the source it was — or was not — grounded in.

    ``grounded`` is not redundant with ``passage``: a claim can name a source and still
    have no passage in it, which is the single most valuable row this feature produces —
    the answer pointed at a page and the page does not say it. That row keeps its source
    fields so the operator can go and look, and reads ``grounded=False`` so the surface
    can lead with it rather than bury it among the ones that checked out.

    ``offset`` is where the claim's text begins in the answer, already **validated**
    against the answer by the caller — an offset that did not land is dropped and the
    claim kept, because a highlight on the wrong sentence is worse than no highlight.
    """

    claim: str
    grounded: bool
    source_key: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    source_kind: str | None = None
    passage: str | None = None
    confidence: str = "low"
    offset: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "grounded": self.grounded,
            "source_key": self.source_key,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "source_kind": self.source_kind,
            "passage": self.passage,
            "confidence": self.confidence,
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> Claim:
        """Read one stored claim back, tolerating a row written by an older shape.

        Degrades rather than raises, for the same reason ``services/answers.parse_answer``
        does: this runs over rows stored before whatever the current shape is, and an
        unreadable one must cost the operator a claim, not the panel.
        """
        return cls(
            claim=str(row.get("claim") or ""),
            grounded=bool(row.get("grounded")),
            source_key=row.get("source_key") or None,
            source_title=row.get("source_title") or None,
            source_url=row.get("source_url") or None,
            source_kind=row.get("source_kind") or None,
            passage=row.get("passage") or None,
            confidence=str(row.get("confidence") or "low"),
            offset=row.get("offset") if isinstance(row.get("offset"), int) else None,
        )


@dataclass(frozen=True)
class MessageClaims:
    """One assistant turn's extraction, as every reader of it sees it."""

    message_id: str
    claims: list[Claim]
    extracted_at: datetime


def cited_citations(claims: Sequence[Claim], sources: Sequence[SourceRecord]) -> list[Citation]:
    """The sources a grounded claim genuinely rests on, as ``cited`` citations.

    This is the first producer of that rung anywhere in the product. Search emits
    ``listed`` and fetch and corpus emit ``read``, and until now nothing could honestly
    emit ``cited`` — the tool boundary does not know what the answer ended up resting on,
    which is precisely the gap the ladder was written around. A claim that an independent
    reader matched to a passage in a source *is* that knowledge, so the rung is minted
    here and nowhere else.

    One citation per source, not per claim: the ladder is about the source, and a page
    three claims rest on is one row on the operator's Sources panel with a stronger rung,
    not three rows. ``snippet`` carries the passage of the first claim that grounded it —
    the panel's reason for showing the rung at all.
    """
    by_key = {record.key: record for record in sources}
    out: list[Citation] = []
    seen: set[str] = set()
    for claim in claims:
        key = claim.source_key
        if not claim.grounded or not key or key in seen:
            continue
        record = by_key.get(key)
        if record is None:
            continue
        seen.add(key)
        base = record.citation
        out.append(
            Citation(
                url=base.url,
                title=base.title,
                snippet=claim.passage or base.snippet,
                published=base.published,
                retrieved_at=base.retrieved_at,
                kind=base.kind,
                engagement="cited",
                source_id=base.source_id,
                ref=base.ref,
            )
        )
    return out


def highest_engagement(records: Iterable[SourceRecord]) -> Engagement:  # pragma: no cover
    """The strongest rung an inventory reached — a convenience for callers reporting on
    one, never a decision input."""
    best: Engagement = "listed"
    for record in records:
        if ENGAGEMENT_ORDER.get(record.citation.engagement, 0) > ENGAGEMENT_ORDER[best]:
            best = record.citation.engagement
    return best


class ConversationAttributions:
    """Reads and writes one assistant turn's claim triples. Owner-scoped; vault-sealed.

    Sealed because a claim is a verbatim span of the answer and a passage a verbatim span
    of something the operator read — the same content the message blob beside it is sealed
    for. A locked vault degrades to *no* attribution rather than to an error, for the
    reason the task list does: this is a reading of the thread, not the thread.
    """

    def __init__(self, db_engine: Engine, vault: Vault) -> None:
        self._db = db_engine
        self._vault = vault

    async def for_message(
        self, owner_id: str, conversation_id: str, message_id: str
    ) -> MessageClaims | None:
        rows = await self.for_conversation(owner_id, conversation_id)
        return next((row for row in rows if row.message_id == message_id), None)

    async def for_conversation(self, owner_id: str, conversation_id: str) -> list[MessageClaims]:
        """Every extraction stored for a thread, oldest first.

        Returned whole rather than per message because the panel draws the thread: one
        round trip, and the client joins by ``message_id`` against turns it already has.
        """

        def work(session: Session) -> list[tuple[str, str, datetime]]:
            rows = session.exec(
                select(MessageAttribution)
                .where(MessageAttribution.owner_id == owner_id)
                .where(MessageAttribution.conversation_id == conversation_id)
                .order_by(MessageAttribution.extracted_at)
            ).all()
            return [(row.message_id, row.claims_enc, row.extracted_at) for row in rows]

        out: list[MessageClaims] = []
        for message_id, sealed, extracted_at in await in_session(self._db, work):
            try:
                rows = json.loads(self._vault.decrypt_str(sealed))
            except (VaultLocked, VaultError):
                logger.debug("attribution unreadable for %s: vault locked", conversation_id)
                return []
            except (TypeError, ValueError):
                logger.warning("attribution unreadable for message %s", message_id)
                continue
            out.append(
                MessageClaims(
                    message_id=message_id,
                    claims=[Claim.from_dict(row) for row in rows if isinstance(row, Mapping)],
                    extracted_at=as_utc(extracted_at),
                )
            )
        return out

    async def replace(
        self, owner_id: str, conversation_id: str, message_id: str, claims: Sequence[Claim]
    ) -> bool:
        """Store ``claims`` for one turn; ``False`` when the vault was locked and nothing
        was written.

        Replaces rather than appends: a re-run of the pass over the same answer supersedes
        whatever the last one read, and two readings of one answer sitting side by side
        would be two panels disagreeing with no way to tell which is current.
        """
        try:
            sealed = self._vault.encrypt_str(json.dumps([claim.as_dict() for claim in claims]))
        except (VaultLocked, VaultError):
            logger.debug("attribution not stored for %s: vault locked", conversation_id)
            return False

        def work(session: Session) -> None:
            row = session.exec(
                select(MessageAttribution)
                .where(MessageAttribution.owner_id == owner_id)
                .where(MessageAttribution.message_id == message_id)
            ).first()
            if row is None:
                row = MessageAttribution(
                    id=new_id(),
                    owner_id=owner_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    claims_enc=sealed,
                )
            else:
                row.claims_enc = sealed
                row.conversation_id = conversation_id
            row.extracted_at = utcnow()
            session.add(row)

        await in_session(self._db, work)
        return True

    async def delete_for_conversation(self, owner_id: str, conversation_id: str) -> None:
        """Drop a thread's attributions when the thread goes.

        A claim quotes the answer and a passage quotes what the operator read, so leaving
        these behind would keep a description of a deleted conversation on disk — the same
        reason the delete path already purges the task list and the View history. Works
        while the vault is locked: it only destroys.
        """

        def work(session: Session) -> None:
            for row in session.exec(
                select(MessageAttribution)
                .where(MessageAttribution.owner_id == owner_id)
                .where(MessageAttribution.conversation_id == conversation_id)
            ).all():
                session.delete(row)

        await in_session(self._db, work)
