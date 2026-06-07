import { createResource, type Resource } from "solid-js";
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

export function useCalendarEvents(): Resource<CalendarEvent[]> {
  const [data] = createResource(fetchEvents);
  return data;
}
