import { createMemo, type JSX } from "solid-js";
import { Select, Tooltip } from "~/ui";
import {
  PERMISSION_LEVELS,
  permissionLevel,
  type PermissionLevel,
} from "../model";

/** Each level's square, warming as the list gives more rope: grey for the level
 *  that only reads, cool for the two that ask, amber once the model rules on its
 *  own calls, red for the one where nothing asks at all. Keyed by the type, so a
 *  further level fails to compile until it is given one. */
const SWATCH: Record<PermissionLevel, string> = {
  plan: "bg-dim",
  manual: "bg-info",
  edit: "bg-nominal",
  auto: "bg-warn",
  yolo: "bg-alert",
};

/** **How far the model may go** in this thread — the composer's other axis.
 *
 *  This slot used to hold the mode picker, which was shown only while the thread
 *  was unsaved because a thread's mode is set once and never again. The level is
 *  the opposite kind of fact: it is the operator's live control over a thread
 *  already in flight, so it is offered at every moment of a thread's life and
 *  carries no such gate. Drop to Manual before something delicate, raise to Auto
 *  once the work is routine, accept a plan and carry on in place.
 *
 *  Presentation only, and — unusually for a control that changes behaviour — it
 *  writes nothing on its own. The chosen level rides the *next send*, which is
 *  what makes switching mid-thread a plain message rather than a second round
 *  trip that could half-apply. The backend persists what that send names and
 *  re-checks what the level permits; nothing here decides anything. */
export function PermissionControl(props: {
  level: PermissionLevel;
  onLevelChange: (level: PermissionLevel) => void;
  /** The thread's stored level has not arrived yet, so the level in hand is a placeholder
   *  (`permissionSeat.ts`). The control says so instead of naming it: the placeholder is
   *  the strictest level, and rendering it would claim on every thread open that the
   *  thread is at Plan — indistinguishable, for the second it lasts, from one that is. */
  pending?: boolean;
}): JSX.Element {
  const description = createMemo(() =>
    props.pending
      ? "Reading this thread's permission level…"
      : (PERMISSION_LEVELS.find((spec) => spec.id === props.level)
          ?.description ?? ""),
  );

  return (
    <Tooltip delay={600} side="top" label={description()}>
      <Select
        // A cell of the composer's status bar; the bar lowercases the label.
        cell
        // No value matches while pending, so the placeholder is what shows.
        value={props.pending ? "" : props.level}
        placeholder="LEVEL…"
        disabled={props.pending}
        onChange={(v) => props.onLevelChange(permissionLevel(v))}
        options={PERMISSION_LEVELS.map((spec) => ({
          value: spec.id,
          label: spec.label,
          description: spec.description,
          swatch: SWATCH[spec.id],
        }))}
        aria-label="Permission level"
      />
    </Tooltip>
  );
}
