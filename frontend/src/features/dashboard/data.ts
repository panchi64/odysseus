import { createResource, type Resource } from "solid-js";
import type { SystemStat, ServiceHealth } from "./mocks";
import { mockSystemBand, mockServices } from "./mocks";

/* ── Read accessors (the seam) ───────────────────────────────────────────────
   Phase 2: replace the mock bodies with api calls from ~/lib/api. */

async function fetchSystemBand(): Promise<SystemStat[]> {
  return mockSystemBand;
}

async function fetchServices(): Promise<ServiceHealth[]> {
  return mockServices;
}

export function useSystemBand(): Resource<SystemStat[]> {
  const [data] = createResource(fetchSystemBand);
  return data;
}

export function useServices(): Resource<ServiceHealth[]> {
  const [data] = createResource(fetchServices);
  return data;
}
