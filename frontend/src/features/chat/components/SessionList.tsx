import { For, Show, type JSX } from "solid-js";
import { EmptyState, Input, LoadingText } from "~/ui";
import { createListView } from "~/lib/list";
import { relativeTime } from "~/lib/format";
import type { ChatSummary } from "../model";
import { isPinned, orderSessions, titleReveals, togglePin } from "../data";
import { SessionRow } from "./SessionRow";

export interface SessionListProps {
  /** Resource accessor for the session summaries (undefined while loading). */
  sessions: () => ChatSummary[] | undefined;
  currentId: string | null;
  onSelect: (id: string) => void;
}

/** Searchable, pinnable thread list shared by the desktop rail and mobile
 *  drawer. Pinned threads sort first; the rest stay newest-first. */
export function SessionList(props: SessionListProps): JSX.Element {
  const view = createListView<ChatSummary>({
    source: () => props.sessions(),
    search: (s) => `${s.title} ${s.preview ?? ""}`,
  });
  const ordered = () => orderSessions(view.items());

  return (
    <Show
      when={props.sessions()}
      fallback={
        <div class="p-3">
          <LoadingText />
        </div>
      }
    >
      <div class="border-b border-line p-2">
        <Input
          leading="search"
          placeholder="SEARCH THREADS"
          value={view.query()}
          onInput={(e) => view.setQuery(e.currentTarget.value)}
        />
      </div>
      <Show
        when={ordered().length}
        fallback={
          <EmptyState
            message={view.isFiltered() ? "NO MATCHES" : "NO THREADS"}
          />
        }
      >
        <For each={ordered()}>
          {(s) => (
            <SessionRow
              title={s.title}
              meta={relativeTime(s.updatedAt)}
              selected={s.id === props.currentId}
              pinned={isPinned(s.id)}
              reveal={titleReveals[s.id]}
              onOpen={() => props.onSelect(s.id)}
              onTogglePin={() => togglePin(s.id)}
            />
          )}
        </For>
      </Show>
    </Show>
  );
}
