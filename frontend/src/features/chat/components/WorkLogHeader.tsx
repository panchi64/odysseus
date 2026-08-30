import { For, Show, type JSX } from "solid-js";
import { Icon, StatusFlag, Text, type IconName } from "~/ui";
import type { WorkShape } from "../workShape";
import { ProcessRow, Sep } from "./ProcessRow";

/** The glyph for reasoning. Not a tool, so it has no registry entry to borrow —
 *  `cpu` is the machine doing its own work, and it is unclaimed by any tool
 *  category, so it can't be mistaken for one. */
const THINK_ICON: IconName = "cpu";

/** One kind of work, as glyph + name + how many times. `×1` is suppressed: a
 *  count of one is the default reading, and printing it on every singleton turns
 *  a summary into a table. */
function Segment(props: {
  icon: IconName;
  label: string;
  count: number;
  dim?: boolean;
}): JSX.Element {
  return (
    <span class="flex shrink-0 items-center gap-1">
      <Icon name={props.icon} size={12} class="text-dim" />
      <Text variant="micro" tone={props.dim ? "dim" : "default"}>
        {props.label}
        {props.count > 1 ? ` ×${props.count}` : ""}
      </Text>
    </span>
  );
}

/** The collapsed work log's own line: what the run was made of.
 *
 *  This replaces `WORK LOG · 7 Steps`, which ranked every turn in a thread
 *  identically — twelve folded logs that all read the same say nothing about
 *  which one is worth opening. The shape does: `Read ×4 · Web search · Write`
 *  names the tools with their own glyphs, so a scroll back through a long
 *  conversation can find the turn that touched files or hit the network without
 *  expanding anything.
 *
 *  Two things are deliberately outside the truncating run of segments. The
 *  **failure flag** sits in the right cluster, so the cap and a narrow viewport
 *  can never be what hides a failure — the one thing in a turn that must not be
 *  missable. And the count is a **`+N` overflow**, not a longer line: past four
 *  segments the header stops being scannable and becomes the list the fold
 *  exists to avoid.
 *
 *  While the turn streams these counts tick upward, and they snap rather than
 *  ease — a value the machine is emitting, in the machine's register (§8). That
 *  is also the cheapest proof-of-life a one-second glance can get. */
export function WorkLogHeader(props: {
  shape: WorkShape;
  open: boolean;
  onToggle: () => void;
}): JSX.Element {
  const s = () => props.shape;
  return (
    <ProcessRow
      open={props.open}
      onToggle={props.onToggle}
      label="Work log"
      trailing={
        <Show when={s().failed > 0}>
          <StatusFlag status="alert">{`${s().failed} failed`}</StatusFlag>
        </Show>
      }
    >
      {/* One clipping container rather than per-segment truncation. A segment cut
          to "Web sea…" reads as a defect; a run of whole segments that stops at
          the edge reads as more of them being off-screen, which is what is
          actually true. */}
      <span class="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
        <For each={s().entries}>
          {(entry) => (
            <>
              <Sep />
              <Segment
                icon={entry.icon}
                label={entry.label}
                count={entry.count}
              />
            </>
          )}
        </For>
        <Show when={s().overflow > 0}>
          <Sep />
          <Text variant="micro" tone="dim" class="shrink-0">
            {`+${s().overflow}`}
          </Text>
        </Show>
        {/* Reasoning last and dim: it is work, but it is not an act on the
            world, so it should never crowd out a tool that was. */}
        <Show when={s().thinks > 0}>
          <Sep />
          <Segment icon={THINK_ICON} label="Reasoning" count={s().thinks} dim />
        </Show>
      </span>
    </ProcessRow>
  );
}
