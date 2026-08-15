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
