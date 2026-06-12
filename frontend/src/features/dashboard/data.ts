import { createResource, type Resource } from "solid-js";
import { api } from "~/lib/api";
import { num } from "~/lib/format";
import type {
  ActiveRun,
  CapabilityHealth,
  Overview,
  SystemStat,
} from "./model";

/* ── Backend DTOs ──────────────────────────────────────────────────────────── */

interface CapabilityDTO {
  key: string;
  label: string;
  status: CapabilityHealth["status"];
  detail: string;
  critical: boolean;
  remediation_href: string | null;
  remediation_label: string | null;
}

interface OverviewDTO {
  version: string;
  main_model: string | null;
  main_provider: string | null;
  context_window: number | null;
  endpoint_count: number;
  conversation_count: number;
  memory_count: number;
  capabilities: CapabilityDTO[];
}

interface RunDTO {
  id: string;
  kind: string;
  status: string;
}

/* ── Mappers (snake_case DTO → seam type) ──────────────────────────────────── */

function toCapability(dto: CapabilityDTO): CapabilityHealth {
  return {
    key: dto.key,
    label: dto.label,
    status: dto.status,
    detail: dto.detail,
    critical: dto.critical,
    remediationHref: dto.remediation_href ?? undefined,
    remediationLabel: dto.remediation_label ?? undefined,
  };
}

function toOverview(dto: OverviewDTO): Overview {
  return {
    version: dto.version,
    mainModel: dto.main_model,
    mainProvider: dto.main_provider,
    contextWindow: dto.context_window,
    endpointCount: dto.endpoint_count,
    conversationCount: dto.conversation_count,
    memoryCount: dto.memory_count,
    capabilities: dto.capabilities.map(toCapability),
  };
}

/** Human readout for an active run's status (the IN FLIGHT detail column). */
const RUN_STATUS_LABEL: Record<string, string> = {
  running: "RUNNING",
  queued: "QUEUED",
  awaiting_input: "NEEDS APPROVAL",
};

function toActiveRun(dto: RunDTO): ActiveRun {
  const status = (dto.status as ActiveRun["status"]) ?? "running";
  return {
    id: dto.id,
    kind: dto.kind.toUpperCase(),
    // A run carries no human title; its kind is the most meaningful label.
    label: `${dto.kind} run`,
    status,
    detail: RUN_STATUS_LABEL[dto.status] ?? dto.status.toUpperCase(),
  };
}

/* ── The system strip's facts band (presentation shaping of real overview data) ─ */

/** The telemetry strip as labelled cells, in glance order. Only facts the
 *  backend actually reports — no fabricated tok/s, VRAM, or uplink. */
export function overviewBand(o: Overview): SystemStat[] {
  const band: SystemStat[] = [{ label: "MODEL", value: o.mainModel ?? "—" }];
  if (o.contextWindow != null)
    band.push({ label: "CTX", value: num(o.contextWindow, 0) });
  band.push(
    { label: "THREADS", value: num(o.conversationCount, 0) },
    { label: "MEMORIES", value: num(o.memoryCount, 0) },
    { label: "ENDPOINTS", value: num(o.endpointCount, 0) },
    { label: "VERSION", value: o.version },
  );
  return band;
}

/* ── Read accessors (the seam) ─────────────────────────────────────────────── */

async function fetchOverview(): Promise<Overview> {
  return toOverview(await api.get<OverviewDTO>("/overview"));
}

export interface UseOverviewResult {
  data: Resource<Overview>;
  refetch: () => void;
}

export function useOverview(): UseOverviewResult {
  const [data, { refetch }] = createResource(fetchOverview);
  return { data, refetch };
}

async function fetchActiveRuns(): Promise<ActiveRun[]> {
  const rows = await api.get<RunDTO[]>("/runs");
  return rows.map(toActiveRun);
}

export interface UseActiveRunsResult {
  data: Resource<ActiveRun[]>;
  refetch: () => void;
}

export function useActiveRuns(): UseActiveRunsResult {
  const [data, { refetch }] = createResource(fetchActiveRuns);
  return { data, refetch };
}
