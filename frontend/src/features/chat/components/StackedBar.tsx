import { For, type JSX } from "solid-js";

/** One run of a stacked bar: how wide, and which neutral step it is drawn in. */
export interface BarSegment {
  key: string;
  /** Share of the bar's full width, 0–100. */
  share: number;
  /** A background utility (`bg-dim` / `bg-text` / `bg-bright` / `bg-line`). */
  fill: string;
}

/** A hairline bar split into runs, drawn against a fixed track.
 *
 *  Shared by the context gauge's fullness bar and the compaction divider's before/after
 *  pair, which are the same picture asked two questions: what is this bar's full width,
 *  and how much of it is spent. Having one of them is what keeps the two reading as the
 *  same instrument rather than as two charts that happen to be near each other.
 *
 *  **What it deliberately does not own** is the denominator. A caller passes shares, so
 *  the decision of what 100% *means* — the model's window in one case, the larger of the
 *  two token figures in the other — stays with the surface that can explain it. A bar
 *  that normalised its own input would quietly answer a different question in each place.
 *
 *  Colour is never a category here: the fills are luminance steps, because in this
 *  codebase hue means severity and nothing else. */
export function StackedBar(props: {
  segments: BarSegment[];
  /** Tailwind height utility. The gauge's bar is `h-1`; callers wanting a heavier
   *  reading pass their own rather than scaling this one with a variant. */
  height?: string;
}): JSX.Element {
  return (
    <div
      class={`flex w-full overflow-hidden rounded-ctl bg-line ${props.height ?? "h-1"}`}
    >
      <For each={props.segments}>
        {(segment) => (
          <div
            class={`h-full ${segment.fill}`}
            style={{ width: `${segment.share}%` }}
          />
        )}
      </For>
    </div>
  );
}
