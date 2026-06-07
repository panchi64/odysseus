/** Memory feature data contracts. */

export type MemoryType = "user" | "feedback" | "project" | "reference";

export interface Memory {
  id: string;
  text: string;
  type: MemoryType;
  createdAt: string;
  pinned: boolean;
}

export interface DedupCandidate {
  a: Memory;
  b: Memory;
  similarity: number;
}
