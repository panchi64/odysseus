import {
  createEffect,
  createResource,
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  Chip,
  EmptyState,
  ErrorState,
  Icon,
  InfoHint,
  InstrumentBand,
  ListRow,
  ListToolbar,
  LoadingText,
  NotConnectedOverlay,
  PageHeader,
  Panel,
  Readout,
  Row,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  confirm,
  toast,
  type Status,
} from "~/ui";
import { createListView } from "~/lib/list";
import { bytes } from "~/lib/format";

const SUITABILITY_HINT =
  "Hardware fit for this model: NOMINAL — runs comfortably within memory; WARN — fits but leaves little headroom, expect slower output; ALERT — exceeds the memory budget, not recommended.";
import {
  useHardware,
  useCookbookModels,
  useRunningServers,
  useRemoteEndpoints,
  searchModels,
} from "../data";
import type { ModelEntry, RunningServer, ServerStatus } from "../model";
import { EmbeddingPanel } from "../components/EmbeddingPanel";
import { ComparePanel } from "../components/ComparePanel";

const suitabilityStatus: Record<string, Status> = {
  nominal: "nominal",
  warn: "warn",
  alert: "alert",
};

// Best-fit band first: NOMINAL → WARN → ALERT. Within a band the backend's
// quality ranking is authoritative, so the default view preserves its order.
const suitabilityRank: Record<string, number> = {
  nominal: 0,
  warn: 1,
  alert: 2,
};

const serverStatusFlag: Record<ServerStatus, Status> = {
  running: "nominal",
  stopped: "idle",
  starting: "info",
  error: "alert",
};

const CAPS_HINT =
  "Model capabilities: TOOLS — native tool/function calling; REASONING — extended thinking; VISION — image input; EMBEDDING — vector embeddings; IMAGE — image generation.";

const QUALITY_HINT =
  "Model quality from a live benchmark source (higher is better). The figure is the active source's headline metric — e.g. an LMArena Elo or an Intelligence Index — blank when the source hasn't rated the model yet (it's then ranked by its family's standing).";

// One row of the compatible-models table. A `subgrid` so its cells inherit the shared
// column tracks and line up with every other row. Read-only: the backend ranks the
// models that fit this hardware; downloading/serving them lands with a later slice.
function ModelRow(props: { model: ModelEntry }): JSX.Element {
  const caps = () => props.model.capabilities;
  const quality = () => props.model.qualityValue;
  return (
    <div class="col-span-full grid grid-cols-subgrid items-center gap-x-4 border-b border-line px-3 py-2 last:border-b-0">
      <span class="flex min-w-0 items-center gap-2">
        <Icon name="layers" size={14} class="shrink-0 text-dim" />
        <Text variant="body" tone="bright" class="truncate">
          {props.model.name}
        </Text>
      </span>
      <Text
        variant="body"
        tone={quality() != null ? "bright" : "dim"}
        class="text-right tabular-nums"
      >
        {quality() != null ? Math.round(quality()!) : "—"}
      </Text>
      <span class="flex items-center gap-1">
        <Show when={caps().tools}>
          <Chip>TOOLS</Chip>
        </Show>
        <Show when={caps().reasoning}>
          <Chip>REASONING</Chip>
        </Show>
        <Show when={caps().vision}>
          <Chip>VISION</Chip>
        </Show>
        <Show when={caps().embedding}>
          <Chip>EMBEDDING</Chip>
        </Show>
        <Show when={caps().imageGen}>
          <Chip>IMAGE</Chip>
        </Show>
      </span>
      <Text variant="body" tone="default" class="text-right tabular-nums">
        {props.model.params}
      </Text>
      <Text variant="body" tone="default">
        {props.model.quant}
      </Text>
      <Text variant="body" tone="default" class="text-right tabular-nums">
        {bytes(props.model.sizeBytes)}
      </Text>
      <StatusFlag status={suitabilityStatus[props.model.suitability]}>
        {props.model.suitability.toUpperCase()}
      </StatusFlag>
    </div>
  );
}

