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
import { toast } from "~/ui";
import type { EngineKind, ServeState, Workload } from "~/lib/api/models-types";
import type {
  DownloadProgress,
  EngineRecommendation,
  KvCacheType,
  LaunchOptionField,
  LaunchOptions,
  ManagedModel,
  ModelSource,
  PickerAvailability,
  ServeStage,
  ServeStageInfo,
  SpeculativeMode,
} from "./model";

// --- backend DTOs (snake_case) — mapped to model.ts types below ------------

interface EngineRecommendationDTO {
  engine: string;
  rank: number;
  available: boolean;
  installed?: boolean;
  reason: string;
  workloads: string[];
  supported_options?: string[];
}

interface DownloadProgressDTO {
  downloaded_bytes: number;
  total_bytes: number | null;
  fraction: number | null;
  file: string | null;
}

interface LaunchOptionsDTO {
  context_size: number | null;
  kv_cache_type: string | null;
  cache_reuse: number | null;
  speculative?: string | null;
  draft_model?: string | null;
  extra_args: string[];
}

interface ServeStageDTO {
  stage: string;
  started_at: string;
  timeout_s: number | null;
}

interface ManagedModelViewDTO {
  id: string;
  engine: string;
  workload: string;
  hf_repo: string;
  quant: string | null;
  state: string;
  source?: string;
  artifact_path?: string | null;
  endpoint_id: string | null;
  endpoint_name: string | null;
  port: number | null;
  last_error: string | null;
  progress: DownloadProgressDTO | null;
  stage?: ServeStageDTO | null;
  speculative?: string | null;
  options: LaunchOptionsDTO;
}

interface PickerAvailabilityDTO {
  available: boolean;
  tool?: string | null;
  reason?: string | null;
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
    supportedOptions: mapSupportedOptions(d.supported_options),
  };
}

/** Wire field name → the camelCase field it names. Explicit, not a cast: the backend
 *  spells these in Python's snake_case and a bare cast would typecheck while matching
 *  nothing, silently emptying the tuning form. */
const OPTION_FIELD_BY_WIRE: Record<string, LaunchOptionField> = {
  context_size: "contextSize",
  kv_cache_type: "kvCacheType",
  cache_reuse: "cacheReuse",
  speculative: "speculative",
  draft_model: "draftModel",
};

/** An unrecognized field name is dropped rather than rendered — a backend that grows a
 *  new tunable this build has no control for should degrade, not crash. */
function mapSupportedOptions(wire: string[] | undefined): LaunchOptionField[] {
  return (wire ?? [])
    .map((name) => OPTION_FIELD_BY_WIRE[name])
    .filter((f): f is LaunchOptionField => f !== undefined);
}

