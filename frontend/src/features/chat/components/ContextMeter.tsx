import { Show, type JSX } from "solid-js";
import { pct } from "~/lib/format";
import { ProgressBar, Text, Tooltip } from "~/ui";
import type { ContextUsage, TokenUsage } from "../model";

export interface ContextMeterProps {
  /** The backend-derived context-window state. The meter only renders it. */
  usage: ContextUsage;
  /** The latest run's token counts, shown as a labelled readout stacked under the
   *  gauge. Absent/null fields render nothing. */
  tokenUsage?: TokenUsage | null;
}

const tokens = (n: number) => n.toLocaleString("en-US");

/** A compact context-window readout for the chat header: a `CTX` label, a
 *  mechanical fill bar, and a tabular percentage, toned by the backend's
 *  severity level. Hovering reveals the exact `used / total tokens`. All values
 *  are computed server-side — this component performs no derivation.
 *
 *  The run's own token counts stack *under* the gauge rather than sitting beside
 *  it, and carry `IN`/`OUT` labels: on one line they read as more context-window
 *  numbers, when they measure a different thing (the last run's traffic). */
export function ContextMeter(props: ContextMeterProps): JSX.Element {
  const percent = () => props.usage.fraction * 100;
  return (
    <span class="flex flex-col items-end gap-0.5">
      <Tooltip
        label={`${tokens(props.usage.used)} / ${tokens(props.usage.window)} tokens`}
        side="bottom"
        float
      >
        <span class="flex items-center gap-1.5">
          <Text variant="label" tone="dim">
            Ctx
          </Text>
          <ProgressBar
            value={percent()}
            tone={props.usage.level}
            class="w-16"
          />
          <Text variant="label" tone={props.usage.level}>
            {pct(percent())}
          </Text>
        </span>
      </Tooltip>
      <Show
        when={
          props.tokenUsage &&
          (props.tokenUsage.input !== null ||
            props.tokenUsage.output !== null) &&
          props.tokenUsage
        }
      >
        {(t) => (
          <Tooltip label="Input / output tokens this run" side="bottom" float>
            <Text variant="micro" tone="dim">
              IN {t().input !== null ? tokens(t().input!) : "—"} · OUT{" "}
              {t().output !== null ? tokens(t().output!) : "—"}
            </Text>
          </Tooltip>
        )}
      </Show>
    </span>
  );
}
