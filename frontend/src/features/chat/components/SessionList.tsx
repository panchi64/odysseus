import {
  For,
  Show,
  createEffect,
  createMemo,
  createSignal,
  on,
  type JSX,
} from "solid-js";
import { sessionModeSpec, type SessionMode } from "~/lib/modes";
import {
  Button,
  Disclosure,
  EmptyState,
  Icon,
  Input,
  LoadingText,
  Menu,
  REVEAL_ON_GROUP_HOVER,
  Text,
  Tooltip,
  cx,
  type MenuItem,
} from "~/ui";
import { createListView } from "~/lib/list";
import type { ChatSummary } from "../model";
import {
  isPinned,
  orderSessions,
  setWorkspaceOpen,
  titleReveals,
  togglePin,
  workspaceOpen,
} from "../data";
import {
  groupSessions,
  type SessionGroup,
  type WorkspaceDirectory,
} from "../sessionGroups";
import { SessionRow } from "./SessionRow";

/** What a directory's heading reports about the repository under it. Resolved by the
 *  caller from the live project listing — this component renders it and reads nothing. */
export interface WorkspaceStatus {
  /** The directory is not a git repository. A code thread cannot start here, so this
   *  outranks everything else the heading could say. */
  notARepo?: boolean;
  /** Uncommitted work in the operator's own checkout, which a worktree cut from the
   *  base ref will not see. */
  uncommitted?: number;
}

export interface SessionListProps {
  /** Resource accessor for the session summaries (undefined while loading). */
  sessions: () => ChatSummary[] | undefined;
  currentId: string | null;
  /** Which mode's list this is — it decides the arrangement, not the contents.
   *  Filtering happens upstream; this only knows how to lay out what it is given. */
  mode: SessionMode;
  onSelect: (id: string) => void;
  /** The directories a worktree mode files threads under, or undefined while the
   *  listing is still in flight. **Undefined is not the same as empty**: a filed thread
   *  whose directory this list does not carry is left out (see `groupSessions`), so
   *  rendering an empty list against a loaded set of threads would blank the rail for
   *  the width of a fetch. Held back as a loading state instead. */
  directories?: readonly WorkspaceDirectory[];
  /** What each directory's heading reports, by project id. */
  status?: (projectId: string) => WorkspaceStatus | undefined;
  /** Start a thread in this directory. */
  onNewThread?: (projectId: string) => void;
  /** The per-directory menu, built by the caller — archiving and deleting a project are
   *  its business, not this list's. */
  actions?: (projectId: string) => MenuItem[];
  /** Point at the chooser. The empty state's only offer, since a worktree mode with no
   *  directories has nothing else it can do. */
  onAddDirectory?: () => void;
  /** The directory a staged (not yet sent) thread will work in. Its heading opens and
   *  takes the selected paint, so a click in the rail is answered in the rail. */
  stagedProjectId?: string | null;
}

/** Searchable, pinnable thread list shared by the desktop rail and mobile
 *  drawer. Pinned threads sort first; the rest stay newest-first.
 *
 *  The arrangement varies by mode (`sessionGroups.ts`): Normal and Research get
 *  the flat run they have always had, Code gets one collapsible section per
 *  working directory — including the directories holding nothing yet, because in
 *  code mode the directory is where work *starts*. A search collapses the difference —
 *  while a query is active the sections stay, but every one of them opens, because a
 *  match the operator cannot see is the same as no match. */
