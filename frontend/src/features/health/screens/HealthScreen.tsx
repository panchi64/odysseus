import {
  createSignal,
  For,
  Show,
  Suspense,
  onCleanup,
  type JSX,
} from "solid-js";
import { createStore } from "solid-js/store";
import {
  Button,
  Drawer,
  EmptyState,
  Icon,
  InfoHint,
  InstrumentBand,
  LoadingText,
  Menu,
  type MenuItem,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  toast,
  type Status,
} from "~/ui";
import { timestamp } from "~/lib/format";
import { Marquee } from "../components/Marquee";
import { useServiceStatuses, useOverallHealth } from "../data";
import type { HealthStatus, ServiceStatus } from "../model";

const healthTone: Record<HealthStatus, string> = {
  nominal: "bg-nominal",
  warn: "bg-warn",
  alert: "bg-alert",
  timeout: "bg-warn",
  partial: "bg-info",
};

const healthFlagStatus: Record<HealthStatus, Status> = {
  nominal: "nominal",
  warn: "warn",
  alert: "alert",
  timeout: "warn",
  partial: "info",
};

/** Maps HealthStatus to the nearest TextTone for InstrumentBand cells. */
const healthTextTone: Record<
  HealthStatus,
  "nominal" | "warn" | "alert" | "info" | "dim"
> = {
  nominal: "nominal",
  warn: "warn",
  alert: "alert",
  timeout: "warn",
  partial: "info",
};

/** Service-specific recovery actions for Phase 1 (toasts as feedback, Phase 2 wires to backend). */
function getServiceActions(
  svc: ServiceStatus,
  onAction: (label: string) => void,
) {
  const base: MenuItem[] = [
    {
      label: "VIEW LOGS",
      icon: "note" as const,
      onSelect: () => onAction(`Viewing logs for ${svc.name}`),
    },
  ];

  if (svc.status === "alert" || svc.status === "timeout") {
    base.unshift({
      label: "RETRY CONNECTION",
      icon: "refresh" as const,
      onSelect: () => onAction(`Retrying connection for ${svc.name}`),
    });
  }

  if (svc.id === "svc-embed") {
    base.unshift({
      label: "REINDEX",
      icon: "database" as const,
      onSelect: () => onAction(`Reindex queued for ${svc.name}`),
    });
  }

  if (svc.status === "partial") {
    base.unshift({
      label: "RETRY PARTIAL",
      icon: "refresh" as const,
      onSelect: () => onAction(`Retry queued for ${svc.name}`),
    });
  }

  return base;
}

/** Health checks run on a fixed interval; each tick = one probe. */
const CHECK_INTERVAL = "30s";
const HISTORY_HINT = `Last 10 health checks (newest on the right). One tick = one probe, every ${CHECK_INTERVAL} — spans ~5 min.`;

function HistoryBar(props: {
  history: HealthStatus[];
  showHint?: boolean;
}): JSX.Element {
  return (
    <div class="flex items-center gap-1" title={HISTORY_HINT}>
      <div class="flex items-center gap-0.5">
        <For each={props.history}>
          {(h) => (
            <span
              class={`inline-block h-3 w-1.5 ${healthTone[h]}`}
              style={{ opacity: h === "nominal" ? "0.7" : "1" }}
            />
          )}
        </For>
      </div>
      <Show when={props.showHint}>
        <InfoHint label={HISTORY_HINT} size={11} />
      </Show>
    </div>
  );
}

