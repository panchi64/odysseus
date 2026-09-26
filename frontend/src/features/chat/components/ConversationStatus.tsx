import { createMemo, createSignal, Show, type JSX } from "solid-js";
import { StatusCell } from "~/ui";
import type { TaskItem } from "~/lib/stream";
import type { ContextUsage, ConversationStats } from "../model";
import { ContextBar } from "./ContextBar";
import { ConversationStatsPanel } from "./ConversationStatsPanel";
import { taskSummary, TaskRows } from "./TaskRows";

export interface ConversationStatusProps {
  conversationId: () => string | null;
  stats: () => ConversationStats | null | undefined;
  usage: () => ContextUsage | null;
  /** The agent's task list for this thread (backend-owned, read-only). */
  tasks: () => TaskItem[];
  /** Ticks when a grant may have changed, so the stats panel's grants row refetches. */
  grantsRevalidate: () => unknown;
}

export interface ConversationStatus {
  /** The status bar's trailing cells: `Tasks x/y` · `Stats` · the context bar. Each is one `StatusCell`, so the caller can drop them into any
   *  `StatusBar` group. */
  items: () => JSX.Element;
  /** The task rows `Tasks` discloses, for directly under that row. */
  taskRows: () => JSX.Element;
}

/** **What this conversation is doing, at a glance**, as the end of the row under the
 *  composer — what used to be `ConversationStatusStrip`, a line of its own.
 *
 *  Two render functions rather than one component, because the pieces land in two
 *  places that share one piece of state: the `Tasks` toggle sits in the Composer's
 *  `trailing` slot, and the rows it opens sit *below* the Composer, outside it. The
 *  open state is the one thing both need, so it lives here and each half reads it. A
 *  function rather than a node for each, so either can be mounted afresh — the row goes
 *  with the Composer while a run is parked and comes back with it.
 *
 *  **It does not report what the stream is doing.** A transport word — Streaming, Idle,
 *  Resyncing — restated what the transcript already shows by animating, in the place
 *  the operator is looking. The one that survived, `Disconnected`, moved to the
 *  composer's header line: a dead stream is the one state the transcript can't show by
 *  moving, and it belongs where the run's own marker and clock would otherwise go on
 *  claiming a run that nothing is listening to.
 *
 *  **What remains on the row is what changes turn to turn.** The task count, and the
 *  context bar (the one figure with a ceiling). Every tally — turns, time, speed,
 *  cache, tokens — and the thread's two settings moved behind `Stats`: individually each
 *  was small enough to dismiss, together they buried the input they sat under.
 *
 *  Every piece is a `StatusCell` of the composer's status bar: the same mono line as
 *  the readouts beside it, with only the hover saying which cells act. */
export function createConversationStatus(
  props: ConversationStatusProps,
): ConversationStatus {
  const [tasksOpen, setTasksOpen] = createSignal(false);
  const summary = createMemo(() => taskSummary(props.tasks()));
  const hasTasks = () => props.tasks().length > 0;

  const items = (): JSX.Element => (
    <>
      {/* The count and the active flag answer "how far along" on their own; the task
          text is what the operator opens when the answer is "not far". */}
      <Show when={hasTasks()}>
        <StatusCell
          active={tasksOpen()}
          aria-expanded={tasksOpen()}
          aria-label={tasksOpen() ? "Hide the tasks" : "Show the tasks"}
          onClick={() => setTasksOpen((v) => !v)}
          class="tabular-nums"
        >
          Tasks {summary().done}/{summary().total}
          {/* Info blue, not warn amber: a running task is live data. */}
          <Show when={summary().active}>
            <span class="text-info">· active</span>
          </Show>
        </StatusCell>
      </Show>

      <ConversationStatsPanel
        conversationId={props.conversationId}
        stats={props.stats}
        grantsRevalidate={props.grantsRevalidate}
      />

      {/* Only once a run has reported. The gauge used to be unconditional and paint an
          alert-toned "context window unknown" whenever it had nothing — which on a
          brand-new thread is simply *before the first turn*, so a fresh chat opened on
          a red gauge announcing a fault that had not been established. The
          genuinely-unknown case is the send gate's, which blocks SEND and explains. */}
      <Show when={props.usage()}>
        {(usage) => (
          <ContextBar
            usage={usage()}
            lastRequest={props.stats()?.lastRequest}
          />
        )}
      </Show>
    </>
  );

  // The rows open downward from the row that discloses them, inside the same sticky
  // dock — so opening the list grows the dock rather than scrolling the transcript out
  // from under it.
  const taskRows = (): JSX.Element => (
    <Show when={tasksOpen() && hasTasks()}>
      <div class="pt-2">
        <TaskRows items={props.tasks} />
      </div>
    </Show>
  );

  return { items, taskRows };
}
