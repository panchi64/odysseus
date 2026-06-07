/** Chat feature data contracts. This is the SEAM: screens depend on these
 *  types, mocks.ts implements them now, and Phase 2 fetchers will return the
 *  same shapes — so no screen changes when real data lands. */

export type Role = "user" | "assistant";

export type ToolStatus = "running" | "ok" | "error";

export interface ToolInvocation {
  id: string;
  /** Namespaced tool name, e.g. "web.search". */
  name: string;
  /** Human-readable argument summary. */
  args: string;
  status: ToolStatus;
  /** Result preview shown when expanded. */
  result?: string;
  elapsedMs?: number;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  /** Separate reasoning/thinking stream, rendered apart from the answer. */
  reasoning?: string;
  tools?: ToolInvocation[];
  /** True while tokens are still streaming in. */
  streaming?: boolean;
  createdAt: string;
  /** Model that produced an assistant message. */
  model?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  model: string;
  messages: ChatMessage[];
}

export interface ChatSummary {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
}
