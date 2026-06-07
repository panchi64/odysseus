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
  EmptyState,
  InstrumentBand,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  type Status,
} from "~/ui";
import { timestamp } from "~/lib/format";
import { useServiceStatuses, useOverallHealth } from "../data";
import type { HealthStatus, ServiceStatus } from "../model";

const healthTone: Record<HealthStatus, string> = {
  nominal: "bg-nominal",
  warn: "bg-warn",
  alert: "bg-alert",
};

const healthFlagStatus: Record<HealthStatus, Status> = {
  nominal: "nominal",
  warn: "warn",
  alert: "alert",
};

function HistoryBar(props: { history: HealthStatus[] }): JSX.Element {
  return (
    <div
      class="flex items-center gap-0.5"
      title="Last 10 checks (newest right)"
    >
      <For each={props.history}>
        {(h) => (
          <span
            class={`inline-block h-3 w-1.5 ${healthTone[h]}`}
            style={{ opacity: h === "nominal" ? "0.7" : "1" }}
          />
        )}
      </For>
    </div>
  );
}

export function HealthScreen(): JSX.Element {
  const overallResource = useOverallHealth();
  const servicesResource = useServiceStatuses();
  const [services, setServices] = createStore<ServiceStatus[]>([]);
  const [seeded, setSeeded] = createSignal(false);
  const [refreshing, setRefreshing] = createSignal(false);
  const [lastRefresh, setLastRefresh] = createSignal(new Date().toISOString());
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
    setRefreshing(true);
    timers.push(
      setTimeout(() => {
        setRefreshing(false);
        setLastRefresh(new Date().toISOString());
      }, 1100),
    );
  }

  const overall = () => overallResource();
  const alertCount = () => services.filter((s) => s.status === "alert").length;
  const warnCount = () => services.filter((s) => s.status === "warn").length;

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
                  tone: o().status,
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
                  <ListRow
                    label={svc.name}
                    leading="activity"
                    right={
                      <Row gap={3} align="center">
                        <Show when={svc.degradationNote}>
                          <Text
                            variant="micro"
                            tone="warn"
                            class="max-w-xs truncate"
                          >
                            {svc.degradationNote}
                          </Text>
                        </Show>
                        <Text variant="micro" tone="dim">
                          {svc.detail}
                        </Text>
                        <Show
                          when={svc.status !== "alert"}
                          fallback={
                            <Text variant="micro" tone="alert">
                              OFFLINE
                            </Text>
                          }
                        >
                          <Text variant="micro" tone="dim">
                            {svc.latencyMs}MS
                          </Text>
                        </Show>
                        <HistoryBar history={svc.history} />
                        <StatusFlag status={healthFlagStatus[svc.status]}>
                          {svc.status.toUpperCase()}
                        </StatusFlag>
                      </Row>
                    }
                  />
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
    </Stack>
  );
}
