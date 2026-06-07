/** RAG / Knowledge Base feature data contracts. */

export type RagIndexStatus = "indexed" | "indexing" | "stale" | "error";

export interface RagSource {
  id: string;
  path: string;
  docCount: number;
  status: RagIndexStatus;
  lastIndexedAt: string;
}

export interface RagIndexStats {
  embeddingModel: string;
  dims: number;
  totalDocs: number;
  totalCollections: number;
  storeSize: string;
}
