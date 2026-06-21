/** Model Cookbook feature data contracts. */

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

/** A curated provider preset for the guided setup — display-only presentation
 *  config (no secrets, no policy). Prefills the endpoint form and carries a
 *  non-authoritative model hint the connect flow prefers discovery over. */
export interface ProviderPreset {
  id: string;
  name: string;
  /** OpenAI-compatible base URL prefilled into the form (operator-overridable). */
  baseUrl: string;
  /** Whether this provider needs an API key — drives the "needs a key" badge. */
  requiresKey: boolean;
  /** Where the operator gets a key (or, for local, sets the server up). */
  docsUrl: string;
  /** Capability defaults seeded into the new endpoint (operator-overridable). */
  nativeTools: boolean;
  vision: boolean;
  thinking: boolean;
  /** A conservative starting-model hint — only a fallback; the connect flow
   *  prefers the provider's real discovered list so stale names self-heal. */
  suggestedModel?: string;
}

/** What the guided "Connect & use this" button captures: the chosen preset and
 *  the (optional) key the operator pasted. Everything else comes from the preset. */
export interface GuidedConnectInput {
  preset: ProviderPreset;
  /** The pasted key — empty when the preset needs none (e.g. a local server). */
  apiKey: string;
}

// --- Local model serving (LOCAL MODELS tab) --------------------------------

/** A local inference engine Odysseus can serve models with. */
export type EngineKind = "llama.cpp" | "mlx";

/** What a model is served for. */
export type Workload = "chat" | "embedding" | "vision";

/** Lifecycle state of a managed (downloaded/served) model. */
export type ServeState =
  | "stopped"
  | "downloading"
  | "starting"
  | "running"
  | "error";

/** A curated catalog model the host can run on a given engine — display-only. */
export interface CatalogEntry {
  /** Hugging Face repo id (the durable identity). */
  repo: string;
  /** Human label for the row. */
  label: string;
  engine: EngineKind;
  workload: Workload;
  /** Parameter count, display-formatted (e.g. "8B"), or null when unknown. */
  params: string | null;
  /** Quantization tag (e.g. "Q4_K_M"), or null. */
  quant: string | null;
  /** Approximate on-disk size in bytes, or null when unknown. */
  approxBytes: number | null;
  /** Whether the model supports native tool-calling. */
  nativeTools: boolean;
  /** Maximum context window in tokens, or null when unknown. */
  contextWindow: number | null;
  /** Short operator-facing note, or null. */
  notes: string | null;
}

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
  /** A small curated set of models to run on this engine. */
  recommendedModels: CatalogEntry[];
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

/** A model Odysseus is managing (downloaded and/or served). */
export interface ManagedModel {
  id: string;
  engine: EngineKind;
  workload: Workload;
  /** Hugging Face repo id. */
  hfRepo: string;
  quant: string | null;
  state: ServeState;
  /** The endpoint this model is served through, when running. */
  endpointId: string | null;
  endpointName: string | null;
  port: number | null;
  /** The last error string when `state === "error"`. */
  lastError: string | null;
  /** Live download progress, present while `state === "downloading"`. */
  progress: DownloadProgress | null;
}
