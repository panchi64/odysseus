import {
  createEffect,
  createResource,
  createSignal,
  onCleanup,
  type Accessor,
  type Resource,
  type Setter,
} from "solid-js";
import { api } from "~/lib/api";
import type {
  DownloadProgress,
  EngineKind,
  EngineRecommendation,
  ManagedModel,
  ServeState,
  Workload,
} from "./model";

// --- backend DTOs (snake_case) — mapped to model.ts types below ------------

interface EngineRecommendationDTO {
  engine: string;
  rank: number;
  available: boolean;
  installed?: boolean;
  reason: string;
  workloads: string[];
}

interface DownloadProgressDTO {
  downloaded_bytes: number;
  total_bytes: number | null;
  fraction: number | null;
  file: string | null;
}

interface ManagedModelViewDTO {
  id: string;
  engine: string;
  workload: string;
  hf_repo: string;
  quant: string | null;
  state: string;
  endpoint_id: string | null;
  endpoint_name: string | null;
  port: number | null;
  last_error: string | null;
  progress: DownloadProgressDTO | null;
}

// --- mappers (presentation only — no domain logic) -------------------------

function mapRecommendation(d: EngineRecommendationDTO): EngineRecommendation {
  return {
    engine: d.engine as EngineKind,
    rank: d.rank,
    available: d.available,
    installed: d.installed ?? false,
    reason: d.reason,
    workloads: d.workloads as Workload[],
  };
}

function mapProgress(d: DownloadProgressDTO | null): DownloadProgress | null {
  if (!d) return null;
  return {
    downloadedBytes: d.downloaded_bytes,
    totalBytes: d.total_bytes,
    fraction: d.fraction,
    file: d.file,
  };
}

function mapManagedModel(d: ManagedModelViewDTO): ManagedModel {
  return {
    id: d.id,
    engine: d.engine as EngineKind,
    workload: d.workload as Workload,
    hfRepo: d.hf_repo,
    quant: d.quant,
    state: d.state as ServeState,
    endpointId: d.endpoint_id,
    endpointName: d.endpoint_name,
    port: d.port,
    lastError: d.last_error,
    progress: mapProgress(d.progress),
  };
}

// --- client fns over ~/lib/api ---------------------------------------------

/** Ranked inference-engine recommendations for the current host. */
export async function fetchRecommendations(): Promise<EngineRecommendation[]> {
  const dto = await api.get<EngineRecommendationDTO[]>(
    "/models/serving/recommendations",
  );
  return dto.map(mapRecommendation);
}

/** The quantizations available in `repo` for `engine` — the quant picker's options.
 *  Empty when the engine bakes the quant into the repo id (MLX) or the repo can't be
 *  introspected, so the UI degrades to the engine's default pick. */
export async function fetchRepoQuants(
  repo: string,
  engine: EngineKind,
): Promise<string[]> {
  const params = new URLSearchParams({ repo, engine });
  return api.get<string[]>(`/models/serving/repo-quants?${params.toString()}`);
}

/** Models Odysseus is currently managing. */
export async function fetchManagedModels(): Promise<ManagedModel[]> {
  const dto = await api.get<ManagedModelViewDTO[]>("/models/serving/models");
  return dto.map(mapManagedModel);
}

/** Begin downloading a Hugging Face model with the chosen engine. The backend
 *  returns the newly-managed model (state `downloading`); the polling controller
 *  then tracks its progress. Null/undefined quant + workload are omitted so the
 *  backend applies its defaults. */
export async function downloadModel(input: {
  engine: EngineKind;
  repo: string;
  quant?: string | null;
  workload?: Workload;
}): Promise<ManagedModel> {
  const body: Record<string, unknown> = {
    engine: input.engine,
    repo: input.repo,
  };
  if (input.quant != null) body.quant = input.quant;
  if (input.workload != null) body.workload = input.workload;
  const dto = await api.post<ManagedModelViewDTO>(
    "/models/serving/download",
    body,
  );
  return mapManagedModel(dto);
}

/** Serve a model: launch its engine and register it as a 127.0.0.1 endpoint
 *  (optionally binding a role). NON-BLOCKING — the backend returns immediately
 *  with state `downloading`/`starting`, then the polling controller tracks it
 *  through `running` (or `error`). Null/undefined fields are omitted so the
 *  backend applies its defaults. */
export async function serveModel(input: {
  engine: EngineKind;
  repo: string;
  role?: string;
  workload?: Workload;
  quant?: string | null;
}): Promise<ManagedModel> {
  const body: Record<string, unknown> = {
    engine: input.engine,
    repo: input.repo,
  };
  if (input.role != null) body.role = input.role;
  if (input.workload != null) body.workload = input.workload;
  if (input.quant != null) body.quant = input.quant;
  const dto = await api.post<ManagedModelViewDTO>(
    "/models/serving/serve",
    body,
  );
  return mapManagedModel(dto);
}

/** Stop a running/starting/downloading managed model — its engine is torn down
 *  and the endpoint deregistered. Returns the model in its stopped state. */
