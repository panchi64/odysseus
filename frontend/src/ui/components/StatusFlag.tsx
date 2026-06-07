import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text, type TextTone } from "../primitives/Text";

/** Semantic status. Each maps to exactly one accent (§4 color discipline). */
export type Status = "idle" | "live" | "nominal" | "warn" | "alert" | "info";

const statusTone: Record<Status, TextTone> = {
  idle: "dim",
  live: "nominal",
  nominal: "nominal",
  warn: "warn",
  alert: "alert",
  info: "info",
};

export interface StatusFlagProps {
  /** Drives the accent color + border. Defaults to idle (neutral, at rest). */
  status?: Status;
  /** Render a leading state dot. */
  dot?: boolean;
  class?: string;
  children: string;
}

/** Small uppercase chip carrying a state (§6.5). Idle is neutral; a screen at
 *  rest shows only idle flags. */
export function StatusFlag(props: StatusFlagProps): JSX.Element {
  const [local] = splitProps(props, ["status", "dot", "class", "children"]);
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
      {local.dot && (
        <span
          class="inline-block size-1.5 rounded-full bg-current"
          aria-hidden="true"
        />
      )}
      <Text variant="label" tone={tone()}>
        {local.children}
      </Text>
    </span>
  );
}
