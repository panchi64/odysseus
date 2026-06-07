import type { ChatSession, ChatSummary } from "./model";

export const mockSessions: ChatSummary[] = [
  {
    id: "s-014",
    title: "Vector index migration plan",
    updatedAt: "2026-06-07T13:58:00Z",
    messageCount: 18,
  },
  {
    id: "s-013",
    title: "SearXNG ranking tuning",
    updatedAt: "2026-06-07T11:20:00Z",
    messageCount: 9,
  },
  {
    id: "s-012",
    title: "Caddy TLS in front of FastAPI",
    updatedAt: "2026-06-06T22:04:00Z",
    messageCount: 24,
  },
  {
    id: "s-011",
    title: "Memory dedup audit results",
    updatedAt: "2026-06-06T16:41:00Z",
    messageCount: 6,
  },
];

export const mockSession: ChatSession = {
  id: "s-014",
  title: "Vector index migration plan",
  model: "qwen2.5-coder-32b",
  messages: [
    {
      id: "m-1",
      role: "user",
      content:
        "What's the safest way to migrate our Chroma collection to a new embedding model without losing retrieval?",
      createdAt: "2026-06-07T13:50:02Z",
    },
    {
      id: "m-2",
      role: "assistant",
      model: "qwen2.5-coder-32b",
      createdAt: "2026-06-07T13:50:05Z",
      reasoning:
        "The user wants zero-downtime re-embedding. Key constraint: embeddings from different models aren't comparable, so a partial swap corrupts ranking. Plan: build a shadow collection, backfill, then atomically switch the read pointer.",
      tools: [
        {
          id: "t-1",
          name: "rag.collection_stats",
          args: 'collection="personal_docs"',
          status: "ok",
          result:
            "documents=4214, dims=768, model=all-MiniLM-L6-v2, size=312MB",
          elapsedMs: 142,
        },
        {
          id: "t-2",
          name: "web.search",
          args: 'query="chroma re-embed collection zero downtime"',
          status: "ok",
          result:
            "6 sources ranked; top: chromadb docs on collection.upsert + alias swap",
          elapsedMs: 1180,
        },
        {
          id: "t-3",
          name: "memory.recall",
          args: 'query="chroma migration notes"',
          status: "error",
          error:
            "ChromaDB connection refused — service may be down (ECONNREFUSED 127.0.0.1:8000)",
          elapsedMs: 32,
        },
      ],
      content: `Migrate behind a **shadow collection** so the live index keeps serving reads the entire time.

## Procedure

1. Create \`personal_docs__next\` with the new model's dimensions.
2. Re-embed every document into it in batches — idempotent \`upsert\` keyed by doc id.
3. Validate recall on a held-out query set against **both** collections.
4. Atomically repoint the read alias to \`__next\`.
5. Drop the old collection after a soak period.

### Why a shadow collection

Embeddings from different models aren't comparable, so a partial swap corrupts ranking. Building the replacement out-of-band avoids any window where the two coexist behind one alias.

\`\`\`python
next = client.create_collection("personal_docs__next", metadata={"dims": 1024})
for batch in chunked(docs, 256):
    next.upsert(ids=ids(batch), documents=texts(batch))
client.set_alias("personal_docs", "personal_docs__next")
\`\`\`

> Run the backfill off-peak; the live collection never sees added load.`,
    },
    {
      id: "m-3",
      role: "user",
      content: "How long will the backfill take for ~4k docs?",
      createdAt: "2026-06-07T13:57:40Z",
    },
  ],
};

/** Canned assistant reply used by the mock streaming controller. */
export const mockStreamingReply = {
  reasoning:
    "Throughput is dominated by embedding model latency, not Chroma writes. At ~80 docs/sec on local MPS for a 768-dim model, 4,214 docs is under a minute of pure compute; batching upserts in groups of 256 keeps overhead low.",
  tools: [
    {
      name: "models.benchmark",
      args: 'model="bge-base-en", batch=256',
      result: "throughput=82 docs/s, p50=3.1s/batch",
      elapsedMs: 3100,
    },
  ],
  content: `For **~4,200 documents** at roughly 80 docs/sec, the backfill itself is about 50–55 seconds of compute, plus a few seconds of \`upsert\` overhead.

- **Compute:** ~52s (4214 ÷ 82 docs/s)
- **Upsert overhead:** ~6s at batch size 256
- **Total:** under two minutes end to end

Run it off-peak and the live collection never sees added load.`,
};
