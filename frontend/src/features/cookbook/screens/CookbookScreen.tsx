import {
  createEffect,
  createSignal,
  For,
  Show,
  Suspense,
  onCleanup,
  type JSX,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  EmptyState,
  ErrorState,
  InfoHint,
  InstrumentBand,
  ListRow,
  ListToolbar,
  LoadingText,
  PageHeader,
  Panel,
  ProgressBar,
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
} from "../data";
import type { ModelEntry, RunningServer, ServerStatus } from "../model";

const suitabilityStatus: Record<string, Status> = {
  nominal: "nominal",
  warn: "warn",
  alert: "alert",
};

// Best-fit first: NOMINAL → WARN → ALERT. (Alphabetical localeCompare would
// invert this, surfacing ALERT/"not recommended" models at the top.)
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

function DownloadRow(props: { model: ModelEntry }): JSX.Element {
  const [progress, setProgress] = createSignal<number | null>(null);
  const [done, setDone] = createSignal(props.model.downloaded);
  const [hasError, setHasError] = createSignal(false);
  const [justFinished, setJustFinished] = createSignal(false);
  const timers: ReturnType<typeof setTimeout>[] = [];

  onCleanup(() => timers.forEach(clearTimeout));

  function cancelDownload() {
    timers.forEach(clearTimeout);
    timers.length = 0;
    setProgress(null);
    setHasError(false);
    toast.warn(`Download cancelled — ${props.model.name}`);
  }

  function startDownload() {
    if (progress() !== null || done()) return;
    setHasError(false);
    setProgress(0);
    let p = 0;
    const tick = () => {
      p += Math.random() * 6 + 2;
      if (p >= 100) {
        setProgress(100);
        timers.push(
          setTimeout(() => {
            setDone(true);
            setProgress(null);
            setJustFinished(true);
            toast.success(`${props.model.name} ready`);
          }, 500),
        );
      } else {
        setProgress(p);
        timers.push(setTimeout(tick, 180));
      }
    };
    timers.push(setTimeout(tick, 100));
  }

  return (
    <div class="border-b border-line last:border-b-0">
      <ListRow
        label={props.model.name}
        leading="layers"
        flush
        right={
          <Row gap={2} align="center">
            <Text variant="micro" tone="dim">
              {props.model.params} · {props.model.quant} ·{" "}
              {bytes(props.model.sizeBytes)}
            </Text>
            <Row gap={1} align="center">
              <StatusFlag status={suitabilityStatus[props.model.suitability]}>
                {props.model.suitability.toUpperCase()}
              </StatusFlag>
              <InfoHint label={SUITABILITY_HINT} size={12} />
            </Row>
            <Show when={done()}>
              <StatusFlag status="nominal">READY</StatusFlag>
            </Show>
            <Show when={hasError()}>
              <StatusFlag status="alert">ERROR</StatusFlag>
              <Button
                size="sm"
                variant="ghost"
                leading="refresh"
                onClick={startDownload}
              >
                RETRY
              </Button>
            </Show>
            <Show when={!done() && !hasError() && progress() === null}>
              <Button
                size="sm"
                variant="ghost"
                leading="download"
                onClick={startDownload}
              >
                GET
              </Button>
            </Show>
            <Show when={progress() !== null && !done()}>
              <Button
                size="sm"
                variant="ghost"
                leading="close"
                onClick={cancelDownload}
              >
                CANCEL
              </Button>
            </Show>
          </Row>
        }
      />
      <Show when={progress() !== null && !done()}>
        <div class="px-3 pb-2">
          <ProgressBar value={progress()!} tone="nominal" showValue />
        </div>
      </Show>
      <Show when={justFinished()}>
        <div class="px-3 pb-2">
          <Text variant="micro" tone="dim">
            Download complete — start a server for this model under RUNNING
            SERVERS to begin serving it.
          </Text>
        </div>
      </Show>
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

  const modelView = createListView<ModelEntry>({
    source: () => models() ?? [],
    search: (m) => `${m.name} ${m.params} ${m.quant}`,
    sorts: {
      fit: {
        label: "FIT",
        compare: (a, b) =>
          suitabilityRank[a.suitability] - suitabilityRank[b.suitability] ||
          a.name.localeCompare(b.name),
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
        subtitle="Local model management, hardware fit analysis, and remote endpoints."
        assetId="SYS-MDL-03.1"
        actions={
          <StatusFlag status="nominal" dot>
            OLLAMA LIVE
          </StatusFlag>
        }
      />

      <Suspense fallback={<LoadingText label="READING HARDWARE" />}>
        <Show when={hardware()}>
          {(hw) => (
            <InstrumentBand
              items={[
                { label: "CHIP", value: hw().chip },
                { label: "RAM", value: hw().ram },
                { label: "VRAM", value: hw().vram },
                { label: "CORES", value: hw().cores },
                { label: "BACKEND", value: "Metal / MPS" },
                { label: "OLLAMA", value: "0.6.4" },
              ]}
            />
          )}
        </Show>
      </Suspense>

      <Tabs
        items={[
          { value: "local", label: "LOCAL MODELS" },
          { value: "remote", label: "REMOTE ENDPOINTS" },
        ]}
        value={tab()}
        onChange={setTab}
      />

      <Show when={tab() === "local"}>
        <Stack gap={4}>
          <Panel label="RECOMMENDED MODELS" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <Show when={models.error}>
                <ErrorState
                  message="FAILED TO LOAD MODELS"
                  hint={String(models.error)}
                />
              </Show>
              <Show
                when={!models.error && (models() ?? []).length}
                fallback={
                  <Show when={!models.error}>
                    <EmptyState
                      icon="layers"
                      message="NO MODELS"
                      hint="No models found in registry."
                    />
                  </Show>
                }
              >
                <div class="border-b border-line p-3">
                  <ListToolbar
                    query={modelView.query()}
                    onQueryChange={modelView.setQuery}
                    placeholder="Search models…"
                    sortKey={modelView.sortKey()}
                    sortOptions={modelView.sortOptions}
                    onSortChange={modelView.setSort}
                    dir={modelView.dir()}
                    onToggleDir={modelView.toggleDir}
                    count={modelView.count()}
                    total={modelView.total()}
                  />
                </div>
                <Show
                  when={modelView.items().length}
                  fallback={
                    <EmptyState
                      icon="search"
                      message="NO MATCHES"
                      hint="No models match your search."
                    />
                  }
                >
                  <For each={modelView.items()}>
                    {(m) => <DownloadRow model={m} />}
                  </For>
                </Show>
              </Show>
            </Suspense>
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
      </Show>

      <Show when={tab() === "remote"}>
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
              when={!remoteEndpoints.error && (remoteEndpoints() ?? []).length}
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
                        <StatusFlag status={ep.apiKeySet ? "nominal" : "warn"}>
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
      </Show>
    </Stack>
  );
}
