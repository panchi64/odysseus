import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { StatusDot, statusTone, type Status } from "./StatusDot";

export type { Status };

export interface StatusFlagProps {
  /** Drives the dot's accent. Defaults to idle (neutral, at rest). */
  status?: Status;
  /** Render a leading state dot. */
  dot?: boolean;
  /** Pulse the state dot to signal live activity (e.g. a stream in flight). */
  pulse?: boolean;
  class?: string;
  children: string;
}

/** Small chip carrying a machine state (§10.5). This is the system reporting
 *  itself, so it is the **mono voice**: uppercase, tracked, and it snaps between
 *  values rather than easing.
 *
 *  **The dot carries the hue; the label stays dim.** A status chip is ambient —
 *  it reports, it does not ask — and a whole word in an accent colour reads as a
 *  demand for attention wherever it appears, which on a screen with a dozen
 *  flags is a dozen demands. Confining the colour to a 6px dot keeps the state
 *  legible at a glance and keeps the accent budget (§5.4) intact.
 *
 *  No fill and no border either: a chip is a label, not an object. */
export function StatusFlag(props: StatusFlagProps): JSX.Element {
  const [local] = splitProps(props, [
    "status",
    "dot",
    "pulse",
    "class",
    "children",
  ]);
  const status = () => local.status ?? "idle";
  /* Dim for every routine state — idle, live, nominal, info. `warn` and `alert`
     keep their accent on the label, because those are the two that genuinely
     need to interrupt, and a failure the operator can miss is worse than one
     more colour on the page. That distinction is the whole point of rationing:
     when only real problems are coloured, a coloured word means something. */
  const tone = () => {
    const s = status();
    return s === "warn" || s === "alert" ? statusTone[s] : "dim";
  };
  return (
    <span
      class={cx("inline-flex items-center gap-1.5 px-0.5 py-0.5", local.class)}
    >
      {local.dot && <StatusDot status={status()} pulse={local.pulse} />}
      <Text variant="meta" tone={tone()}>
        {local.children}
      </Text>
    </span>
  );
}
