import type { ApiToken } from "./model";

export const mockTokens: ApiToken[] = [
  {
    id: "tok-001",
    label: "Automation Scripts",
    prefix: "ody_k3mA…",
    scopes: ["chat", "memory", "rag"],
    createdAt: "2026-05-01T10:00:00Z",
    lastUsedAt: "2026-06-07T12:43:00Z",
    // Expires in ~3 days — should render warn flag
    expiresAt: "2026-06-10T10:00:00Z",
    revoked: false,
  },
  {
    id: "tok-002",
    label: "Research Pipeline",
    prefix: "ody_9fXz…",
    scopes: ["chat", "tools", "rag"],
    createdAt: "2026-05-15T08:30:00Z",
    lastUsedAt: "2026-06-06T22:10:00Z",
    expiresAt: "2026-09-12T08:30:00Z",
    revoked: false,
  },
  {
    id: "tok-003",
    label: "Read-only Monitor",
    prefix: "ody_rN2p…",
    scopes: ["read-only"],
    createdAt: "2026-04-20T14:00:00Z",
    lastUsedAt: undefined,
    expiresAt: undefined,
    revoked: false,
  },
  {
    id: "tok-004",
    label: "Old Dev Token",
    prefix: "ody_t7Yw…",
    scopes: ["chat", "admin"],
    createdAt: "2026-03-10T09:00:00Z",
    lastUsedAt: "2026-04-02T16:00:00Z",
    expiresAt: undefined,
    revoked: true,
  },
];
