import type { ResearchReport, ResearchSummary } from "./model";

export const mockReportSummaries: ResearchSummary[] = [
  {
    id: "r-007",
    title: "Pydantic AI agent loop patterns for local model inference",
    sourceCount: 31,
    createdAt: "2026-06-07T09:14:00Z",
    status: "complete",
  },
  {
    id: "r-006",
    title: "ChromaDB vs Qdrant persistent vector store benchmarks",
    sourceCount: 24,
    createdAt: "2026-06-06T18:45:00Z",
    status: "complete",
  },
  {
    id: "r-005",
    title: "BGE-M3 multi-lingual embedding cross-lingual retrieval quality",
    sourceCount: 19,
    createdAt: "2026-06-06T11:22:00Z",
    status: "complete",
  },
  {
    id: "r-004",
    title: "SearXNG instance tuning for low-noise research queries",
    sourceCount: 14,
    createdAt: "2026-06-05T21:03:00Z",
    status: "archived",
  },
  {
    id: "r-003",
    title: "Apple Silicon MLX inference throughput scaling with batch size",
    sourceCount: 22,
    createdAt: "2026-06-04T15:30:00Z",
    status: "complete",
  },
  {
    id: "r-002",
    title: "Self-hosted RAG pipeline evaluation methodologies",
    sourceCount: 28,
    createdAt: "2026-06-03T08:17:00Z",
    status: "complete",
  },
  {
    id: "r-001",
    title: "FastAPI background task lifetime management patterns",
    sourceCount: 11,
    createdAt: "2026-06-01T20:55:00Z",
    status: "archived",
  },
];

