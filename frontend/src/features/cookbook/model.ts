/** Model Cookbook feature data contracts. The wire-level unions
 *  (`EngineKind`/`Workload`/`ServeState`) live in `~/lib/api/models-types`. */

import type { EngineKind, ServeState, Workload } from "~/lib/api/models-types";
import type { ModelProvider } from "~/lib/stores/models";

export interface RuntimeInfo {
  /** Serving runtime name (e.g. "ollama", "llama.cpp", "mlx-lm"). */
  name: string;
  /** Detected version, or null when present but unparsable. */
  version: string | null;
}

export interface HardwareInfo {
  chip: string;
  ram: string;
  vram: string;
  cores: string;
  /** Primary compute backend, display-formatted (e.g. "Metal / MPS", "CUDA"). */
  backend: string;
  /** Serving runtimes detected on PATH (only the available ones). */
  runtimes: RuntimeInfo[];
}

/** What the guided "Connect & use this" button captures: the chosen provider
 *  preset (served by `GET /models/providers`), the base URL (the preset's default,
 *  or typed when the provider has none), and the (optional) pasted key. */
export interface GuidedConnectInput {
  provider: ModelProvider;
  baseUrl: string;
  /** The pasted key — empty when the provider needs none (e.g. a local server). */
  apiKey: string;
}

// --- Local model serving (LOCAL MODELS tab) --------------------------------

/** A ranked engine recommendation for the current host. */
export interface EngineRecommendation {
  engine: EngineKind;
  /** 1-based rank; rank 1 leads. */
  rank: number;
  /** Whether the engine can run on this host right now. */
  available: boolean;
  /** Whether the engine runtime is already present (no first-serve download).
   *  `available && !installed` means it's fetched on first serve. */
  installed: boolean;
  /** Why this engine is (or isn't) recommended. */
  reason: string;
  /** The workloads this engine covers on this host. */
  workloads: Workload[];
  /** The `LaunchOptions` fields this engine can translate into its own flags — the
   *  tuning form renders these and nothing else, so it offers only what will reach
   *  a process. The backend is the authority on which those are. */
  supportedOptions: LaunchOptionField[];
}

/** Live download progress for a managed model — mirrors the backend's HF download
 *  stream. `fraction` is 0..1 (not a percent); `totalBytes`/`fraction` are null
 *  until the backend knows the size, which is when a determinate bar can show. */
export interface DownloadProgress {
  /** Bytes downloaded so far. */
  downloadedBytes: number;
  /** Total bytes to download, or null when unknown. */
  totalBytes: number | null;
  /** Completion fraction in 0..1, or null when unknown. */
  fraction: number | null;
  /** The file currently downloading, or null. */
  file: string | null;
}

/** KV cache precision. `f16` is the engine default — each engine spells it in its
 *  own flags (a dtype for llama.cpp, a bit width for mlx-vlm). */
export type KvCacheType = "f16" | "q8_0" | "q4_0";

/** The tunable fields, by name — what an engine reports in `supportedOptions`. */
export type LaunchOptionField =
  "contextSize" | "kvCacheType" | "cacheReuse" | "speculative" | "draftModel";

/** Whether to draft tokens ahead with the model's own multi-token-prediction head.
 *  `auto` enables it exactly when the weights actually carry it — MTP is a training-time
 *  property, so no flag can add it to a model that lacks it. */
export type SpeculativeMode = "auto" | "off";

/** Per-model engine launch overrides, in engine-neutral terms — the backend's
 *  adapter translates each into its own flags. Every field unset means the engine's
 *  own default stands: the engine already auto-sizes slots, GPU layers and batching,
 *  so an unset field must stay unset rather than being filled with a guess. */
export interface LaunchOptions {
  /** The context window the server should hold, or null for the model's own. */
  contextSize: number | null;
  kvCacheType: KvCacheType | null;
  cacheReuse: number | null;
  /** Draft-token decoding. Null means `auto`. */
  speculative: SpeculativeMode | null;
  /** An explicit drafter — a local path or a Hugging Face repo id. MLX needs one (its
   *  conversion splits the MTP head into a companion `…-MTP-<quant>` repo); llama.cpp
   *  only needs it for a separate draft *model*, since its MTP heads ride in the GGUF. */
  draftModel: string | null;
  /** Passed to the engine verbatim, and an override: naming a flag one of the fields
   *  above would emit replaces it rather than duplicating it. Unsupported by design. */
  extraArgs: string[];
}

/** What a `starting` model is doing. Both steps run for minutes on a real host, so
 *  the state flag alone would read as a stall. */
export type ServeStage = "installing_engine" | "loading_model";

export interface ServeStageInfo {
  stage: ServeStage;
  /** ISO timestamp the step began — the UI derives elapsed from it. */
  startedAt: string;
  /** When this step gives up, in seconds, or null when unbounded. */
  timeoutS: number | null;
}

/** Where a managed model's weights came from. `local` weights belong to the operator
 *  and live wherever they put them — read where they are, never moved or deleted. */
export type ModelSource = "huggingface" | "local";

/** A model Odysseus is managing (downloaded and/or served). */
export interface ManagedModel {
  id: string;
  engine: EngineKind;
  workload: Workload;
  /** Hugging Face repo id, or the display name of an imported local model. */
  hfRepo: string;
  quant: string | null;
  state: ServeState;
  source: ModelSource;
  /** Where the weights live on disk, once known. */
  artifactPath: string | null;
  /** The endpoint this model is served through, when running. */
  endpointId: string | null;
  endpointName: string | null;
  port: number | null;
  /** The last error string when `state === "error"`. */
  lastError: string | null;
  /** Live download progress, present while `state === "downloading"`. */
  progress: DownloadProgress | null;
  /** What's happening now, present while `state === "starting"`. */
  stage: ServeStageInfo | null;
  /** What draft-token capability the downloaded weights actually carry, phrased for
   *  the operator — null when they carry none. Read from the weights, not the config. */
  speculative: string | null;
  /** The launch overrides this model is served with. */
  options: LaunchOptions;
}

/** Whether this host can open a native file/folder dialog. The typed path field
 *  works either way — this only decides whether a BROWSE control is offered. */
export interface PickerAvailability {
  available: boolean;
  /** Why not, phrased for the operator, when unavailable. */
  reason: string | null;
}
