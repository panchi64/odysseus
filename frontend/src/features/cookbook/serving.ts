import {
  createResource,
  createSignal,
  onCleanup,
  type Accessor,
  type Resource,
} from "solid-js";
import { api } from "~/lib/api";
import type {
  CatalogEntry,
  DownloadProgress,
  EngineKind,
  EngineRecommendation,
  ManagedModel,
  ServeState,
  Workload,
} from "./model";

// --- backend DTOs (snake_case) — mapped to model.ts types below ------------

interface CatalogEntryDTO {
  repo: string;
  label: string;
  engine: string;
  workload: string;
  params: string | null;
  quant: string | null;
  approx_bytes: number | null;
  native_tools: boolean;
  context_window: number | null;
  notes: string | null;
}

interface EngineRecommendationDTO {
  engine: string;
  rank: number;
  available: boolean;
  reason: string;
  workloads: string[];
  recommended_models: CatalogEntryDTO[];
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

function mapCatalogEntry(d: CatalogEntryDTO): CatalogEntry {
  return {
    repo: d.repo,
    label: d.label,
    engine: d.engine as EngineKind,
    workload: d.workload as Workload,
    params: d.params,
    quant: d.quant,
    approxBytes: d.approx_bytes,
    nativeTools: d.native_tools,
    contextWindow: d.context_window,
    notes: d.notes,
  };
}

function mapRecommendation(d: EngineRecommendationDTO): EngineRecommendation {
  return {
    engine: d.engine as EngineKind,
    rank: d.rank,
    available: d.available,
    reason: d.reason,
    workloads: d.workloads as Workload[],
    recommendedModels: d.recommended_models.map(mapCatalogEntry),
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

/** The curated catalog for an engine + workload. */
export async function fetchCatalog(
  engine: EngineKind,
  workload: Workload,
): Promise<CatalogEntry[]> {
  const dto = await api.get<CatalogEntryDTO[]>(
    `/models/serving/catalog?engine=${encodeURIComponent(engine)}&workload=${encodeURIComponent(workload)}`,
  );
  return dto.map(mapCatalogEntry);
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

// --- hooks (mirror useHardware) --------------------------------------------

export function useRecommendations(): Resource<EngineRecommendation[]> {
  const [data] = createResource(fetchRecommendations);
  return data;
}

/** A managed model is "in flight" while its download/start is still progressing —
 *  this is what drives the polling cadence below. */
function isInFlight(m: ManagedModel): boolean {
  return m.state === "downloading" || m.state === "starting";
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
      if (next.some(isInFlight)) ensureTimer();
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
