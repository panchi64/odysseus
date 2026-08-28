import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { StatusDot, statusTone, type Status } from "./StatusDot";

export type { Status };

export interface StatusFlagProps {
  /** Drives the accent color + border. Defaults to idle (neutral, at rest). */
  status?: Status;
  /** Render a leading state dot. */
  dot?: boolean;
  /** Pulse the state dot to signal live activity (e.g. a stream in flight). */
  pulse?: boolean;
  class?: string;
  children: string;
}

/** Small uppercase chip carrying a state (§6.5). Idle is neutral; a screen at
 *  rest shows only idle flags. */
export function StatusFlag(props: StatusFlagProps): JSX.Element {
  const [local] = splitProps(props, [
    "status",
    "dot",
    "pulse",
    "class",
    "children",
  ]);
  const status = () => local.status ?? "idle";
  const tone = () => statusTone[status()];
  return (
    <span
      class={cx(
        "inline-flex items-center gap-1 rounded-ctl border bg-surface px-2 py-0.5",
        status() === "idle" ? "border-line" : "border-current",
        `text-${tone()}`,
        local.class,
      )}
    >
      {local.dot && <StatusDot status={status()} pulse={local.pulse} />}
      <Text variant="label" tone={tone()}>
        {local.children}
      </Text>
    </span>
  );
}