export const mockReport: ResearchReport = {
  id: "r-007",
  title: "Pydantic AI agent loop patterns for local model inference",
  query:
    "What are the best patterns for building a Pydantic AI-based agent loop that works reliably with locally-hosted models via Ollama/LM Studio?",
  status: "complete",
  rounds: 4,
  sourceCount: 31,
  findingCount: 47,
  durationMs: 183400,
  createdAt: "2026-06-07T09:14:00Z",
  sections: [
    {
      heading: "EXECUTIVE SUMMARY",
      body: "Pydantic AI's agent loop is structurally compatible with local models via Ollama and LM Studio, but requires explicit accommodation for the quality ceiling imposed by sub-70B quantised models. The primary failure modes are: (1) unreliable structured-output adherence when tool schemas are large, (2) context-window exhaustion in multi-round loops, and (3) stochastic tool-call formatting under temperature >0.3. Mitigation strategies, detailed below, bring production-grade reliability within reach for models ≥ 32B.",
    },
    {
      heading: "TOOL SCHEMA COMPLEXITY",
      body: "Models below ~32B struggle with tool schemas that contain more than 8 fields per tool or more than 6 concurrent tool definitions. Empirical testing across qwen2.5-coder-32b, deepseek-r1-32b, and llama-3.3-70b shows adherence rates drop from 97% → 71% when schema field count exceeds 10. The recommended mitigation is schema splitting: expose separate lightweight tools for common paths and full schemas only on explicit escalation. Pydantic AI's `ToolDefinition` accepts a `strict` flag; setting strict=True with a simplified schema outperforms strict=False with a full one for sub-70B models.",
    },
    {
      heading: "CONTEXT WINDOW MANAGEMENT",
      body: "Multi-round agent loops accumulate tool results quickly. A 4-round research loop with 6 sources per round can exhaust a 32K context window before the WRITING phase if raw source text is retained. The recommended pattern is hierarchical summarisation: after each SEARCHING round, compress retrieved sources to a structured Finding record (title, domain, key_claim, relevance_score) before appending to context. This reduces per-round token cost from ~4,200 to ~180 tokens per source with negligible information loss on downstream synthesis tasks.",
    },
    {
      heading: "TEMPERATURE AND DETERMINISM",
      body: "Tool-call formatting reliability is highly sensitive to temperature. Testing at T=0.0, 0.1, 0.3, and 0.7 across 200 agent invocations shows that above T=0.3, the rate of malformed JSON tool calls increases non-linearly: T=0.0 → 0.4% failure, T=0.1 → 1.1%, T=0.3 → 3.8%, T=0.7 → 14.2%. For agent loops where tool use is mandatory, T≤0.1 is recommended. A separate generation pass at higher temperature for the final synthesis step can recover stylistic diversity without compromising the loop's structural reliability.",
    },
    {
      heading: "RETRY AND FALLBACK STRATEGY",
      body: "Pydantic AI's built-in `max_retries` applies per tool call. For local models, setting max_retries=3 with exponential backoff (base 500ms) covers the majority of transient formatting failures. A more robust pattern adds a model-level fallback: maintain a primary (fast/small) and secondary (slow/large) model handle; on structured output failure after retries, escalate to the secondary. This two-model pattern is particularly effective for the WRITING phase where output quality matters most.",
    },
    {
      heading: "STREAMING CONSIDERATIONS",
      body: "LM Studio's OpenAI-compatible streaming endpoint behaves differently from Ollama's native stream for partial tool calls: LM Studio buffers tool call deltas until the closing brace is emitted, making partial-streaming displays for tool arguments unreliable. Odysseus's current streaming handler already accounts for this via a chunked-accumulation buffer in the SSE consumer. No changes needed for the research engine integration, but any new streaming consumers should be tested against both endpoints.",
    },
    {
      heading: "RECOMMENDED ARCHITECTURE",
      body: "Based on the above findings, the recommended Pydantic AI agent loop configuration for local inference is: (1) 32B+ quantised model as primary, 70B as fallback; (2) simplified tool schemas (≤6 fields, ≤4 tools in context simultaneously); (3) T=0.05 for tool-use phases, T=0.4 for synthesis; (4) hierarchical source compression between rounds; (5) max_retries=3 with 500ms/1000ms/2000ms backoff; (6) explicit system prompt section listing available tools with one-line descriptions, which measurably improves zero-shot tool selection for models not fine-tuned on function calling.",
    },
  ],
  sources: [
    {
      title: "Pydantic AI Documentation — Tool Definition Reference",
      url: "https://ai.pydantic.dev/tools/",
      domain: "ai.pydantic.dev",
      relevance: 0.97,
    },
    {
      title: "Ollama OpenAI Compatibility Layer — Structured Output Support",
      url: "https://ollama.com/blog/openai-compatibility",
      domain: "ollama.com",
      relevance: 0.94,
    },
    {
      title: "Qwen2.5-Coder-32B Function Calling Benchmark Results",
      url: "https://qwenlm.github.io/blog/qwen2.5-coder/",
      domain: "qwenlm.github.io",
      relevance: 0.91,
    },
    {
      title: "LM Studio OpenAI Server — Tool Call Streaming Behaviour",
      url: "https://lmstudio.ai/docs/app/api/endpoints/openai",
      domain: "lmstudio.ai",
      relevance: 0.88,
    },
    {
      title: "Context Window Management in Multi-Turn Agent Loops",
      url: "https://www.anthropic.com/research/context-scaling",
      domain: "anthropic.com",
      relevance: 0.85,
    },
    {
      title: "DeepSeek-R1 Reasoning Model Tool Use Analysis",
      url: "https://github.com/deepseek-ai/DeepSeek-R1",
      domain: "github.com",
      relevance: 0.83,
    },
    {
      title: "Temperature Effects on Structured Output Reliability — Survey",
      url: "https://arxiv.org/abs/2402.18571",
      domain: "arxiv.org",
      relevance: 0.81,
    },
    {
      title: "Llama 3.3 70B Function Calling Fine-Tuning Details",
      url: "https://llama.meta.com/docs/model-cards-and-prompt-formats/llama3_3/",
      domain: "llama.meta.com",
      relevance: 0.79,
    },
    {
      title: "Hierarchical Summarisation for RAG Context Compression",
      url: "https://arxiv.org/abs/2404.10246",
      domain: "arxiv.org",
      relevance: 0.77,
    },
    {
      title: "Pydantic AI Agent Loop Retry Mechanics — Source",
      url: "https://github.com/pydantic/pydantic-ai/blob/main/pydantic_ai_slim/pydantic_ai/agent.py",
      domain: "github.com",
      relevance: 0.75,
    },
  ],
};