export async function stopModel(id: string): Promise<ManagedModel> {
  const dto = await api.post<ManagedModelViewDTO>(
    `/models/serving/${id}/stop`,
    {},
  );
  return mapManagedModel(dto);
}

/** Delete a managed model (its files + record). 204 No Content. */
export async function deleteModel(id: string): Promise<void> {
  await api.del(`/models/serving/${id}`);
}

// --- models directory settings ---------------------------------------------

interface ModelsDirSettingsDTO {
  models_dir: string;
}

/** The absolute directory new model downloads are written to. */
export async function fetchModelsDir(): Promise<string> {
  const dto = await api.get<ModelsDirSettingsDTO>("/models/serving/settings");
  return dto.models_dir;
}

/** Point new downloads at `path`. The backend is the authority — it validates the
 *  path and returns 400 with a `detail` reason — so it returns the stored absolute
 *  path to display back. */
export async function updateModelsDir(path: string): Promise<string> {
  const dto = await api.put<ModelsDirSettingsDTO>("/models/serving/settings", {
    models_dir: path,
  });
  return dto.models_dir;
}

// --- in-flight helpers (shared by the local/embedding panels) --------------

/** A model state is "in flight" while its download/start is still progressing. */
export function isInFlight(state: ServeState): boolean {
  return state === "downloading" || state === "starting";
}

/** The top-ranked engine that can run on this host right now — the picker's default
 *  selection and the engine a free-text download targets until the operator picks
 *  another. `null` when nothing is available (or the recommendations haven't loaded). */
export function topAvailableEngine(
  recs: EngineRecommendation[] | undefined,
): EngineKind | null {
  if (!recs) return null;
  return (
    [...recs].sort((a, b) => a.rank - b.rank).find((r) => r.available)
      ?.engine ?? null
  );
}

/** The set of `hfRepo`s with an in-flight managed model — used to disable a repo's
 *  download/serve action so it can't double-fire while one is already running. */
export function inFlightRepos(models: ManagedModel[]): Set<string> {
  return new Set(
    models.filter((m) => isInFlight(m.state)).map((m) => m.hfRepo),
  );
}

// --- hooks (mirror useHardware) --------------------------------------------

export function useRecommendations(): Resource<EngineRecommendation[]> {
  const [data] = createResource(fetchRecommendations);
  return data;
}

/** Owns the engine selection for the local-serve forms: preselect the top engine the host
 *  can run, and self-heal if the ranking shifts under a now-invalid pick — while leaving a
 *  deliberate operator override in place as long as it stays available. Returns the
 *  selected-engine accessor and its setter (mirrors `createSignal`). */
export function useEngineSelection(
  recommendations: Resource<EngineRecommendation[]>,
): [Accessor<EngineKind | null>, Setter<EngineKind | null>] {
  const [selected, setSelected] = createSignal<EngineKind | null>(null);
  createEffect(() => {
    const recs = recommendations.latest;
    if (!recs) return;
    const cur = selected();
    const stillValid =
      cur != null && recs.some((r) => r.engine === cur && r.available);
    if (!stillValid) setSelected(topAvailableEngine(recs));
  });
  return [selected, setSelected];
}

/** The managed-models controller the panel consumes. */
export interface ManagedModelsController {
  models: Accessor<ManagedModel[]>;
  /** True only on the very first load (subsequent polls refresh in place). */
  loading: Accessor<boolean>;
  /** Force an immediate re-fetch (e.g. right after triggering a download). */
  refresh: () => void;
}

/** Polls the managed-models list while any model is downloading/starting, and
 *  idles the timer otherwise (a final settle fetch lands the terminal states).
 *  Mirrors the browser-timer controller style in `chat/data.ts`: an interval
 *  owned here, torn down on `onCleanup`. */
export function useManagedModels(intervalMs = 1500): ManagedModelsController {
  const [models, setModels] = createSignal<ManagedModel[]>([]);
  const [loading, setLoading] = createSignal(true);
  let timer: ReturnType<typeof setInterval> | undefined;
  let inFlightFetch = false;

  function stopTimer(): void {
    if (timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
    }
  }

  function ensureTimer(): void {
    if (timer === undefined) timer = setInterval(() => void poll(), intervalMs);
  }

  async function poll(): Promise<void> {
    // Avoid overlapping fetches if one runs long past the interval.
    if (inFlightFetch) return;
    inFlightFetch = true;
    try {
      const next = await fetchManagedModels();
      setModels(next);
      // Keep polling while anything is in flight; otherwise this fetch was the
      // settle that lands the terminal states, so stand the timer down.
      if (next.some((m) => isInFlight(m.state))) ensureTimer();
      else stopTimer();
    } catch {
      // Transient errors leave the last list on screen; the next poll retries.
    } finally {
      inFlightFetch = false;
      setLoading(false);
    }
  }

  void poll();

  function refresh(): void {
    // An immediate re-fetch, and (re)arm the timer — a freshly-triggered download
    // is in flight, so polling should resume even if it had idled.
    ensureTimer();
    void poll();
  }

  onCleanup(stopTimer);

  return { models, loading, refresh };
}
