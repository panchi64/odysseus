/** What a folded run of work amounts to — the last thing it did, and how much of
 *  it there is.
 *
 *  Two summaries have been tried here and both failed for the same reason: they
 *  reported *magnitude* where the operator was reading for *identity*. `7 Steps`
 *  ranked every turn in a thread identically. `Read ×4 · Web search · Write`
 *  named the tools, which was better, but a per-tool tally is still a number
 *  without a referent — whether the agent read four files or seven changes
 *  nothing about whether this fold is worth opening, and the `+N` overflow was
 *  worse still, counting kinds the operator could not see.
 *
 *  What actually distinguishes one fold from another is **what it last did**:
 *  `Read agent.py`, `Web search "pydantic ai streaming"`. That is a fact with a
 *  noun in it. It also does the work the old summary could not do at all —
 *  while the turn streams, settled work keeps folding in, so this line advances
 *  as the run progresses and is the fold's own proof of life.
 *
 *  The size of the run rides along as dim metadata rather than as the headline,
 *  because "is opening this worth it" is the one question a magnitude genuinely
 *  answers.
 *
 *  Pure data → data, like `blocks.ts`: no Solid, no DOM, so the rules stay
 *  testable and live in one place. */

import type { IconName } from "~/ui";
import { INJECTION_ICON, segmentLabel } from "./contextLabels";
import { toolEntry } from "./toolPresentation";
import type { AssistantBlock } from "./model";
import type { BlockGroup } from "./blocks";

/** The glyph for reasoning. Not a tool, so it has no registry entry to borrow —
 *  `cpu` is the machine doing its own work, and it is unclaimed by any tool
 *  category, so it can't be mistaken for one. Declared here rather than in the
 *  two components that draw it, so the settled reasoning row and the work log
 *  header cannot drift onto different glyphs for the same idea. */
export const THINK_ICON: IconName = "cpu";

/** One piece of work, in the same anatomy its own card uses: `glyph · Label ·
 *  what it was about`. The header speaking the sentence its rows speak is the
 *  point — the fold then reads as its own most recent row rather than as a
 *  different species of line sitting on top of them. */
export interface WorkStep {
  icon: IconName;
  /** The kind, in the interface's voice: "Read", "Web search", "Reasoning". */
  label: string;
  /** What it was about — a path, a query, a command. Absent when the call
   *  carried nothing salient, and always absent for reasoning, which is about
   *  nothing nameable. */
  detail?: string;
}

export interface WorkShape {
  /** The run's most recent step. Undefined only for a run with nothing in it,
   *  which never reaches the header. */
  latest?: WorkStep;
  /** How many rows expanding would reveal — one per group, which is exactly what
   *  the open log renders. */
  steps: number;
}

/** Host commands borrow the registry entry of the tool that produces them, so
 *  the header's glyph matches the terminal card's. */
const HOST_TOOL = "code_run_host_command";

/** A View version or the live head. Not a tool call, so it has no registry entry
 *  to borrow — but it is work that lands in a run, and a fold ending on a View
 *  chip would otherwise summarize as nothing at all. */
const VIEW_ICON: IconName = "panel-right";
const VIEW_LABEL = "View";

/** The one glyph a review row leads with, wherever it appears — the header's summary and
 *  the row itself must agree, or the fold and its contents read as two different events. */
const REVIEW_ICON: IconName = "review";

/** One block as a step, or `undefined` for a block kind that is not work the log
 *  reports (nothing else reaches a fold today, but the log's membership rules
 *  live in `blocks.ts` and this must not assume they never widen). */
function stepOf(block: AssistantBlock): WorkStep | undefined {
  switch (block.kind) {
    case "thinking":
      return { icon: THINK_ICON, label: "Reasoning" };
    case "tool": {
      const { icon, label } = toolEntry(block.tool.name);
      // The salient argument only. Never `tool.args`: the card falls back to the
      // full `k=v` dump because an open card has room for it, and a header does
      // not — a serialized argument blob here would push the one readable word
      // off the end of the row.
      return { icon, label, detail: block.tool.detail };
    }
    case "host_command": {
      const { icon, label } = toolEntry(HOST_TOOL);
      return { icon, label, detail: block.command.command };
    }
    case "context":
      return {
        icon: INJECTION_ICON,
        label: segmentLabel(block.injection.contributor),
        detail: "injected",
      };
    case "review":
      // Named by the tool it judged, not by the review — a collapsed log ending on
      // "Review · Shell · refused" says what happened; one ending on "Review"
      // alone says only that something did.
      return {
        icon: REVIEW_ICON,
        label: toolEntry(block.review.name).label,
        detail: block.review.decision
          ? `review: ${block.review.decision}`
          : "reviewing",
      };
    case "view_version":
      return { icon: VIEW_ICON, label: VIEW_LABEL, detail: block.title };
    case "view_live":
      return { icon: VIEW_ICON, label: VIEW_LABEL, detail: block.live.title };
    default:
      return undefined;
  }
}

/** The shape of a run of work groups — what the collapsed work log leads with.
 *
 *  Scanned from the end, because the answer is the *last* step and a run can be
 *  forty blocks long. There is no failure count here on purpose: `isCollapsible`
 *  pins a failed call inline, so a failure cannot be inside a fold, and a field
 *  that is structurally always zero is a field that will eventually be believed. */
export function workShape(groups: BlockGroup[]): WorkShape {
  for (let g = groups.length - 1; g >= 0; g--) {
    const blocks = groups[g].blocks;
    for (let b = blocks.length - 1; b >= 0; b--) {
      const step = stepOf(blocks[b]);
      if (step) return { latest: step, steps: groups.length };
    }
  }
  return { steps: groups.length };
}
