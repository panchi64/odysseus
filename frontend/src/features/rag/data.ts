import {
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import type { RagIndexStats, RagSource, RagIndexStatus } from "./model";
import { mockIndexStats, mockRagSources } from "./mocks";

/* ── Sources — mutable local store so Phase-1 actions are visible ───────── */

const [sourcesStore, setSourcesStore] = createStore<RagSource[]>(
  mockRagSources.map((s) => ({ ...s })),
);

/** Read-only accessor for the sources list. */
export function useRagSources(): () => RagSource[] {
  return () => sourcesStore;
}

/** Add a new source. Returns the new source entry. */
export function addRagSource(path: string): RagSource {
  const id = `rs-${Date.now()}`;
  const entry: RagSource = {
    id,
    path,
    docCount: 0,
    status: "indexing",
    lastIndexedAt: new Date().toISOString(),
  };
  setSourcesStore(produce((list) => list.push(entry)));
  return entry;
}

/** Remove a source by id. */
export function removeRagSource(id: string): RagSource | undefined {
  const removed = sourcesStore.find((s) => s.id === id);
  setSourcesStore((list) => list.filter((s) => s.id !== id));
  return removed;
}

/** Restore a source (undo remove). */
export function restoreRagSource(source: RagSource): void {
  setSourcesStore(produce((list) => list.push(source)));
}

/** Trigger a reindex on a source — transitions it through indexing → indexed. */
export function createReindexController() {
  const [reindexingIds, setReindexingIds] = createSignal<Set<string>>(
    new Set(),
  );
  const timers: ReturnType<typeof setTimeout>[] = [];

  function reindex(id: string): void {
    if (reindexingIds().has(id)) return;
    setReindexingIds((prev) => new Set([...prev, id]));
    setSourcesStore(
      (s) => s.id === id,
      produce((s) => {
        s.status = "indexing" as RagIndexStatus;
      }),
    );
    timers.push(
      setTimeout(
        () => {
          setSourcesStore(
            (s) => s.id === id,
            produce((s) => {
              s.status = "indexed" as RagIndexStatus;
              s.lastIndexedAt = new Date().toISOString();
              s.docCount =
                s.docCount > 0
                  ? s.docCount
                  : Math.floor(Math.random() * 50) + 10;
            }),
          );
          setReindexingIds((prev) => {
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
        },
        3000 + Math.random() * 1500,
      ),
    );
  }

  onCleanup(() => timers.forEach(clearTimeout));

  return { reindexingIds, reindex };
}

/* ── Index stats ────────────────────────────────────────────────────────── */

async function fetchIndexStats(): Promise<RagIndexStats> {
  return mockIndexStats;
}

export function useIndexStats(): Resource<RagIndexStats> {
  const [data] = createResource(fetchIndexStats);
  return data;
}
