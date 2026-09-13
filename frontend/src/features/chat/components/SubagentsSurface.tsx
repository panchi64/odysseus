import { For, Show, createMemo, createSignal, type JSX } from "solid-js";
import { Disclosure, EmptyState, Text } from "~/ui";
import { isLive, type Subagent } from "../data";
import { SubagentCard } from "./SubagentCard";
import { SubagentDetail } from "./SubagentDetail";

/** Waiting on the operator first, then working, then whatever went wrong.
 *
 *  Deliberately not chronological. A list ordered by when things started puts the one
 *  thing that is blocked on the operator wherever it happens to fall, which is the one
 *  ordering guaranteed not to surface it. */
const RANK: Record<string, number> = {
  blocked: 0,
  running: 1,
  failed: 2,
  cancelled: 3,
};

function byUrgency(a: Subagent, b: Subagent): number {
  const rank = (RANK[a.status] ?? 9) - (RANK[b.status] ?? 9);
  return rank !== 0 ? rank : b.startedAt.localeCompare(a.startedAt);
}

/**
 * The sub-agents a thread has launched, and what they are doing.
 *
 * The operator cannot talk to a sub-agent — there is nowhere to type — so this is the
 * whole of their relationship with one: watch it work, read what it did, and see where
 * it went wrong. That shapes every choice here.
 *
 * **Three tiers, and the third is the interesting one.** Live sub-agents are the reason
 * the panel is open, so they are simply there. A sub-agent that *failed* stays with them
 * rather than folding away, because "see if anything went wrong" is the main reason to
 * come here at all and a failure hidden one click deep behind something labelled
 * *Finished* works against exactly that. Everything that finished cleanly goes into a
 * collapsed accordion: it is kept — a transcript is the record of what happened, and the
 * question about it is usually asked later — but a session's worth of successes between
 * the operator and the two cards they care about is a panel they stop opening.
 *
 * **Collapsed by default, every time.** Not remembered, deliberately: the accordion
 * exists to keep the panel readable, and a remembered *expanded* state would reopen a
 * long session's whole history the next time the panel is opened.
 *
 * **A card opens its sub-agent's own view, and the list gives way to it.** The transcript
 * used to unfold underneath the card instead, which made every row below it move — and
 * since a live transcript grows on every poll, the row the operator wanted next kept
 * sliding away from the cursor. See `SubagentDetail`.
 */
export function SubagentsSurface(props: {
  subagents: () => Subagent[];
  /** Re-read the cards — after a decision the operator just gave one of them. */
  onSettled?: () => void;
}): JSX.Element {
  const [openId, setOpenId] = createSignal<string | null>(null);

  // Resolved against the live list rather than held as an object: the panel re-reads
  // these while anything is working, and a captured card would go on showing the status
  // and the context figures it had when it was clicked.
  const open = createMemo(
    () => props.subagents().find((s) => s.id === openId()) ?? null,
  );

  // Failed and cancelled sit with the live ones — see the note above. `cancelled` is
  // there for the same reason in a quieter register: a sub-agent the operator stopped,
  // or one a restart closed out, did not do its job either.
  const showing = (): Subagent[] =>
    props
      .subagents()
      .filter((s) => isLive(s) || s.status !== "done")
      .sort(byUrgency);
  const finished = (): Subagent[] =>
    props.subagents().filter((s) => s.status === "done");
  // Derived once and read twice, and it is the count that decides the wording as well as
  // supplying its number — a thread with nothing in the panel has neither "0 working" nor
  // "0 done" to say, and says nothing.
  const working = (): number => props.subagents().filter(isLive).length;

  const card = (subagent: Subagent): JSX.Element => (
    <SubagentCard subagent={subagent} onOpen={() => setOpenId(subagent.id)} />
  );

  return (
    <div class="flex h-full min-h-0 flex-col gap-2 px-3 py-2">
      {/* One sub-agent, or all of them — never both. A sub-agent that is closed out
          while its view is open (a thread switch, a cancel) resolves to nothing and
          drops back to the list rather than holding a stale card on screen.

          Unkeyed, deliberately: every poll hands back freshly built cards, so a keyed
          `Show` would see a new object every few seconds and tear the whole view down
          and build it again — remounting the transcript, losing its scroll position and
          re-reading it from scratch, which is the exact instability this pane was made
          to stop. The accessor keeps the same view alive and lets the new figures
          through it. */}
      <Show when={open()}>
        {(subagent) => (
          <SubagentDetail
            subagent={subagent()}
            onBack={() => setOpenId(null)}
            onSettled={props.onSettled}
          />
        )}
      </Show>

      <Show when={!open()}>
        <div class="flex min-h-0 flex-col gap-2 overflow-y-auto">
          <div class="flex items-baseline justify-between gap-2">
            <Text variant="label" tone="bright">
              Agents
            </Text>
            <Show when={props.subagents().length > 0}>
              <Text variant="micro" tone="dim">
                {working() > 0
                  ? `${working()} working`
                  : `${props.subagents().length} done`}
              </Text>
            </Show>
          </div>

          <Show
            when={showing().length > 0 || finished().length > 0}
            fallback={
              <EmptyState
                message="No sub-agents yet"
                hint="Work the agent hands to a sub-agent shows up here while it happens."
              />
            }
          >
            <div class="flex flex-col gap-1.5">
              <For each={showing()}>{card}</For>
            </div>
          </Show>

          <Show when={finished().length > 0}>
            <Disclosure label={`Finished (${finished().length})`}>
              <div class="flex flex-col gap-1.5 pt-1">
                <For each={finished()}>{card}</For>
              </div>
            </Disclosure>
          </Show>
        </div>
      </Show>
    </div>
  );
}
