import type { ManagedUser } from "./model";

export const mockUsers: ManagedUser[] = [
  {
    id: "u-001",
    name: "OPERATOR",
    isAdmin: true,
    lastActiveAt: "2026-06-07T14:00:00Z",
    privileges: [
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
    ],
    status: "active",
  },
  {
    id: "u-002",
    name: "ANALYST",
    isAdmin: false,
    lastActiveAt: "2026-06-07T09:30:00Z",
    privileges: ["memory", "documents", "rag", "uploads"],
    status: "active",
  },
  {
    id: "u-003",
    name: "RESEARCHER",
    isAdmin: false,
    lastActiveAt: "2026-06-06T22:15:00Z",
    privileges: ["memory", "skills", "documents", "rag"],
    status: "active",
  },
  {
    id: "u-004",
    name: "ARCHIVIST",
    isAdmin: false,
    lastActiveAt: "2026-05-31T11:00:00Z",
    privileges: ["documents", "uploads", "gallery"],
    status: "disabled",
  },
];