function ServerRow(props: {
  server: RunningServer;
  onToggle: (id: string) => void;
  onRetry: (id: string) => void;
}): JSX.Element {
  return (
    <ListRow
      label={props.server.model}
      leading="cpu"
      right={
        <Row gap={3} align="center">
          <Text variant="micro" tone="dim">
            :{props.server.port}
          </Text>
          <Show
            when={props.server.status === "running" && props.server.contextLen}
          >
            <Readout
              size="md"
              label="CTX"
              labelPosition="bottom"
              value={props.server.contextLen!.toLocaleString()}
              unit="tok"
            />
          </Show>
          <Show when={props.server.tokensPerSec}>
            <Text variant="micro" tone="dim">
              {props.server.tokensPerSec} T/S
            </Text>
          </Show>
          <StatusFlag
            status={serverStatusFlag[props.server.status]}
            dot={props.server.status === "running"}
          >
            {props.server.status.toUpperCase()}
          </StatusFlag>
          <Show when={props.server.status === "error"}>
            <Button
              size="sm"
              variant="default"
              leading="refresh"
              onClick={() => props.onRetry(props.server.id)}
            >
              RETRY
            </Button>
          </Show>
          <Show when={props.server.status !== "error"}>
            <Show
              when={props.server.status === "running"}
              fallback={
                <Button
                  size="sm"
                  variant="default"
                  leading="play"
                  onClick={() => props.onToggle(props.server.id)}
                >
                  START
                </Button>
              }
            >
              <Button
                size="sm"
                variant="danger"
                leading="stop"
                onClick={() => props.onToggle(props.server.id)}
              >
                STOP
              </Button>
            </Show>
          </Show>
        </Row>
      }
    />
  );
}

