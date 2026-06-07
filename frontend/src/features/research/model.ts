/** Deep Research feature data contracts. SEAM: screens depend on these types,
 *  mocks.ts implements them now, Phase 2 fetchers return the same shapes. */

export type ResearchPhase =
  | "PLANNING"
  | "SEARCHING"
  | "READING"
  | "ANALYZING"
  | "WRITING"
  | "DONE";

export type ResearchStatus = "running" | "complete" | "archived" | "error";

export interface ResearchSource {
  title: string;
  url: string;
  domain: string;
  /** 0–1 normalised relevance score. */
  relevance: number;
}

export interface ResearchSection {
  heading: string;
  body: string;
}

export interface ResearchReport {
  id: string;
  title: string;
  query: string;
  status: ResearchStatus;
  rounds: number;
  sourceCount: number;
  findingCount: number;
  durationMs: number;
  createdAt: string;
  sections: ResearchSection[];
  sources: ResearchSource[];
}

export interface ResearchSummary {
  id: string;
  title: string;
  sourceCount: number;
  createdAt: string;
  status: ResearchStatus;
}

export interface ResearchRunState {
  phase: ResearchPhase;
  round: number;
  sourcesFound: number;
  findingsExtracted: number;
  /** 0–100 */
  progress: number;
  query: string;
}
