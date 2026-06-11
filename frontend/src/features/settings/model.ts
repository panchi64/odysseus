/** Settings feature data contracts.
 *
 * The connected surface is model configuration: the backend's endpoint registry
 * (`/models/endpoints`) and the role→endpoint bindings (`/models/roles`). There
 * is no user-preferences/2FA/account model — Odysseus is single-operator. */

export interface ModelEndpoint {
  id: string;
  name: string;
  baseUrl: string;
  model: string;
  /** Whether a key is stored — the value is write-only and never returned. */
  hasApiKey: boolean;
  contextWindow: number | null;
  nativeTools: boolean;
  vision: boolean;
  thinking: boolean;
}

/** Form values for creating/updating an endpoint. `apiKey` omitted = unchanged;
 *  "" = clear. */
export interface EndpointInput {
  name: string;
  baseUrl: string;
  model: string;
  apiKey?: string;
  contextWindow: number | null;
  nativeTools: boolean;
  vision: boolean;
  thinking: boolean;
}

/** The named roles the agent resolves through ordered endpoint chains. */
export const MODEL_ROLES = ["main", "utility", "embedding"] as const;
export type ModelRole = (typeof MODEL_ROLES)[number];

/** role → ordered endpoint ids (a FallbackModel chain). */
export type RoleBindings = Record<string, string[]>;
