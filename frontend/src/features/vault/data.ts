import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type { VaultEntry, VaultEntryInput, VaultState } from "./model";

/* ── Backend DTOs → seam types ────────────────────────────────────────────── */

interface VaultStateOut {
  configured: boolean;
  unlocked: boolean;
}

interface EntryOut {
  id: string;
  name: string;
  username: string;
  url: string;
  password: string;
  createdAt: string;
  updatedAt: string;
}

/** The backend reports `unlocked`; the screen reads `locked`. One inversion, here
 *  at the seam, so no component re-derives it. */
function toState(dto: VaultStateOut): VaultState {
  return { configured: dto.configured, locked: !dto.unlocked };
}

function toEntry(dto: EntryOut): VaultEntry {
  return {
    id: dto.id,
    name: dto.name,
    username: dto.username,
    url: dto.url,
    password: dto.password,
  };
}

/* ── State (the seam) ─────────────────────────────────────────────────────── */

const [stateTick, setStateTick] = createSignal(0);

export function useVaultState(): Resource<VaultState> {
  const [data] = createResource(stateTick, async () =>
    toState(await api.get<VaultStateOut>("/vault/state")),
  );
  return data;
}

/* ── Entries (the seam) ───────────────────────────────────────────────────── */

const [entriesTick, setEntriesTick] = createSignal(0);

/** The stored credentials, fetched only while the vault is open — a locked vault
 *  answers 409 rather than an empty list, and that is not an error worth surfacing
 *  while the screen is already rendering its own unlock prompt. */
export function useVaultEntries(
  unlocked: () => boolean,
): Resource<VaultEntry[]> {
  const [data] = createResource(
    () => (unlocked() ? entriesTick() : null),
    async () => (await api.get<EntryOut[]>("/vault/entries")).map(toEntry),
  );
  return data;
}

/** Invalidate the entry list after a mutation. */
function refreshEntries(): void {
  setEntriesTick((n) => n + 1);
}

/** Invalidate the configure/lock state after a lifecycle call. */
function refreshState(): void {
  setStateTick((n) => n + 1);
}

/* ── Lock lifecycle ───────────────────────────────────────────────────────── */

/** Choose the vault's passphrase for the first time. 409 if one already exists. */
export async function configureVault(passphrase: string): Promise<VaultState> {
  const dto = await api.post<VaultStateOut>("/vault/configure", { passphrase });
  refreshState();
  refreshEntries();
  return toState(dto);
}

/** Open the vault. The backend answers 403 for a wrong passphrase — deliberately not
 *  401/423, which the API client would read as the app session itself having failed. */
export async function unlockVault(passphrase: string): Promise<VaultState> {
  const dto = await api.post<VaultStateOut>("/vault/unlock", { passphrase });
  refreshState();
  refreshEntries();
  return toState(dto);
}

export async function lockVault(): Promise<VaultState> {
  const dto = await api.post<VaultStateOut>("/vault/lock");
  refreshState();
  refreshEntries();
  return toState(dto);
}

/* ── Entry mutations ──────────────────────────────────────────────────────── */

export async function createVaultEntry(
  input: VaultEntryInput,
): Promise<VaultEntry> {
  const dto = await api.post<EntryOut>("/vault/entries", input);
  refreshEntries();
  return toEntry(dto);
}

export async function updateVaultEntry(
  id: string,
  patch: Partial<VaultEntryInput>,
): Promise<VaultEntry> {
  const dto = await api.patch<EntryOut>(`/vault/entries/${id}`, patch);
  refreshEntries();
  return toEntry(dto);
}

/** Permanent — the row is gone from the store, so there is nothing to undo. */
export async function deleteVaultEntry(id: string): Promise<void> {
  await api.del(`/vault/entries/${id}`);
  refreshEntries();
}
