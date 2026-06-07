/** User management feature data contracts. */

export type UserStatus = "active" | "disabled";

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
  | "code";

export interface ManagedUser {
  id: string;
  name: string;
  isAdmin: boolean;
  lastActiveAt: string;
  privileges: Privilege[];
  status: UserStatus;
}

export const ALL_PRIVILEGES: Privilege[] = [
  "memory",
  "skills",
  "documents",
  "email",
  "calendar",
  "contacts",
  "rag",
  "uploads",
  "gallery",
  "code",
];
