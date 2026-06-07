/** Model Comparison feature data contracts. SEAM: screens depend on these
 *  types, mocks.ts implements them now, Phase 2 fetchers return the same shapes. */

export type CompareSlot = "A" | "B" | "C";

export interface CompareCandidate {
  slot: CompareSlot;
  /** Human-readable model identifier (hidden until reveal). */
  model: string;
  /** Response text (built up during streaming). */
  response: string;
  /** True while tokens are streaming in. */
  streaming: boolean;
}

export interface CompareRun {
  id: string;
  prompt: string;
  candidates: CompareCandidate[];
  /** True after the user has voted and identities are shown. */
  revealed: boolean;
  /** The slot the user voted for. */
  winner?: CompareSlot;
}

export interface LeaderboardEntry {
  model: string;
  wins: number;
  losses: number;
  total: number;
  winRate: number;
}
