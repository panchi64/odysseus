import { createSignal } from "solid-js";
import type { VaultEntry } from "./model";
import { mockVaultEntries } from "./mocks";

/** Mutable in-Phase-1 store of vault entries — Phase 2 replaces with API. */
const [entries, setEntries] = createSignal<VaultEntry[]>([...mockVaultEntries]);

export function useVaultEntries() {
  return entries;
}

export function deleteVaultEntry(id: string): VaultEntry | undefined {
  const removed = entries().find((e) => e.id === id);
  if (removed) setEntries((prev) => prev.filter((e) => e.id !== id));
  return removed;
}

export function restoreVaultEntry(entry: VaultEntry) {
  setEntries((prev) => [...prev, entry]);
}
