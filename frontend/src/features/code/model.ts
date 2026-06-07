/** Code Runner feature data contracts. */

export type CodeLanguage = "python" | "javascript" | "html";
export type RunStatus = "ok" | "error";

export interface CodeRun {
  id: string;
  language: CodeLanguage;
  source: string;
  output: string;
  status: RunStatus;
  durationMs: number;
  ranAt: string;
}