export function SessionList(props: SessionListProps): JSX.Element {
  const view = createListView<ChatSummary>({
    source: () => props.sessions(),
    search: (s) => `${s.title} ${s.preview ?? ""} ${s.workspace ?? ""}`,
  });
  /** The grouping, or undefined while a worktree mode is still waiting on its
   *  directories. One value rather than a second flag the render has to keep in step
   *  with the first — see `directories` above for why the wait matters. */
  const grouped = createMemo(() => {
    const dirs = props.directories;
    // Keyed on the mode, not on whether a caller happened to pass an add handler: it
    // is filing under directories that makes the wait necessary, and a caller that
    // groups without offering to add would otherwise skip it and blank the list.
    if (sessionModeSpec(props.mode).workspace === "worktree" && !dirs)
      return undefined;
    const all = groupSessions(orderSessions(view.items()), props.mode, dirs);
    // A search asks "where is this thread", and a directory with no match is not an
    // answer — it is a heading in the way of one. Seeded-but-empty sections are the
    // resting state's business.
    return {
      all,
      shown: view.isFiltered() ? all.filter((g) => g.sessions.length) : all,
    };
  });
  const groups = createMemo(() => grouped()?.shown ?? []);
  /** The section that opens itself when the operator has expressed no preference: the
   *  first one, which is the most recently touched directory.
   *
   *  Read off the **unfiltered** run, or it would move as the operator types — and a
   *  section's resting state must not be a function of a query it is about to clear. */
  const leadId = createMemo(() => grouped()?.all[0]?.id);
  const total = createMemo(() =>
    groups().reduce((n, group) => n + group.sessions.length, 0),
  );
  /** Nothing at all to show — no threads *and* nowhere to start one. In a worktree
   *  mode that is the first-run screen and it gets its own offer; elsewhere it is the
   *  ordinary empty list. */
  const barren = createMemo(() => total() === 0 && groups().length === 0);

  return (
    <Show
      when={props.sessions() && grouped()}
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
        when={!barren()}
        fallback={
          <Show
            when={props.onAddDirectory && !view.isFiltered()}
            fallback={
              <EmptyState
                message={view.isFiltered() ? "No matches" : "No threads"}
              />
            }
          >
            <EmptyState
              icon="library"
              message="No directories yet"
              hint="A code thread works in a git worktree of a directory on this machine — pick one to start."
              action={
                <Button
                  variant="ghost"
                  size="sm"
                  leading="library"
                  onClick={() => props.onAddDirectory?.()}
                >
                  Add directory
                </Button>
              }
            />
          </Show>
        }
      >
        <For each={groups()}>
          {(group) => (
            <SessionGroupRows
              group={group}
              currentId={props.currentId}
              forceOpen={view.isFiltered()}
              lead={group.id === leadId()}
              // A directory match, never a null one: `Unfiled` has no project, and
              // comparing null to the "nothing staged" null would mark it as the place
              // the next thread lands — which is the one section it cannot be.
              staged={
                group.projectId !== null &&
                group.projectId === props.stagedProjectId
              }
              status={
                group.projectId ? props.status?.(group.projectId) : undefined
              }
              actions={
                group.projectId ? props.actions?.(group.projectId) : undefined
              }
              onNewThread={props.onNewThread}
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
 *  The header is a chevron, not the plus/minus the rail's area headers use: nothing
 *  here navigates, so a chevron cannot be misread as "go there" — and the row now
 *  carries a real plus meaning *start a thread in this directory*, which is exactly
 *  what a plus/minus marker beside it would be confused with.
 *
 *  The toggle is a whole-width trigger with its controls beside it (`Disclosure`'s
 *  `actions`), because a button inside a button is invalid HTML. */
function SessionGroupRows(props: {
  group: SessionGroup;
  currentId: string | null;
  forceOpen: boolean;
  /** The first section in the list — the most recently touched directory. */
  lead: boolean;
  staged: boolean;
  status?: WorkspaceStatus;
  actions?: MenuItem[];
  onNewThread?: (projectId: string) => void;
  onSelect: (id: string) => void;
}): JSX.Element {
  // Stored-then-derived: an explicit open or close by the operator wins and outlives
  // the reload, and a section they have never touched decides for itself. Without the
  // derived half, opening a thread from a search and then clearing the query would hide
  // the thread you are looking at; without the stored half, a rail of a dozen
  // directories re-collapses itself every time the app is opened.
  //
  // The default is deliberately narrow: this section holds the open thread, or is where
  // the staged one will go, or is the first directory in the listing (the most recently
  // opened — the one place work is likeliest to continue). Everything else starts shut,
  // because a cold load that opened all twelve would be a screen of headings with the
  // threads pushed off the bottom.
  // Keyed by the group's own id — the project id for a directory, and the literal
  // `Unfiled` for the run that has none. A section without a project is still a section
  // the operator can close and expect to stay closed.
  const stored = () => workspaceOpen(props.group.id);
  const holdsCurrent = () =>
    props.group.sessions.some((s) => s.id === props.currentId);
  // Memoized, because the header reads this four times over (the aria state, the
  // toggle's next value, the glyph, the body) and the rail re-renders every three
  // seconds while a run is live — so the scan through the section's rows was being
  // paid four times a tick, per section.
  const derived = createMemo(
    () => stored() ?? (holdsCurrent() || props.staged || props.lead),
  );
  // While a query holds every matching section open, the chevron is still a control and
  // still has to move when pressed — but what it moves is *this search*, not the
  // section's resting state. Written to the store instead, a click here would appear
  // inert (the query still forces the section open) and then take effect minutes later
  // when the query cleared. Reset whenever the search itself starts or ends, so a
  // collapse never outlives the query that prompted it.
  const [searchClosed, setSearchClosed] = createSignal(false);
  createEffect(
    on(
      () => props.forceOpen,
      () => setSearchClosed(false),
    ),
  );
  const open = createMemo(() =>
    props.forceOpen ? !searchClosed() : derived(),
  );
  const toggle = () =>
    props.forceOpen
      ? setSearchClosed((c) => !c)
      : setWorkspaceOpen(props.group.id, !derived());

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
            marker="chevron"
            open={open()}
            onToggle={toggle}
            labelNode={<WorkspaceLabel label={label()} />}
            // A staged thread has no row of its own — it is not saved yet — so the
            // heading is what says where it will land, in the same raised fill a
            // selected row takes. On the whole row rather than the trigger, or the
            // fill would stop short of the controls and mark half a heading.
            rowClass={cx("hover:bg-raised", props.staged && "bg-raised")}
            // No gap of its own: `cx` is a plain joiner, so a second `gap-*` here
            // would leave the winner to stylesheet order rather than to intent.
            triggerClass="px-3 py-1.5"
            // The rows are the body — no top margin between them and the header.
            class=""
            trailing={
              <>
                <WorkspaceStatusMark status={props.status} />
                {/* The count is what makes a closed section worth leaving closed —
                    it says how much is in there without opening it. */}
                <Text variant="micro" tone="dim" class="ml-auto pl-2">
                  {props.group.sessions.length}
                </Text>
              </>
            }
            actions={
              <Show
                when={props.group.projectId}
                // `Unfiled` has no directory, so neither control means anything on
                // it — but the gutter has to stay, or its count would sit where every
                // other section's buttons are. Two `size-7` slots, which is why both
                // controls below are pinned to that size rather than sized by their
                // own contents: a gutter that tracked the label inside a button would
                // shift the column the day that label changed.
                fallback={<span aria-hidden class="h-7 w-14 shrink-0" />}
              >
                {(projectId) => (
                  <>
                    <Tooltip label={`New thread in ${label()}`} side="right">
                      <Button
                        variant="ghost"
                        size="sm"
                        leading="plus"
                        aria-label={`New thread in ${label()}`}
                        class="size-7 shrink-0"
                        onClick={() => props.onNewThread?.(projectId())}
                      />
                    </Tooltip>
                    <Show when={props.actions}>
                      {(items) => (
                        <Menu
                          items={items()}
                          trigger={
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`${label()} actions`}
                              // Quiet at rest — the plus is the one control this row
                              // is for. Keyboard focus and touch still reach it.
                              class={cx(
                                "size-7 shrink-0",
                                REVEAL_ON_GROUP_HOVER,
                              )}
                            >
                              ···
                            </Button>
                          }
                        />
                      )}
                    </Show>
                  </>
                )}
              </Show>
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

/** `parent/name`, with the parent giving way first.
 *
 *  The name is the half that identifies the directory, so it never truncates — the
 *  operator has more than one `frontend`, and a heading clipped to `client-a/front…`
 *  would have spent the width on the part they already knew. */
function WorkspaceLabel(props: { label: string }): JSX.Element {
  // Split once, at the LAST separator. Taking the first segment and the last instead
  // reads a three-part name as its two ends — `acme/web/frontend` rendering as
  // `acme/frontend`, which names a directory that does not exist and can collide with
  // one that does.
  const cut = createMemo(() => props.label.lastIndexOf("/"));
  const head = createMemo(() =>
    cut() > 0 ? props.label.slice(0, cut() + 1) : "",
  );
  const name = createMemo(() =>
    cut() > 0 ? props.label.slice(cut() + 1) : props.label,
  );
  return (
    <span class="flex min-w-0 items-baseline">
      <Show when={head()}>
        <Text variant="label" tone="dim" class="min-w-0 truncate opacity-60">
          {head()}
        </Text>
      </Show>
      <Text variant="label" tone="dim" class="shrink-0">
        {name()}
      </Text>
    </span>
  );
}

/** What the heading says about the repository — the durable form of the warning the
 *  chooser gives once and then loses. Nothing at all for the ordinary case: a clean
 *  git repository is what a directory is supposed to be here. */
function WorkspaceStatusMark(props: { status?: WorkspaceStatus }): JSX.Element {
  return (
    <Show when={props.status}>
      {(status) => (
        <Show
          when={status().notARepo}
          fallback={
            <Show when={status().uncommitted}>
              {(n) => (
                <Tooltip
                  side="right"
                  label={`${n()} uncommitted change${n() === 1 ? "" : "s"} here won't be visible to the agent`}
                >
                  <Text variant="micro" tone="dim" class="shrink-0 pl-2">
                    ±{n()}
                  </Text>
                </Tooltip>
              )}
            </Show>
          }
        >
          <Tooltip
            side="right"
            label="Not a git repository — a code thread can't start here"
          >
            <Icon name="warning" size={12} class="shrink-0 text-warn" />
          </Tooltip>
        </Show>
      )}
    </Show>
  );
}
