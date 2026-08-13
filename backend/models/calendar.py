"""Calendar schema (`CAL-*`) — **reserved stub**, filled in by the calendar track (T2).

See ``models/mail.py`` for why the module is imported before it declares anything.

For the track that fills this in: store the recurrence rule as its RFC 5545 RRULE string and
expand it at read time rather than materializing occurrences, and keep the event's IANA time
zone alongside its timestamps so an all-day or recurring event survives a DST boundary.
"""

from __future__ import annotations
