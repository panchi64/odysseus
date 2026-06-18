import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type { RagIndexStats, RagSource } from "./model";

/* ── The seam ─────────────────────────────────────────────────────────────
 * The backend's /corpus out-shapes are already camelCase and match RagSource /
 * RagIndexStats one-for-one, so the DTOs ARE the seam types — no remapping. The
 * backend is the source of truth; every action mutates there and we refetch. */

const [tick, setTick] = createSignal(0);

/** Refetch the source list + stats (both resources track this signal). */
export function refreshCorpus(): void {
  setTick((n) => n + 1);
}

export function useRagSources(): Resource<RagSource[]> {
  const [data] = createResource(tick, () =>
    api.get<RagSource[]>("/corpus/sources"),
  );
  return data;
}

export function useIndexStats(): Resource<RagIndexStats> {
  const [data] = createResource(tick, () =>
    api.get<RagIndexStats>("/corpus/stats"),
  );
  return data;
}

/* ── Mutations (backend-owned; refresh on completion) ─────────────────────── */

/** Register a host folder as a corpus source; indexing starts server-side. */
export async function addRagSource(path: string): Promise<void> {
  await api.post("/corpus/folders", { path });
  refreshCorpus();
}

/** Remove an operator-added folder source and its indexed chunks. */
export async function removeRagSource(id: string): Promise<void> {
  await api.del(`/corpus/folders/${id}`);
  refreshCorpus();
}

/** Reindex one source — heal a surface's embeddings, or re-crawl a folder. */
export async function reindexSource(id: string): Promise<void> {
  await api.post(`/corpus/sources/${id}/reindex`);
  refreshCorpus();
}

/** Re-crawl one folder source from scratch. */
export async function rebuildSource(id: string): Promise<void> {
  await api.post(`/corpus/sources/${id}/rebuild`);
  refreshCorpus();
}

/** Re-crawl every operator-added folder (the global "rebuild index" action).
 *  Surfaces own their own content, so only folders are rebuilt here. */
export async function rebuildAllFolders(sources: RagSource[]): Promise<void> {
  const folders = sources.filter((s) => s.kind === "folder");
  await Promise.all(
    folders.map((s) => api.post(`/corpus/sources/${s.id}/rebuild`)),
  );
  refreshCorpus();
}
