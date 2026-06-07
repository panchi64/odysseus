import type { DedupCandidate, Memory } from "./model";

export const mockMemories: Memory[] = [
  {
    id: "mem-001",
    text: "User prefers concise, tabular responses with no fluff. Use bullet points or structured output over prose when summarizing.",
    type: "user",
    createdAt: "2026-06-07T13:58:00Z",
    pinned: true,
  },
  {
    id: "mem-002",
    text: "Odysseus runs on a 128GB Apple Silicon Mac. Local models preferred. Use MPS where possible.",
    type: "project",
    createdAt: "2026-06-07T12:00:00Z",
    pinned: true,
  },
  {
    id: "mem-003",
    text: "The pydantic-ai agent engine rebuild is deferred. Spec written at docs/spec/. Current priority is frontend feature screens.",
    type: "project",
    createdAt: "2026-06-07T10:30:00Z",
    pinned: false,
  },
  {
    id: "mem-004",
    text: "User found the streaming token-by-token rendering satisfying. Keep it for future reply affordances.",
    type: "feedback",
    createdAt: "2026-06-06T18:20:00Z",
    pinned: false,
  },
  {
    id: "mem-005",
    text: "bun is the preferred package manager for the frontend. uv is preferred for Python.",
    type: "reference",
    createdAt: "2026-06-06T09:00:00Z",
    pinned: false,
  },
  {
    id: "mem-006",
    text: "Git commit messages use past tense. E.g. 'Fixed bug', 'Added feature'.",
    type: "reference",
    createdAt: "2026-06-05T15:00:00Z",
    pinned: true,
  },
  {
    id: "mem-007",
    text: "User dislikes unnecessary back-and-forth. Ask clarifying questions only at genuine decision points.",
    type: "user",
    createdAt: "2026-06-05T11:00:00Z",
    pinned: false,
  },
  {
    id: "mem-008",
    text: "The Odysseus frontend uses vanilla ES modules, no build step. SolidJS SPA with SolidStart was adopted for the rebuild.",
    type: "project",
    createdAt: "2026-06-04T20:00:00Z",
    pinned: false,
  },
  {
    id: "mem-009",
    text: "Always run the linter before marking work as complete. Fix ALL lint errors, not just introduced ones.",
    type: "feedback",
    createdAt: "2026-06-04T16:00:00Z",
    pinned: false,
  },
  {
    id: "mem-010",
    text: "User prefers async Python handlers. core/exceptions.py defines the exception hierarchy.",
    type: "reference",
    createdAt: "2026-06-03T08:00:00Z",
    pinned: false,
  },
];

export const mockDedupCandidates: DedupCandidate[] = [
  {
    a: mockMemories[0],
    b: mockMemories[6],
    similarity: 0.91,
  },
  {
    a: mockMemories[4],
    b: mockMemories[8],
    similarity: 0.74,
  },
];
