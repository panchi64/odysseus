import {
  createEffect,
  createResource,
  createSignal,
  type Resource,
} from "solid-js";
import type { Calendar, CalendarEvent } from "./model";
import { mockCalendars, mockEvents } from "./mocks";

async function fetchCalendars(): Promise<Calendar[]> {
  return mockCalendars;
}

async function fetchEvents(): Promise<CalendarEvent[]> {
  return mockEvents;
}

export function useCalendars(): Resource<Calendar[]> {
  const [data] = createResource(fetchCalendars);
  return data;
}

// Mutable local event list — Phase 1 mock state.
// Phase 2: replace fetchEvents with a real API call; addLocalEvent will POST then refetch.
const [localEvents, setLocalEvents] = createSignal<CalendarEvent[]>([]);
let eventsSeeded = false;

export function useCalendarEvents(): Resource<CalendarEvent[]> {
  const [data] = createResource(fetchEvents);

  // Seed the local signal exactly once when the resource first resolves. Guard
  // on a module-level flag (not localEvents().length) so deleting every event
  // doesn't re-trigger this effect and resurrect them.
  createEffect(() => {
    const resolved = data();
    if (resolved && !eventsSeeded) {
      eventsSeeded = true;
      setLocalEvents(resolved);
    }
  });

  return data;
}

/** Returns the live (possibly mutated) event list for Phase-1 mutations. */
export function useLocalEvents() {
  return localEvents;
}

/** Append a new event to the local mutable list. */
export function addLocalEvent(evt: CalendarEvent): void {
  setLocalEvents((prev) => [...prev, evt]);
}

/** Remove an event from the local mutable list. */
export function removeLocalEvent(id: string): void {
  setLocalEvents((prev) => prev.filter((e) => e.id !== id));
}
