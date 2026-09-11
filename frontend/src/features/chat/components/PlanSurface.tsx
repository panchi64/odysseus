import { type JSX } from "solid-js";
import { Text } from "~/ui";
import type { PlanItem } from "~/lib/stream/events";
import { PlanRows, planSummary } from "./PlanRows";

/**
 * The agent's task list, as a surface.
 *
 * It has lived under the composer, folded into the status strip, where it was a
 * five-row window on a list in a band sized for one-line readouts — a thing you
 * expand, read, and collapse again because it is in the way of the thing it is
 * about. Beside the transcript it is just there, next to the work it describes.
 *
 * **A strip, not a panel.** A plan is a handful of short rows and takes its own
 * height; giving it a full-height pane would hand most of the panel to whitespace
 * and push whatever the operator is actually reading out of view. `PlanRows` is
 * reused exactly as the status strip uses it — the rows are the same rows, and a
 * second renderer for them would be a second thing to keep in step.
 */
export function PlanSurface(props: {
  items: () => PlanItem[];
  /** Rows before the list scrolls inside itself rather than growing. Roughly
   *  `maxRows` × the row's line box; an exact height would need measuring, and
   *  being a little generous costs nothing a scrollbar does not fix. */
  maxRows: number;
}): JSX.Element {
  // Cancelled tasks are already out of `total`, so this counts what the plan is
  // still claiming it will do rather than everything it ever said.
  const progress = (): string => {
    const { done, total } = planSummary(props.items());
    return `${done}/${total}`;
  };

  return (
    <div class="flex flex-col gap-1 px-3 py-2">
      <div class="flex items-baseline justify-between gap-2">
        <Text variant="label" tone="bright">
          Plan
        </Text>
        <Text variant="micro" tone="dim">
          {progress()}
        </Text>
      </div>
      <div
        class="overflow-y-auto"
        style={{ "max-height": `${props.maxRows * 1.75}rem` }}
      >
        <PlanRows items={props.items} />
      </div>
    </div>
  );
}
