import { createMemo, Index, Show, type JSX } from "solid-js";
import { ListGroupHeader } from "~/ui";
import type { TaskItem } from "~/lib/stream/events";
import type { Subagent } from "../data";
import { groupTasks } from "../taskGroups";
import { TaskRows } from "./TaskRows";

/**
 * The agent's task list, as a surface — **and its sub-agents' lists under it**.
 *
 * It has lived under the composer, folded into the status strip, where it was a
 * five-row window on a list in a band sized for one-line readouts — a thing you
 * expand, read, and collapse again because it is in the way of the thing it is
 * about. Beside the transcript it is just there, next to the work it describes.
 *
 * **A strip, not a panel** — and the one thing that distinguishes it from the plan
 * surface beside it. This is a handful of short rows that takes its own height;
 * giving it a full-height pane would hand most of the panel to whitespace and push
 * whatever the operator is actually reading out of view. A plan is read end to end
 * before answering, so that one is a panel. `TaskRows` is reused exactly as the
 * status strip uses it — the rows are the same rows, and a second renderer for them
 * would be a second thing to keep in step.
 *
 * **A delegated list is a heading, not more rows.** Work handed to a sub-agent used to
 * be invisible here: its list lives in its own thread, so this surface showed the
 * launching turn's four steps and said nothing about the four sub-agents working through
 * lists of their own. `groupTasks` is the whole of that rule; see it for why the lists
 * are kept apart rather than interleaved.
 */
export function TasksSurface(props: {
  items: () => TaskItem[];
  /** The thread's sub-agents, for the lists they are keeping for themselves. */
  subagents: () => Subagent[];
  /** Rows before the list scrolls inside itself rather than growing. Roughly
   *  `maxRows` × the row's line box; an exact height would need measuring, and
   *  being a little generous costs nothing a scrollbar does not fix. */
  maxRows: number;
}): JSX.Element {
  const groups = createMemo(() => groupTasks(props.items(), props.subagents()));

  return (
    // No title and no progress figure: the pane's frame draws both, for every surface
    // rather than for the three that happened to draw their own. The count it shows is
    // this same derivation — see `SURFACE_META`.
    <div class="flex w-full flex-col gap-1 px-3 pb-2">
      <div
        class="overflow-y-auto"
        style={{ "max-height": `${props.maxRows * 1.75}rem` }}
      >
        {/* `Index`, not `For`: `groupTasks` builds fresh objects every time it runs, and
            it runs on every sub-agent poll — a reference-keyed `For` would therefore
            dispose and rebuild every `TaskRows` a few seconds apart, collapsing a list
            the operator had just expanded with +N MORE. Indexing by position keeps each
            group's rows alive and lets the new items through them. */}
        <Index each={groups()}>
          {(group) => (
            <>
              <Show when={group().label}>
                {(label) => <ListGroupHeader label={label()} />}
              </Show>
              <TaskRows items={() => group().items} />
            </>
          )}
        </Index>
      </div>
    </div>
  );
}
