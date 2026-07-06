import { createResource, onCleanup, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type { EmbeddingRole, ReindexState, ReindexStatus } from "./model";

interface RoleViewDTO {
  endpoint_ids: string[];
  model: string | null;
}

interface ReindexStatusDTO {
  state: ReindexState;
  memories: number;
  messages: number;
  detail: string | null;
  completed_at: string | null;
}

function toReindexStatus(dto: ReindexStatusDTO): ReindexStatus {
  return {
    state: dto.state,
    memories: dto.memories,
    messages: dto.messages,
    detail: dto.detail ?? undefined,
    completedAt: dto.completed_at ?? undefined,
  };
}

async function fetchEmbeddingRole(): Promise<EmbeddingRole> {
  const roles = await api.get<Record<string, RoleViewDTO>>("/models/roles");
  const embedding = roles.embedding;
  return {
    endpointId: embedding?.endpoint_ids[0] ?? null,
    model: embedding?.model ?? null,
  };
}

/** The `embedding` role's current binding. */
export function useEmbeddingRole(): Resource<EmbeddingRole> & {
  refetch: () => void;
} {
  const [data, { refetch }] = createResource(fetchEmbeddingRole);
  return Object.assign(data, { refetch }) as Resource<EmbeddingRole> & {
    refetch: () => void;
  };
}

/** Bind the `embedding` role to a served model's endpoint — the backend heals
 *  existing vectors into the new space automatically (a changed embedding
 *  endpoint/model triggers a reindex server-side). */
export async function setEmbeddingRole(
  endpointId: string,
  model: string | null,
): Promise<void> {
  await api.put(`/models/roles/embedding`, {
    endpoint_ids: [endpointId],
    model,
  });
}

const REINDEX_POLL_MS = 1500;

async function fetchReindexStatus(): Promise<ReindexStatus> {
  const dto = await api.get<ReindexStatusDTO>("/models/embedding/reindex");
  return toReindexStatus(dto);
}

/** The re-embed job's status, polled while running so the panel reflects
 *  progress live — mirrors the serving surface's download-progress poll. */
export function useReindexStatus(): Resource<ReindexStatus> & {
  refetch: () => void;
} {
  const [data, { refetch }] = createResource(fetchReindexStatus);
  const timer = setInterval(() => {
    if (data()?.state === "running") refetch();
  }, REINDEX_POLL_MS);
  onCleanup(() => clearInterval(timer));
  return Object.assign(data, { refetch }) as Resource<ReindexStatus> & {
    refetch: () => void;
  };
}

/** Manually trigger a reindex — for a first index that failed, or to force a
 *  redo after a model change the operator wants re-applied. */
export async function triggerReindex(): Promise<ReindexStatus> {
  const dto = await api.post<ReindexStatusDTO>("/models/embedding/reindex", {});
  return toReindexStatus(dto);
}
