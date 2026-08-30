/** What a folded run of work amounts to — the tools it actually used, not how
 *  many steps it took.
 *
 *  A step count ranks every turn in a thread identically: twelve collapsed logs
 *  reading `WORK LOG · 7 Steps` say nothing about which one is worth opening.
 *  What distinguishes them is *shape* — which tools ran, how often, and whether
 *  anything failed. "Read ×4 · Web search · Write" is the same line of pixels
 *  carrying the one fact the operator is scanning for.
 *
 *  Grouped by tool **name**, so the row keeps the specific identity
 *  `toolPresentation` gives it — `Read`, not the `files` family. Ordered by
 *  first appearance, so the summary reads in the order the work happened.
 *
 *  Pure data → data, like `blocks.ts`: no Solid, no DOM, so the rules stay
 *  testable and live in one place. */

import type { IconName } from "~/ui";
import { toolEntry, type ToolPresentation } from "./toolPresentation";
import type { BlockGroup } from "./blocks";

export interface WorkShapeEntry {
  /** Stable grouping key — the tool's registry name, or one of the synthetic
   *  keys below for the block kinds that are work but are not tool calls. */
  key: string;
  icon: IconName;
  label: string;
  count: number;
}

export interface WorkShape {
  /** In first-appearance order, capped at `SHAPE_MAX_ENTRIES`. */
  entries: WorkShapeEntry[];
  /** Distinct kinds of work past the cap, for a `+N` segment. */
  overflow: number;
  /** Failures anywhere in the run — reported separately so a failure is never
   *  the thing the cap drops. */
  failed: number;
  thinks: number;
}

/** Past four segments the header stops being scannable and becomes a list, which
 *  is the thing the fold exists to avoid. */
export const SHAPE_MAX_ENTRIES = 4;

/** Every host command is one entry however many there are — they are all the
 *  same act from the summary's point of view, and they borrow the registry
 *  entry of the tool that produces them so the glyph matches the card's. */
const HOST_KEY = "host";
const HOST_TOOL = "code_run_host_command";

/** A View version or the live head. Not a tool call, so it has no registry entry
 *  to borrow — but it is work that lands in a run, and a fold made only of View
 *  chips would otherwise summarize as nothing at all. */
const VIEW_KEY = "view";
const VIEW_ICON: IconName = "panel-right";
const VIEW_LABEL = "View";

/** The shape of a run of work groups — what the collapsed work log leads with. */
export function workShape(groups: BlockGroup[]): WorkShape {
  // A Map preserves insertion order, which IS the first-appearance order the
  // summary wants — no separate ordering pass.
  const byKey = new Map<string, WorkShapeEntry>();
  let failed = 0;
  let thinks = 0;

  /** `icon`/`label` are resolved only on first sight of a key — `toolEntry` is a
   *  table lookup plus a fallback humanize, and a run of forty reads shouldn't
   *  pay for it forty times. */
  const bump = (key: string, resolve: () => ToolPresentation): void => {
    const found = byKey.get(key);
    if (found) {
      found.count++;
      return;
    }
    const { icon, label } = resolve();
    byKey.set(key, { key, icon, label, count: 1 });
  };

  for (const group of groups) {
    for (const b of group.blocks) {
      switch (b.kind) {
        case "thinking":
          thinks++;
          break;
        case "tool":
          bump(b.tool.name, () => toolEntry(b.tool.name));
          if (b.tool.status === "error") failed++;
          break;
        case "host_command":
          bump(HOST_KEY, () => toolEntry(HOST_TOOL));
          if (b.command.phase === "error") failed++;
          break;
        case "view_version":
        case "view_live":
          bump(VIEW_KEY, () => ({ icon: VIEW_ICON, label: VIEW_LABEL }));
          break;
      }
    }
  }

  const all = [...byKey.values()];
  return {
    entries: all.slice(0, SHAPE_MAX_ENTRIES),
    overflow: Math.max(0, all.length - SHAPE_MAX_ENTRIES),
    failed,
    thinks,
  };
}
