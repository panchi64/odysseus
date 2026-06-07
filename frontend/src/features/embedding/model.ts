/** Embedding Models feature data contracts. */

export type EmbeddingProvider = "local" | "remote";

export interface EmbeddingModel {
  id: string;
  name: string;
  dims: number;
  provider: EmbeddingProvider;
  active: boolean;
  sizeBytes?: number;
  description?: string;
}

export interface ReindexProgress {
  docsProcessed: number;
  estimatedSecsRemaining: number;
}

export interface IndexStats {
  indexedDocs: number;
  dims: number;
  throughputDocsSec: number;
  lastIndexedAt: string;
  requiresReindex: boolean;
  isReindexing: boolean;
  reindexProgress?: ReindexProgress;
}
