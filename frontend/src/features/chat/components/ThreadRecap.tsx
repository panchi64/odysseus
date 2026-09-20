import { For, Show, createMemo, type JSX } from "solid-js";
import { Button, ConsoleGroup, StatusDot, Text } from "~/ui";
import { relativeTime } from "~/lib/format";
import { sessionModeSpec } from "~/lib/modes";
import type { BranchState } from "../data";
import type { ChatSummary } from "../model";
import { resolveRunState, runStateSpec } from "../runState";

export interface ThreadRecapProps {
  /** The thread, as the shared session list already knows it. */
  summary: () => ChatSummary | undefined;
  /** Its branch, for a code thread; null or undefined for every other mode. */
  branch: () => BranchState | null | undefined;
  /** True while a run is driving this thread — a recap is for a thread at rest. */
  streaming: () => boolean;
  /** Put it away for this visit. */
  onDismiss: () => void;
}

/** One legend over one value — the whole vocabulary of the band. */
function Cell(props: {
  label: string;
  value: JSX.Element;
  /** A state mark before the value, for the one cell that carries a state. */
  mark?: JSX.Element;
}): JSX.Element {
  return (
    <div class="flex min-w-0 flex-col gap-0.5 px-2 py-1">
      {/* `plate` names the cell, `meta` reports what is in it — the legend/readout
          split (§4), which is also what keeps two lines of mono from reading as one
          block of grey. */}
      <Text variant="plate" tone="dim">
        {props.label}
      </Text>
      <span class="flex min-w-0 items-center gap-1.5">
        {props.mark}
        <Text variant="meta" tone="default" class="min-w-0 truncate">
          {props.value}
        </Text>
      </span>
    </div>
  );
}

/**
 * What this thread is, for an operator who has just come back to it.
 *
 * **The problem it solves is re-entry, not summary.** Opening a thread from three days
 * ago drops you at the bottom of a transcript, mid-argument, with a title above it and
 * nothing else — what kind of thread this is, how old it is, how much of it there is,
 * whether the last run even finished, and (for a code thread) what is sitting on the
 * branch are all answerable only by scrolling up through the thing you were trying to
 * orient yourself in first.
 *
 * **Every figure here already existed.** Mode, `created_at`, `message_count` and the
 * terminal outcome ride on the session list the rail is already reading; the branch and
 * its diffstat ride on the read the header's chip and the Changes surface already
 * share. Nothing new is fetched and nothing is computed — the only derivations are
 * formatting ones (`relativeTime`, a mode's label), which is the line the frontend is
 * allowed to be on.
 *
 * **It is a `ConsoleGroup` and not a card**, which is the §7 case: fixed cells read by
 * scanning, flush by construction, with the frame saying where the readout begins and
 * ends. Prose would want a `Panel`; this is six values in a row.
 *
 * **It sits above the transcript rather than in it.** A recap folded into the scroll
 * would be a message that is not one, at the top of a thread nobody scrolls to. Pinned
 * under the header it is where re-entry actually happens — and it is dismissible,
 * because the second thing an operator does after orienting is want the space back.
 *
 * Absent for a thread with nothing to recap: a fresh composer, a one-turn thread, and
 * any thread with a run in flight, where the live state is the answer and a summary of
 * the last one would be reporting the past over the present.
 */
export function ThreadRecap(props: ThreadRecapProps): JSX.Element {
  /** The thread's state at rest. `activity` is still consulted — a run that is live
   *  means this is not a cold thread at all, and the band should not be up. */
  const state = createMemo(() => {
    const s = props.summary();
    return s ? resolveRunState(s.activity, s.lastOutcome) : undefined;
  });

  const cold = createMemo(() => {
    const s = props.summary();
    if (!s || props.streaming()) return false;
    // Two turns, not one: a thread with a single exchange in it is already entirely on
    // screen, and a band recapping what the operator can see is furniture.
    if (s.messageCount < 2) return false;
    const st = state();
    return !(st && runStateSpec(st).live);
  });

  const cells = createMemo((): { label: string; value: string }[] => {
    const s = props.summary();
    if (!s) return [];
    const b = props.branch();
    const rows = [
      { label: "MODE", value: sessionModeSpec(s.mode).label },
      { label: "OPENED", value: relativeTime(s.createdAt) },
      { label: "TURNS", value: String(s.messageCount) },
    ];
    if (b) {
      rows.push({ label: "BRANCH", value: b.branch });
      rows.push({
        label: "CHANGES",
        value: `${b.filesChanged} FILE${b.filesChanged === 1 ? "" : "S"} +${b.insertions} −${b.deletions}`,
      });
      // On `> 0`, not on presence: the backend sends 0 both for "level with the base"
      // and for "could not tell", and a cell reading `0 BEHIND` claims the first.
      if (b.behind > 0) {
        rows.push({ label: "BEHIND", value: `${b.behind} COMMITS` });
      }
      if (b.lastCommitAt) {
        rows.push({
          label: "LAST COMMIT",
          value: relativeTime(b.lastCommitAt),
        });
      }
    }
    return rows;
  });

  return (
    <Show when={cold()}>
      <ConsoleGroup
        label="Thread recap"
        class="mb-3"
        right={
          <Button
            variant="ghost"
            size="sm"
            aria-label="Dismiss thread recap"
            onClick={() => props.onDismiss()}
          >
            ✕
          </Button>
        }
      >
        <div class="flex flex-wrap items-start gap-x-2 gap-y-1">
          <For each={cells()}>
            {(cell) => <Cell label={cell.label} value={cell.value} />}
          </For>
          {/* Last, and with the only mark in the band: how the thread's last run ended
              is the one cell an operator is looking *for* rather than reading past, and
              the trailing position is where the eye lands after the diffstat. Absent
              when the backend has nothing to say — the run registry is bounded, so a
              thread that plainly finished can carry no outcome, and a cell reading
              UNKNOWN would invent a state out of a missing record. */}
          <Show when={state()}>
            {(st) => (
              <Cell
                label="Last run"
                value={runStateSpec(st()).readout}
                mark={<StatusDot status={runStateSpec(st()).status} />}
              />
            )}
          </Show>
        </div>
      </ConsoleGroup>
    </Show>
  );
}
