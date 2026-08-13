"""Calendar prompts — the utility-model call behind natural-language event entry.

One narrow instruction, consumed by the chassis (`services/calendar/nl.py`) and never
shown to the operator verbatim: the parse is turned into a structured draft they confirm.
"""

from __future__ import annotations

# Turns "lunch Friday 1pm" into a structured event (`CAL-3`). The instruction is
# deliberately blunt about the two things a model gets wrong here: inventing detail the
# operator didn't say, and answering in prose instead of filling the fields. Relative
# dates are resolved against a "now" the caller supplies, so the prompt itself carries no
# notion of the current date.
CALENDAR_NL_INSTRUCTIONS = (
    "You turn a short phrase into a calendar event. You are given the current date and "
    "time and the operator's time zone; resolve every relative reference (today, "
    "tomorrow, Friday, next week, this evening) against them, always choosing the next "
    "such moment in the future unless the phrase clearly says otherwise.\n"
    "\n"
    "Fill the fields from what the phrase actually says. Write times as local wall-clock "
    "time in the operator's zone, with no offset or 'Z' suffix. Give the event a short, "
    "natural title — the activity itself, not a restatement of the phrase, and never "
    "with the date or time in it. Set an end time only when one is stated or clearly "
    "implied by a duration; otherwise leave it empty. Set all_day only for a phrase that "
    "names no time at all. Set location only when a place is named. Set rrule only when "
    "the phrase describes a repetition, as a bare RFC 5545 rule such as "
    "FREQ=WEEKLY;BYDAY=FR — never with an RRULE: prefix.\n"
    "\n"
    "Invent nothing. If the phrase does not name something, leave that field empty."
)
