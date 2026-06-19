"""Shared HTTP-layer helpers for the routers.

Small transport concerns that more than one surface needs, kept in one place so a
hardening fix lands everywhere at once rather than per-copy. The first is the
``Content-Disposition`` builder both the artifacts and uploads routes serve files with.
"""

from __future__ import annotations

import re
from urllib.parse import quote


def content_disposition(filename: str, *, inline: bool, fallback: str = "file") -> str:
    """A safe ``Content-Disposition`` for an untrusted/operator-provided filename.

    The visible token is reduced to a conservative ASCII set (so a ``"`` or newline
    can't break out of the header or inject another), and the full name rides in the
    RFC 5987 ``filename*`` field, percent-encoded. ``inline`` picks the disposition
    (``inline`` for in-browser preview, ``attachment`` for download); ``fallback`` names
    the token when the filename has no safe characters."""
    ascii_token = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or fallback
    disposition = "inline" if inline else "attachment"
    return f"{disposition}; filename=\"{ascii_token}\"; filename*=UTF-8''{quote(filename, safe='')}"
