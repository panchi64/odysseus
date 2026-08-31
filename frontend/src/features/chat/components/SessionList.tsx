import { For, Show, createMemo, createSignal, type JSX } from "solid-js";
import type { SessionMode } from "~/lib/modes";
import { Disclosure, EmptyState, Input, LoadingText, Text } from "~/ui";
import { createListView } from "~/lib/list";
import { relativeTime } from "~/lib/format";
import type { ChatSummary } from "../model";
import { isPinned, orderSessions, titleReveals, togglePin } from "../data";
import { groupSessions, type SessionGroup } from "../sessionGroups";
import { SessionRow } from "./SessionRow";

export interface SessionListProps {
  /** Resource accessor for the session summaries (undefined while loading). */
  sessions: () => ChatSummary[] | undefined;
  currentId: string | null;
  /** Which mode's list this is — it decides the arrangement, not the contents.
   *  Filtering happens upstream; this only knows how to lay out what it is given. */
  mode: SessionMode;
  onSelect: (id: string) => void;
}

/** Searchable, pinnable thread list shared by the desktop rail and mobile
 *  drawer. Pinned threads sort first; the rest stay newest-first.
 *
 *  The arrangement varies by mode (`sessionGroups.ts`): Normal and Research get
 *  the flat run they have always had, Code gets one collapsible section per
 *  working directory. A search collapses the difference — while a query is
 *  active the sections stay, but every one of them opens, because a match the
 *  operator cannot see is the same as no match. */
export function SessionList(props: SessionListProps): JSX.Element {
  const view = createListView<ChatSummary>({
    source: () => props.sessions(),
    search: (s) => `${s.title} ${s.preview ?? ""} ${s.workspace ?? ""}`,
  });
  const groups = createMemo(() =>
    groupSessions(orderSessions(view.items()), props.mode),
  );
  const total = createMemo(() =>
    groups().reduce((n, group) => n + group.sessions.length, 0),
  );

  return (
    <Show
      when={props.sessions()}
      fallback={
        <div class="p-3">
          <LoadingText />
        </div>
      }
    >
      <div class="p-2">
        <Input
          leading="search"
          placeholder="Search threads"
          value={view.query()}
          onInput={(e) => view.setQuery(e.currentTarget.value)}
        />
      </div>
      <Show
        when={total()}
        fallback={
          <EmptyState
            message={view.isFiltered() ? "No matches" : "No threads"}
          />
        }
      >
        <For each={groups()}>
          {(group) => (
            <SessionGroupRows
              group={group}
              currentId={props.currentId}
              forceOpen={view.isFiltered()}
              onSelect={props.onSelect}
            />
          )}
        </For>
      </Show>
    </Show>
  );
}

/** The rows themselves — a component rather than a shared JSX value, so the
 *  headed and unheaded branches below each render their own nodes instead of
 *  passing one set of DOM back and forth across a `Show`. */
function SessionRows(props: {
  sessions: ChatSummary[];
  currentId: string | null;
  onSelect: (id: string) => void;
}): JSX.Element {
  return (
    <For each={props.sessions}>
      {(s) => (
        <SessionRow
          title={s.title}
          meta={relativeTime(s.updatedAt)}
          selected={s.id === props.currentId}
          pinned={isPinned(s.id)}
          reveal={titleReveals[s.id]}
          activity={s.activity}
          onOpen={() => props.onSelect(s.id)}
          onTogglePin={() => togglePin(s.id)}
        />
      )}
    </For>
  );
}

/** One run of rows, with a disclosure header when the group has a name.
 *
 *  `Disclosure`'s plus/minus marker rather than a header of its own: beside a label a
 *  chevron reads as "go there", and the rail's area headers made the same call. It is a
 *  whole-width trigger here — unlike the nav areas there is nowhere for a workspace
 *  heading to navigate *to*, so the header and the toggle are one control instead of
 *  two siblings. */
function SessionGroupRows(props: {
  group: SessionGroup;
  currentId: string | null;
  forceOpen: boolean;
  onSelect: (id: string) => void;
}): JSX.Element {
  // Derived-then-overridden, like the nav rail's sections: a group holding the
  // open thread opens itself, and after that it is whatever the operator last
  // set it to. Without the derived half, opening a thread from a search and then
  // clearing the query would hide the thread you are looking at.
  const [override, setOverride] = createSignal<boolean>();
  const holdsCurrent = () =>
    props.group.sessions.some((s) => s.id === props.currentId);
  // Memoized, because the header reads this four times over (the aria state, the
  // toggle's next value, the glyph, the body) and the rail re-renders every three
  // seconds while a run is live — so the scan through the section's rows was being
  // paid four times a tick, per section.
  const open = createMemo(
    () => props.forceOpen || (override() ?? holdsCurrent()),
  );

  return (
    <Show
      when={props.group.label}
      fallback={
        <SessionRows
          sessions={props.group.sessions}
          currentId={props.currentId}
          onSelect={props.onSelect}
        />
      }
    >
      {(label) => (
        <div class="pb-1">
          <Disclosure
            label={label()}
            marker="plusminus"
            open={open()}
            onToggle={() => setOverride(!open())}
            // No gap of its own: `cx` is a plain joiner, so a second `gap-*` here
            // would leave the winner to stylesheet order rather than to intent.
            triggerClass="w-full px-3 py-1.5 hover:bg-raised"
            // The rows are the body — no top margin between them and the header.
            class=""
            trailing={
              // The count is what makes a closed section worth leaving closed —
              // it says how much is in there without opening it.
              <Text variant="micro" tone="dim" class="ml-auto pl-2">
                {props.group.sessions.length}
              </Text>
            }
          >
            <SessionRows
              sessions={props.group.sessions}
              currentId={props.currentId}
              onSelect={props.onSelect}
            />
          </Disclosure>
        </div>
      )}
    </Show>
  );
}
