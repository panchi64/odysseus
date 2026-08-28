import { createResource, createSignal, type Resource } from "solid-js";
import { api, isApiError } from "~/lib/api";
import type {
  Integration,
  IntegrationAction,
  IntegrationPreset,
  IntegrationStatus,
} from "./model";

/* ── Backend DTOs → seam types ────────────────────────────────────────────── */

interface IntegrationActionOut {
  name: string;
  method: string;
  path: string;
  description: string;
  takesBody: boolean;
  enabled: boolean;
  trusted: boolean;
}

interface IntegrationPresetOut {
  id: string;
  name: string;
  category: string;
  description: string;
  baseUrl: string;
  auth: string;
  credentialRequired: boolean;
  actions: string[];
}

interface IntegrationOut {
  id: string;
  name: string;
  slug: string;
  preset: string;
  category: string;
  description: string;
  baseUrl: string;
  credentialRequired: boolean;
  configured: boolean;
  enabled: boolean;
  status: string;
  lastError: string | null;
  lastTestedAt: string | null;
  actions: IntegrationActionOut[];
}

/** The wire's open `status` narrowed to the three the screen renders. Anything
 *  unrecognized reads as untested — the least-claiming of the three. */
function toStatus(value: string): IntegrationStatus {
  return value === "ok" || value === "error" ? value : "untested";
}

function toAction(dto: IntegrationActionOut): IntegrationAction {
  return {
    name: dto.name,
    method: dto.method,
    path: dto.path,
    description: dto.description,
    enabled: dto.enabled,
    trusted: dto.trusted,
  };
}

function toPreset(dto: IntegrationPresetOut): IntegrationPreset {
  return {
    id: dto.id,
    name: dto.name,
    category: dto.category,
    description: dto.description,
    baseUrl: dto.baseUrl,
    credentialRequired: dto.credentialRequired,
    actions: dto.actions,
  };
}

function toIntegration(dto: IntegrationOut): Integration {
  return {
    id: dto.id,
    name: dto.name,
    type: dto.preset,
    baseUrl: dto.baseUrl,
    configured: dto.configured,
    status: toStatus(dto.status),
    enabled: dto.enabled,
    actions: dto.actions.map(toAction),
    lastTestedAt: dto.lastTestedAt ?? undefined,
    description: dto.description,
    errorMessage: dto.lastError ?? undefined,
    credentialRequired: dto.credentialRequired,
  };
}

/* ── List (the seam) ──────────────────────────────────────────────────────── */

const [listTick, setListTick] = createSignal(0);

async function fetchIntegrations(): Promise<Integration[]> {
  const rows = await api.get<IntegrationOut[]>("/integrations");
  return rows.map(toIntegration);
}

export function useIntegrations(): Resource<Integration[]> {
  const [data] = createResource(listTick, fetchIntegrations);
  return data;
}

/** Invalidate the connector list after a mutation. */
export function refreshIntegrations(): void {
  setListTick((n) => n + 1);
}

/* ── Presets ──────────────────────────────────────────────────────────────── */

/** The catalog a connector can be instantiated from. Static on the backend, so it
 *  is fetched once rather than invalidated with the list. */
export function useIntegrationPresets(): Resource<IntegrationPreset[]> {
  const [data] = createResource(async () => {
    const rows = await api.get<IntegrationPresetOut[]>("/integrations/presets");
    return rows.map(toPreset);
  });
  return data;
}

/* ── Mutations ────────────────────────────────────────────────────────────── */

/** Configure a connector from a preset. The preset fixes the request shape and the
 *  default base URL; `baseUrl` overrides it for a self-hosted instance. */
export async function configureIntegration(input: {
  preset: string;
  name?: string;
  baseUrl?: string;
  credentials?: Record<string, string>;
}): Promise<Integration> {
  const dto = await api.post<IntegrationOut>("/integrations", {
    preset: input.preset,
    name: input.name,
    base_url: input.baseUrl,
    credentials: input.credentials,
  });
  refreshIntegrations();
  return toIntegration(dto);
}

/** Amend an existing connector. A credential goes in and never comes back, so
 *  omitting it leaves the stored one untouched rather than clearing it. */
export async function updateIntegration(
  id: string,
  patch: {
    name?: string;
    baseUrl?: string;
    credentials?: Record<string, string>;
    enabled?: boolean;
  },
): Promise<Integration> {
  const dto = await api.patch<IntegrationOut>(`/integrations/${id}`, {
    name: patch.name,
    base_url: patch.baseUrl,
    credentials: patch.credentials,
    enabled: patch.enabled,
  });
  refreshIntegrations();
  return toIntegration(dto);
}

/** Prove the credential before anything relies on it. A failure answers 200 with
 *  `status: "error"` and the reason — that outcome is what the operator asked for. */
export async function testIntegration(id: string): Promise<Integration> {
  const dto = await api.post<IntegrationOut>(`/integrations/${id}/test`);
  refreshIntegrations();
  return toIntegration(dto);
}

export async function deleteIntegration(id: string): Promise<void> {
  await api.del(`/integrations/${id}`);
  refreshIntegrations();
}

/** Set one action's enable and/or trust decision — the same per-tool grant an MCP
 *  tool gets, because a connector's action is the same kind of unknown. */
export async function setIntegrationActionPolicy(
  integrationId: string,
  actionName: string,
  patch: { enabled?: boolean; trusted?: boolean },
): Promise<IntegrationAction> {
  const dto = await api.patch<IntegrationActionOut>(
    `/integrations/${integrationId}/actions/${encodeURIComponent(actionName)}`,
    patch,
  );
  refreshIntegrations();
  return toAction(dto);
}

/* ── Errors ───────────────────────────────────────────────────────────────── */

/** The backend's message for a failure, verbatim — it decides what's wrong and how
 *  to say it. `fallback` covers a transport failure, which produced no message. */
export function integrationErrorMessage(
  err: unknown,
  fallback: string,
): string {
  return isApiError(err) ? err.detail : fallback;
}
