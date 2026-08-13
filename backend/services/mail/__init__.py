"""The mail capability (`EMAIL-1..5`).

One facade (:class:`~services.mail.service.MailService`) over a pluggable provider seam
(:class:`~services.mail.transport.MailTransport`), with the AI parts — triage (`EMAIL-2`)
and the writing-style profile (`EMAIL-3`) — layered on top of the cache rather than the
network. See ``services/mail/CLAUDE.md``.
"""

from __future__ import annotations

from .errors import MailAuthError, MailError, MailUnavailableError, MailUnsupportedError
from .models import (
    AccountSpec,
    MailAddress,
    MailBody,
    MailFolder,
    MailHeader,
    OutgoingMail,
    TransportCapabilities,
)
from .transport import MailTransport, WatchableTransport

__all__ = [
    "AccountSpec",
    "MailAddress",
    "MailAuthError",
    "MailBody",
    "MailError",
    "MailFolder",
    "MailHeader",
    "MailTransport",
    "MailUnavailableError",
    "MailUnsupportedError",
    "OutgoingMail",
    "TransportCapabilities",
    "WatchableTransport",
]
