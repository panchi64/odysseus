import { For, Show, createMemo, type JSX } from "solid-js";
import { Collapse } from "~/ui";
import type { WorkLogEntry } from "../blocks";
import { workShape } from "../workShape";
import {
  BlockRow,
  fullWidthTop,
  type RowHandlers,
  type TopSpacing,
} from "./BlockRow";
import { WorkLogHeader } from "./WorkLogHeader";

/** The turn's account of what it did: one log per turn, in order, under one
 *  header.
 *
 *  The header leads with the run's *last step*, in the same `glyph · Label ·
 *  detail` anatomy the rows inside use — not a step count, and no longer a
 *  per-tool tally. See `WorkLogHeader`.
 *
 *  **Some rows the fold may not hide, and they stay in place rather than outside.**
 *  A call in flight, a failure, a screenshot and a refusal are all pinned
 *  (`pinsRunInline` in `blocks.ts`), and they used to be pinned by being *ejected*
 *  from the log — which ended it and started a second one underneath with the same
 *  name. A turn with one failed call rendered as three separate items the operator
 *  had to reassemble into one sequence. The promise was only ever that such a row
 *  stays visible; it is kept here by rendering it outside the fold's collapse while
 *  leaving it where it happened.
 *
 *  That is why this walks one list and gates each row individually instead of
 *  wrapping the whole run in one `Collapse`: the fold has to be able to close
 *  around a pinned row without closing over it. */
export function WorkLog(
  props: {
    entries: WorkLogEntry[];
    /** Open state is owned by the turn (keyed by a stable id) so it survives the
     *  remount when a streaming delta rebuilds the layout — a local signal here
     *  would reset on every new block. */
    open: boolean;
    onToggle: () => void;
    forceOpen?: boolean;
    top?: TopSpacing;
    /** Groups with a call in flight, for the rail's LED. Read here because a live
     *  call is now pinned *inside* the log rather than lifted out of it. */
    activeIds?: ReadonlySet<string>;
    streaming?: boolean;
  } & RowHandlers,
): JSX.Element {
  const shape = createMemo(() => workShape(props.entries.map((e) => e.group)));
  /* What the header counts. A pinned row is already on screen, so counting it
     among what "opening this would reveal" overstates the fold — the operator
     reads `5 steps`, opens it, and two rows appear. */
  const hidden = createMemo(
    () => props.entries.filter((e) => !e.pinned).length,
  );
  /* Every row is on screen already, so the chevron would open onto nothing. */
  const foldable = createMemo(() => hidden() > 0);
  /** Whether the foldable segments are showing. `forceOpen` is the turn's expand-all. */
  const open = () => props.open || props.forceOpen === true;

  /* Consecutive rows of the same kind, in order.
   *
   *  Two things fall out of segmenting once instead of deciding per row. A stretch of
   *  foldable rows shares **one** `Collapse` — the shape the log had before a pinned row
   *  was allowed to sit inside it, and the reason matters: a `Collapse` per row is a
   *  height measurement and a transition per row, so a forty-call turn folded in forty
   *  independent animations where one would do. And each row's rail spacing becomes a
   *  running fact rather than a rescan of everything above it, which is what that
   *  spacing cost when every row sliced its own prefix. */
  const segments = createMemo(() => {
    const out: { pinned: boolean; rows: WorkLogEntry[] }[] = [];
    for (const entry of props.entries) {
      const tail = out[out.length - 1];
      if (tail && tail.pinned === entry.pinned) tail.rows.push(entry);
      else out.push({ pinned: entry.pinned, rows: [entry] });
    }
    return out;
  });

  return (
    <div class={fullWidthTop(props.top)}>
      <WorkLogHeader
        shape={shape()}
        steps={hidden()}
        open={props.open}
        foldable={foldable()}
        onToggle={() => props.onToggle()}
      />
      <div class="mt-2">
        <For each={segments()}>
          {(segment, s) => {
            /* Whether anything is drawn above this segment, which is what decides if
               its first row joins the rail above or starts it. Every earlier segment
               shows when the log is open; shut, only the pinned ones do. */
            const anythingAbove = () =>
              s() > 0 &&
              (open() || segments().some((seg, j) => j < s() && seg.pinned));
            const rows = (
              <For each={segment.rows}>
                {(entry, i) => (
                  <BlockRow
                    group={entry.group}
                    active={props.activeIds?.has(entry.group.id)}
                    streaming={props.streaming}
                    top={i() > 0 || anythingAbove() ? "connect" : "none"}
                    forceOpen={props.forceOpen}
                    onResolveHostCommands={props.onResolveHostCommands}
                    onOpenInView={props.onOpenInView}
                    chipLookup={props.chipLookup}
                    seenIndex={props.seenIndex}
                  />
                )}
              </For>
            );
            /* `Collapse` rather than a bare `Show`: folding a stretch of rows away
               instantly takes everything below it with it, which is a jump the reader
               has to recover their place after. A pinned segment skips it entirely —
               it is never the thing being folded. */
            return (
              <Show when={!segment.pinned} fallback={rows}>
                <Collapse open={open()}>{rows}</Collapse>
              </Show>
            );
          }}
        </For>
      </div>
    </div>
  );
}
