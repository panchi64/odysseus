import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import {
  refreshEndpoints,
  setEndpointEnabled,
  testEndpoint,
  useEndpoints,
} from "~/lib/stores/models";
import type {
  ChatSettings,
  EmbeddingHealth,
  EndpointInput,
  ReindexStatus,
  RoleBindings,
  SearchProvider,
  SearchProviderInput,
} from "./model";

// The endpoint catalog (read) is owned by the shared models store so the chat
// picker and Settings share one fetch and one type; this module owns the writes
// (CRUD + role bindings) and the role read. Health probe + enable/disable are
// also store-owned (they cascade to the shared picker) and re-exported here so
// the screen reaches everything through this one seam.
export { useEndpoints, testEndpoint, setEndpointEnabled };

/** Map form values to the backend's snake_case body. `apiKey` undefined is
 *  omitted (leave unchanged); "" clears it. */
function toBody(input: Partial<EndpointInput>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.baseUrl !== undefined) body.base_url = input.baseUrl;
  if (input.model !== undefined) body.model = input.model;
  if (input.apiKey !== undefined) body.api_key = input.apiKey;
  if (input.contextWindow !== undefined)
    body.context_window = input.contextWindow;
  if (input.nativeTools !== undefined) body.native_tools = input.nativeTools;
  if (input.vision !== undefined) body.vision = input.vision;
  if (input.thinking !== undefined) body.thinking = input.thinking;
  if (input.enabled !== undefined) body.enabled = input.enabled;
  return body;
}

/* ── Endpoints (writes) ───────────────────────────────────────────────────── */

/** Create an endpoint and return its backend id (the guided cookbook flow needs
 *  it to test + auto-select the new connection; the Settings form ignores it). */
export async function createEndpoint(input: EndpointInput): Promise<string> {
  const created = await api.post<{ id: string }>(
    "/models/endpoints",
    toBody(input),
  );
  refreshEndpoints();
  return created.id;
}

export async function updateEndpoint(
  id: string,
  patch: Partial<EndpointInput>,
): Promise<void> {
  await api.patch(`/models/endpoints/${id}`, toBody(patch));
  refreshEndpoints();
}

export async function deleteEndpoint(id: string): Promise<void> {
  await api.del(`/models/endpoints/${id}`);
  refreshEndpoints();
}

/* ── Role bindings ────────────────────────────────────────────────────────── */

const [rolesTick, setRolesTick] = createSignal(0);

interface RoleViewDTO {
  endpoint_ids: string[];
  model: string | null;
}

async function fetchRoles(): Promise<RoleBindings> {
  const dto = await api.get<Record<string, RoleViewDTO>>("/models/roles");
  const out: RoleBindings = {};
  for (const [role, v] of Object.entries(dto)) {
    out[role] = { endpointIds: v.endpoint_ids, model: v.model };
  }
  return out;
}

export function useRoles(): Resource<RoleBindings> {
  const [data] = createResource(rolesTick, fetchRoles);
  return data;
}

/** Bind a role to an ordered chain (and, for `embedding`, a pinned model).
 *  Errors are intentionally *not* swallowed — the backend rejects a non-embeddings
 *  model with a 422, and the caller surfaces that detail to the operator.
 *
 *  Returns whether the bind kicked off a background re-embed — only possible for
 *  the `embedding` role, and only when the endpoint/model actually changed — so
 *  the caller can acknowledge the work the operator just set in motion. */
export async function setRoleBinding(
  role: string,
  endpointIds: string[],
  model: string | null = null,
): Promise<boolean> {
  await api.put(`/models/roles/${role}`, {
    endpoint_ids: endpointIds,
    model,
  });
  setRolesTick((n) => n + 1);
  void refreshEmbeddingHealth(); // a bind can flip recall health
  // A changed embedding endpoint/model strands existing vectors, so the backend
  // heals them with a background re-embed. Pull the just-started status so the
  // live readout (and its poller) reflect it; report whether one kicked off.
  if (role !== "embedding") return false;
  await refreshReindexStatus();
  return reindexStatus()?.state === "running";
}

/* ── Embedding health + re-embed (reindex) ───────────────────────────────────
   These are LIVE-POLLED reads, so they must NOT go through `createResource` /
   Suspense: a refetching resource re-enters its pending state and re-triggers the
   route's `<Suspense>` fallback, flashing the whole page on every poll. Plain
   signals update in place — the readout ticks over without disrupting the screen. */

interface CapabilityDTO {
  key: string;
  status: string;
  detail: string;
}

const [embeddingHealth, setEmbeddingHealth] =
  createSignal<EmbeddingHealth | null>(null);

