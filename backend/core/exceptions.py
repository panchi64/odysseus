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
