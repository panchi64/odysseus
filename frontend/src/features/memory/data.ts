import { createResource, createSignal, type Resource } from "solid-js";
import { createStore, produce } from "solid-js/store";
import type { DedupCandidate, Memory } from "./model";
import { mockDedupCandidates, mockMemories } from "./mocks";

// Mutable local state for Phase 1 — actions mutate this directly.
// In Phase 2, these become API calls; the return types stay the same.
const [memoriesStore, setMemoriesStore] = createStore<Memory[]>([
  ...mockMemories,
]);
const [dedupStore, setDedupStore] = createStore<DedupCandidate[]>([
  ...mockDedupCandidates,
]);

// Trigger signal to invalidate the resource when the store changes.
const [memTick, setMemTick] = createSignal(0);
const [dedupTick, setDedupTick] = createSignal(0);

function bump() {
  setMemTick((n) => n + 1);
}
function bumpDedup() {
  setDedupTick((n) => n + 1);
}

async function fetchMemories(): Promise<Memory[]> {
  void memTick(); // reactive dependency
  return [...memoriesStore];
}

async function fetchDedupCandidates(): Promise<DedupCandidate[]> {
  void dedupTick(); // reactive dependency
  return [...dedupStore];
}

export function useMemories(): Resource<Memory[]> {
  const [data] = createResource(memTick, fetchMemories);
  return data;
}

export function useDedupCandidates(): Resource<DedupCandidate[]> {
  const [data] = createResource(dedupTick, fetchDedupCandidates);
  return data;
}

/** Toggle pinned state for a memory. Returns the new pinned value. */
export function togglePin(id: string): boolean {
  let next = false;
  setMemoriesStore(
    produce((list) => {
      const mem = list.find((m) => m.id === id);
      if (mem) {
        mem.pinned = !mem.pinned;
        next = mem.pinned;
      }
    }),
  );
  bump();
  return next;
}

/** Remove a memory by id. Returns the removed memory for undo. */
export function deleteMemory(id: string): Memory | undefined {
  const removed = memoriesStore.find((m) => m.id === id);
  setMemoriesStore((list) => list.filter((m) => m.id !== id));
  bump();
  return removed ? { ...removed } : undefined;
}

/** Restore a previously deleted memory (undo). */
export function restoreMemory(mem: Memory): void {
  setMemoriesStore(
    produce((list) => {
      list.push(mem);
      list.sort(
        (a, b) =>
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
      );
    }),
  );
  bump();
}

/** Merge a dedup pair: keep A, remove B, remove the pair from the dedup list.
 *  Returns both memories for the toast message. */
export function mergePair(pair: DedupCandidate): void {
  setMemoriesStore((list) => list.filter((m) => m.id !== pair.b.id));
  setDedupStore((list) =>
    list.filter((p) => !(p.a.id === pair.a.id && p.b.id === pair.b.id)),
  );
  bump();
  bumpDedup();
}

/** Dismiss a dedup pair without merging (keep both). */
export function dismissPair(pair: DedupCandidate): void {
  setDedupStore((list) =>
    list.filter((p) => !(p.a.id === pair.a.id && p.b.id === pair.b.id)),
  );
  bumpDedup();
}
