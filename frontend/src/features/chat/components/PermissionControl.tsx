import { createMemo, type JSX } from "solid-js";
import { Select, Tooltip } from "~/ui";
import {
  PERMISSION_LEVELS,
  permissionLevel,
  type PermissionLevel,
} from "../model";

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
}): JSX.Element {
  const description = createMemo(
    () =>
      PERMISSION_LEVELS.find((spec) => spec.id === props.level)?.description ??
      "",
  );

  return (
    <Tooltip delay={600} side="top" label={description()}>
      <Select
        value={props.level}
        onChange={(v) => props.onLevelChange(permissionLevel(v))}
        options={PERMISSION_LEVELS.map((spec) => ({
          value: spec.id,
          label: spec.label,
        }))}
        aria-label="Permission level"
      />
    </Tooltip>
  );
}
