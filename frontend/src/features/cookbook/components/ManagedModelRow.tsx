import { createSignal, Show, type JSX } from "solid-js";
import { Button, Row, Stack, Text } from "~/ui";
import type { ManagedModel } from "../model";
import { DownloadProgress } from "./DownloadProgress";
import { ServeStateFlag } from "./ServeStateFlag";

/** One managed-model row, shared by every surface that lists managed models: engine
 *  + repo, a state flag (and port when running), the live download bar while
 *  downloading, the last error when failed, and the lifecycle actions for the current
 *  state — SERVE (stopped) / RETRY (error) / STOP (running) / CANCEL (in flight) /
 *  DELETE. Buttons relay intent to the backend, which owns the transition; the row
 *  reflects the next polled state. */
export function ManagedModelRow(props: {
  model: ManagedModel;
  onServe: () => Promise<void>;
  onStop: () => Promise<void>;
  onDelete: () => Promise<void>;
}): JSX.Element {
  const [busy, setBusy] = createSignal(false);
  const state = () => props.model.state;
  const inFlight = () => state() === "downloading" || state() === "starting";

  // Only the overrides the operator actually set — a row on engine defaults says nothing
  // rather than listing a column of "auto".
  const tuning = () => {
    const o = props.model.options;
    const parts: string[] = [];
    if (o.contextSize != null)
      parts.push(`ctx ${o.contextSize.toLocaleString()}`);
    if (o.kvCacheType != null) parts.push(`kv ${o.kvCacheType}`);
    if (o.cacheReuse != null) parts.push(`reuse ${o.cacheReuse}`);
    if (o.extraArgs.length > 0) parts.push(o.extraArgs.join(" "));
    return parts.join(" · ");
  };

  // Each action runs at most once at a time; the busy flag disables the row's
  // buttons until the request settles (the poll then lands the new state).
  const run = (fn: () => Promise<void>) => async () => {
    if (busy()) return;
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack gap={2} class="border-b border-line px-3 py-3 last:border-0">
      <Row align="center" justify="between" gap={3}>
        <Row align="center" gap={2} class="min-w-0">
          <Text variant="label" tone="dim" class="shrink-0">
            {props.model.engine}
          </Text>
          <Text variant="label" tone="bright" class="truncate">
            {props.model.hfRepo}
          </Text>
        </Row>
        <Row align="center" gap={2} class="shrink-0">
          <Show when={state() === "running" && props.model.port}>
            <Text variant="micro" tone="dim">
              :{props.model.port}
            </Text>
          </Show>
          <ServeStateFlag state={state()} />
        </Row>
      </Row>
      <Show when={tuning()}>
        <Text variant="micro" tone="dim" class="truncate">
          {tuning()}
        </Text>
      </Show>
      <Show when={state() === "downloading" && props.model.progress}>
        <DownloadProgress progress={props.model.progress!} />
      </Show>
      <Show when={state() === "error" && props.model.lastError}>
        <Text variant="micro" tone="alert">
          {props.model.lastError}
        </Text>
      </Show>
      <Row gap={2} align="center" justify="end">
        <Show when={state() === "stopped" || state() === "error"}>
          <Button
            size="sm"
            leading="play"
            disabled={busy()}
            onClick={run(props.onServe)}
          >
            {state() === "error" ? "RETRY" : "SERVE"}
          </Button>
        </Show>
        <Show when={state() === "running" || inFlight()}>
          <Button
            size="sm"
            variant="ghost"
            leading="stop"
            disabled={busy()}
            onClick={run(props.onStop)}
          >
            {inFlight() ? "CANCEL" : "STOP"}
          </Button>
        </Show>
        <Show when={!inFlight()}>
          <Button
            size="sm"
            variant="ghost"
            leading="trash"
            disabled={busy()}
            onClick={run(props.onDelete)}
          >
            DELETE
          </Button>
        </Show>
      </Row>
    </Stack>
  );
}
