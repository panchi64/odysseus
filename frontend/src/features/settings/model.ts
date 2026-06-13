/** Settings feature data contracts.
 *
 * The connected surface is model configuration: the backend's endpoint registry
 * (`/models/endpoints`) and the role→endpoint bindings (`/models/roles`), plus the
 * web-search provider registry (`/search/providers`). There is no
 * user-preferences/2FA/account model — Odysseus is single-operator. The endpoint
 * read shape (`ModelEndpoint`) is owned by `~/lib/stores/models`, shared with the
 * chat picker; this module holds the write/form and role contracts, and the
 * search-provider shapes (which only Settings reads — the agent reaches search
 * through its tool, not the frontend). */

/** Form values for creating/updating an endpoint. `apiKey` omitted = unchanged,
 *  `apiKey: ""` clears the key; `model: ""` clears the default model. */
export interface EndpointInput {
  name: string;
  baseUrl: string;
  model?: string;
  apiKey?: string;
  contextWindow: number | null;
  nativeTools: boolean;
  vision: boolean;
  thinking: boolean;
}

/** The named roles the agent resolves through ordered endpoint chains. `main`
 *  (chat) is chosen from the top-bar model picker, not bound here. */
export const MODEL_ROLES = ["main", "utility", "embedding"] as const;
export type ModelRole = (typeof MODEL_ROLES)[number];

/** Roles still bound in Settings — `main` is driven by the top-bar picker. */
export const BINDABLE_ROLES = ["utility", "embedding"] as const;

/** role → ordered endpoint ids (a FallbackModel chain). */
export type RoleBindings = Record<string, string[]>;

/* ── Web search providers ──────────────────────────────────────────────────── */

/** The operator's view of a configured search provider (a SearXNG instance). The
 *  agent's web search queries the first `enabled` one; the rest stay configured as
 *  alternates. The API key is write-only — only its presence is exposed. */
export interface SearchProvider {
  id: string;
  name: string;
  baseUrl: string;
  enabled: boolean;
  /** Optional SearXNG engine filter (e.g. ["google", "duckduckgo"]); [] ⇒ default. */
  engines: string[];
  /** Extra query params passed through verbatim (e.g. {"language": "en"}). */
  params: Record<string, unknown>;
  /** Whether a key is stored — the value is write-only and never returned. */
  hasApiKey: boolean;
}

/** Form values for creating/updating a provider. `apiKey` omitted = unchanged,
 *  `apiKey: ""` clears the key. */
export interface SearchProviderInput {
  name: string;
  baseUrl: string;
  enabled: boolean;
  engines: string[];
  params: Record<string, unknown>;
  apiKey?: string;
}
