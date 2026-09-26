import { Match, Show, Switch, createMemo, type JSX } from "solid-js";
import { MetClock, type Status } from "~/ui";
import type { ChatActivity, ChatOutcome } from "../model";
import type { RunClock } from "../stream/fold";
import { resolveRunState, runStateSpec } from "../runState";

export interface ComposerHeaderStatusProps {
  /** The room's stream is driving a run — a turn, or a hand-started fold. */
  streaming: () => boolean;
  /** That run is a fold rather than a turn. */
  compacting: () => boolean;
  /** The live run's transport gave up reconnecting. */
  detached: () => boolean;
  /** The run's own start instant and newest step, as the stream reported them. */
  runClock: () => RunClock | null;
  /** The backend's status for this thread's live run, when it has one. */
  activity: () => ChatActivity | undefined;
  /** How this thread's last terminal run ended, when the backend still remembers. */
  lastOutcome: () => ChatOutcome | undefined;
}

/* One Status → text colour, as the header line's pieces carry their own tone. The line
   is `plate` type already, so a `Text` here would restate a size it cannot change. */
const STATUS_CLASS: Record<Status, string> = {
  idle: "",
  live: "text-nominal",
  nominal: "text-nominal",
  warn: "text-warn",
  alert: "text-alert",
  info: "text-info",
};

/**
 * The left of the composer's header line: what the input — and the thread behind it —
 * is doing. `Input` when there is nothing to report, which is most of the time.
 *
 * **This is where the thread's state is said now.** It used to fly as a flag in an
 * eyebrow above the title, beside the model name and a clock of the thread's age; the
 * model moved to the status bar and the rest was clutter over a title. What could not
 * be dropped is a state that needs the operator — a failed run, one stopped at a limit —
 * so it lands here, in the line the operator reads before they type the next message.
 *
 * **Precedence, highest first**, and each rung says why it outranks the next:
 * - `Disconnected` — a run whose transport gave up is still guarded as in flight, so the
 *   run marker and its clock would go on ticking over a run nothing is listening to.
 * - The live run: `● Run` (or `● Folding` for a hand-started fold, which is a run of
 *   its own), its clock from the backend's `run.started` instant and the step it is on.
 *   A piece the stream has not reported is left out, never estimated.
 * - The resolved run state from the same `runState.ts` table the rail reads — except
 *   `done`, which is the ordinary ending and says nothing `Input` does not. So a
 *   failed, blocked or cancelled run, and one the backend reports live that this room
 *   is not driving, are named in their own tone; two surfaces wording one fact
 *   differently is how a room calls a run finished while its rail row is lit amber.
 */
export function ComposerHeaderStatus(
  props: ComposerHeaderStatusProps,
): JSX.Element {
  const atRest = createMemo(() => {
    const s = resolveRunState(props.activity(), props.lastOutcome());
    return s && s !== "done" ? runStateSpec(s) : undefined;
  });

  return (
    <Switch fallback="Input">
      <Match when={props.detached()}>
        <span class="text-alert">Disconnected</span>
      </Match>
      <Match when={props.streaming()}>
        <span class="text-info">
          ● {props.compacting() ? "Folding" : "Run"}
        </span>
        <Show when={props.runClock()}>
          {(clock) => (
            <>
              {" · "}
              <MetClock variant="plate" startedAt={clock().startedAt} />
              <Show when={clock().step}>{(step) => ` · Step ${step()}`}</Show>
            </>
          )}
        </Show>
      </Match>
      <Match when={atRest()}>
        {(s) => <span class={STATUS_CLASS[s().status]}>● {s().readout}</span>}
      </Match>
    </Switch>
  );
}
