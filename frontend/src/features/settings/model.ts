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

import type { ReindexState } from "~/lib/api/models-types";

/** Form values for creating/updating an endpoint. `apiKey` omitted = unchanged,
 *  `apiKey: ""` clears the key; `model: ""` clears the default model. */
export interface EndpointInput {
  name: string;
  baseUrl: string;
  /** The provider adapter id (from `GET /models/providers`); omitted on create ⇒
   *  the backend's default ("openai-compatible"). */
  provider?: string;
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

/** Roles bound as ordered chains in Settings — `main` is single-endpoint and
 *  driven by the top-bar picker. The binding shape (`RoleBinding`/`RoleBindings`)
 *  is owned by `~/lib/stores/models`, shared with the picker. */
export const BINDABLE_ROLES = ["utility", "embedding"] as const;

/** Progress of a background re-embed (after the embedding model changes). The
 *  vectors of every memory + chat message are re-embedded into the new model's
 *  space; until it finishes, semantic recall is partially degraded. */
export interface ReindexStatus {
  state: ReindexState;
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
 *  tool pointer (images are always retained, regardless). The `compaction*` fields tune
 *  tool-result compaction — digesting oversized prior-turn tool outputs for the model
 *  (the operator always keeps the full output): whether it's on, how many of the newest
 *  results stay full, and the token floor below which a result is left untouched.
 *  The `autoCompact*` fields tune the other reduction — folding whole earlier *turns*
 *  into a utility-model summary once the context window fills: whether it's on, and how
 *  full the window must get first (`autoCompactThreshold` is a fraction of the window,
 *  the same 0–1 quantity the context meter reports; the UI presents it as a percentage).
 *  `agentRequestLimit` is how many model round-trips a single turn may spend before it
 *  stops — the ceiling a long tool-using turn actually runs out of. */
export interface ChatSettings {
  attachmentInlineMaxTokens: number;
  compactionEnabled: boolean;
  compactionKeepRecent: number;
  compactionMinTokens: number;
  autoCompactEnabled: boolean;
  autoCompactThreshold: number;
  agentRequestLimit: number;
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

/* ── Agent tools ───────────────────────────────────────────────────────────── */

/** One tool in the agent's catalog, as the backend reports it. The catalog is
 *  derived from the live toolset registry — the frontend never enumerates tools of
 *  its own. `name` is the namespaced `category_tool` name the agent is offered;
 *  `enabled: false` means the operator switched it off, and the backend then withholds
 *  it from every run (`AE-3.3`). Offline mode can withhold the web tools on top of
 *  this without changing `enabled` — that's the backend's call, not a second state
 *  the operator sets. */
export interface AgentTool {
  name: string;
  category: string;
  description: string;
  enabled: boolean;
}