/** Drawer showing detail and recovery actions for a single service. */
function ServiceDrawer(props: {
  svc: ServiceStatus | null;
  onClose: () => void;
}): JSX.Element {
  function handleAction(label: string) {
    props.onClose();
    toast.info(`${label} — available in Phase 2`, { duration: 3500 });
  }

  return (
    <Drawer
      open={props.svc !== null}
      onClose={props.onClose}
      title={props.svc?.name ?? ""}
    >
      <Show when={props.svc}>
        {(svc) => (
          <Stack gap={4}>
            <Row gap={2} align="center">
              <StatusFlag status={healthFlagStatus[svc().status]}>
                {svc().status.toUpperCase()}
              </StatusFlag>
              <Text variant="body" tone="dim">
                {svc().detail}
              </Text>
            </Row>

            <Show when={svc().degradationNote}>
              <Panel label="DEGRADATION NOTE" state="alert">
                <Text
                  variant="body"
                  tone={svc().status === "alert" ? "alert" : "warn"}
                >
                  {svc().degradationNote}
                </Text>
              </Panel>
            </Show>

            <Stack gap={2}>
              <Text variant="label" tone="dim">
                RECOVERY ACTIONS
              </Text>
              <For each={getServiceActions(svc(), handleAction)}>
                {(action) => (
                  <Button
                    variant="ghost"
                    leading={action.icon}
                    onClick={action.onSelect}
                    class="w-full justify-start"
                  >
                    {action.label}
                  </Button>
                )}
              </For>
              <Show
                when={
                  svc().status === "nominal" &&
                  getServiceActions(svc(), handleAction).length <= 1
                }
              >
                <Text variant="micro" tone="dim">
                  No recovery actions needed — service is healthy.
                </Text>
              </Show>
            </Stack>

            <Stack gap={1}>
              <Row gap={1} align="center">
                <Text variant="label" tone="dim">
                  HISTORY · EVERY {CHECK_INTERVAL}
                </Text>
                <InfoHint label={HISTORY_HINT} size={11} />
              </Row>
              <HistoryBar history={svc().history} />
            </Stack>

            <Show when={svc().latencyMs > 0}>
              <Row gap={2} align="baseline">
                <Text variant="micro" tone="dim">
                  LATENCY: {svc().latencyMs}MS
                </Text>
                <Text variant="micro" tone="dim">
                  · {svc().baselineMs}MS baseline
                </Text>
                <InfoHint
                  label="Baseline = typical latency for this service under normal load. Live latency well above baseline indicates degradation."
                  size={11}
                />
              </Row>
            </Show>
          </Stack>
        )}
      </Show>
    </Drawer>
  );
}

