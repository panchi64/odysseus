import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  Field,
  Input,
  InstrumentBand,
  ListRow,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  Row,
  Select,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  confirm,
  toast,
} from "~/ui";
import { date } from "~/lib/format";
import {
  useCalendars,
  useCalendarEvents,
  useLocalEvents,
  addLocalEvent,
  removeLocalEvent,
} from "../data";
import type { CalendarEvent } from "../model";

const DAYS_OF_WEEK = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];

const TONE_STATUS = {
  nominal: "nominal",
  info: "info",
  warn: "warn",
  alert: "alert",
} as const;

function getDaysInMonth(year: number, month: number): Date[] {
  const days: Date[] = [];
  // month is 0-indexed
  const firstDay = new Date(Date.UTC(year, month, 1));
  // Adjust to start on Monday (ISO week)
  let startDow = firstDay.getUTCDay(); // 0=Sun
  startDow = startDow === 0 ? 6 : startDow - 1; // 0=Mon

  // pad with previous month days
  for (let i = startDow - 1; i >= 0; i--) {
    days.push(new Date(Date.UTC(year, month, -i)));
  }
  // current month days
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  for (let d = 1; d <= lastDay; d++) {
    days.push(new Date(Date.UTC(year, month, d)));
  }
  // pad to complete final row (multiple of 7)
  while (days.length % 7 !== 0) {
    const last = days[days.length - 1];
    days.push(
      new Date(
        Date.UTC(
          last.getUTCFullYear(),
          last.getUTCMonth(),
          last.getUTCDate() + 1,
        ),
      ),
    );
  }
  return days;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getUTCFullYear() === b.getUTCFullYear() &&
    a.getUTCMonth() === b.getUTCMonth() &&
    a.getUTCDate() === b.getUTCDate()
  );
}

const MONTH_NAMES = [
  "JANUARY",
  "FEBRUARY",
  "MARCH",
  "APRIL",
  "MAY",
  "JUNE",
  "JULY",
  "AUGUST",
  "SEPTEMBER",
  "OCTOBER",
  "NOVEMBER",
  "DECEMBER",
];

