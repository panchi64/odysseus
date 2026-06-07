import type { EmbeddingModel, IndexStats } from "./model";

export const mockEmbeddingModels: EmbeddingModel[] = [
  {
    id: "all-minilm-l6-v2",
    name: "all-MiniLM-L6-v2",
    dims: 384,
    provider: "local",
    active: true,
    sizeBytes: 91_000_000,
    description: "Fast, compact. Good for semantic search.",
  },
  {
    id: "bge-base-en-v1.5",
    name: "BGE Base EN v1.5",
    dims: 768,
    provider: "local",
    active: false,
    sizeBytes: 438_000_000,
    description: "Better recall at higher dimensionality.",
  },
  {
    id: "bge-large-en-v1.5",
    name: "BGE Large EN v1.5",
    dims: 1024,
    provider: "local",
    active: false,
    sizeBytes: 1_340_000_000,
    description: "Highest quality local embedding.",
  },
  {
    id: "text-embedding-3-small",
    name: "text-embedding-3-small",
    dims: 1536,
    provider: "remote",
    active: false,
    description: "OpenAI remote — requires API key.",
  },
  {
    id: "text-embedding-3-large",
    name: "text-embedding-3-large",
    dims: 3072,
    provider: "remote",
    active: false,
    description: "OpenAI remote — highest quality, higher cost.",
  },
];

export const mockIndexStats: IndexStats = {
  indexedDocs: 4214,
  dims: 384,
  throughputDocsSec: 80,
  lastIndexedAt: "2026-06-07T11:40:00Z",
  requiresReindex: false,
  isReindexing: false,
};
