import { createResource, createSignal, type Resource } from "solid-js";
import type { EmbeddingModel, IndexStats } from "./model";
import { mockEmbeddingModels, mockIndexStats } from "./mocks";

async function fetchEmbeddingModels(): Promise<EmbeddingModel[]> {
  return mockEmbeddingModels;
}

async function fetchIndexStats(): Promise<IndexStats> {
  return mockIndexStats;
}

export function useEmbeddingModels(): Resource<EmbeddingModel[]> & {
  refetch: () => void;
} {
  const [data, { refetch }] = createResource(fetchEmbeddingModels);
  return Object.assign(data, { refetch }) as Resource<EmbeddingModel[]> & {
    refetch: () => void;
  };
}

export function useIndexStats(): Resource<IndexStats> {
  const [data] = createResource(fetchIndexStats);
  return data;
}

/** Mutable Phase-1 reindex state — simulates an in-progress re-index operation. */
export interface ReindexState {
  active: boolean;
  docsProcessed: number;
  totalDocs: number;
  estimatedSecsRemaining: number;
}

const [reindexState, setReindexState] = createSignal<ReindexState | null>(null);
let _reindexTimer: ReturnType<typeof setInterval> | null = null;

export function reindexSignal() {
  return reindexState();
}

export function startReindex(totalDocs: number): void {
  if (_reindexTimer) clearInterval(_reindexTimer);
  setReindexState({
    active: true,
    docsProcessed: 0,
    totalDocs,
    estimatedSecsRemaining: Math.ceil(totalDocs / 80),
  });
  _reindexTimer = setInterval(() => {
    setReindexState((prev) => {
      if (!prev) return null;
      const next = prev.docsProcessed + 80;
      if (next >= prev.totalDocs) {
        clearInterval(_reindexTimer!);
        _reindexTimer = null;
        return null; // done
      }
      return {
        ...prev,
        docsProcessed: next,
        estimatedSecsRemaining: Math.max(
          0,
          Math.ceil((prev.totalDocs - next) / 80),
        ),
      };
    });
  }, 1000);
}

export function cancelReindex(): void {
  if (_reindexTimer) {
    clearInterval(_reindexTimer);
    _reindexTimer = null;
  }
  setReindexState(null);
}
