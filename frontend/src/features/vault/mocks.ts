import type { VaultEntry } from "./model";

export const mockVaultEntries: VaultEntry[] = [
  {
    id: "v-001",
    name: "Production Database",
    username: "db_admin",
    url: "postgresql://prod.internal:5432",
    password: "P@ssw0rd#Prod2026!",
  },
  {
    id: "v-002",
    name: "SearXNG Instance",
    username: "searxng_op",
    url: "https://search.internal",
    password: "searxNG_secret_k3y",
  },
  {
    id: "v-003",
    name: "ChromaDB API",
    username: "chroma_svc",
    url: "http://chroma.internal:8000",
    password: "chroma_t0k3n_2026",
  },
  {
    id: "v-004",
    name: "Admin Email Account",
    username: "admin@workspace.local",
    url: "https://mail.workspace.local",
    password: "Adm1n_M@il_S3cur3",
  },
];