export function CalendarScreen(): JSX.Element {
  const calendars = useCalendars();
  // Seed local events from the resource; use local signal as the live list.
  useCalendarEvents();
  // useLocalEvents() returns the localEvents signal accessor directly.
  const events = useLocalEvents();

  const today = new Date();
  const [viewYear, setViewYear] = createSignal(today.getUTCFullYear());
  const [viewMonth, setViewMonth] = createSignal(today.getUTCMonth());
  const [viewMode, setViewMode] = createSignal("month");
  const [selectedEvent, setSelectedEvent] = createSignal<CalendarEvent | null>(
    null,
  );
  const [eventModalOpen, setEventModalOpen] = createSignal(false);
  const [newEventOpen, setNewEventOpen] = createSignal(false);
  const [quickAdd, setQuickAdd] = createSignal("");

  // Sync state
  const [syncing, setSyncing] = createSignal(false);

  // New event form state
  const [newTitle, setNewTitle] = createSignal("");
  const [newTitleError, setNewTitleError] = createSignal("");
  const [newStart, setNewStart] = createSignal("");
  const [newEnd, setNewEnd] = createSignal("");
  const [newLocation, setNewLocation] = createSignal("");
  const [newRecurrence, setNewRecurrence] = createSignal("none");
  const [newCalendarId, setNewCalendarId] = createSignal("");

  const days = () => getDaysInMonth(viewYear(), viewMonth());

  const eventsForDay = (d: Date) =>
    events().filter((evt) => sameDay(new Date(evt.start), d));

  const calendarForEvent = (evt: CalendarEvent) =>
    (calendars() ?? []).find((c) => c.id === evt.calendarId);

  const eventsThisMonth = () =>
    events().filter((evt) => {
      const d = new Date(evt.start);
      return (
        d.getUTCFullYear() === viewYear() && d.getUTCMonth() === viewMonth()
      );
    }).length;

  function prevMonth() {
    if (viewMonth() === 0) {
      setViewYear((y) => y - 1);
      setViewMonth(11);
    } else {
      setViewMonth((m) => m - 1);
    }
  }

  function nextMonth() {
    if (viewMonth() === 11) {
      setViewYear((y) => y + 1);
      setViewMonth(0);
    } else {
      setViewMonth((m) => m + 1);
    }
  }

  function goToday() {
    setViewYear(today.getUTCFullYear());
    setViewMonth(today.getUTCMonth());
  }

  function openEvent(evt: CalendarEvent) {
    setSelectedEvent(evt);
    setEventModalOpen(true);
  }

  // Sync button handler: mock a brief async sync, then confirm success.
  async function handleSync() {
    setSyncing(true);
    await new Promise<void>((r) => setTimeout(r, 1200));
    setSyncing(false);
    toast.success("SYNC COMPLETE");
  }

  // Delete event with confirm guard + undo toast.
  async function handleDeleteEvent() {
    const evt = selectedEvent();
    if (!evt) return;
    const ok = await confirm({
      title: `DELETE EVENT: "${evt.title}"?`,
      detail: "This cannot be undone.",
      confirmLabel: "DELETE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    const snapshot = evt;
    removeLocalEvent(evt.id);
    setEventModalOpen(false);
    setSelectedEvent(null);
    toast.success("Event deleted", {
      action: {
        label: "UNDO",
        onClick: () => {
          addLocalEvent(snapshot);
          toast.info("Event restored");
        },
      },
    });
  }

  // Create event with validation + local state mutation.
  function handleCreateEvent() {
    const title = newTitle().trim();
    if (!title) {
      setNewTitleError("TITLE IS REQUIRED");
      return;
    }
    setNewTitleError("");

    const calId = newCalendarId() || calendars()?.[0]?.id || "cal-1";
    const id = `evt-new-${Date.now()}`;
    const startIso = newStart()
      ? new Date(newStart()).toISOString()
      : new Date().toISOString();
    const endIso = newEnd()
      ? new Date(newEnd()).toISOString()
      : new Date(Date.now() + 3600_000).toISOString();

    addLocalEvent({
      id,
      calendarId: calId,
      title,
      start: startIso,
      end: endIso,
      location: newLocation() || undefined,
      recurrence: newRecurrence() as CalendarEvent["recurrence"],
    });

    // Reset form
    setNewTitle("");
    setNewStart("");
    setNewEnd("");
    setNewLocation("");
    setNewRecurrence("none");
    setNewCalendarId("");
    setNewEventOpen(false);
    toast.success(`Event "${title}" created`);
  }

  // Initialise newCalendarId when calendars resolve.
  const resolvedCalendarId = () =>
    newCalendarId() || (calendars()?.[0]?.id ?? "");

  return (
    <Stack gap={6}>
      <PageHeader
        title="CALENDAR"
        subtitle="Events, scheduling, and CalDAV sync."
        assetId="COMM-CAL-01.0"
        actions={
          <Row gap={2}>
            <Button
              variant="ghost"
              leading="refresh"
              size="sm"
              disabled={syncing()}
              onClick={handleSync}
            >
              {syncing() ? "SYNCING…" : "SYNC"}
            </Button>
            <Button
              variant="primary"
              leading="plus"
              onClick={() => setNewEventOpen(true)}
            >
              NEW EVENT
            </Button>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText label="LOADING CALENDARS" />}>
        <InstrumentBand
          items={[
            {
              label: "MONTH",
              value: `${MONTH_NAMES[viewMonth()]} ${viewYear()}`,
            },
            { label: "EVENTS THIS MONTH", value: String(eventsThisMonth()) },
            { label: "CALENDARS", value: String(calendars()?.length ?? 0) },
            {
              label: "SYNC STATUS",
              value: syncing()
                ? "SYNCING…"
                : (calendars() ?? []).every((c) => c.synced)
                  ? "ALL SYNCED"
                  : "PARTIAL",
              tone: syncing()
                ? "info"
                : (calendars() ?? []).every((c) => c.synced)
                  ? "nominal"
                  : "warn",
            },
          ]}
        />
      </Suspense>

      <div class="flex min-h-0 gap-4">
        {/* Sidebar: calendars list */}
        <aside class="hidden w-48 shrink-0 flex-col gap-4 lg:flex">
          <Panel label="CALENDARS" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <Show
                when={(calendars()?.length ?? 0) > 0}
                fallback={
                  <div class="p-3">
                    <EmptyState
                      message="NO CALENDARS CONNECTED"
                      hint="Link or sync a calendar to get started."
                    />
                  </div>
                }
              >
                <For each={calendars()}>
                  {(cal) => (
                    <ListRow
                      label={cal.name}
                      right={
                        <StatusFlag
                          status={cal.synced ? TONE_STATUS[cal.tone] : "warn"}
                          dot={cal.synced}
                        >
                          {cal.synced ? "SYNC" : "LOCAL"}
                        </StatusFlag>
                      }
                    />
                  )}
                </For>
              </Show>
            </Suspense>
          </Panel>

          {/* Upcoming events */}
          <Panel label="UPCOMING" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <For
                each={events()
                  .filter((e) => new Date(e.start) >= today)
                  .sort(
                    (a, b) =>
                      new Date(a.start).getTime() - new Date(b.start).getTime(),
                  )
                  .slice(0, 5)}
                fallback={
                  <div class="p-3">
                    <EmptyState message="NO UPCOMING EVENTS" />
                  </div>
                }
              >
                {(evt) => (
                  <ListRow
                    label={evt.title}
                    onClick={() => openEvent(evt)}
                    right={
                      <Text variant="micro" tone="dim">
                        {date(evt.start).slice(5)}
                      </Text>
                    }
                  />
                )}
              </For>
            </Suspense>
          </Panel>
        </aside>

        {/* Calendar main */}
        <div class="flex min-w-0 flex-1 flex-col gap-3">
          <Row justify="between" align="center">
            <Row gap={2} align="center">
              <Button
                variant="ghost"
                leading="chevron-left"
                size="sm"
                onClick={prevMonth}
              />
              <Text variant="readout" tone="bright">
                {MONTH_NAMES[viewMonth()]} {viewYear()}
              </Text>
              <Button
                variant="ghost"
                leading="chevron-right"
                size="sm"
                onClick={nextMonth}
              />
              <Button variant="default" size="sm" onClick={goToday}>
                TODAY
              </Button>
            </Row>
            <Tabs
              items={[
                { value: "month", label: "MONTH" },
                { value: "week", label: "WEEK" },
                { value: "day", label: "DAY" },
              ]}
              value={viewMode()}
              onChange={setViewMode}
            />
          </Row>

          {/* Quick-add bar */}
          <Row gap={2} align="center">
            <Input
              value={quickAdd()}
              onInput={(e) => setQuickAdd(e.currentTarget.value)}
              placeholder="Quick add — e.g. 'Team sync Monday 14:00'"
              class="flex-1"
            />
            <Button
              variant="default"
              size="sm"
              leading="plus"
              onClick={() => setNewEventOpen(true)}
            >
              ADD
            </Button>
          </Row>

          {/* Month grid */}
          <Suspense fallback={<LoadingText label="LOADING EVENTS" />}>
            <Panel flush>
              {/* Day-of-week headers */}
              <div class="grid grid-cols-7 border-b border-line">
                <For each={DAYS_OF_WEEK}>
                  {(day) => (
                    <div class="border-r border-line px-2 py-1 last:border-r-0">
                      <Text variant="label" tone="dim">
                        {day}
                      </Text>
                    </div>
                  )}
                </For>
              </div>

              {/* Day cells */}
              <Show
                when={eventsThisMonth() > 0}
                fallback={
                  <div class="grid grid-cols-7">
                    <For each={days()}>
                      {(day) => {
                        const isCurrentMonth = () =>
                          day.getUTCMonth() === viewMonth();
                        const isToday = () => sameDay(day, today);
                        return (
                          <div
                            class="min-h-20 border-b border-r border-line p-1 last:border-r-0 transition-colors hover:bg-raised"
                            classList={{ "bg-raised": isToday() }}
                          >
                            <Text
                              variant="label"
                              tone={
                                isToday()
                                  ? "bright"
                                  : isCurrentMonth()
                                    ? "default"
                                    : "dim"
                              }
                              class="mb-1"
                            >
                              {isToday()
                                ? `[${day.getUTCDate()}]`
                                : String(day.getUTCDate())}
                            </Text>
                          </div>
                        );
                      }}
                    </For>
                    <div class="col-span-7 py-8">
                      <EmptyState
                        message="NO EVENTS THIS MONTH"
                        hint="Use NEW EVENT to schedule something."
                      />
                    </div>
                  </div>
                }
              >
                <div class="grid grid-cols-7">
                  <For each={days()}>
                    {(day) => {
                      const isCurrentMonth = () =>
                        day.getUTCMonth() === viewMonth();
                      const isToday = () => sameDay(day, today);
                      const dayEvents = () => eventsForDay(day);
                      return (
                        <div
                          class="min-h-20 border-b border-r border-line p-1 last:border-r-0 transition-colors hover:bg-raised"
                          classList={{
                            "bg-raised": isToday(),
                          }}
                        >
                          <Text
                            variant="label"
                            tone={
                              isToday()
                                ? "bright"
                                : isCurrentMonth()
                                  ? "default"
                                  : "dim"
                            }
                            class="mb-1"
                          >
                            {isToday()
                              ? `[${day.getUTCDate()}]`
                              : String(day.getUTCDate())}
                          </Text>
                          <Stack gap={0}>
                            <For each={dayEvents().slice(0, 3)}>
                              {(evt) => {
                                const cal = () => calendarForEvent(evt);
                                return (
                                  <button
                                    type="button"
                                    class="mb-0.5 w-full truncate px-1 py-0.5 text-left text-label font-mono uppercase tracking-label transition-colors hover:bg-raised"
                                    classList={{
                                      "text-nominal": cal()?.tone === "nominal",
                                      "text-info": cal()?.tone === "info",
                                      "text-warn": cal()?.tone === "warn",
                                      "text-alert": cal()?.tone === "alert",
                                      "text-dim": !cal()?.tone,
                                    }}
                                    onClick={() => openEvent(evt)}
                                  >
                                    {evt.title}
                                  </button>
                                );
                              }}
                            </For>
                            <Show when={dayEvents().length > 3}>
                              <Text variant="micro" tone="dim">
                                +{dayEvents().length - 3} MORE
                              </Text>
                            </Show>
                          </Stack>
                        </div>
                      );
                    }}
                  </For>
                </div>
              </Show>
            </Panel>
          </Suspense>
        </div>
      </div>

      {/* Event detail modal */}
      <Show when={selectedEvent()}>
        {(evt) => (
          <Modal
            open={eventModalOpen()}
            onClose={() => setEventModalOpen(false)}
            title="EVENT DETAIL"
            footer={
              <Row gap={2}>
                <Button
                  variant="ghost"
                  onClick={() => setEventModalOpen(false)}
                >
                  CLOSE
                </Button>
                <Button
                  variant="danger"
                  leading="trash"
                  onClick={handleDeleteEvent}
                >
                  DELETE
                </Button>
                <Button variant="primary" leading="edit">
                  EDIT
                </Button>
              </Row>
            }
          >
            <Stack gap={4}>
              <Field label="TITLE" value={evt().title} />
              <Row gap={4}>
                <Field
                  label="START"
                  value={evt().start.replace("T", " ").replace("Z", " UTC")}
                />
                <Field
                  label="END"
                  value={evt().end.replace("T", " ").replace("Z", " UTC")}
                />
              </Row>
              <Show when={evt().location}>
                <Field label="LOCATION" value={evt().location!} />
              </Show>
              <Field
                label="RECURRENCE"
                value={(evt().recurrence ?? "none").toUpperCase()}
              />
              <Show when={evt().description}>
                <Field label="DESCRIPTION" value={evt().description!} />
              </Show>
              <Show when={calendarForEvent(evt())}>
                {(cal) => (
                  <Field
                    label="CALENDAR"
                    value={
                      <StatusFlag status={TONE_STATUS[cal().tone]} dot>
                        {cal().name.toUpperCase()}
                      </StatusFlag>
                    }
                  />
                )}
              </Show>
            </Stack>
          </Modal>
        )}
      </Show>

      {/* New event modal */}
      <Modal
        open={newEventOpen()}
        onClose={() => setNewEventOpen(false)}
        title="NEW EVENT"
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={() => setNewEventOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              leading="plus"
              onClick={handleCreateEvent}
            >
              CREATE
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          <Input
            label="TITLE"
            value={newTitle()}
            onInput={(e) => {
              setNewTitle(e.currentTarget.value);
              if (newTitleError()) setNewTitleError("");
            }}
            placeholder="Event title"
            invalid={!!newTitleError()}
            hint={newTitleError() || undefined}
          />
          <Input
            label="START"
            type="datetime-local"
            value={newStart()}
            onInput={(e) => setNewStart(e.currentTarget.value)}
          />
          <Input
            label="END"
            type="datetime-local"
            value={newEnd()}
            onInput={(e) => setNewEnd(e.currentTarget.value)}
          />
          <Input
            label="LOCATION"
            value={newLocation()}
            onInput={(e) => setNewLocation(e.currentTarget.value)}
            placeholder="Optional location"
          />
          <Select
            label="RECURRENCE"
            value={newRecurrence()}
            onChange={setNewRecurrence}
            options={[
              { value: "none", label: "No recurrence" },
              { value: "daily", label: "Daily" },
              { value: "weekly", label: "Weekly" },
              { value: "weekdays", label: "Weekdays" },
              { value: "monthly", label: "Monthly" },
            ]}
          />
          <Select
            label="CALENDAR"
            value={resolvedCalendarId()}
            onChange={setNewCalendarId}
            options={(calendars() ?? []).map((c) => ({
              value: c.id,
              label: c.name,
            }))}
          />
          <Text variant="micro" tone="dim">
            TIMEZONE: UTC (server local)
          </Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
