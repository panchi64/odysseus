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
