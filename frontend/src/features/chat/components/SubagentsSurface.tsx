import { For, Show, createSignal, type JSX } from "solid-js";
import { Disclosure, EmptyState, Text } from "~/ui";
import { isLive, type Subagent } from "../data";
import { SubagentApproval } from "./SubagentApproval";
import { SubagentCard } from "./SubagentCard";
import { SubagentTranscript } from "./SubagentTranscript";

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
 * **A card opens its transcript, and only one at a time.** Two open transcripts is two
 * scroll positions in a pane with room for neither.
 */
export function SubagentsSurface(props: {
  subagents: () => Subagent[];
  /** Re-read the cards — after a decision the operator just gave one of them. */
  onSettled?: () => void;
}): JSX.Element {
  const [openId, setOpenId] = createSignal<string | null>(null);

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

  const toggle = (id: string): void => {
    setOpenId((current) => (current === id ? null : id));
  };

  const card = (subagent: Subagent): JSX.Element => (
    <div class="flex flex-col gap-1">
      <SubagentCard
        subagent={subagent}
        expanded={openId() === subagent.id}
        onToggle={() => toggle(subagent.id)}
      />
      <Show when={openId() === subagent.id}>
        <Show when={subagent.status === "blocked"}>
          <SubagentApproval
            subagent={subagent}
            onSettled={() => props.onSettled?.()}
          />
        </Show>
        <SubagentTranscript subagent={subagent} />
      </Show>
    </div>
  );

  return (
    <div class="flex h-full flex-col gap-2 overflow-y-auto px-3 py-2">
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
  );
}
