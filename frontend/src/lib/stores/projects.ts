/** Global project state — the operator's working directories and which one is
 *  active. One place owns it so the nav switcher, the projects screens, and the
 *  chat composer's coding-mode picker share a single source of truth.
 *
 *  **The selection is the backend's, not ours.** `POST /projects/{id}/activate`
 *  persists it, and the response carries the whole listing back, so activating
 *  reseats from one shape rather than patching a local guess. What lives here is
 *  the echo plus the header the client sends (`~/lib/api/projectScope`), which only
 *  ever relays that selection — the backend decides what a scope means and
 *  re-resolves it on every request.
 *
 *  **Null is a real state, not an empty one.** No active project means the operator
 *  sees their unfiled work: exactly what the app showed before projects existed.
 *  Activating one *adds* that project's items to the unfiled ones; it never hides
 *  them. Another project's items are what stay invisible. */

import {
  createEffect,
  createResource,
  createRoot,
  createSignal,
  type Resource,
} from "solid-js";
import { api } from "~/lib/api";
import { ALL_PROJECTS, setProjectScope } from "~/lib/api/projectScope";
import { useSession } from "~/lib/stores/session";

/** The git facts, re-probed by the backend on every listing. */
export interface ProjectRepo {
  exists: boolean;
  isGitRepo: boolean;
  /** Null when the path is not a repo — distinct from 0, which means a clean tree. */
  uncommittedChanges: number | null;
  currentBranch: string | null;
}

export interface Project {
  id: string;
  name: string;
  rootPath: string;
  gitInitialized: boolean;
  baseRef: string;
  archived: boolean;
  createdAt: string;
  lastOpenedAt: string;
  repo: ProjectRepo;
}

interface ProjectsDTO {
  projects: Project[];
  activeId: string | null;
}

async function fetchProjects(): Promise<ProjectsDTO> {
  return api.get<ProjectsDTO>("/projects");
}

const store = createRoot(() => {
  const session = useSession();

  const [tick, setTick] = createSignal(1);
  const [data] = createResource(
    () => (session.isAuthenticated ? tick() : false),
    fetchProjects,
  );

  // The active id, held as a local echo so the switcher moves at click speed. Seeded
  // and reconciled from the backend listing, which is authoritative.
  const [activeId, setActiveId] = createSignal<string | null>(null);
  // True only while the operator has explicitly asked for ALL PROJECTS. Distinct from
  // "nothing is active": the backend reads an absent header as "use the stored
  // selection", so saying *unscoped* takes a literal.
  const [unscoped, setUnscoped] = createSignal(false);

  // Seed the echo from every listing the backend returns — not just from the writes
  // that happen to return one. Without this the echo stays null across a reload while
  // the backend is still scoped to its stored selection, so the switcher reads
  // "UNFILED ONLY" and no project row looks selected while the operator is in fact
  // inside a project. Worse, toggling ALL PROJECTS and back would then write that null
  // into the request header and genuinely change the scope to match the wrong label.
  createEffect(() => {
    const dto = data.latest;
    if (!dto || unscoped()) return;
    setActiveId(dto.activeId);
    setProjectScope(dto.activeId);
  });

  return { data, tick, setTick, activeId, setActiveId, unscoped, setUnscoped };
});

/** The listing, including archived-excluded projects. */
export function useProjects(): Resource<ProjectsDTO> {
  return store.data;
}

export function activeProjectId(): string | null {
  return store.unscoped() ? null : store.activeId();
}

export function isUnscoped(): boolean {
  return store.unscoped();
}

/** The active project's full record, or null when nothing is active. */
export function activeProject(): Project | null {
  const id = activeProjectId();
  if (!id) return null;
  return store.data.latest?.projects.find((p) => p.id === id) ?? null;
}

export function refreshProjects(): void {
  store.setTick((n) => n + 1);
}

/** Reconcile the local echo from a backend listing. Called after any write that
 *  returns one, so the two can't drift. */
function adopt(dto: ProjectsDTO): void {
  store.setActiveId(dto.activeId);
  setProjectScope(store.unscoped() ? ALL_PROJECTS : dto.activeId);
}

/** Switch the active project, or pass `null` to clear it. The backend persists the
 *  selection and returns the whole listing; we reseat from that. */
export async function setActiveProject(
  projectId: string | null,
): Promise<void> {
  store.setUnscoped(false);
  const dto = projectId
    ? await api.post<ProjectsDTO>(`/projects/${projectId}/activate`, {})
    : await api.post<ProjectsDTO>("/projects/deactivate", {});
  adopt(dto);
  store.setTick((n) => n + 1);
}

/** ALL PROJECTS — deliberately unscoped, which is a different request from having
 *  no active project. Held client-side because it is a way of *asking*, not a stored
 *  preference: the operator's actual selection stays put underneath it. */
export function setUnscoped(on: boolean): void {
  store.setUnscoped(on);
  setProjectScope(on ? ALL_PROJECTS : store.activeId());
}

export async function createProject(
  name: string,
  rootPath: string,
): Promise<Project> {
  const created = await api.post<Project>("/projects", { name, rootPath });
  refreshProjects();
  return created;
}

export async function updateProject(
  id: string,
  patch: { name?: string; baseRef?: string; archived?: boolean },
): Promise<Project> {
  const updated = await api.patch<Project>(`/projects/${id}`, patch);
  refreshProjects();
  return updated;
}

export async function deleteProject(id: string): Promise<void> {
  await api.del(`/projects/${id}`);
  // Deleting the active project clears the selection backend-side; re-read rather
  // than guessing which way it went.
  const dto = await fetchProjects();
  adopt(dto);
  refreshProjects();
}
