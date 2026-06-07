import { createResource, type Resource } from "solid-js";
import type { RagIndexStats, RagSource } from "./model";
import { mockIndexStats, mockRagSources } from "./mocks";

async function fetchRagSources(): Promise<RagSource[]> {
  return mockRagSources;
}

async function fetchIndexStats(): Promise<RagIndexStats> {
  return mockIndexStats;
}

export function useRagSources(): Resource<RagSource[]> {
  const [data] = createResource(fetchRagSources);
  return data;
}

export function useIndexStats(): Resource<RagIndexStats> {
  const [data] = createResource(fetchIndexStats);
  return data;
}
