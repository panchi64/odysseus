import type { RemoteEndpoint } from "./model";

// Hardware, recommendations, and running servers are now backend-sourced (see
// data.ts); only REMOTE ENDPOINTS remains a Phase-1 mock surface.
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
