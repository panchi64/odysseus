import type { DocumentDetail, DocumentSummary } from "./model";

export const mockDocuments: DocumentSummary[] = [
  {
    id: "doc-001",
    title: "Vector Index Migration Plan",
    snippet:
      "A zero-downtime approach to re-embedding 4k documents into a new Chroma collection using shadow indices and atomic pointer swaps.",
    updatedAt: "2026-06-07T14:02:00Z",
    words: 1840,
    status: "active",
  },
  {
    id: "doc-002",
    title: "SearXNG Tuning Notes",
    snippet:
      "Configuration notes for ranking, safe-search defaults, and custom bangs. Covers engine priority, timeout budgets, and result deduplication.",
    updatedAt: "2026-06-06T18:30:00Z",
    words: 620,
    status: "active",
  },
  {
    id: "doc-003",
    title: "Odysseus Security Model",
    snippet:
      "AuthManager, bcrypt, pyotp 2FA, per-user privileges, admin gating, and regression test coverage for the security layer.",
    updatedAt: "2026-06-05T09:12:00Z",
    words: 3200,
    status: "active",
  },
  {
    id: "doc-004",
    title: "Caddy TLS Reverse Proxy Setup",
    snippet:
      "Caddyfile snippet for terminating TLS in front of FastAPI on port 7000. Includes HTTP-to-HTTPS redirect and ACME auto-certs.",
    updatedAt: "2026-06-04T22:00:00Z",
    words: 310,
    status: "active",
  },
  {
    id: "doc-005",
    title: "Old API Design Draft",
    snippet:
      "Initial REST API design from the pre-FastAPI era. Archived after the pydantic-ai migration decision. Retained for historical reference.",
    updatedAt: "2026-05-20T11:00:00Z",
    words: 890,
    status: "archived",
  },
  {
    id: "doc-006",
    title: "Docker Compose Notes (Legacy)",
    snippet:
      "Legacy compose file documentation. Superseded by the updated stack with ChromaDB, SearXNG, and ntfy service definitions.",
    updatedAt: "2026-05-01T08:00:00Z",
    words: 450,
    status: "archived",
  },
];

export const mockDocumentDetail: DocumentDetail = {
  id: "doc-001",
  title: "Vector Index Migration Plan",
  snippet:
    "A zero-downtime approach to re-embedding 4k documents into a new Chroma collection using shadow indices and atomic pointer swaps.",
  updatedAt: "2026-06-07T14:02:00Z",
  words: 1840,
  status: "active",
  body: `# Vector Index Migration Plan

## Overview

This document outlines the procedure for migrating the personal_docs Chroma collection from all-MiniLM-L6-v2 (768 dims) to a higher-quality embedding model without interrupting live retrieval.

## Constraints

- The live collection must remain fully readable throughout migration.
- Embeddings from different models are not comparable — partial swaps corrupt ranking.
- Total collection size: ~4,200 documents, 312 MB.

## Migration Steps

### Phase 1 — Shadow Collection

1. Create \`personal_docs__next\` with the target model's dimension.
2. Stream all documents through the new embedding model in batches of 256.
3. Upsert by doc id (idempotent — safe to resume if interrupted).

### Phase 2 — Validation

1. Take a held-out query set (100 queries with known relevant docs).
2. Run recall@5 and NDCG against both collections.
3. Gate: \`personal_docs__next\` must meet or exceed baseline on all metrics.

### Phase 3 — Atomic Cutover

1. Repoint the read alias to \`personal_docs__next\`.
2. Monitor retrieval quality for 24h soak period.
3. Drop the old collection after soak.

## Estimated Runtime

~55 seconds compute at 82 docs/sec (MPS), plus ~10s Chroma overhead. Run off-peak.
`,
  versions: [
    {
      id: "v-3",
      label: "v3 — Added validation phase",
      author: "admin",
      createdAt: "2026-06-07T14:02:00Z",
      body: `# Vector Index Migration Plan\n\n## Overview\n\nThis document outlines the procedure for migrating the personal_docs Chroma collection from all-MiniLM-L6-v2 (768 dims) to a higher-quality embedding model without interrupting live retrieval.\n\n## Constraints\n\n- The live collection must remain fully readable throughout migration.\n- Embeddings from different models are not comparable — partial swaps corrupt ranking.\n- Total collection size: ~4,200 documents, 312 MB.\n\n## Migration Steps\n\n### Phase 1 — Shadow Collection\n\n1. Create \`personal_docs__next\` with the target model's dimension.\n2. Stream all documents through the new embedding model in batches of 256.\n3. Upsert by doc id (idempotent — safe to resume if interrupted).\n\n### Phase 2 — Validation\n\n1. Take a held-out query set (100 queries with known relevant docs).\n2. Run recall@5 and NDCG against both collections.\n3. Gate: \`personal_docs__next\` must meet or exceed baseline on all metrics.\n\n### Phase 3 — Atomic Cutover\n\n1. Repoint the read alias to \`personal_docs__next\`.\n2. Monitor retrieval quality for 24h soak period.\n3. Drop the old collection after soak.\n\n## Estimated Runtime\n\n~55 seconds compute at 82 docs/sec (MPS), plus ~10s Chroma overhead. Run off-peak.\n`,
    },
    {
      id: "v-2",
      label: "v2 — Expanded phase 1 detail",
      author: "admin",
      createdAt: "2026-06-07T11:15:00Z",
      body: `# Vector Index Migration Plan\n\n## Overview\n\nMigrating the personal_docs Chroma collection to a higher-quality embedding model.\n\n## Migration Steps\n\n### Phase 1 — Shadow Collection\n\n1. Create \`personal_docs__next\` with the target model's dimension.\n2. Stream all documents through the new embedding model in batches of 256.\n3. Upsert by doc id (idempotent — safe to resume if interrupted).\n\n### Phase 3 — Atomic Cutover\n\n1. Repoint the read alias to \`personal_docs__next\`.\n2. Monitor retrieval quality for 24h soak period.\n3. Drop the old collection after soak.\n`,
    },
    {
      id: "v-1",
      label: "v1 — Initial draft",
      author: "admin",
      createdAt: "2026-06-06T09:30:00Z",
      body: `# Vector Index Migration Plan\n\n## Overview\n\nMigrating the personal_docs Chroma collection to a higher-quality embedding model without interrupting live retrieval.\n\n## Steps\n\n1. Create shadow collection.\n2. Re-embed all documents.\n3. Cut over the read alias.\n`,
    },
  ],
};

/** Canned AI-generated suggestion text for mock streaming. */
export const mockAiSuggestion =
  "Consider adding a rollback procedure section: if validation fails, document the steps to drop the shadow collection and retry with adjusted batch size or different target model. This ensures the migration can be safely aborted at any phase.";
