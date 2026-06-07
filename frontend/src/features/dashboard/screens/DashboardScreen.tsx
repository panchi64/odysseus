import { For, Show, Suspense, type JSX } from "solid-js";
import {
  InstrumentBand,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  Readout,
  Stack,
  StatusFlag,
  Text,
  Tile,
  type Status,
} from "~/ui";
import { NAV } from "~/app/nav";
import { useSystemBand, useServices } from "../data";

const healthStatus: Record<string, Status> = {
  nominal: "nominal",
  warn: "warn",
  alert: "alert",
};

/** Home overview: system telemetry, service health, and quick-access tiles. */
export function DashboardScreen(): JSX.Element {
  const systemBand = useSystemBand();
  const services = useServices();
  const quickTiles = NAV[0].items.concat(NAV[1].items.slice(0, 5));

  return (
    <Stack gap={6}>
      <PageHeader
        title="OVERVIEW"
        subtitle="Workspace status and quick access."
        assetId="ODY-HUD-00.1 EDITION 02"
        actions={
          <StatusFlag status="nominal" dot>
            ALL SYSTEMS
          </StatusFlag>
        }
      />

      <Suspense fallback={<LoadingText />}>
        <Show when={systemBand()}>
          {(band) => (
            <InstrumentBand
              items={band().map((s) => ({ label: s.label, value: s.value }))}
            />
          )}
        </Show>
      </Suspense>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel label="THROUGHPUT" class="lg:col-span-1">
          <Stack gap={4}>
            <Readout label="TOKENS / SEC" value="82.4" unit="T/S" />
            <Readout label="QUEUE DEPTH" value="0" size="md" tone="dim" />
          </Stack>
        </Panel>

        <Panel
          label="SERVICE HEALTH"
          meta={
            <Text variant="micro" tone="dim">
              6 MONITORED
            </Text>
          }
          flush
          class="lg:col-span-2"
        >
          <Suspense fallback={<LoadingText />}>
            <Show when={services()}>
              {(svcs) => (
                <For each={svcs()}>
                  {(svc) => (
                    <ListRow
                      label={svc.name}
                      right={
                        <span class="flex items-center gap-2">
                          <Text variant="micro" tone="dim">
                            {svc.detail}
                          </Text>
                          <StatusFlag status={healthStatus[svc.status]}>
                            {svc.status.toUpperCase()}
                          </StatusFlag>
                        </span>
                      }
                    />
                  )}
                </For>
              )}
            </Show>
          </Suspense>
        </Panel>
      </div>

      <Stack gap={3}>
        <Text variant="label" tone="dim">
          QUICK ACCESS
        </Text>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          <For each={quickTiles}>
            {(item) => (
              <Tile icon={item.icon} label={item.label} href={item.href} />
            )}
          </For>
        </div>
      </Stack>
    </Stack>
  );
}
