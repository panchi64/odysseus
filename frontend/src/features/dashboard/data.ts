import { createResource, type Resource } from "solid-js";
import type { SystemStat, ServiceHealth, TaskActivity } from "./mocks";
import { mockSystemBand, mockServices, mockTasks } from "./mocks";

/* ── Read accessors (the seam) ───────────────────────────────────────────────
   Phase 2: replace the mock bodies with api calls from ~/lib/api. */

async function fetchSystemBand(): Promise<SystemStat[]> {
  return mockSystemBand;
}

async function fetchServices(): Promise<ServiceHealth[]> {
  return mockServices;
}

async function fetchTasks(): Promise<TaskActivity[]> {
  return mockTasks;
}

export interface UseSystemBandResult {
  data: Resource<SystemStat[]>;
  refetch: () => void;
}

export function useSystemBand(): UseSystemBandResult {
  const [data, { refetch }] = createResource(fetchSystemBand);
  return { data, refetch };
}

export interface UseServicesResult {
  data: Resource<ServiceHealth[]>;
  refetch: () => void;
}

export function useServices(): UseServicesResult {
  const [data, { refetch }] = createResource(fetchServices);
  return { data, refetch };
}

export interface UseTasksResult {
  data: Resource<TaskActivity[]>;
  refetch: () => void;
}

export function useTasks(): UseTasksResult {
  const [data, { refetch }] = createResource(fetchTasks);
  return { data, refetch };
}