/** The backend owns the verdict on recall health — Settings only renders it (read
 *  off `/overview`, the home page's source of truth, not re-derived here). */
export function useEmbeddingHealth(): () => EmbeddingHealth | null {
  return embeddingHealth;
}

export async function refreshEmbeddingHealth(): Promise<void> {
  try {
    const o = await api.get<{ capabilities: CapabilityDTO[] }>("/overview");
    const cap = o.capabilities.find((c) => c.key === "embeddings");
    setEmbeddingHealth(
      cap
        ? {
            status: cap.status as EmbeddingHealth["status"],
            detail: cap.detail,
          }
        : null,
    );
  } catch {
    // Keep the last known health — a transient failure shouldn't blank the badge.
  }
}

interface ReindexStatusDTO {
  state: string;
  memories: number;
  messages: number;
  detail: string | null;
  completed_at: string | null;
}

function toReindexStatus(d: ReindexStatusDTO): ReindexStatus {
  return {
    state: d.state as ReindexStatus["state"],
    memories: d.memories,
    messages: d.messages,
    detail: d.detail,
    completedAt: d.completed_at,
  };
}

const [reindexStatus, setReindexStatus] = createSignal<ReindexStatus | null>(
  null,
);

export function useReindexStatus(): () => ReindexStatus | null {
  return reindexStatus;
}

/** Poll the reindex status once (drives the live progress readout in place). */
export async function refreshReindexStatus(): Promise<void> {
  try {
    setReindexStatus(
      toReindexStatus(
        await api.get<ReindexStatusDTO>("/models/embedding/reindex"),
      ),
    );
  } catch {
    // Keep the last status on a transient poll failure.
  }
}

/** Manually re-embed memories + the chat index against the current embedding
 *  model (for a first index that failed, or to force a redo). The POST returns the
 *  freshly-started status, so the readout reflects it without a round-trip. */
export async function triggerReindex(): Promise<void> {
  setReindexStatus(
    toReindexStatus(
      await api.post<ReindexStatusDTO>("/models/embedding/reindex", {}),
    ),
  );
}

/* ── Web search providers ──────────────────────────────────────────────────── */

interface SearchProviderView {
  id: string;
  name: string;
  base_url: string;
  enabled: boolean;
  engines: string[];
  params: Record<string, unknown>;
  has_api_key: boolean;
}

/** The single snake_case→camel mapper for a provider row. */
function toSearchProvider(dto: SearchProviderView): SearchProvider {
  return {
    id: dto.id,
    name: dto.name,
    baseUrl: dto.base_url,
    enabled: dto.enabled,
    engines: dto.engines,
    params: dto.params,
    hasApiKey: dto.has_api_key,
  };
}

/** Map form values to the backend's snake_case body. `apiKey` undefined is
 *  omitted (leave unchanged); "" clears it. */
function toProviderBody(
  input: Partial<SearchProviderInput>,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.baseUrl !== undefined) body.base_url = input.baseUrl;
  if (input.enabled !== undefined) body.enabled = input.enabled;
  if (input.engines !== undefined) body.engines = input.engines;
  if (input.params !== undefined) body.params = input.params;
  if (input.apiKey !== undefined) body.api_key = input.apiKey;
  return body;
}

const [providersTick, setProvidersTick] = createSignal(0);

async function fetchSearchProviders(): Promise<SearchProvider[]> {
  const rows = await api.get<SearchProviderView[]>("/search/providers");
  return rows.map(toSearchProvider);
}

export function useSearchProviders(): Resource<SearchProvider[]> {
  const [data] = createResource(providersTick, fetchSearchProviders);
  return data;
}

export async function createSearchProvider(
  input: SearchProviderInput,
): Promise<void> {
  await api.post("/search/providers", toProviderBody(input));
  setProvidersTick((n) => n + 1);
}

export async function updateSearchProvider(
  id: string,
  patch: Partial<SearchProviderInput>,
): Promise<void> {
  await api.patch(`/search/providers/${id}`, toProviderBody(patch));
  setProvidersTick((n) => n + 1);
}

export async function deleteSearchProvider(id: string): Promise<void> {
  await api.del(`/search/providers/${id}`);
  setProvidersTick((n) => n + 1);
}

/* ── Chat settings (attachment inline token cap) ───────────────────────────── */

export function useChatSettings(): Resource<ChatSettings> {
  const [data] = createResource(() => api.get<ChatSettings>("/chat/settings"));
  return data;
}

/** Persist the attachment inline token cap; returns the stored settings. */
export async function saveChatSettings(
  attachmentInlineMaxTokens: number,
): Promise<ChatSettings> {
  return api.put<ChatSettings>("/chat/settings", { attachmentInlineMaxTokens });
}
