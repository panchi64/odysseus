import type { ContextSegment } from "~/lib/stream";
import { segmentLabel } from "../contextLabels";
import type { ContextUsage } from "../model";

/** A line in the breakdown: one of the three groups the window is filled by, or the
 *  room left in it. */
export interface ContextRow {
  key: string;
  label: string;
  /** The neutral step this row is drawn in, in the bar and in its swatch. */
  fill: string;
  tokens: number;
  /** Share of the **window** (not of `used`), 0–100 — so every row on the panel,
   *  free space included, is measured against the same ceiling and they total 100. */
  share: number;
  /** What this row is made of, when the backend itemised it. Empty ⇒ no disclosure. */
  detail: ContextDetail[];
}

export interface ContextDetail {
  key: string;
  label: string;
  tokens: number;
  /** Tools in a category; null where there is no population to report. */
  count: number | null;
}

/** The three groups, in the order they are stacked — smallest and most fixed first, so
 *  the bar reads left to right as "what I can't change, then what I can", and the list
 *  below it reads in the same order rather than making the operator re-find each row.
 *
 *  **Distinguished by luminance, not by hue.** Three arbitrary colours would be the
 *  obvious way to key a legend, and it is the one thing the palette rule forbids:
 *  colour here means severity and nothing else, so spending three hues on category
 *  labels would leave the amber that matters competing with a purple that doesn't.
 *  Neutral steps carry the same distinction — and they order the parts by weight while
 *  they do it, since the brightest is the one the operator can actually act on. */
const GROUPS = [
  { group: "brief", key: "system", label: "Standing brief", fill: "bg-dim" },
  { group: "tools", key: "tools", label: "Tool schemas", fill: "bg-text" },
  { group: "messages", key: "messages", label: "Messages", fill: "bg-bright" },
] as const satisfies readonly {
  group: ContextSegment["group"];
  key: "system" | "tools" | "messages";
  label: string;
  fill: string;
}[];

/** The panel's rows, in bar order, from the backend's composition.
 *
 *  Nothing here decides anything: the tokens are the backend's, the grouping is the
 *  backend's `group` field, and the only arithmetic is the share of the window each
 *  figure is — which is the bar's geometry, and so presentation.
 *
 *  **Rows appear as they earn their place.** A group with no measured weight is left
 *  out entirely rather than shown as a zero, and so is a detail line, because the
 *  backend already omits what rounds to nothing. What the operator sees is the list of
 *  things actually costing them the window, which on a fresh thread is two rows and on
 *  a long tool-heavy one is a dozen. */
export function contextRows(usage: ContextUsage): ContextRow[] {
  const parts = usage.parts;
  const share = (tokens: number) =>
    Math.max(0, Math.min(100, (tokens / usage.window) * 100));

  const rows: ContextRow[] = [];
  if (parts) {
    for (const group of GROUPS) {
      const tokens = parts[group.key];
      if (tokens <= 0) continue;
      rows.push({
        key: group.key,
        label: group.label,
        fill: group.fill,
        tokens,
        share: share(tokens),
        detail: parts.segments
          .filter((segment) => segment.group === group.group)
          .sort((a, b) => b.tokens - a.tokens)
          .map((segment) => ({
            key: segment.id,
            label: segmentLabel(segment.id),
            tokens: segment.tokens,
            count: segment.count,
          })),
      });
    }
  } else {
    // No split measured: one undifferentiated row, at the weight the largest group
    // would have had. Better than three confident guesses.
    rows.push({
      key: "used",
      label: "In use",
      fill: "bg-bright",
      tokens: usage.used,
      share: share(usage.used),
      detail: [],
    });
  }

  // Free space last, and always present — it is the only row that answers the question
  // the operator opened a *window* gauge to ask, which is not "what is in there" but
  // "how much room is left".
  const free = Math.max(0, usage.window - usage.used);
  rows.push({
    key: "free",
    label: "Free space",
    fill: "bg-line",
    tokens: free,
    share: share(free),
    detail: [],
  });
  return rows;
}

/** Where the fold sits on the bar, and how much room is left before it fires. */
export interface FoldMarker {
  /** Its position along the **window**, 0–100 — the same scale the rows use, so the
   *  mark and the fill are read against one ceiling. */
  pct: number;
  /** Tokens between here and the fold. 0 once the thread is past it. */
  headroomTokens: number;
  /** Whether folding is switched on for this thread. A paused fold still draws, dimmed:
   *  where the fold *would* be is what tells the operator what the pause is costing. */
  active: boolean;
  /** True once fullness has reached the fold point — with folding on this is a
   *  momentary state (the next turn folds), and with it off it is where a thread sits
   *  while it spends the room the fold was going to reclaim. */
  passed: boolean;
}

/** The fold mark for a usage reading, or null when the backend reported no policy.
 *
 *  Derived here rather than in the component for the reason every readout in this
 *  codebase is: a screen renders a derivation, it doesn't perform one. Null and
 *  `active: false` are deliberately different answers — null means "nothing to say",
 *  while inactive means "here, but not armed", and only one of them draws. */
export function foldMarker(usage: ContextUsage): FoldMarker | null {
  const fold = usage.fold;
  if (!fold || !usage.window) return null;
  return {
    pct: Math.min(100, Math.max(0, fold.fraction * 100)),
    headroomTokens: Math.max(
      0,
      Math.round(fold.fraction * usage.window - usage.used),
    ),
    active: fold.active,
    passed: usage.fraction >= fold.fraction,
  };
}
