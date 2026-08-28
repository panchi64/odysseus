import { createSignal, Show, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { Button, Chip, Row, Stack, StatusFlag, Text, toast } from "~/ui";
import {
  effectiveSelection,
  setSelectedModel,
  useEndpoints,
} from "~/lib/stores/models";
import { modelsPageAction } from "../chatModelNotice";
import type { LaunchOptionField, LaunchOptions, ManagedModel } from "../model";
import { optionsForEngine } from "../serving";
import { AdvancedServeOptions } from "./AdvancedServeOptions";
import { DownloadProgress } from "./DownloadProgress";
import { ServeStateFlag } from "./ServeStateFlag";
import { ServeStageReadout } from "./ServeStageReadout";

/** One managed-model row, shared by every surface that lists managed models: engine
 *  + repo, a state flag (and port when running), the live download bar while
 *  downloading, the named step + elapsed clock while starting, the last error when
 *  failed, per-model engine tuning, and the lifecycle actions for the current state —
 *  SERVE (stopped) / RETRY (error) / STOP (running) / CANCEL (in flight) / DELETE.
 *  Buttons relay intent to the backend, which owns the transition; the row reflects
 *  the next polled state.
 *
 *  USE FOR CHAT is the manual half of choosing the chat model. The backend claims the
 *  role on its own when nothing else usable is bound; when more than one model is live
 *  that's a choice, and this is where the operator makes it. */
export function ManagedModelRow(props: {
  model: ManagedModel;
  /** The tuning fields this model's engine honours (from its recommendation). */
  supportedOptions?: LaunchOptionField[];
  onServe: (options?: LaunchOptions) => Promise<void>;
  onStop: () => Promise<void>;
  onDelete: () => Promise<void>;
}): JSX.Element {
  const [busy, setBusy] = createSignal(false);
  const [options, setOptions] = createSignal(props.model.options);
  const endpoints = useEndpoints();
  const navigate = useNavigate();
  const state = () => props.model.state;
  const inFlight = () => state() === "downloading" || state() === "starting";
  const isLocal = () => props.model.source === "local";

  // The model id this endpoint answers to — what the chat binding has to name. It comes
  // from the endpoint the backend registered, never guessed from the repo: MLX serves a
  // model under its snapshot path, not its repo id.
  const servedModel = (): string | null => {
    const id = props.model.endpointId;
    if (!id) return null;
    return (endpoints.latest ?? []).find((e) => e.id === id)?.model ?? null;
  };

  // The MLX ecosystem publishes a model's MTP head as a sibling repo named after the
  // base one, so the likely answer can be offered rather than made up: it is only ever a
  // placeholder, never a value, because a guessed repo that doesn't exist would fail at
  // launch rather than at typing time.
  const draftHint = (): string | undefined => {
    if (props.model.engine !== "mlx" || props.model.source === "local")
      return undefined;
    const repo = props.model.hfRepo;
    const dash = repo.lastIndexOf("-");
    return dash > 0
      ? `${repo.slice(0, dash)}-MTP${repo.slice(dash)}`
      : undefined;
  };

  const isChatModel = (): boolean => {
    const sel = effectiveSelection();
    return !!sel && sel.endpointId === props.model.endpointId;
  };

  // Only the overrides the operator actually set — a row on engine defaults says nothing
  // rather than listing a column of "auto".
  const tuning = () => {
    const o = props.model.options;
    const parts: string[] = [];
    if (o.contextSize != null)
      parts.push(`ctx ${o.contextSize.toLocaleString()}`);
    if (o.kvCacheType != null) parts.push(`kv ${o.kvCacheType}`);
    if (o.cacheReuse != null) parts.push(`reuse ${o.cacheReuse}`);
    if (o.speculative === "off") parts.push("no drafting");
    if (o.draftModel) parts.push(`draft ${o.draftModel}`);
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

  async function useForChat(): Promise<void> {
    const model = servedModel();
    const endpointId = props.model.endpointId;
    if (!model || !endpointId) return;
    try {
      await setSelectedModel({ endpointId, model });
      // Name the change, not just the model: this button rebinds the chat model
      // for the whole workspace, and MODELS is where that can be seen or undone.
      toast.success(`Chat model set to ${props.model.hfRepo}.`, {
        action: modelsPageAction(navigate),
      });
    } catch {
      toast.error(`Couldn't switch to ${props.model.hfRepo}`);
    }
  }

  return (
    <Stack gap={2} class="px-3 py-3">
      <Row align="center" justify="between" gap={3}>
        <Row align="center" gap={2} class="min-w-0">
          <Text variant="label" tone="dim" class="shrink-0">
            {props.model.engine}
          </Text>
          <Text variant="label" tone="bright" class="truncate">
            {props.model.hfRepo}
          </Text>
          <Show when={isLocal()}>
            <Chip>On disk</Chip>
          </Show>
        </Row>
        <Row align="center" gap={2} class="shrink-0">
          <Show when={state() === "running" && isChatModel()}>
            <StatusFlag status="nominal">Chat</StatusFlag>
          </Show>
          <Show when={state() === "running" && props.model.port}>
            <Text variant="micro" tone="dim">
              :{props.model.port}
            </Text>
          </Show>
          <ServeStateFlag state={state()} />
        </Row>
      </Row>
      <Show when={isLocal() && props.model.artifactPath}>
        <Text variant="micro" tone="dim" class="truncate">
          {props.model.artifactPath}
        </Text>
      </Show>
      <Show when={props.model.speculative}>
        <Text variant="micro" tone="dim" class="truncate">
          {props.model.speculative}
        </Text>
      </Show>
      <Show when={tuning()}>
        <Text variant="micro" tone="dim" class="truncate">
          {tuning()}
        </Text>
      </Show>
      <Show when={state() === "downloading" && props.model.progress}>
        <DownloadProgress progress={props.model.progress!} />
      </Show>
      <Show when={state() === "starting" && props.model.stage}>
        <ServeStageReadout stage={props.model.stage!} />
      </Show>
      <Show when={state() === "error" && props.model.lastError}>
        <Text variant="micro" tone="alert">
          {props.model.lastError}
        </Text>
      </Show>
      <Show when={!inFlight()}>
        <AdvancedServeOptions
          supportedOptions={props.supportedOptions ?? []}
          value={options()}
          onChange={setOptions}
          speculativeNote={props.model.speculative}
          draftPlaceholder={draftHint()}
        />
      </Show>
      <Row gap={2} align="center" justify="end">
        <Show when={state() === "running" && props.model.endpointId}>
          <Button
            size="sm"
            variant="ghost"
            leading="chat"
            disabled={busy() || isChatModel() || !servedModel()}
            onClick={run(useForChat)}
          >
            {isChatModel() ? "In use for chat" : "Use for chat"}
          </Button>
        </Show>
        <Show when={state() === "stopped" || state() === "error"}>
          <Button
            size="sm"
            leading="play"
            disabled={busy()}
            onClick={run(() =>
              // Only this engine's fields, and omitted when untouched, so a plain
              // re-serve keeps the tuning the model was last given rather than clearing
              // it.
              props.onServe(
                optionsForEngine(options(), props.supportedOptions ?? []) ??
                  undefined,
              ),
            )}
          >
            {state() === "error" ? "Retry" : "Serve"}
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
            {inFlight() ? "Cancel" : "Stop"}
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
            {isLocal() ? "Remove" : "Delete"}
          </Button>
        </Show>
      </Row>
    </Stack>
  );
}
