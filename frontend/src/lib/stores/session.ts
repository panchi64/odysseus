import { createSignal } from "solid-js";
import type { Privilege } from "../types";

/**
 * Session/auth store — STUB for Phase 1 (UI on mock data).
 *
 * Today it returns a fixed admin user so every surface is reachable for the
 * navigation walkthrough. Phase 2 replaces the internals with real auth (login,
 * 2FA, privileges from the backend) WITHOUT changing this public shape — guards
 * and screens read `useSession()` and never touch the implementation.
 *
 * To exercise privilege denial during review, flip `MOCK_IS_ADMIN` to false or
 * trim `MOCK_PRIVILEGES`.
 */
export interface CurrentUser {
  id: string;
  name: string;
  isAdmin: boolean;
  privileges: Privilege[];
}

const MOCK_IS_ADMIN = true;
const MOCK_PRIVILEGES: Privilege[] = [
  "memory",
  "skills",
  "documents",
  "email",
  "calendar",
  "contacts",
  "rag",
  "uploads",
  "gallery",
  "signatures",
];

const [user] = createSignal<CurrentUser | null>({
  id: "u-001",
  name: "OPERATOR",
  isAdmin: MOCK_IS_ADMIN,
  privileges: MOCK_PRIVILEGES,
});

export function useSession() {
  return {
    get user() {
      return user();
    },
    get isAuthenticated() {
      return user() !== null;
    },
    get isAdmin() {
      return user()?.isAdmin ?? false;
    },
    hasPrivilege(privilege: Privilege): boolean {
      return user()?.privileges.includes(privilege) ?? false;
    },
  };
}
