import { createResource, type Resource } from "solid-js";
import type { EmbeddingModel, IndexStats } from "./model";
import { mockEmbeddingModels, mockIndexStats } from "./mocks";

async function fetchEmbeddingModels(): Promise<EmbeddingModel[]> {
  return mockEmbeddingModels;
}

async function fetchIndexStats(): Promise<IndexStats> {
  return mockIndexStats;
}

export function useEmbeddingModels(): Resource<EmbeddingModel[]> {
  const [data] = createResource(fetchEmbeddingModels);
  return data;
}

export function useIndexStats(): Resource<IndexStats> {
  const [data] = createResource(fetchIndexStats);
  return data;
}
