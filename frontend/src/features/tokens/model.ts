/** API tokens feature data contracts. */

export type TokenScope =
  | "chat"
  | "memory"
  | "rag"
  | "tools"
  | "admin"
  | "read-only";

export interface ApiToken {
  id: string;
  label: string;
  /** Visible prefix e.g. "ody_k3m…" */
  prefix: string;
  scopes: TokenScope[];
  createdAt: string;
  lastUsedAt?: string;
  revoked: boolean;
}

export const ALL_SCOPES: TokenScope[] = [
  "chat",
  "memory",
  "rag",
  "tools",
  "admin",
  "read-only",
];
