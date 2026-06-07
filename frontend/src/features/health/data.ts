import { createResource, type Resource } from "solid-js";
import type { ServiceStatus, OverallHealth } from "./model";
import { mockServiceStatuses, mockOverallHealth } from "./mocks";

async function fetchServiceStatuses(): Promise<ServiceStatus[]> {
  return mockServiceStatuses;
}

async function fetchOverallHealth(): Promise<OverallHealth> {
  return mockOverallHealth;
}

export function useServiceStatuses(): Resource<ServiceStatus[]> {
  const [data] = createResource(fetchServiceStatuses);
  return data;
}

export function useOverallHealth(): Resource<OverallHealth> {
  const [data] = createResource(fetchOverallHealth);
  return data;
}