export function HealthScreen(): JSX.Element {
  const overallResource = useOverallHealth();
  const servicesResource = useServiceStatuses();
  const [services, setServices] = createStore<ServiceStatus[]>([]);
  const [seeded, setSeeded] = createSignal(false);
  const [refreshing, setRefreshing] = createSignal(false);
  const [lastRefresh, setLastRefresh] = createSignal(new Date().toISOString());
  const [drawerSvc, setDrawerSvc] = createSignal<ServiceStatus | null>(null);
  const timers: ReturnType<typeof setTimeout>[] = [];

  onCleanup(() => timers.forEach(clearTimeout));

  const resolveServices = () => {
    const data = servicesResource();
    if (data && !seeded()) {
      setSeeded(true);
      setServices(data.map((s) => ({ ...s, history: [...s.history] })));
    }
    return data;
  };

  function refresh() {
    if (refreshing()) return;

    const prevDegradedIds = new Set(
      services.filter((s) => s.degradationNote).map((s) => s.id),
    );

    setRefreshing(true);
    timers.push(
      setTimeout(() => {
        setRefreshing(false);
        const now = new Date();
        setLastRefresh(now.toISOString());

        // Determine if any degradations resolved since last check.
        const resolvedCount = services.filter(
          (s) => prevDegradedIds.has(s.id) && !s.degradationNote,
        ).length;

        const timeStr = now.toLocaleTimeString("en-US", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        });

        if (resolvedCount > 0) {
          toast.success(
            `${resolvedCount} issue${resolvedCount > 1 ? "s" : ""} resolved — checked at ${timeStr}`,
          );
        } else {
          toast.success(`Status checked — ${timeStr}`);
        }
      }, 1100),
    );
  }

  const overall = () => overallResource();
  const alertCount = () => services.filter((s) => s.status === "alert").length;
  const warnCount = () =>
    services.filter(
      (s) =>
        s.status === "warn" || s.status === "timeout" || s.status === "partial",
    ).length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="HEALTH DASHBOARD"
        subtitle="Live service diagnostics and degradation tracking."
        assetId="SYS-HLT-07.1"
        actions={
          <Row gap={2} align="center">
            <Show when={overall()}>
              {(o) => (
                <StatusFlag
                  status={healthFlagStatus[o().status]}
                  dot={o().status !== "nominal"}
                >
                  {o().status.toUpperCase()}
                </StatusFlag>
              )}
            </Show>
            <Button
              variant="ghost"
              leading="refresh"
              onClick={refresh}
              disabled={refreshing()}
            >
              {refreshing() ? "CHECKING…" : "REFRESH"}
            </Button>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText label="CHECKING SERVICES" />}>
        <Show when={overall()}>
          {(o) => (
            <InstrumentBand
              items={[
                {
                  label: "OVERALL",
                  value: o().status.toUpperCase(),
                  tone: healthTextTone[o().status],
                },
                {
                  label: "UP",
                  value: `${o().servicesUp} / ${o().servicesTotal}`,
                  tone: "nominal",
                },
                {
                  label: "ALERTS",
                  value: String(alertCount()),
                  tone: alertCount() > 0 ? "alert" : "dim",
                },
                {
                  label: "WARNINGS",
                  value: String(warnCount()),
                  tone: warnCount() > 0 ? "warn" : "dim",
                },
                { label: "LAST CHECK", value: timestamp(lastRefresh()) },
                { label: "UPTIME", value: "99.1%" },
              ]}
            />
          )}
        </Show>
      </Suspense>

      <Suspense fallback={<LoadingText label="LOADING SERVICES" />}>
        <Show when={resolveServices()}>
          <Show
            when={services.length}
            fallback={<EmptyState icon="activity" message="NO SERVICES" />}
          >
            <Panel label="SERVICE GRID" flush>
              <For each={services}>
                {(svc) => (
                  <div
                    role="button"
                    tabindex={0}
                    onClick={() => setDrawerSvc(svc)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setDrawerSvc(svc);
                      }
                    }}
                    class="flex w-full min-w-0 cursor-pointer items-center gap-3 border-b border-line px-3 py-2 text-left transition-colors hover:bg-raised"
                  >
                    <span class="flex shrink-0 items-center gap-2">
                      <Icon name="activity" class="text-dim" />
                      <Text variant="label">{svc.name}</Text>
                    </span>

                    {/* Flexible slot: a long degradation note marquees here
                        rather than pushing the row past full width. */}
                    <Show
                      when={svc.degradationNote}
                      fallback={<span class="flex-1" />}
                    >
                      <Marquee class="min-w-0 flex-1">
                        <Text
                          variant="micro"
                          tone={svc.status === "alert" ? "alert" : "warn"}
                        >
                          {svc.degradationNote}
                        </Text>
                      </Marquee>
                    </Show>

                    <span class="flex shrink-0 items-center gap-3">
                      <Text variant="micro" tone="dim">
                        {svc.detail}
                      </Text>
                      <Show
                        when={
                          svc.status !== "alert" && svc.status !== "timeout"
                        }
                        fallback={
                          <Text
                            variant="micro"
                            tone={svc.status === "timeout" ? "warn" : "alert"}
                          >
                            {svc.status === "timeout" ? "TIMEOUT" : "OFFLINE"}
                          </Text>
                        }
                      >
                        <span title={`Baseline ${svc.baselineMs}MS`}>
                          <Text
                            variant="micro"
                            tone={
                              svc.latencyMs > svc.baselineMs * 2
                                ? "warn"
                                : "dim"
                            }
                          >
                            {svc.latencyMs}
                            <span class="text-dim">/{svc.baselineMs}MS</span>
                          </Text>
                        </span>
                      </Show>
                      <HistoryBar history={svc.history} showHint />
                      <StatusFlag status={healthFlagStatus[svc.status]}>
                        {svc.status.toUpperCase()}
                      </StatusFlag>
                      <Show
                        when={
                          svc.status === "alert" ||
                          svc.status === "warn" ||
                          svc.status === "timeout" ||
                          svc.status === "partial"
                        }
                      >
                        <span onClick={(e) => e.stopPropagation()}>
                          <Menu
                            trigger={
                              <Button variant="ghost" size="sm">
                                ACTIONS
                              </Button>
                            }
                            items={getServiceActions(svc, (label) => {
                              toast.info(`${label} — available in Phase 2`, {
                                duration: 3500,
                              });
                            })}
                            align="right"
                          />
                        </span>
                      </Show>
                    </span>
                  </div>
                )}
              </For>
            </Panel>
          </Show>
        </Show>
      </Suspense>

      <Show when={services.filter((s) => s.degradationNote).length > 0}>
        <Panel label="DEGRADATION NOTES" state="alert">
          <Stack gap={3}>
            <For each={services.filter((s) => s.degradationNote)}>
              {(svc) => (
                <Row gap={3} align="center">
                  <StatusFlag status={healthFlagStatus[svc.status]}>
                    {svc.name}
                  </StatusFlag>
                  <Text
                    variant="body"
                    tone={svc.status === "alert" ? "alert" : "warn"}
                  >
                    {svc.degradationNote}
                  </Text>
                </Row>
              )}
            </For>
          </Stack>
        </Panel>
      </Show>

      <ServiceDrawer svc={drawerSvc()} onClose={() => setDrawerSvc(null)} />
    </Stack>
  );
}
