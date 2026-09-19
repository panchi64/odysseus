import { createResource, createSignal, type Resource } from "solid-js";
import { api, isApiError } from "~/lib/api";
import type { Workflow } from "./model";

/* ── Backend DTOs → seam types ────────────────────────────────────────────── */

interface WorkflowOut {
  id: string;
  name: string;
  title: string;
  description: string;
  body: string;
  argumentHint?: string | null;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

function toWorkflow(dto: WorkflowOut): Workflow {
  return {
    id: dto.id,
    name: dto.name,
    title: dto.title,
    description: dto.description,
    body: dto.body,
    argumentHint: dto.argumentHint ?? null,
    enabled: dto.enabled,
    createdAt: dto.createdAt,
    updatedAt: dto.updatedAt,
  };
}

/* ── List (the seam) ──────────────────────────────────────────────────────── */

const [listTick, setListTick] = createSignal(0);

async function fetchWorkflows(): Promise<Workflow[]> {
  const rows = await api.get<WorkflowOut[]>("/commands/workflows");
  return rows.map(toWorkflow);
}

/** Every saved workflow, disabled ones included — this is the editor's list, not the
 *  composer's menu. The menu is a different read entirely (`GET /commands`), because it
 *  is a *merge* of five sources and the backend decides what it contains. */
export function useWorkflows(): Resource<Workflow[]> {
  const [data] = createResource(listTick, fetchWorkflows);
  return data;
}

/** Invalidate the list after a mutation. */
export function refreshWorkflows(): void {
  setListTick((n) => n + 1);
}

/* ── Mutations ────────────────────────────────────────────────────────────── */

/** Everything `PATCH /commands/workflows/{id}` accepts. Request bodies are snake_case
 *  (only responses are camelCase), so `argumentHint` is renamed on the way out. */
export interface WorkflowPatch {
  name?: string;
  title?: string;
  description?: string;
  body?: string;
  argumentHint?: string;
  enabled?: boolean;
}

export async function createWorkflow(
  name: string,
  body: string,
  description = "",
): Promise<Workflow> {
  const dto = await api.post<WorkflowOut>("/commands/workflows", {
    name,
    body,
    description,
  });
  refreshWorkflows();
  return toWorkflow(dto);
}

export async function updateWorkflow(
  id: string,
  patch: WorkflowPatch,
): Promise<Workflow> {
  const { argumentHint, ...rest } = patch;
  const dto = await api.patch<WorkflowOut>(`/commands/workflows/${id}`, {
    ...rest,
    ...(argumentHint !== undefined ? { argument_hint: argumentHint } : {}),
  });
  refreshWorkflows();
  return toWorkflow(dto);
}

export async function deleteWorkflow(id: string): Promise<void> {
  await api.del(`/commands/workflows/${id}`);
  refreshWorkflows();
}

/* ── Errors ───────────────────────────────────────────────────────────────── */

export function workflowErrorMessage(err: unknown, fallback: string): string {
  return isApiError(err) ? err.detail : fallback;
}

/** The input a 422 blamed, when it named one, so a form can attach the message to that
 *  control instead of only toasting it. */
export function workflowErrorField(err: unknown): string | null {
  return isApiError(err) ? (err.field ?? null) : null;
}
