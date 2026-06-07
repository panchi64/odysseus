/** Calendar feature data contracts. */

export type RecurrenceRule =
  | "none"
  | "daily"
  | "weekly"
  | "monthly"
  | "weekdays";

export interface Calendar {
  id: string;
  name: string;
  /** Color expressed as a TextTone accent for status chips. */
  tone: "nominal" | "info" | "warn" | "alert";
  synced: boolean;
  syncUrl?: string;
}

export interface CalendarEvent {
  id: string;
  calendarId: string;
  title: string;
  start: string; // ISO datetime
  end: string; // ISO datetime
  location?: string;
  recurrence?: RecurrenceRule;
  allDay?: boolean;
  description?: string;
}
