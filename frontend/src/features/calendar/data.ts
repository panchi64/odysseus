import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type { Calendar, CalendarEvent, RecurrenceRule } from "./model";

/* ── Backend DTOs → seam types ────────────────────────────────────────────── */

interface CalendarOut {
  id: string;
  name: string;
  tone: Calendar["tone"];
  synced: boolean;
  syncUrl: string | null;
  readOnly: boolean;
  lastSyncedAt: string | null;
}

/** One dated instance of an event — what the grid renders. */
interface OccurrenceOut {
  occurrenceId: string;
  eventId: string;
  calendarId: string;
  title: string;
  start: string;
  end: string;
  timezone: string;
  allDay: boolean;
  recurring: boolean;
  description: string | null;
  location: string | null;
  rrule: string | null;
}

interface DraftOut {
  title: string;
  start: string;
  end: string;
  timezone: string;
  allDay: boolean;
  description: string | null;
  location: string | null;
  rrule: string | null;
}

/** The aggregate of one "sync everything" pass — the backend decides which calendars are
 *  remote and what one press of SYNC means across them. */
interface SyncAllOut {
  calendars: number;
  changed: number;
  failed: string[];
}

/** The operator's own IANA zone, read from the browser. Sent with every write so the
 *  backend stores an event against the zone it was created in — capturing context, not
 *  deciding anything. */
function browserZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** The RFC 5545 rule the backend stores, shown as the coarse choice the UI offers.
 *  Anything the picker can't express reads as `custom` — never as `none`, which would
 *  tell the operator a repeating event doesn't repeat. */
function toRecurrence(rrule: string | null): RecurrenceRule {
  if (!rrule) return "none";
  const rule = rrule.toUpperCase();
  const byday = /BYDAY=([A-Z,]+)/.exec(rule)?.[1];
  if (rule.includes("FREQ=DAILY")) return byday ? "custom" : "daily";
  if (rule.includes("FREQ=WEEKLY")) {
    if (byday === "MO,TU,WE,TH,FR") return "weekdays";
    return byday ? "custom" : "weekly";
  }
  if (rule.includes("FREQ=MONTHLY")) return byday ? "custom" : "monthly";
  return "custom";
}

/** The inverse, for a write. `custom` is not offered on the way in — the picker can only
 *  produce the four rules below — so it maps to no rule at all. */
function toRrule(recurrence: RecurrenceRule | undefined): string | undefined {
  switch (recurrence) {
    case "daily":
      return "FREQ=DAILY";
    case "weekly":
      return "FREQ=WEEKLY";
    case "monthly":
      return "FREQ=MONTHLY";
    case "weekdays":
      return "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR";
    default:
      return undefined;
  }
}

/** An occurrence carries its instance id as `id`: opaque to the screen, decoded here (the
 *  only place that talks to the backend) when a delete has to name one instance of a
 *  series. */
function toEvent(dto: OccurrenceOut): CalendarEvent {
  return {
    id: dto.occurrenceId,
    calendarId: dto.calendarId,
    title: dto.title,
    start: dto.start,
    end: dto.end,
    location: dto.location ?? undefined,
    description: dto.description ?? undefined,
    allDay: dto.allDay,
    recurrence: toRecurrence(dto.rrule),
    recurring: dto.recurring,
  };
}

function toCalendar(dto: CalendarOut): Calendar {
  return {
    id: dto.id,
    name: dto.name,
    tone: dto.tone,
    synced: dto.synced,
    syncUrl: dto.syncUrl ?? undefined,
  };
}

/** Split an occurrence id back into the event it belongs to and the instant it falls on. */
function splitOccurrenceId(id: string): { eventId: string; start: string } {
  const at = id.indexOf("@");
  return at === -1
    ? { eventId: id, start: "" }
    : { eventId: id.slice(0, at), start: id.slice(at + 1) };
}

/* ── Calendars (the seam) ─────────────────────────────────────────────────── */

const [calendarTick, setCalendarTick] = createSignal(0);

async function fetchCalendars(): Promise<Calendar[]> {
  const out = await api.get<{ items: CalendarOut[] }>("/calendar/calendars");
  return out.items.map(toCalendar);
}

export function useCalendars(): Resource<Calendar[]> {
  const [data] = createResource(calendarTick, fetchCalendars);
  return data;
}

export function refreshCalendars(): void {
  setCalendarTick((n) => n + 1);
}

/* ── Events (the seam) ────────────────────────────────────────────────────── */

