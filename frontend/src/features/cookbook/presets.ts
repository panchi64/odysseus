/** Curated provider presets for the guided "it just works" setup.
 *
 * This is **display-only presentation config** — no secrets, no policy. Each
 * preset prefills the endpoint form (name + base URL + capability defaults) and
 * carries a *hint* of which model to start with. The hint is never authoritative:
 * the connect flow prefers the provider's live discovered list, so a stale
 * `suggestedModel` self-heals (see `connectAndSelectEndpoint` in `data.ts`).
 *
 * The backend is the single source of truth for what these connections can
 * actually do; these flags only seed the form the operator can override. */

import type { EndpointInput } from "~/features/settings/model";
import type { ProviderPreset } from "./model";

/** The OpenAI-compatible providers the guided setup offers, plus a generic
 *  local-server option. Order is the display order in the picker. */
export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "openai",
    name: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    requiresKey: true,
    docsUrl: "https://platform.openai.com/api-keys",
    nativeTools: true,
    vision: true,
    thinking: false,
    suggestedModel: "gpt-4o",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    requiresKey: true,
    docsUrl: "https://openrouter.ai/keys",
    nativeTools: true,
    vision: true,
    thinking: false,
    suggestedModel: "anthropic/claude-3.5-sonnet",
  },
  {
    id: "groq",
    name: "Groq",
    baseUrl: "https://api.groq.com/openai/v1",
    requiresKey: true,
    docsUrl: "https://console.groq.com/keys",
    nativeTools: true,
    vision: false,
    thinking: false,
    suggestedModel: "llama-3.3-70b-versatile",
  },
  {
    id: "together",
    name: "Together",
    baseUrl: "https://api.together.xyz/v1",
    requiresKey: true,
    docsUrl: "https://api.together.xyz/settings/api-keys",
    nativeTools: true,
    vision: false,
    thinking: false,
    suggestedModel: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
  },
  {
    id: "local",
    name: "Local server (Ollama / LM Studio / vLLM)",
    baseUrl: "http://localhost:11434/v1",
    requiresKey: false,
    docsUrl: "https://ollama.com/download",
    nativeTools: true,
    vision: false,
    thinking: false,
  },
];

/** Look up a preset by id (the picker holds the id; the form needs the rest). */
export function presetById(id: string): ProviderPreset | undefined {
  return PROVIDER_PRESETS.find((p) => p.id === id);
}

/** The single preset→endpoint field mapping. Both the guided connect flow (which
 *  creates/updates the endpoint) and the simple form values derive from this, so
 *  the preset→endpoint shape is spelled out once. `apiKey` is left undefined when
 *  empty (the preset needs no key); the model is the preset's non-authoritative
 *  hint and `contextWindow` is unset (discovered/defaulted by the backend). */
export function presetToEndpointInput(
  preset: ProviderPreset,
  apiKey: string,
): EndpointInput {
  return {
    name: preset.name,
    baseUrl: preset.baseUrl,
    model: preset.suggestedModel,
    apiKey: apiKey || undefined,
    contextWindow: null,
    nativeTools: preset.nativeTools,
    vision: preset.vision,
    thinking: preset.thinking,
  };
}
