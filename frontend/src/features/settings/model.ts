/** Settings feature data contracts.
 *
 * The connected surface is model configuration: the backend's endpoint registry
 * (`/models/endpoints`) and the role→endpoint bindings (`/models/roles`). There
 * is no user-preferences/2FA/account model — Odysseus is single-operator. The
 * endpoint read shape (`ModelEndpoint`) is owned by `~/lib/stores/models`, shared
 * with the chat picker; this module holds the write/form and role contracts. */

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
