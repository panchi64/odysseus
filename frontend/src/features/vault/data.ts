import { createResource, type Resource } from "solid-js";
import type { VaultEntry } from "./model";
import { mockVaultEntries } from "./mocks";

async function fetchVaultEntries(): Promise<VaultEntry[]> {
  return mockVaultEntries;
}

export function useVaultEntries(): Resource<VaultEntry[]> {
  const [data] = createResource(fetchVaultEntries);
  return data;
}
