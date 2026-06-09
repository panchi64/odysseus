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