export function CookbookScreen(): JSX.Element {
  const hardware = useHardware();
  const models = useCookbookModels();
  const serversResource = useRunningServers();
  const remoteEndpoints = useRemoteEndpoints();
  const [tab, setTab] = createSignal("local");
  const [servers, setServers] = createStore<RunningServer[]>([]);

  // The search box queries the full catalog on the backend (debounced), so the operator
  // can check any model — not just the curated compatible list — against their hardware.
  // Empty query → the curated list; a query → backend search results, both scored here.
  const [query, setQuery] = createSignal("");
  const [debounced, setDebounced] = createSignal("");
  createEffect(() => {
    const q = query().trim();
    const timer = setTimeout(() => setDebounced(q), 300);
    onCleanup(() => clearTimeout(timer));
  });
  const [searchResults] = createResource(
    () => debounced() || null,
    (q) => searchModels(q),
  );
  const isSearching = () => debounced().length > 0;
  const displayModels = (): ModelEntry[] =>
    isSearching() ? (searchResults() ?? []) : (models() ?? []);

  const modelView = createListView<ModelEntry>({
    // Sort-only over the displayed set (curated list or search results); filtering is
    // the backend search's job, so no client `search` predicate here.
    source: displayModels,
    sorts: {
      fit: {
        label: "FIT",
        // Band only — within a band, the stable sort keeps the backend's quality
        // order (newer/stronger models first). Re-sorting by name would discard it.
        compare: (a, b) =>
          suitabilityRank[a.suitability] - suitabilityRank[b.suitability],
      },
      name: { label: "NAME", compare: (a, b) => a.name.localeCompare(b.name) },
      size: { label: "SIZE", compare: (a, b) => a.sizeBytes - b.sizeBytes },
    },
    initialSort: "fit",
  });

  // Seed local mutable store from data layer once resource resolves.
  // Phase 2: only fetchServers() body changes — store/screen stay stable.
  createEffect(() => {
    const data = serversResource();
    if (data) setServers(data.map((s) => ({ ...s })));
  });

  // Drive a server from its current state up to running: flip to "starting",
  // then after a beat mark it running with live readouts. Shared by the
  // start-from-stopped and retry-from-error paths (they differ only in toast).
  function bringServerUp(id: string, successMsg: string) {
    setServers(
      produce((s) => {
        const target = s.find((x) => x.id === id);
        if (target) target.status = "starting";
      }),
    );
    setTimeout(() => {
      setServers(
        produce((s) => {
          const target = s.find((x) => x.id === id);
          if (target) {
            target.status = "running";
            target.tokensPerSec = 74.1;
            if (!target.contextLen) target.contextLen = 32768;
          }
        }),
      );
      toast.success(successMsg);
    }, 1200);
  }

  async function toggleServer(id: string) {
    const srv = servers.find((x) => x.id === id);
    if (!srv) return;

    if (srv.status === "running") {
      const ok = await confirm({
        title: `Stop server ${srv.model} on :${srv.port}?`,
        detail: "This will disconnect active sessions using this model.",
        confirmLabel: "STOP SERVER",
        tone: "alert",
      });
      if (!ok) return;

      setServers(
        produce((s) => {
          const target = s.find((x) => x.id === id);
          if (!target) return;
          target.status = "stopped";
          target.tokensPerSec = undefined;
        }),
      );
      toast.success(`Server stopped — ${srv.model}`);
    } else {
      bringServerUp(id, `Server started — ${srv.model}`);
    }
  }

  function retryServer(id: string) {
    const srv = servers.find((x) => x.id === id);
    if (!srv) return;
    bringServerUp(id, `Server recovered — ${srv.model}`);
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="MODEL COOKBOOK"
        subtitle="Local and remote model serving, hardware fit, embedding configuration, and side-by-side comparison."
        assetId="SYS-MDL-03.1"
        actions={
          <Show when={hardware()}>
            {(hw) => (
              <StatusFlag status="nominal" dot>
                {hw().backend}
              </StatusFlag>
            )}
          </Show>
        }
      />

      <Show when={tab() === "local" || tab() === "remote"}>
        <Suspense fallback={<LoadingText label="READING HARDWARE" />}>
          <Show when={hardware()}>
            {(hw) => (
              <InstrumentBand
                items={[
                  { label: "CHIP", value: hw().chip },
                  { label: "RAM", value: hw().ram },
                  { label: "VRAM", value: hw().vram },
                  { label: "CORES", value: hw().cores },
                  { label: "BACKEND", value: hw().backend },
                  ...(hw().runtimes.length
                    ? hw().runtimes.map((r) => ({
                        label: r.name.toUpperCase(),
                        value: r.version ?? "—",
                      }))
                    : [
                        {
                          label: "RUNTIME",
                          value: "none detected",
                          tone: "dim" as const,
                        },
                      ]),
                ]}
              />
            )}
          </Show>
        </Suspense>
      </Show>

      <Tabs
        items={[
          { value: "local", label: "LOCAL MODELS" },
          { value: "remote", label: "REMOTE ENDPOINTS" },
          { value: "embedding", label: "EMBEDDING" },
          { value: "compare", label: "COMPARE" },
        ]}
        value={tab()}
        onChange={setTab}
      />

      {/* LOCAL MODELS is wired: the hardware band + compatible models come from the
          backend Cookbook. REMOTE ENDPOINTS and EMBEDDING remain mock surfaces and
          carry their own inline NOT CONNECTED marker. */}
      <Show when={tab() === "local"}>
        <div class="relative">
          <Stack gap={4}>
            <Panel label="COMPATIBLE MODELS" flush>
              <Show
                when={!models.error}
                fallback={
                  <ErrorState
                    message="FAILED TO LOAD MODELS"
                    hint={String(models.error)}
                  />
                }
              >
                {/* Toolbar stays mounted (outside Suspense) so the search box never
                    vanishes while a search is in flight. */}
                <div class="border-b border-line p-3">
                  <ListToolbar
                    query={query()}
                    onQueryChange={setQuery}
                    placeholder="Search all models…"
                    sortKey={modelView.sortKey()}
                    sortOptions={modelView.sortOptions}
                    onSortChange={modelView.setSort}
                    dir={modelView.dir()}
                    onToggleDir={modelView.toggleDir}
                    count={modelView.count()}
                    total={modelView.total()}
                  />
                </div>
                <Suspense
                  fallback={
                    <div class="p-3">
                      <LoadingText
                        label={isSearching() ? "SEARCHING" : "LOADING"}
                      />
                    </div>
                  }
                >
                  <Show
                    when={modelView.items().length}
                    fallback={
                      <EmptyState
                        icon="search"
                        message={isSearching() ? "NO MATCHES" : "NO MODELS"}
                        hint={
                          isSearching()
                            ? `No models found for “${debounced()}”.`
                            : "No models compatible with this hardware."
                        }
                      />
                    }
                  >
                    {/* One shared grid drives the header + every row (each a
                        `subgrid`), so the columns line up vertically for fast
                        scanning. Numbers are right-aligned and tabular. */}
                    <div class="overflow-x-auto">
                      <div class="grid min-w-max grid-cols-[1fr_auto_auto_auto_auto_auto_auto]">
                        <div class="col-span-full grid grid-cols-subgrid items-center gap-x-4 border-b border-line px-3 py-2">
                          <Text variant="label" tone="dim">
                            MODEL
                          </Text>
                          <Row gap={1} align="center" class="justify-end">
                            <Text variant="label" tone="dim">
                              QUALITY
                            </Text>
                            <InfoHint label={QUALITY_HINT} size={12} />
                          </Row>
                          <Row gap={1} align="center">
                            <Text variant="label" tone="dim">
                              CAPABILITIES
                            </Text>
                            <InfoHint label={CAPS_HINT} size={12} />
                          </Row>
                          <Text variant="label" tone="dim" class="text-right">
                            PARAMS
                          </Text>
                          <Text variant="label" tone="dim">
                            QUANT
                          </Text>
                          <Text variant="label" tone="dim" class="text-right">
                            SIZE
                          </Text>
                          <Row gap={1} align="center">
                            <Text variant="label" tone="dim">
                              FIT
                            </Text>
                            <InfoHint label={SUITABILITY_HINT} size={12} />
                          </Row>
                        </div>
                        <For each={modelView.items()}>
                          {(m) => <ModelRow model={m} />}
                        </For>
                      </div>
                    </div>
                  </Show>
                </Suspense>
              </Show>
            </Panel>

            <Panel
              label="RUNNING SERVERS"
              meta={
                <Text variant="micro" tone="dim">
                  {servers.filter((s) => s.status === "running").length} ACTIVE
                </Text>
              }
              flush
            >
              <Suspense
                fallback={
                  <div class="p-3">
                    <LoadingText />
                  </div>
                }
              >
                <Show when={serversResource.error}>
                  <ErrorState
                    message="FAILED TO LOAD SERVERS"
                    hint={String(serversResource.error)}
                  />
                </Show>
                <Show when={!serversResource.error}>
                  <Show
                    when={servers.length}
                    fallback={
                      <EmptyState
                        icon="cpu"
                        message="NO SERVERS"
                        hint="No model servers configured."
                      />
                    }
                  >
                    <For each={servers}>
                      {(srv) => (
                        <ServerRow
                          server={srv}
                          onToggle={toggleServer}
                          onRetry={retryServer}
                        />
                      )}
                    </For>
                  </Show>
                </Show>
              </Suspense>
            </Panel>
          </Stack>
        </div>
      </Show>

      <Show when={tab() === "remote"}>
        <div class="relative">
          <Panel label="REMOTE ENDPOINTS" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <Show when={remoteEndpoints.error}>
                <ErrorState
                  message="FAILED TO LOAD ENDPOINTS"
                  hint={String(remoteEndpoints.error)}
                />
              </Show>
              <Show
                when={
                  !remoteEndpoints.error && (remoteEndpoints() ?? []).length
                }
                fallback={
                  <Show when={!remoteEndpoints.error}>
                    <EmptyState
                      icon="link"
                      message="NO ENDPOINTS"
                      hint="Add a remote model API endpoint."
                    />
                  </Show>
                }
              >
                <For each={remoteEndpoints()}>
                  {(ep) => (
                    <ListRow
                      label={ep.name}
                      leading="link"
                      right={
                        <Row gap={2} align="center">
                          <Text variant="micro" tone="dim">
                            {ep.baseUrl}
                          </Text>
                          <Show when={ep.latencyMs}>
                            <Text variant="micro" tone="dim">
                              {ep.latencyMs}MS
                            </Text>
                          </Show>
                          <StatusFlag
                            status={ep.apiKeySet ? "nominal" : "warn"}
                          >
                            {ep.apiKeySet ? "KEY SET" : "NO KEY"}
                          </StatusFlag>
                          <StatusFlag
                            status={
                              ep.status === "ok"
                                ? "nominal"
                                : ep.status === "error"
                                  ? "alert"
                                  : "idle"
                            }
                          >
                            {ep.status.toUpperCase()}
                          </StatusFlag>
                        </Row>
                      }
                    />
                  )}
                </For>
              </Show>
            </Suspense>
          </Panel>
          <NotConnectedOverlay />
        </div>
      </Show>

      <Show when={tab() === "embedding"}>
        <div class="relative">
          <EmbeddingPanel />
          <NotConnectedOverlay />
        </div>
      </Show>

      <Show when={tab() === "compare"}>
        <ComparePanel />
      </Show>
    </Stack>
  );
}
