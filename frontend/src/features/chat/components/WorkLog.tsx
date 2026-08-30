import { For, createMemo, type JSX } from "solid-js";
import { Collapse } from "~/ui";
import type { BlockGroup } from "../blocks";
import { workShape } from "../workShape";
import {
  BlockRow,
  fullWidthTop,
  type RowHandlers,
  type TopSpacing,
} from "./BlockRow";
import { WorkLogHeader } from "./WorkLogHeader";

/** The compacted work log: one run of consecutive process blocks folded into a
 *  single accordion, so a busy turn doesn't bury the screen. Expanding restores
 *  the full ordered run.
 *
 *  The header leads with the *shape* of what folded — the tools by name, with
 *  their counts — rather than a step count. See `WorkLogHeader`.
 *
 *  Nothing that must be seen ends up in here: `isCollapsible` in `blocks.ts`
 *  keeps a call in flight, a pending approval and, since this rework, a failure
 *  out of the fold entirely. */
export function WorkLog(
  props: {
    groups: BlockGroup[];
    /** Open state is owned by the turn (keyed by a stable id) so it survives the
     *  remount when a streaming delta rebuilds the layout — a local signal here
     *  would reset on every new block. */
    open: boolean;
    onToggle: () => void;
    forceOpen?: boolean;
    top?: TopSpacing;
  } & RowHandlers,
): JSX.Element {
  const shape = createMemo(() => workShape(props.groups));

  return (
    <div class={fullWidthTop(props.top)}>
      <WorkLogHeader
        shape={shape()}
        open={props.open}
        onToggle={() => props.onToggle()}
      />
      {/* `Collapse` rather than a bare `Show`: folding a run of a dozen rows
          away instantly takes everything below it with it, which is a jump the
          reader has to recover their place after. */}
      <Collapse open={props.open}>
        <div class="mt-2">
          {/* Folded groups are mostly rail blocks (they connect into one line); a
              View chip in the run renders full-width between them. */}
          <For each={props.groups}>
            {(group, i) => (
              <BlockRow
                group={group}
                top={i() === 0 ? "none" : "connect"}
                forceOpen={props.forceOpen}
                onResolveApproval={props.onResolveApproval}
                onResolveHostCommands={props.onResolveHostCommands}
                chipLookup={props.chipLookup}
                seenIndex={props.seenIndex}
              />
            )}
          </For>
        </div>
      </Collapse>
    </div>
  );
}
