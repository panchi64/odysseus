/** How a context contributor reads on screen — the slug the backend sends becoming a
 *  glyph and a word.
 *
 *  The sibling of `toolPresentation.ts`, and for the same reason: the backend sends a
 *  registry slug (`skill_catalog`, `repo`, `plan`) because the wording of a readout is
 *  presentation and it has no business choosing sentence case, and two surfaces then need
 *  the same slug to become the same words. The context gauge's breakdown row and the work
 *  log's injection row are one block seen from two distances; naming it "Project
 *  instructions" in one and "Repo" in the other would leave the operator working out that
 *  they are the same thing.
 *
 *  **The overrides are a short list, not a registry.** Every tool category and every
 *  instruction provider the backend grows later reads correctly from its own id, so
 *  nothing here has to be edited when a feature ships one — only the few slugs whose own
 *  words would actively mislead are named. */

import type { IconName } from "~/ui";

/** The few slugs whose de-slugged form would be wrong or unhelpful. */
const LABELS: Record<string, string> = {
  base: "Base prompt",
  external: "MCP & connectors",
  repo: "Project instructions",
  skill_catalog: "Skills",
  plan: "Plan reminder",
  date: "Today's date",
  mode: "Mode posture",
  delegate: "Delegates",
};

/** A backend slug as a row label: an override if it has one, else its own words
 *  (`tool_results` → "Tool results"). */
export function segmentLabel(id: string): string {
  const named = LABELS[id];
  if (named) return named;
  const words = id.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The one glyph every injection row leads with.
 *
 *  Deliberately **not** per-contributor, the way a tool row's glyph is per-family. A
 *  column of tool rows is scanned to tell the calls apart; a column of injection rows is
 *  scanned to tell them apart *from the calls*, and the fastest way to say "these are all
 *  the same kind of thing, and it isn't work" is one shape repeated. */
export const INJECTION_ICON: IconName = "inject";
