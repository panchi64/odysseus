/**
 * A thread's sub-agents — the cards, and the transcript behind one.
 *
 * Two reads, and only one of them is about sub-agents at all. The list is this feature's
 * own; a sub-agent's transcript is just a conversation's messages, fetched with the same
 * function the main room uses, because a sub-agent *is* a conversation. Its live tail,
 * its approval and its cancel are run routes for the same reason.
 *
 * **The list degrades to empty rather than erroring.** A thread that has never launched
 * one is the ordinary case, and so is a deployment with the feature switched off — in
 * neither does the panel have anything to say, and neither is worth a broken surface.
 */

import { api } from "~/lib/api";

/** One sub-agent, as the panel shows it. */
export interface Subagent {
  id: string;
  /** Its own thread — where the transcript is read from. */
  conversationId: string;
  /** Its run — the live tail, the approval, and cancelling. */
  runId: string;
  name: string;
  task: string;
  status: SubagentStatus;
  /** Its report once it has one; while it runs, its latest answer instead. */
  summary: string | null;
  error: string | null;
  contextUsed: number | null;
  contextWindow: number | null;
  startedAt: string;
  endedAt: string | null;
}

/** `blocked` is waiting on the operator rather than on the machine, which is the one
 *  state worth putting in front of them. */
export type SubagentStatus =
  "running" | "blocked" | "done" | "failed" | "cancelled";

/** Still expected to report. Both count as live, and a blocked one sorts above the rest
 *  because it is the only one that is waiting on a person. */
export function isLive(subagent: Subagent): boolean {
  return subagent.status === "running" || subagent.status === "blocked";
}

interface SubagentDTO {
  id: string;
  conversation_id: string;
  run_id: string;
  name: string;
  task: string;
  status: SubagentStatus;
  summary: string | null;
  error: string | null;
  context_used: number | null;
  context_window: number | null;
  started_at: string;
  ended_at: string | null;
}

function toSubagent(dto: SubagentDTO): Subagent {
  return {
    id: dto.id,
    conversationId: dto.conversation_id,
    runId: dto.run_id,
    name: dto.name,
    task: dto.task,
    status: dto.status,
    summary: dto.summary,
    error: dto.error,
    contextUsed: dto.context_used,
    contextWindow: dto.context_window,
    startedAt: dto.started_at,
    endedAt: dto.ended_at,
  };
}

/** Every sub-agent this thread has launched, newest first. */
export async function fetchSubagents(
  conversationId: string,
): Promise<Subagent[]> {
  try {
    const res = await api.get<{ subagents: SubagentDTO[] }>(
      `/conversations/${conversationId}/subagents`,
    );
    return res.subagents.map(toSubagent);
  } catch (err) {
    console.warn("sub-agents unavailable", err);
    return [];
  }
}
