/** The dashboard (home) data contract. Every type here mirrors a real backend
 *  shape — the home page is a launchpad into chat plus a faithful readout of
 *  what the backend actually knows (`GET /overview`, `GET /runs`). It invents
 *  nothing: telemetry/services that don't exist yet simply aren't represented. */

/** A single labelled telemetry cell in the system strip. */
export interface SystemStat {
  label: string;
  value: string;
}

/** A capability's backend-decided health. The backend owns the policy (what
 *  counts as nominal/degraded/down) and the remediation target; the frontend
 *  only renders it. Mirrors the overview `Capability`. */
export interface CapabilityHealth {
  /** Stable id: `chat_model` | `embeddings` | `sandbox`. */
  key: string;
  label: string;
  status: "nominal" | "warn" | "alert";
  detail: string;
  /** A capability the workspace cannot function without — drives overall status. */
  critical: boolean;
  /** Where to go to fix a degraded/down capability. */
  remediationHref?: string;
  remediationLabel?: string;
}

/** The home overview aggregate — the single source of truth the launchpad reads
 *  for its facts band and capability health. */
export interface Overview {
  version: string;
  endpointCount: number;
  conversationCount: number;
  memoryCount: number;
  capabilities: CapabilityHealth[];
}

/** A run still in flight (not yet terminal) — the IN FLIGHT panel's unit. */
export interface ActiveRun {
  id: string;
  /** Display tag: CHAT / RESEARCH / AGENT. */
  kind: string;
  /** Human one-liner for the row. */
  label: string;
  status: "running" | "queued" | "awaiting_input";
  /** Compact status readout, e.g. RUNNING / QUEUED / NEEDS APPROVAL. */
  detail: string;
}
