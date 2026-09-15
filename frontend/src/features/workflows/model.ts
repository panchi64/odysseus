/** Workflows feature data contracts.
 *
 *  A workflow is a **prompt the operator saved under a name they can type**. `/standup`
 *  in the composer puts its template in front of the model for that one turn; nothing
 *  else in the product can reach it, and the model is never told it exists.
 *
 *  That is the whole difference from a skill, and it is worth holding on to while
 *  reading this folder: a skill is written for the *agent* to choose and open, so
 *  publishing one is a trust boundary. A workflow is written for the operator's own
 *  fingers, so `enabled` is a convenience — it keeps a half-written one out of the menu
 *  and means nothing else.
 *
 *  The backend owns every rule below; the types here only describe what it sends back.
 */

import type { Status } from "~/ui";

/** One saved workflow, as its author sees it. There is no summary/detail split: a
 *  workflow is four short fields and a template, so the list ships the whole thing and
 *  the editor opens what it already has. */
export interface Workflow {
  id: string;
  /** What the operator types after the slash. Also the uniqueness key. */
  name: string;
  /** The picker's row label. Falls back to the name, server-side, so it is never blank. */
  title: string;
  /** The line under it in the picker. */
  description: string;
  /** The template — the only field here a model ever reads. */
  body: string;
  /** What to type after the name ("the version"), or null when it takes nothing. */
  argumentHint: string | null;
  /** Whether the picker offers it. Not a trust boundary — see the module note. */
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

/* ── Presentation mirrors of the backend's rules ──────────────────────────────
   Shown so a field goes red before the operator submits. The backend still
   decides, and its 422 message is what actually renders. Never gate a submit on
   these — a frontend that refused what the server would have accepted is a
   second, quieter rulebook. */

export const WORKFLOW_NAME_MAX = 64;
export const WORKFLOW_TITLE_MAX = 120;
export const WORKFLOW_DESCRIPTION_MAX = 400;
export const WORKFLOW_ARGUMENT_HINT_MAX = 120;
export const WORKFLOW_BODY_MAX = 8000;

/** Lowercase letters, numbers, hyphens and underscores — the same shape a sub-agent's
 *  name has, because both are typed after the same slash. */
export const WORKFLOW_NAME_PATTERN = /^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$/;

/**
 * What the backend will actually store, mirrored so the field does not go red for
 * something the server would have accepted.
 *
 * It normalises rather than refuses, on the grounds that `Stand Up` is what someone
 * writes when they are thinking about the ritual rather than about an identifier, and a
 * leading slash is the obvious mistake to make when the slash appears everywhere else.
 * Checking the raw text against the pattern would mark both of those invalid and then
 * accept them anyway on save — the exact second rulebook these mirrors exist to avoid.
 */
export function normalizeWorkflowName(raw: string): string {
  return raw.trim().replace(/^\/+/, "").toLowerCase().replaceAll(" ", "-");
}

/** `"12 / 64"` — the live count under a length-limited field. */
export function charCount(value: string, max: number): string {
  return `${value.length} / ${max}`;
}

/** How a row's on/off state reads in the directory. Deliberately not "published" or
 *  "draft": those words describe a skill crossing into the agent's view, and nothing
 *  here crosses anywhere. */
export function workflowStatusLabel(enabled: boolean): string {
  return enabled ? "ON" : "OFF";
}

export function workflowStatusFlag(enabled: boolean): Status {
  return enabled ? "nominal" : "idle";
}
