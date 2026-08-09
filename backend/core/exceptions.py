"""The application exception hierarchy.

Lower layers raise these domain errors — never transport-layer ``HTTPException``.
``app.py`` maps them to HTTP responses (wired as the error-handling layer lands).
"""

from __future__ import annotations


class OdysseusError(Exception):
    """Base for all application errors."""


class NotFoundError(OdysseusError):
    """A requested resource does not exist."""


class PermissionDeniedError(OdysseusError):
    """The operator is not permitted to perform this action."""


class ApprovalRequiredError(OdysseusError):
    """A sensitive action needs explicit operator approval before it runs."""


class DegradedCapabilityError(OdysseusError):
    """An optional capability is unavailable; the caller should degrade gracefully."""


class SpanEditError(OdysseusError):
    """A targeted (surgical) edit's ``old_text`` did not match exactly one span — either
    absent (``occurrences == 0``) or ambiguous (``occurrences > 1``). Carries the count so
    the caller can phrase a precise retry for the model. Raised by
    :func:`core.text.replace_unique`, the one implementation behind every surgical edit."""

    def __init__(self, occurrences: int) -> None:
        self.occurrences = occurrences
        super().__init__(
            "old_text was not found" if occurrences == 0
            else f"old_text matched {occurrences} spans"
        )


class DocumentSpanError(SpanEditError):
    """A :class:`SpanEditError` on a document body (`DOC-2`). Its own type so the document
    routes/tool keep mapping it to their existing phrasing unchanged."""


class SkillSpanError(SpanEditError):
    """A :class:`SpanEditError` on a skill's ``SKILL.md`` body (`SKILL-3`)."""


class SkillValidationError(OdysseusError):
    """A skill bundle violates the Agent Skills standard. Carries the offending ``field`` so
    the operator is told *which* part of their bundle to fix, not merely that it failed."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


class ModelLoadError(OdysseusError):
    """An inference server refused a request because it couldn't bring the model
    up (e.g. an on-demand cold-load that failed, or a concurrent-load race). The
    message carries an operator-actionable hint — the fix is engine-side (pre-load
    the model, let the server hold more than one), not ours."""


class RateLimitedError(OdysseusError):
    """An action was refused because the caller exceeded its allowed rate. Carries
    the number of seconds to wait before retrying so the route can surface a
    ``Retry-After`` (uploads are rate-limited to protect the service, `UP-4`)."""

    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"rate limit exceeded; retry in {retry_after_s:.1f}s")
        self.retry_after_s = retry_after_s


class SSRFError(OdysseusError):
    """An outbound request was refused because its target resolves to a
    non-public address (loopback, private, link-local, cloud metadata) or uses a
    disallowed scheme — a server-side request forgery guard."""


class SchemaMigrationError(OdysseusError):
    """Bringing the DB to head failed because its recorded revision and/or its
    physical schema disagree with the migration scripts — typically a dev DB left
    stamped at a deleted or regenerated migration. Carries an operator-actionable
    diagnostic (DB path, stamped vs head revision) in place of the raw Alembic /
    SQLAlchemy traceback; raised at startup, aborting the boot."""


class WebFetchError(OdysseusError):
    """A web fetch failed for a single URL in a way the caller can retry against a
    different source — a network error, a non-OK status, too many redirects, or a
    page with no extractable content. Distinct from a missing capability."""


class ServingError(OdysseusError):
    """A local model-serving action failed in a way the operator can act on — a
    download that couldn't fetch the repo, an engine runtime that wouldn't install
    or start, or a request against an engine that isn't available on this host.
    Carries a plain-language message; never contains a secret (local servers have none)."""


class ServingUnavailableError(ServingError):
    """A serving request can't be satisfied by the host's current state — the engine
    isn't available/supported here, or there isn't enough memory to fit the model
    alongside what's already running. A precondition the operator resolves (free room,
    pick another engine), not an engine/upstream failure — so routes map it to 409,
    distinct from the 502 a genuine download/launch failure gets."""
