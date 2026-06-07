import { createResource, type Resource } from "solid-js";
import type { DedupCandidate, Memory } from "./model";
import { mockDedupCandidates, mockMemories } from "./mocks";

async function fetchMemories(): Promise<Memory[]> {
  return mockMemories;
}

async function fetchDedupCandidates(): Promise<DedupCandidate[]> {
  return mockDedupCandidates;
}

export function useMemories(): Resource<Memory[]> {
  const [data] = createResource(fetchMemories);
  return data;
}

export function useDedupCandidates(): Resource<DedupCandidate[]> {
  const [data] = createResource(fetchDedupCandidates);
  return data;
}
