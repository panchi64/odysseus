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

export type ModelSuitability = "nominal" | "warn" | "alert";

export interface ModelCapabilities {
  tools: boolean;
  vision: boolean;
  reasoning: boolean;
  embedding: boolean;
  imageGen: boolean;
}

export interface ModelEntry {
  id: string;
  name: string;
  params: string;
  quant: string;
  sizeBytes: number;
  suitability: ModelSuitability;
  downloaded: boolean;
  capabilities: ModelCapabilities;
  /** LMArena Chatbot Arena Elo (human-preference quality), null when unranked. */
  arenaElo: number | null;
  description: string;
}

export type ServerStatus = "running" | "stopped" | "starting" | "error";

export interface RunningServer {
  id: string;
  model: string;
  port: number;
  status: ServerStatus;
  tokensPerSec?: number;
  contextLen?: number;
}

export interface RemoteEndpoint {
  id: string;
  name: string;
  baseUrl: string;
  apiKeySet: boolean;
  status: "ok" | "error" | "untested";
  latencyMs?: number;
}
