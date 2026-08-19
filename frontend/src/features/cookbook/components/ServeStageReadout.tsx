import { createSignal, onCleanup, Show, type JSX } from "solid-js";
import { ProgressBar, Row, Stack, Text } from "~/ui";
import type { ServeStage, ServeStageInfo } from "../model";

const STAGE_LABEL: Record<ServeStage, string> = {
  installing_engine: "INSTALLING ENGINE RUNTIME",
  loading_model: "LOADING MODEL",
};

const STAGE_HINT: Record<ServeStage, string> = {
  installing_engine:
    "One-time setup for this engine — the next model starts straight into loading.",
  loading_model: "The server answers once the weights are resident.",
};

/** Seconds as a compact clock — `0:42`, `3:07`. */
function elapsed(sinceIso: string, now: number): string {
  const started = Date.parse(sinceIso);
  const seconds = Number.isNaN(started)
    ? 0
    : Math.max(0, Math.floor((now - started) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * What a starting model is doing, and how long it has been doing it.
 *
 * Neither step reports a percentage — installing a runtime and loading weights are
 * opaque from outside — so the bar is deliberately indeterminate and the honest signal
 * is the named step plus a running clock. Without this, a multi-minute model load is
 * indistinguishable from a hang.
 */
export function ServeStageReadout(props: {
  stage: ServeStageInfo;
}): JSX.Element {
  const [now, setNow] = createSignal(Date.now());
  const timer = setInterval(() => setNow(Date.now()), 1000);
  onCleanup(() => clearInterval(timer));

  const overBudget = () => {
    const budget = props.stage.timeoutS;
    if (budget == null) return false;
    const started = Date.parse(props.stage.startedAt);
    return !Number.isNaN(started) && (now() - started) / 1000 > budget * 0.8;
  };

  return (
    <Stack gap={1}>
      <Row align="baseline" justify="between" gap={2}>
        <Text variant="micro" tone="dim">
          {STAGE_LABEL[props.stage.stage]}
        </Text>
        <Text variant="micro" tone={overBudget() ? "warn" : "dim"}>
          {elapsed(props.stage.startedAt, now())}
        </Text>
      </Row>
      <ProgressBar tone={overBudget() ? "warn" : "info"} />
      <Show when={STAGE_HINT[props.stage.stage]}>
        <Text variant="micro" tone="dim">
          {STAGE_HINT[props.stage.stage]}
        </Text>
      </Show>
    </Stack>
  );
}
