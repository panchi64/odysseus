/** Model Cookbook feature data contracts. */

export interface HardwareInfo {
  chip: string;
  ram: string;
  vram: string;
  cores: string;
}

export type ModelSuitability = "nominal" | "warn" | "alert";

export interface ModelEntry {
  id: string;
  name: string;
  params: string;
  quant: string;
  sizeBytes: number;
  suitability: ModelSuitability;
  recommended: boolean;
  downloaded: boolean;
  description: string;
}

export type ServerStatus = "running" | "stopped" | "starting";

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
