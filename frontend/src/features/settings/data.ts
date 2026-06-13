import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import { refreshEndpoints, useEndpoints } from "~/lib/stores/models";
import type {
  EndpointInput,
  RoleBindings,
  SearchProvider,
  SearchProviderInput,
} from "./model";

// The endpoint catalog (read) is owned by the shared models store so the chat
// picker and Settings share one fetch and one type; this module owns the writes
// (CRUD + role bindings) and the role read.
export { useEndpoints };

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
  return body;
}

/* ── Endpoints (writes) ───────────────────────────────────────────────────── */

export async function createEndpoint(input: EndpointInput): Promise<void> {
  await api.post("/models/endpoints", toBody(input));
  refreshEndpoints();
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

async function fetchRoles(): Promise<RoleBindings> {
  return api.get<RoleBindings>("/models/roles");
}

export function useRoles(): Resource<RoleBindings> {
  const [data] = createResource(rolesTick, fetchRoles);
  return data;
}

export async function setRoleBinding(
  role: string,
  endpointIds: string[],
): Promise<void> {
  await api.put(`/models/roles/${role}`, { endpoint_ids: endpointIds });
  setRolesTick((n) => n + 1);
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