export interface EventWindow {
  /** ISO instants bounding what to load. Recurrences are expanded inside it, so the
   *  window is what keeps an open-ended rule finite. */
  start: string;
  end: string;
}

const [eventTick, setEventTick] = createSignal(0);

async function fetchEvents(window: EventWindow): Promise<CalendarEvent[]> {
  const out = await api.get<{ items: OccurrenceOut[] }>(
    `/calendar/occurrences?start=${encodeURIComponent(window.start)}&end=${encodeURIComponent(window.end)}`,
  );
  return out.items.map(toEvent);
}

export function useCalendarEvents(
  window: () => EventWindow,
): Resource<CalendarEvent[]> {
  const [data] = createResource(
    () => [window(), eventTick()] as const,
    ([w]) => fetchEvents(w),
  );
  return data;
}

export function refreshCalendarEvents(): void {
  setEventTick((n) => n + 1);
}

/* ── Mutations ────────────────────────────────────────────────────────────── */

export interface NewEvent {
  calendarId: string;
  title: string;
  start: string;
  end?: string;
  location?: string;
  description?: string;
  allDay?: boolean;
  recurrence?: RecurrenceRule;
}

export async function createEvent(input: NewEvent): Promise<void> {
  await api.post("/calendar/events", {
    calendarId: input.calendarId,
    title: input.title,
    start: input.start,
    end: input.end,
    timezone: browserZone(),
    allDay: input.allDay ?? false,
    location: input.location,
    description: input.description,
    rrule: toRrule(input.recurrence),
  });
  refreshCalendarEvents();
}

/**
 * Amend a stored event (`CAL-1`). The id may be an occurrence id, so it is split back to
 * the underlying event — a series is edited as a series, which is what the backend's
 * `PATCH /calendar/events/{id}` acts on. There is no per-occurrence edit: the schema has
 * no override row, and faking one here would write the whole series while claiming
 * otherwise.
 *
 * `recurrence: "none"` is sent as an explicit `clearRrule` rather than an omitted field,
 * because omitting means "leave unchanged" — dropping a repeat has to be expressible.
 */
export async function updateEvent(
  event: CalendarEvent,
  patch: Omit<NewEvent, "calendarId"> & { calendarId?: string },
): Promise<void> {
  const { eventId } = splitOccurrenceId(event.id);
  const dropsRepeat = patch.recurrence === "none";
  await api.patch(`/calendar/events/${eventId}`, {
    calendarId: patch.calendarId,
    title: patch.title,
    start: patch.start,
    end: patch.end,
    timezone: browserZone(),
    allDay: patch.allDay,
    location: patch.location ?? "",
    description: patch.description,
    rrule: dropsRepeat ? undefined : toRrule(patch.recurrence),
    clearRrule: dropsRepeat,
  });
  refreshCalendarEvents();
}

/**
 * Remove what the operator clicked. One instance of a series is *cancelled* (the rule
 * survives, so the rest of the series stays); a non-recurring event is deleted outright.
 * Which one applies is decided from the event itself, not guessed by the screen.
 */
export async function deleteEvent(event: CalendarEvent): Promise<void> {
  const { eventId, start } = splitOccurrenceId(event.id);
  if (event.recurring && start) {
    await api.del(
      `/calendar/events/${eventId}/occurrences?start=${encodeURIComponent(start)}`,
    );
  } else {
    await api.del(`/calendar/events/${eventId}`);
  }
  refreshCalendarEvents();
}

/** Reconcile every calendar bound to a remote server (`CAL-2`). One call — which
 *  calendars are remote, and what one sync means across them, is the backend's call. */
export async function syncCalendars(): Promise<SyncAllOut> {
  const result = await api.post<SyncAllOut>("/calendar/sync");
  refreshCalendars();
  refreshCalendarEvents();
  return result;
}

/** Parse a phrase into a draft event (`CAL-3`). Nothing is stored — the caller confirms
 *  it by calling `createEvent`. */
export async function parseEventPhrase(
  phrase: string,
): Promise<Omit<NewEvent, "calendarId">> {
  const draft = await api.post<DraftOut>("/calendar/parse", {
    phrase,
    timezone: browserZone(),
  });
  return {
    title: draft.title,
    start: draft.start,
    end: draft.end,
    location: draft.location ?? undefined,
    description: draft.description ?? undefined,
    allDay: draft.allDay,
    recurrence: toRecurrence(draft.rrule),
  };
}