function mapStage(d: ServeStageDTO | null | undefined): ServeStageInfo | null {
  if (!d) return null;
  return {
    stage: d.stage as ServeStage,
    startedAt: d.started_at,
    timeoutS: d.timeout_s,
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

function mapOptions(d: LaunchOptionsDTO | null | undefined): LaunchOptions {
  return {
    contextSize: d?.context_size ?? null,
    kvCacheType: (d?.kv_cache_type as KvCacheType | null) ?? null,
    cacheReuse: d?.cache_reuse ?? null,
    speculative: (d?.speculative as SpeculativeMode | null) ?? null,
    draftModel: d?.draft_model ?? null,
    extraArgs: d?.extra_args ?? [],
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
    source: (d.source ?? "huggingface") as ModelSource,
    artifactPath: d.artifact_path ?? null,
    endpointId: d.endpoint_id,
    endpointName: d.endpoint_name,
    port: d.port,
    lastError: d.last_error,
    progress: mapProgress(d.progress),
    stage: mapStage(d.stage),
    speculative: d.speculative ?? null,
    options: mapOptions(d.options),
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
  options?: LaunchOptions | null;
}): Promise<ManagedModel> {
  const body: Record<string, unknown> = {
    engine: input.engine,
    repo: input.repo,
  };
  if (input.role != null) body.role = input.role;
  if (input.workload != null) body.workload = input.workload;
  if (input.quant != null) body.quant = input.quant;
  // Omitted entirely when absent, so a serve with no advanced section touched keeps
  // whatever the model was last tuned with instead of resetting it.
  if (input.options != null) {
    body.options = {
      context_size: input.options.contextSize,
      kv_cache_type: input.options.kvCacheType,
      cache_reuse: input.options.cacheReuse,
      speculative: input.options.speculative,
      draft_model: input.options.draftModel,
      extra_args: input.options.extraArgs,
    };
  }
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

/** Delete a managed model. Downloaded weights are removed with it; an imported
 *  model's files are the operator's and are left where they are. 204 No Content. */
export async function deleteModel(id: string): Promise<void> {
  await api.del(`/models/serving/${id}`);
}

/** Register weights already on disk as a managed model, so it can be served with
 *  nothing to download. `path` is absolute and stays where it is. */
export async function importLocalModel(input: {
  engine: EngineKind;
  path: string;
  workload?: Workload;
  name?: string | null;
}): Promise<ManagedModel> {
  const body: Record<string, unknown> = {
    engine: input.engine,
    path: input.path,
  };
  if (input.workload != null) body.workload = input.workload;
  if (input.name) body.name = input.name;
  const dto = await api.post<ManagedModelViewDTO>(
    "/models/serving/import",
    body,
  );
  return mapManagedModel(dto);
}

// --- the native file chooser -----------------------------------------------

/** Whether this host can open a native file/folder dialog. */
export async function fetchPickerAvailability(): Promise<PickerAvailability> {
  const dto = await api.get<PickerAvailabilityDTO>(
    "/models/serving/file-picker",
  );
  return { available: dto.available, reason: dto.reason ?? null };
}

/** Open a native chooser on the host and return the absolute path, or null when
 *  the operator cancelled. A browser can't produce a host path, so the backend —
 *  which runs on their machine — opens the dialog and hands the path back. */
export async function pickPath(input: {
  mode: "file" | "directory";
  title?: string;
  startDir?: string | null;
  extensions?: string[] | null;
}): Promise<string | null> {
  const dto = await api.post<{ path: string | null }>(
    "/models/serving/file-picker",
    {
      mode: input.mode,
      title: input.title ?? "Choose",
      start_dir: input.startDir ?? null,
      extensions: input.extensions ?? null,
    },
  );
  return dto.path;
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

/** The tuning fields an engine honours, per its recommendation. Empty until the
 *  recommendations load or when no engine is chosen, which renders as a form with only
 *  the always-available extra-arguments escape hatch. */
export function supportedOptionsFor(
  recs: EngineRecommendation[] | undefined,
  engine: EngineKind | null,
): LaunchOptionField[] {
  if (!recs || engine == null) return [];
  return recs.find((r) => r.engine === engine)?.supportedOptions ?? [];
}

/** The blank slate: every field unset, so the engine's own defaults stand. */
export const EMPTY_OPTIONS: LaunchOptions = {
  contextSize: null,
  kvCacheType: null,
  cacheReuse: null,
  speculative: null,
  draftModel: null,
  extraArgs: [],
};

/** Whether the operator set anything at all, so a serve request can omit the options
 *  entirely and keep whatever the model was last tuned with. */
export function hasAnyOption(o: LaunchOptions): boolean {
  return (
    o.contextSize != null ||
    o.kvCacheType != null ||
    o.cacheReuse != null ||
    o.speculative != null ||
    !!o.draftModel ||
    o.extraArgs.length > 0
  );
}

/** The launch overrides to actually send for `supported` — every other field cleared.
 *
 *  The form keeps its state across an engine change, so a value typed under one engine
 *  would otherwise still be transmitted after switching to one that has no equivalent,
 *  and the backend would (correctly) reject a field the operator can no longer see or
 *  clear. Returns null when nothing survives, which the callers use to omit `options`
 *  entirely so a plain re-serve keeps whatever the model was last tuned with. */
export function optionsForEngine(
  options: LaunchOptions,
  supported: LaunchOptionField[],
): LaunchOptions | null {
  const scoped: LaunchOptions = {
    contextSize: supported.includes("contextSize") ? options.contextSize : null,
    kvCacheType: supported.includes("kvCacheType") ? options.kvCacheType : null,
    cacheReuse: supported.includes("cacheReuse") ? options.cacheReuse : null,
    speculative: supported.includes("speculative") ? options.speculative : null,
    draftModel: supported.includes("draftModel") ? options.draftModel : null,
    extraArgs: options.extraArgs,
  };
  return hasAnyOption(scoped) ? scoped : null;
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

/** A `PathInput`'s BROWSE handler, or `undefined` when this host has no native
 *  chooser — the control hides itself and the typed field carries on working. The
 *  availability probe is cheap and answers once per mount. */
export function usePathPicker(): Accessor<PathPicker | undefined> {
  const [availability] = createResource(fetchPickerAvailability);
  return () => {
    if (!availability.latest?.available) return undefined;
    return async (opts) => {
      try {
        return await pickPath(opts);
      } catch (err) {
        // A chooser that can't open (a macOS host with no GUI session advertises
        // osascript but can't show a dialog) has to say so — a BROWSE button that
        // silently does nothing is worse than not offering one.
        toast.error(
          (err as { detail?: string })?.detail ??
            "Couldn't open a file chooser — type the path instead",
        );
        return null;
      }
    };
  };
}

/** What `PathInput` calls: open a chooser and resolve to a path (or null when the
 *  operator cancelled). */
export type PathPicker = (opts: {
  mode: "file" | "directory";
  title?: string;
  extensions?: string[] | null;
}) => Promise<string | null>;

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

/** Carry forward the previous object for any row that came back unchanged.
 *
 *  Solid's `<For>` reconciles by reference, so a poll that replaces every object tears
 *  down and rebuilds every row — wiping whatever local UI state they hold (an open
 *  disclosure, a half-typed argument) once a second while a *different* model downloads.
 *  Reusing the unchanged objects keeps those rows mounted. Presentation stability only:
 *  the backend's list is still the whole truth, and a row that actually changed is
 *  replaced. A structural compare is fine at this size — a handful of small records. */
function preserveIdentity(
  prev: ManagedModel[],
  next: ManagedModel[],
): ManagedModel[] {
  const byId = new Map(prev.map((m) => [m.id, m]));
  return next.map((m) => {
    const old = byId.get(m.id);
    return old && JSON.stringify(old) === JSON.stringify(m) ? old : m;
  });
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
      setModels((prev) => preserveIdentity(prev, next));
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
