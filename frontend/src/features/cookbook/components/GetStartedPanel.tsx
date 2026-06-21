import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  LoadingText,
  Panel,
  Row,
  Select,
  Stack,
  StatusFlag,
  Text,
} from "~/ui";
import {
  EndpointForm,
  type EndpointFormValues,
} from "~/features/settings/components/EndpointForm";
import { EndpointHealthFlag } from "~/features/settings/components/EndpointHealthFlag";
import {
  PROVIDER_PRESETS,
  presetById,
  presetToEndpointInput,
} from "../presets";
import { connectAndSelectEndpoint, useRemoteEndpoints } from "../data";

/** The guided "it just works" setup: pick a provider preset → paste a key →
 *  "Connect & use this". The backend tests the connection and a sensible default
 *  model is auto-selected, so the operator never has to choose one. Discovering /
 *  evaluating models is out of scope here.
 *
 *  Presentation-only: every decision (does it work, which model resolves at send
 *  time) is the backend's; this surface captures intent and renders the verdict. */
export function GetStartedPanel(): JSX.Element {
  const endpoints = useRemoteEndpoints();

  // `null` = the two-choice entry; "remote" = the guided form is open.
  const [mode, setMode] = createSignal<null | "remote">(null);
  const [presetId, setPresetId] = createSignal(PROVIDER_PRESETS[0].id);
  const [apiKey, setApiKey] = createSignal("");
  const [connecting, setConnecting] = createSignal(false);

  const preset = createMemo(
    () => presetById(presetId()) ?? PROVIDER_PRESETS[0],
  );

  // The simple form is preset-driven: name/base URL come from the preset and only
  // the key is captured. Derived from the same preset→endpoint mapping the connect
  // flow uses (so the two never drift); the advanced-only fields the simple render
  // ignores are filled from it too — string-shaped for the form.
  const formValues = createMemo<EndpointFormValues>(() => {
    const input = presetToEndpointInput(preset(), apiKey());
    return {
      name: input.name,
      baseUrl: input.baseUrl,
      model: input.model ?? "",
      apiKey: apiKey(),
      contextWindow:
        input.contextWindow != null ? String(input.contextWindow) : "",
      nativeTools: input.nativeTools,
      vision: input.vision,
      thinking: input.thinking,
    };
  });

  const canConnect = () =>
    !connecting() && (!preset().requiresKey || apiKey().trim() !== "");

  const connect = async () => {
    if (!canConnect()) return;
    setConnecting(true);
    try {
      const ok = await connectAndSelectEndpoint({
        preset: preset(),
        apiKey: apiKey().trim(),
      });
      if (ok) {
        // Connected & selected — collapse the form; the new endpoint shows below.
        setMode(null);
        setApiKey("");
      }
    } finally {
      setConnecting(false);
    }
  };

  const presetOptions = PROVIDER_PRESETS.map((p) => ({
    value: p.id,
    label: p.name,
  }));

  return (
    <Stack gap={6}>
      <Panel label="GET STARTED">
        <Stack gap={4}>
          <Text variant="micro" tone="dim">
            Connect a model and start chatting. Pick a provider, paste a key,
            and we wire it up — testing the connection and selecting a model for
            you.
          </Text>

          {/* Two-choice entry. */}
          <Show when={mode() === null}>
            <Row gap={3} align="stretch">
              <button
                type="button"
                onClick={() => setMode("remote")}
                class="flex-1 border border-line bg-surface p-4 text-left transition-colors hover:border-bright"
              >
                <Stack gap={1}>
                  <Text variant="label" tone="bright">
                    USE A REMOTE API
                  </Text>
                  <Text variant="micro" tone="dim">
                    OpenAI, OpenRouter, Groq, Together, or a local server.
                  </Text>
                </Stack>
              </button>
              <div class="flex-1 cursor-not-allowed border border-line bg-surface p-4 opacity-40">
                <Stack gap={1}>
                  <Row gap={2} align="center">
                    <Text variant="label" tone="default">
                      RUN LOCALLY
                    </Text>
                    <StatusFlag status="idle">COMING SOON</StatusFlag>
                  </Row>
                  <Text variant="micro" tone="dim">
                    Download and serve a model on this machine.
                  </Text>
                </Stack>
              </div>
            </Row>
          </Show>

          {/* Guided remote-API form. */}
          <Show when={mode() === "remote"}>
            <Stack gap={3}>
              <Select
                label="PROVIDER"
                options={presetOptions}
                value={presetId()}
                onChange={(v) => {
                  setPresetId(v);
                  setApiKey("");
                }}
              />
              <EndpointForm
                variant="simple"
                requiresKey={preset().requiresKey}
                values={formValues()}
                onChange={(key, value) => {
                  if (key === "apiKey") setApiKey(value as string);
                }}
              />
              <Show when={preset().docsUrl}>
                <a
                  href={preset().docsUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  class="underline-offset-2 hover:underline"
                >
                  <Text variant="micro" tone="info">
                    {preset().requiresKey
                      ? "Get an API key ↗"
                      : "Set up the local server ↗"}
                  </Text>
                </a>
              </Show>
              <Row gap={2} justify="end">
                <Button
                  variant="ghost"
                  disabled={connecting()}
                  onClick={() => {
                    setMode(null);
                    setApiKey("");
                  }}
                >
                  CANCEL
                </Button>
                <Button
                  variant="primary"
                  disabled={!canConnect()}
                  onClick={connect}
                >
                  {connecting() ? "CONNECTING…" : "CONNECT & USE THIS"}
                </Button>
              </Row>
            </Stack>
          </Show>
        </Stack>
      </Panel>

      {/* What's already connected — read off the shared store (the same endpoints
          the top-bar picker and Settings use). */}
      <Panel label="CONNECTED PROVIDERS" flush>
        <Show
          when={endpoints.latest}
          fallback={
            <div class="p-3">
              <LoadingText />
            </div>
          }
        >
          <Show
            when={(endpoints.latest ?? []).length}
            fallback={
              <EmptyState
                icon="link"
                message="NOTHING CONNECTED YET"
                hint="Connect a provider above to start chatting."
              />
            }
          >
            <Stack gap={0}>
              <For each={endpoints.latest ?? []}>
                {(ep) => (
                  <Row
                    align="center"
                    justify="between"
                    gap={3}
                    class="border-b border-line px-3 py-2 last:border-0"
                  >
                    <Stack
                      gap={1}
                      class={`min-w-0 ${ep.enabled ? "" : "opacity-40"}`}
                    >
                      <Text variant="label" tone="bright">
                        {ep.name}
                      </Text>
                      <Text variant="micro" tone="dim" class="truncate">
                        {ep.model ? `${ep.model} · ${ep.baseUrl}` : ep.baseUrl}
                      </Text>
                    </Stack>
                    <Row gap={2} align="center" class="shrink-0">
                      <Show when={ep.hasApiKey}>
                        <StatusFlag status="nominal">KEY</StatusFlag>
                      </Show>
                      <EndpointHealthFlag status={ep.lastStatus} />
                    </Row>
                  </Row>
                )}
              </For>
            </Stack>
          </Show>
        </Show>
      </Panel>
    </Stack>
  );
}
