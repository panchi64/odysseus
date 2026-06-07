/** Cross-cutting types shared across features. */

/** Access tiers from the security model (see docs/spec). */
export type PrivilegeTier = "open" | "user" | "admin";

/** Per-user privilege keys (gate individual features). Extend as features land. */
export type Privilege =
  | "memory"
  | "skills"
  | "documents"
  | "email"
  | "calendar"
  | "contacts"
  | "rag"
  | "uploads"
  | "gallery"
  | "signatures";

export type ID = string;

/** A loadable async value with explicit states (mirrors createResource). */
export type Loadable<T> =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; data: T };
