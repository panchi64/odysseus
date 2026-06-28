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
  /** Whether the endpoint is active. Omitted from the create/edit form (which
   *  defaults it on the backend); carried so the row toggle can PATCH it. */
  enabled?: boolean;
}

/** The named roles the agent resolves through ordered endpoint chains. `main`
 *  (chat) is chosen from the top-bar model picker, not bound here. */
export const MODEL_ROLES = ["main", "utility", "embedding"] as const;
export type ModelRole = (typeof MODEL_ROLES)[number];

/** Roles still bound in Settings — `main` is driven by the top-bar picker. */
export const BINDABLE_ROLES = ["utility", "embedding"] as const;

/** A role binding: the ordered endpoint chain (a FallbackModel chain) plus an
 *  optional pinned model. `model` is used by `embedding` (no per-conversation
 *  picker like `main`); `null` ⇒ the endpoint's own default model. */
export interface RoleBinding {
  endpointIds: string[];
  model: string | null;
}

/** role → its binding. */
export type RoleBindings = Record<string, RoleBinding>;

/** Progress of a background re-embed (after the embedding model changes). The
 *  vectors of every memory + chat message are re-embedded into the new model's
 *  space; until it finishes, semantic recall is partially degraded. */
export interface ReindexStatus {
  state: "idle" | "running" | "done" | "degraded" | "error";
  memories: number;
  messages: number;
  detail: string | null;
  completedAt: string | null;
}

/** The backend's authoritative read on whether semantic recall is healthy:
 *  `nominal` (hybrid recall) or `warn` (keyword-only — no/!ready embedder). */
export interface EmbeddingHealth {
  status: "nominal" | "warn" | "alert";
  detail: string;
}

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

/** Operator-tunable chat preferences. `attachmentInlineMaxTokens` is the token
 *  budget an attached file's text is retained inline for before it's cut off with a
 *  tool pointer (images are always retained, regardless). */
export interface ChatSettings {
  attachmentInlineMaxTokens: number;
}

/* ── Offline mode ──────────────────────────────────────────────────────────── */

/** The backend's read on offline mode (connectivity-aware web-container suspension).
 *  The backend owns every decision here — the frontend only renders this and relays
 *  the two switches back. `manualOffline` forces offline; `autoDetect` lets the
 *  connectivity monitor toggle it; `online` is the raw connectivity verdict; and
 *  `effectiveOffline` (= manual OR (auto AND NOT online)) is what's actually in
 *  effect — the web containers are down and the agent's web tools are hidden. */
export interface OfflineState {
  manualOffline: boolean;
  autoDetect: boolean;
  online: boolean;
  effectiveOffline: boolean;
}
