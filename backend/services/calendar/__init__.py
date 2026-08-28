"""The calendar capability (`CAL-1..3`).

- ``service`` — calendars + events, and the window read that expands recurrences.
- ``recurrence`` — RFC 5545 ``RRULE`` expansion, done in the event's own time zone.
- ``ics`` — import/export of standard calendar files (`CAL-2`).
- ``caldav`` — sync against a remote CalDAV collection (`CAL-2`).
- ``nl`` — natural-language event entry (`CAL-3`).
"""

from __future__ import annotations

from services.calendar.service import (
    CalendarService,
    CalendarView,
    EventView,
    OccurrenceView,
)

__all__ = ["CalendarService", "CalendarView", "EventView", "OccurrenceView"]
