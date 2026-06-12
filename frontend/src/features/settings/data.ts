import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import { refreshEndpoints, useEndpoints } from "~/lib/stores/models";
import type { EndpointInput, RoleBindings } from "./model";

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
