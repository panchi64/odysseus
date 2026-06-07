import type {
  HardwareInfo,
  ModelEntry,
  RunningServer,
  RemoteEndpoint,
} from "./model";

export const mockHardware: HardwareInfo = {
  chip: "Apple M2 Ultra",
  ram: "128 GB",
  vram: "96 GB",
  cores: "24C / 76GPU",
};

export const mockModels: ModelEntry[] = [
  {
    id: "qwen2.5-32b-q4",
    name: "Qwen 2.5 32B",
    params: "32B",
    quant: "Q4_K_M",
    sizeBytes: 21_474_836_480,
    suitability: "nominal",
    recommended: true,
    downloaded: true,
    description: "Best balance of quality and speed for this hardware.",
  },
  {
    id: "qwen2.5-coder-32b-q4",
    name: "Qwen 2.5 Coder 32B",
    params: "32B",
    quant: "Q4_K_M",
    sizeBytes: 21_474_836_480,
    suitability: "nominal",
    recommended: true,
    downloaded: true,
    description: "Specialized code model, strong on structured output.",
  },
  {
    id: "llama3.3-70b-q4",
    name: "Llama 3.3 70B",
    params: "70B",
    quant: "Q4_K_M",
    sizeBytes: 42_949_672_960,
    suitability: "warn",
    recommended: false,
    downloaded: false,
    description: "Fits with 4-bit quant but leaves little headroom.",
  },
  {
    id: "deepseek-r1-14b-q8",
    name: "DeepSeek R1 14B",
    params: "14B",
    quant: "Q8_0",
    sizeBytes: 15_032_385_536,
    suitability: "nominal",
    recommended: false,
    downloaded: false,
    description: "High-quality reasoning chain model.",
  },
  {
    id: "mistral-small-24b-q4",
    name: "Mistral Small 24B",
    params: "24B",
    quant: "Q4_K_M",
    sizeBytes: 16_106_127_360,
    suitability: "nominal",
    recommended: false,
    downloaded: false,
    description: "Fast inference, strong instruction following.",
  },
  {
    id: "command-r-plus-q3",
    name: "Command R+ 104B",
    params: "104B",
    quant: "Q3_K_S",
    sizeBytes: 46_179_488_030,
    suitability: "alert",
    recommended: false,
    downloaded: false,
    description: "Exceeds VRAM budget — not recommended.",
  },
];

export const mockServers: RunningServer[] = [
  {
    id: "srv-1",
    model: "qwen2.5-32b-q4",
    port: 11434,
    status: "running",
    tokensPerSec: 82.4,
    contextLen: 32768,
  },
  {
    id: "srv-2",
    model: "qwen2.5-coder-32b-q4",
    port: 11435,
    status: "stopped",
  },
];

export const mockRemoteEndpoints: RemoteEndpoint[] = [
  {
    id: "re-1",
    name: "Anthropic API",
    baseUrl: "https://api.anthropic.com",
    apiKeySet: true,
    status: "ok",
    latencyMs: 240,
  },
  {
    id: "re-2",
    name: "OpenRouter",
    baseUrl: "https://openrouter.ai/api",
    apiKeySet: false,
    status: "untested",
  },
];
