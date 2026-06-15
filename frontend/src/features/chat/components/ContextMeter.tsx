import { type JSX } from "solid-js";
import { pct } from "~/lib/format";
import { ProgressBar, Text, Tooltip } from "~/ui";
import type { ContextUsage } from "../model";

export interface ContextMeterProps {
  /** The backend-derived context-window state. The meter only renders it. */
  usage: ContextUsage;
}

const tokens = (n: number) => n.toLocaleString("en-US");

/** A compact context-window readout for the chat header: a `CTX` label, a
 *  mechanical fill bar, and a tabular percentage, toned by the backend's
 *  severity level. Hovering reveals the exact `used / total tokens`. All values
 *  are computed server-side — this component performs no derivation. */
export function ContextMeter(props: ContextMeterProps): JSX.Element {
  const percent = () => props.usage.fraction * 100;
  return (
    <Tooltip
      label={`${tokens(props.usage.used)} / ${tokens(props.usage.window)} tokens`}
      side="bottom"
      float
    >
      <span class="flex items-center gap-1.5">
        <Text variant="label" tone="dim">
          CTX
        </Text>
        <ProgressBar value={percent()} tone={props.usage.level} class="w-16" />
        <Text variant="label" tone={props.usage.level}>
          {pct(percent())}
        </Text>
      </span>
    </Tooltip>
  );
}
