import { createSignal, For, onCleanup, onMount, type JSX } from "solid-js";
import {
  Button,
  InstrumentBand,
  ListRow,
  PageHeader,
  Panel,
  Readout,
  Resource,
  Stack,
  StatusFlag,
  Text,
  Tile,
  type Status,
} from "~/ui";
import { NAV } from "~/app/nav";
import { useSession } from "~/lib/stores/session";
import { useSystemBand, useServices } from "../data";
import type { ServiceHealth } from "../mocks";

/** Derives the worst-case status from the service list for the ALL SYSTEMS flag. */
function computeOverallStatus(svcs: ServiceHealth[]): Status {
  if (svcs.some((s) => s.status === "alert")) return "alert";
  if (svcs.some((s) => s.status === "warn")) return "warn";
  return "nominal";
}

/** Returns an HH:MM:SS string in local time. */
function nowHMS(): string {
  const d = new Date();
  const p = (n: number) => n.toString().padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** Tier access check: admin can access everything, user can access user/open,
 *  unauthenticated can only access open. */
function isTierAccessible(
  tier: "open" | "user" | "admin",
  isAdmin: boolean,
  isAuthenticated: boolean,
): boolean {
  if (tier === "open") return true;
  if (tier === "user") return isAuthenticated;
  return isAdmin;
}

/** Home overview: system telemetry, service health, and quick-access tiles. */
export function DashboardScreen(): JSX.Element {
  const session = useSession();
  const { data: systemBand, refetch: refetchBand } = useSystemBand();
  const { data: services, refetch: refetchServices } = useServices();

  // Throughput timestamp — shows when the snapshot was captured.
  const [throughputAt, setThroughputAt] = createSignal(nowHMS());
  let ticker: ReturnType<typeof setInterval> | undefined;

  onMount(() => {
    ticker = setInterval(() => setThroughputAt(nowHMS()), 5000);
  });

  onCleanup(() => clearInterval(ticker));

  // Quick-access tiles drawn from first two NAV sections (same as before).
  const quickTiles = NAV[0].items.concat(NAV[1].items.slice(0, 5));

  // Derived: overall health from the resolved services list.
  const overallStatus = (): Status => {
    const svcs = services();
    if (!svcs) return "nominal";
    return computeOverallStatus(svcs);
  };

  const overallLabel = (): string => {
    const s = overallStatus();
    if (s === "alert") return "SYSTEM ALERT";
    if (s === "warn") return "SYSTEM WARNING";
    return "ALL SYSTEMS";
  };

  return (
    <Stack gap={6}>
      <PageHeader
        title="OVERVIEW"
        subtitle="Workspace status and quick access."
        assetId="ODY-HUD-00.1 EDITION 02"
        actions={
          <StatusFlag status={overallStatus()} dot>
            {overallLabel()}
          </StatusFlag>
        }
      />

      <Resource
        data={systemBand}
        onRetry={refetchBand}
        errorMessage="TELEMETRY UNAVAILABLE"
      >
        {(band) => (
          <InstrumentBand
            items={band().map((s) => ({ label: s.label, value: s.value }))}
          />
        )}
      </Resource>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel label="THROUGHPUT" class="lg:col-span-1">
          <Stack gap={4}>
            <Readout label="TOKENS / SEC" value="82.4" unit="T/S" />
            <Readout label="QUEUE DEPTH" value="0" size="md" tone="dim" />
            <Text variant="micro" tone="dim">
              AS OF {throughputAt()}
            </Text>
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
          <Resource
            data={services}
            onRetry={refetchServices}
            errorMessage="SERVICE DATA UNAVAILABLE"
            emptyMessage="NO SERVICES MONITORED"
          >
            {(svcs) => (
              <For each={svcs()}>
                {(svc) => (
                  <ListRow
                    label={svc.name}
                    right={
                      <span class="flex items-center gap-2">
                        {svc.critical && (
                          <StatusFlag status="info">CRITICAL</StatusFlag>
                        )}
                        <Text variant="micro" tone="dim">
                          {svc.detail}
                        </Text>
                        <StatusFlag status={svc.status}>
                          {svc.status.toUpperCase()}
                        </StatusFlag>
                        {svc.status !== "nominal" &&
                          svc.remediationHref &&
                          svc.remediationLabel && (
                            <Button
                              variant="ghost"
                              size="sm"
                              href={svc.remediationHref}
                            >
                              {svc.remediationLabel}
                            </Button>
                          )}
                      </span>
                    }
                  />
                )}
              </For>
            )}
          </Resource>
        </Panel>
      </div>

      <Stack gap={3}>
        <Text variant="label" tone="dim">
          QUICK ACCESS
        </Text>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          <For each={quickTiles}>
            {(item) => (
              <Tile
                icon={item.icon}
                label={item.label}
                href={
                  isTierAccessible(
                    item.tier,
                    session.isAdmin,
                    session.isAuthenticated,
                  )
                    ? item.href
                    : undefined
                }
                locked={
                  !isTierAccessible(
                    item.tier,
                    session.isAdmin,
                    session.isAuthenticated,
                  )
                }
              />
            )}
          </For>
        </div>
      </Stack>
    </Stack>
  );
}
