import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import { refreshModelOptions } from "~/lib/stores/models";
import type { EndpointInput, ModelEndpoint, RoleBindings } from "./model";

/* ── Backend DTOs ─────────────────────────────────────────────────────────── */

interface EndpointView {
  id: string;
  name: string;
  base_url: string;
  model: string | null;
  has_api_key: boolean;
  context_window: number | null;
  native_tools: boolean;
  vision: boolean;
  thinking: boolean;
}

function toEndpoint(dto: EndpointView): ModelEndpoint {
  return {
    id: dto.id,
    name: dto.name,
    baseUrl: dto.base_url,
    model: dto.model,
    hasApiKey: dto.has_api_key,
    contextWindow: dto.context_window,
    nativeTools: dto.native_tools,
    vision: dto.vision,
    thinking: dto.thinking,
  };
}

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

/* ── Endpoints ────────────────────────────────────────────────────────────── */

const [endpointsTick, setEndpointsTick] = createSignal(0);

async function fetchEndpoints(): Promise<ModelEndpoint[]> {
  const rows = await api.get<EndpointView[]>("/models/endpoints");
  return rows.map(toEndpoint);
}

export function useEndpoints(): Resource<ModelEndpoint[]> {
  const [data] = createResource(endpointsTick, fetchEndpoints);
  return data;
}

function refreshEndpoints(): void {
  setEndpointsTick((n) => n + 1);
  refreshModelOptions(); // keep the chat picker in sync
}

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
  refreshModelOptions();
}
