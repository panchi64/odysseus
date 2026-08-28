import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import {
  Button,
  EmptyState,
  ExternalLink,
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
import { useProviders, type ModelProvider } from "~/lib/stores/models";
import { connectAndSelectEndpoint, useRemoteEndpoints } from "../data";
import { LocalSetupForm } from "./LocalSetupForm";

/** The guided "it just works" setup: pick a provider preset (served by
 *  `GET /models/providers` — nothing hardcoded here) → paste a key →
 *  "Connect & use this". The backend tests the connection and a sensible default
 *  model is auto-selected, so the operator never has to choose one. Discovering /
 *  evaluating models is out of scope here.
 *
 *  Presentation-only: every decision (does it work, which model resolves at send
 *  time) is the backend's; this surface captures intent and renders the verdict. */
export function GetStartedPanel(): JSX.Element {
  const endpoints = useRemoteEndpoints();
  const allProviders = useProviders();
  const navigate = useNavigate();

  // The serving-managed "local" adapter isn't a connectable API — that's the
  // RUN LOCALLY tile's path — so the remote form offers every other preset.
  const providers = createMemo<ModelProvider[]>(() =>
    (allProviders.latest ?? []).filter((p) => p.id !== "local"),
  );

  // `null` = the two-choice entry; "remote"/"local" = that guided form is open.
  const [mode, setMode] = createSignal<null | "remote" | "local">(null);
  const [providerId, setProviderId] = createSignal<string | null>(null);
  const [typedBaseUrl, setTypedBaseUrl] = createSignal("");
  const [apiKey, setApiKey] = createSignal("");
  const [connecting, setConnecting] = createSignal(false);

  const provider = createMemo<ModelProvider | undefined>(
    () => providers().find((p) => p.id === providerId()) ?? providers()[0],
  );
  // The preset's base URL when it carries one; operator-typed otherwise.
  const baseUrl = () => provider()?.defaultBaseUrl ?? typedBaseUrl();
  const baseUrlEditable = () => provider()?.defaultBaseUrl == null;

  // The simple form is preset-driven: the name comes from the provider and only
  // the key (plus the base URL, when the preset carries none) is captured —
  // string-shaped for the form; the advanced-only fields it ignores stay blank.
  const formValues = createMemo<EndpointFormValues>(() => ({
    name: provider()?.displayName ?? "",
    baseUrl: baseUrl(),
    provider: provider()?.id ?? "",
    model: "",
    apiKey: apiKey(),
    contextWindow: "",
    nativeTools: provider()?.nativeTools ?? true,
    vision: provider()?.vision ?? false,
    thinking: false,
  }));

  const canConnect = () => {
    const p = provider();
    return (
      !connecting() &&
      p !== undefined &&
      baseUrl().trim() !== "" &&
      (!p.requiresKey || apiKey().trim() !== "")
    );
  };

  const connect = async () => {
    const p = provider();
    if (!canConnect() || !p) return;
    setConnecting(true);
    try {
      const ok = await connectAndSelectEndpoint(
        {
          provider: p,
          baseUrl: baseUrl().trim(),
          apiKey: apiKey().trim(),
        },
        navigate,
      );
      if (ok) {
        // Connected & selected — collapse the form; the new endpoint shows below.
        setMode(null);
        setApiKey("");
        setTypedBaseUrl("");
      }
    } finally {
      setConnecting(false);
    }
  };

  const presetOptions = createMemo(() =>
    providers().map((p) => ({ value: p.id, label: p.displayName })),
  );

  return (
    <Stack gap={6}>
      <Panel label="Get started">
        <Stack gap={4}>
          <Text variant="micro" tone="dim">
            Connect a model and start chatting — bring your own remote API, or
            download and serve one locally on this machine. Either way we wire
            it up and select a model for you.
          </Text>

          {/* Two-choice entry. */}
          <Show when={mode() === null}>
            <Row gap={3} align="stretch">
              <button
                type="button"
                onClick={() => setMode("remote")}
                class="flex-1 rounded-panel bg-surface p-4 text-left shadow-1 transition-colors hover:bg-raised"
              >
                <Stack gap={1}>
                  <Text variant="label" tone="bright">
                    Use a remote API
                  </Text>
                  <Text variant="micro" tone="dim">
                    Anthropic, Google, or any OpenAI-compatible server.
                  </Text>
                </Stack>
              </button>
              <button
                type="button"
                onClick={() => setMode("local")}
                class="flex-1 rounded-panel bg-surface p-4 text-left shadow-1 transition-colors hover:bg-raised"
              >
                <Stack gap={1}>
                  <Text variant="label" tone="bright">
                    Run locally
                  </Text>
                  <Text variant="micro" tone="dim">
                    Download and serve a model on this machine.
                  </Text>
                </Stack>
              </button>
            </Row>
          </Show>

          {/* Guided local-serve flow. */}
          <Show when={mode() === "local"}>
            <LocalSetupForm onDone={() => setMode(null)} />
          </Show>

          {/* Guided remote-API form. */}
          <Show when={mode() === "remote"}>
            <Show when={provider()} fallback={<LoadingText />}>
              {(p) => (
                <Stack gap={3}>
                  <Select
                    label="Provider"
                    options={presetOptions()}
                    value={p().id}
                    onChange={(v) => {
                      setProviderId(v);
                      setApiKey("");
                      setTypedBaseUrl("");
                    }}
                  />
                  <EndpointForm
                    variant="simple"
                    requiresKey={p().requiresKey}
                    baseUrlEditable={baseUrlEditable()}
                    keyHint={p().keyHint ?? undefined}
                    values={formValues()}
                    onChange={(key, value) => {
                      if (key === "apiKey") setApiKey(value as string);
                      if (key === "baseUrl") setTypedBaseUrl(value as string);
                    }}
                  />
                  <Show when={p().docsUrl}>
                    {(docsUrl) => (
                      <ExternalLink href={docsUrl()}>
                        {p().requiresKey
                          ? "Get an API key ↗"
                          : "Set up the server ↗"}
                      </ExternalLink>
                    )}
                  </Show>
                  <Row gap={2} justify="end">
                    <Button
                      variant="ghost"
                      disabled={connecting()}
                      onClick={() => {
                        setMode(null);
                        setApiKey("");
                        setTypedBaseUrl("");
                      }}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      disabled={!canConnect()}
                      onClick={connect}
                    >
                      {connecting() ? "Connecting…" : "Connect & use this"}
                    </Button>
                  </Row>
                </Stack>
              )}
            </Show>
          </Show>
        </Stack>
      </Panel>

      {/* What's already connected — read off the shared store (the same endpoints
          the top-bar picker and Settings use). */}
      <Panel label="Connected providers" flush>
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
                message="Nothing connected yet"
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
                    class="px-3 py-2"
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
                        <StatusFlag status="nominal">Key</StatusFlag>
                      </Show>
                      {/* A managed engine's liveness is its process state, not
                          its enabled switch or a probe verdict. */}
                      <Show when={ep.managed}>
                        <StatusFlag
                          status={
                            ep.liveStatus === "running" ? "nominal" : "warn"
                          }
                        >
                          {ep.liveStatus === "running" ? "Running" : "Stopped"}
                        </StatusFlag>
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
