import { createResource, createSignal, type Resource } from "solid-js";
import { api, isApiError } from "~/lib/api";
import type {
  McpAuthCredentials,
  McpServer,
  McpStatus,
  McpTool,
  McpTransport,
} from "./model";

/* ── Backend DTOs → seam types ────────────────────────────────────────────── */

interface McpToolOut {
  name: string;
  description: string;
  enabled: boolean;
  trusted: boolean;
}

interface McpServerOut {
  id: string;
  name: string;
  slug: string;
  transport: string;
  url: string | null;
  command: string | null;
  args: string[];
  envKeys: string[];
  enabled: boolean;
  status: string;
  authRequired: boolean;
  hasCredentials: boolean;
  lastError: string | null;
  lastErrorAt: string | null;
  tools: McpToolOut[];
}

/** The wire's open strings narrowed to what the screen knows how to render. An
 *  unrecognized value reads as the least-claiming one — a server we can't classify
 *  is not "connected", and a transport we don't know is dialled over HTTP. */
function toStatus(value: string): McpStatus {
  return value === "connected" || value === "error" ? value : "disconnected";
}

function toTransport(value: string): McpTransport {
  return value === "stdio" || value === "sse" ? value : "http";
}

/** How a server is addressed, as one line: the endpoint for the HTTP transports,
 *  the command line for stdio. The card shows one field either way. */
function address(dto: McpServerOut): string {
  if (dto.transport === "stdio") {
    return [dto.command ?? "", ...dto.args].join(" ").trim();
  }
  return dto.url ?? "";
}

function toTool(dto: McpToolOut): McpTool {
  return {
    name: dto.name,
    description: dto.description,
    enabled: dto.enabled,
    trusted: dto.trusted,
  };
}

function toServer(dto: McpServerOut): McpServer {
  return {
    id: dto.id,
    name: dto.name,
    slug: dto.slug,
    transport: toTransport(dto.transport),
    url: address(dto),
    status: toStatus(dto.status),
    tools: dto.tools.map(toTool),
    enabled: dto.enabled,
    authRequired: dto.authRequired,
    hasCredentials: dto.hasCredentials,
    envKeys: dto.envKeys,
    errorMessage: dto.lastError ?? undefined,
    errorAt: dto.lastErrorAt ?? undefined,
  };
}

/* ── List (the seam) ──────────────────────────────────────────────────────── */

const [listTick, setListTick] = createSignal(0);

async function fetchMcpServers(): Promise<McpServer[]> {
  const rows = await api.get<McpServerOut[]>("/mcp/servers");
  return rows.map(toServer);
}

export function useMcpServers(): Resource<McpServer[]> {
  const [data] = createResource(listTick, fetchMcpServers);
  return data;
}

/** Invalidate the server list after a mutation. */
export function refreshMcpServers(): void {
  setListTick((n) => n + 1);
}

/* ── Mutations ────────────────────────────────────────────────────────────── */

/** What the register form collects. A stdio server is a command line, an HTTP one a
 *  URL — the backend decides which its transport requires, and says so on a 422. */
export interface McpServerInput {
  name: string;
  transport: McpTransport;
  command?: string;
  args?: string[];
  url?: string;
  authRequired?: boolean;
  credentials?: McpAuthCredentials;
}

/** Register and connect in one step — the backend dials on registration, so what
 *  comes back already carries the outcome and the discovered tools. */
export async function registerMcpServer(
  input: McpServerInput,
): Promise<McpServer> {
  const dto = await api.post<McpServerOut>("/mcp/servers", {
    name: input.name,
    transport: input.transport,
    command: input.command,
    args: input.args ?? [],
    url: input.url,
    auth_required: input.authRequired ?? false,
    credentials: input.credentials,
  });
  refreshMcpServers();
  return toServer(dto);
}

/** Store (or replace) the credentials an auth-required server is dialled with. */
export async function setMcpCredentials(
  id: string,
  credentials: McpAuthCredentials,
): Promise<McpServer> {
  const dto = await api.patch<McpServerOut>(`/mcp/servers/${id}`, {
    auth_required: true,
    credentials,
  });
  refreshMcpServers();
  return toServer(dto);
}

/** Reconnect and re-discover. A server that refuses answers 200 with
 *  `status: "error"` and the reason — the outcome is the point, not an exception. */
export async function connectMcpServer(id: string): Promise<McpServer> {
  const dto = await api.post<McpServerOut>(`/mcp/servers/${id}/connect`);
  refreshMcpServers();
  return toServer(dto);
}

export async function deleteMcpServer(id: string): Promise<void> {
  await api.del(`/mcp/servers/${id}`);
  refreshMcpServers();
}

/** Set one tool's enable and/or trust decision. Only the fields passed change, so
 *  toggling one never disturbs the other — and trust is set one tool at a time,
 *  because there is deliberately no way to trust a whole server at once. */
export async function setMcpToolPolicy(
  serverId: string,
  toolName: string,
  patch: { enabled?: boolean; trusted?: boolean },
): Promise<McpTool> {
  const dto = await api.patch<McpToolOut>(
    `/mcp/servers/${serverId}/tools/${encodeURIComponent(toolName)}`,
    patch,
  );
  refreshMcpServers();
  return toTool(dto);
}

/* ── Errors ───────────────────────────────────────────────────────────────── */

/** The backend's message for a failure, verbatim — it decides what's wrong and how
 *  to say it. `fallback` covers a transport failure, which produced no message. */
export function mcpErrorMessage(err: unknown, fallback: string): string {
  return isApiError(err) ? err.detail : fallback;
}
