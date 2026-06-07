import type { RagIndexStats, RagSource } from "./model";

export const mockRagSources: RagSource[] = [
  {
    id: "rs-001",
    path: "/data/personal_docs",
    docCount: 4214,
    status: "indexed",
    lastIndexedAt: "2026-06-07T13:00:00Z",
  },
  {
    id: "rs-002",
    path: "/data/uploads",
    docCount: 182,
    status: "indexed",
    lastIndexedAt: "2026-06-07T08:30:00Z",
  },
  {
    id: "rs-003",
    path: "/home/panchi/notes",
    docCount: 74,
    status: "stale",
    lastIndexedAt: "2026-05-28T10:00:00Z",
  },
  {
    id: "rs-004",
    path: "/home/panchi/projects/docs",
    docCount: 0,
    status: "error",
    lastIndexedAt: "2026-06-01T09:15:00Z",
  },
];

export const mockIndexStats: RagIndexStats = {
  embeddingModel: "all-MiniLM-L6-v2",
  dims: 768,
  totalDocs: 4470,
  totalCollections: 4,
  storeSize: "347.2 MB",
};
