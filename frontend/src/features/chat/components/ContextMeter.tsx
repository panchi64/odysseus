import { Show, type JSX } from "solid-js";
import { pct } from "~/lib/format";
import { Text, Tooltip } from "~/ui";
import type { ContextUsage, TokenUsage } from "../model";

export interface ContextMeterProps {
  /** The backend-derived context-window state. The meter only renders it. */
  usage: ContextUsage;
  /** The latest run's token counts, shown beside the percentage. Absent/null
   *  fields render nothing. */
  tokenUsage?: TokenUsage | null;
}

const tokens = (n: number) => n.toLocaleString("en-US");

/** The context-window readout, as one segment of the composer's meta line: a
 *  `Ctx` label, a tabular percentage toned by the backend's severity level, and
 *  the run's own token traffic beside it. Hovering reveals the exact
 *  `used / total tokens`. Every value is computed server-side — this component
 *  performs no derivation.
 *
 *  It used to carry a `ProgressBar`. The bar went with the move below the
 *  composer: that line is a readout, and a gauge in it is a piece of chrome in a
 *  run of text. The percentage already carries the severity tone, and the number
 *  the bar was approximating is one hover away. */
export function ContextMeter(props: ContextMeterProps): JSX.Element {
  const percent = () => props.usage.fraction * 100;
  return (
    <>
      <Tooltip
        label={`${tokens(props.usage.used)} / ${tokens(props.usage.window)} tokens`}
        side="top"
      >
        <span class="flex items-center gap-1">
          <Text variant="micro" tone="dim">
            Ctx
          </Text>
          <Text variant="micro" tone={props.usage.level} class="tabular-nums">
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
          <Tooltip label="Input / output tokens this run" side="top">
            {/* `·`, not `|` — this is the same measurement as the percentage
                beside it (what this thread costs the window), so it stays inside
                that group rather than starting a new one. */}
            <Text variant="micro" tone="dim" class="tabular-nums">
              · in {t().input !== null ? tokens(t().input!) : "—"} out{" "}
              {t().output !== null ? tokens(t().output!) : "—"}
            </Text>
          </Tooltip>
        )}
      </Show>
    </>
  );
}
