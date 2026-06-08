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
  /** ISO date string if token has an expiry; undefined = never expires. */
  expiresAt?: string;
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

/** Plain-English explanation of what each scope grants, for InfoHint. */
export const SCOPE_DESCRIPTIONS: Record<TokenScope, string> = {
  chat: "Send and receive chat messages and stream model responses.",
  memory:
    "Read and write the persistent memory store (saved facts and preferences).",
  rag: "Query and ingest documents in the retrieval (RAG) knowledge base.",
  tools: "Invoke agent tools, including shell, Python, and other capabilities.",
  admin:
    "Full administrative control: settings, users, MCP, and serving. Grant sparingly.",
  "read-only": "View data only — no writes, no tool execution, no mutations.",
};

/** TTL options for the issue modal. */
export type ExpiryOption = "30d" | "90d" | "1y" | "never";

export const EXPIRY_OPTIONS: Array<{ value: ExpiryOption; label: string }> = [
  { value: "30d", label: "30 DAYS" },
  { value: "90d", label: "90 DAYS (RECOMMENDED)" },
  { value: "1y", label: "1 YEAR" },
  { value: "never", label: "NEVER (NOT RECOMMENDED)" },
];

/** Compute ISO expiry date from an ExpiryOption, or undefined for "never". */
export function computeExpiresAt(opt: ExpiryOption): string | undefined {
  const now = new Date();
  if (opt === "30d") {
    now.setDate(now.getDate() + 30);
    return now.toISOString();
  }
  if (opt === "90d") {
    now.setDate(now.getDate() + 90);
    return now.toISOString();
  }
  if (opt === "1y") {
    now.setFullYear(now.getFullYear() + 1);
    return now.toISOString();
  }
  return undefined;
}

/** Days remaining until expiry, or null if no expiry set. */
export function daysUntilExpiry(token: ApiToken): number | null {
  if (!token.expiresAt) return null;
  const ms = new Date(token.expiresAt).getTime() - Date.now();
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}
