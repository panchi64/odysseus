import { createResource, type Resource } from "solid-js";
import type { Integration } from "./model";
import { mockIntegrations } from "./mocks";

async function fetchIntegrations(): Promise<Integration[]> {
  return mockIntegrations;
}

export function useIntegrations(): Resource<Integration[]> {
  const [data] = createResource(fetchIntegrations);
  return data;
}
