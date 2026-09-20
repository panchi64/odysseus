/**
 * A thread's sub-agents — the cards, and the transcript behind one.
 *
 * Two reads, and only one of them is about sub-agents at all. The list is this feature's
 * own; a sub-agent's transcript is just a conversation's messages, fetched with the same
 * function the main room uses, because a sub-agent *is* a conversation. Its live tail,
 * its approval and its cancel are run routes for the same reason.
 *
 * **A read that failed is not a thread with no sub-agents**, and the difference is the
 * whole reason this returns a result rather than a list. A deployment with the feature
 * switched off genuinely has none, and neither that nor a thread that has never launched
 * one is worth a broken surface. But one dropped request is not evidence of either — read
 * as "none" it would empty a panel of working sub-agents in front of the operator, and
 * stop the poll that would have corrected it, since nothing left in the list is live.
 */

import { api } from "~/lib/api";
import type { TaskItem } from "~/lib/stream/events";

/** One sub-agent, as the panel shows it. */
export interface Subagent {
  id: string;
  /** Its own thread — where the transcript is read from. */
  conversationId: string;
  /** Its run — the live tail, the approval, and cancelling. */
  runId: string;
  /** The name the launching agent gave *this* sub-agent — `helper-function-finder`
   *  rather than `explorer`. It is what the model addresses it by, and what the operator
   *  reads on the card: a thread with three explorers out has three cards that are
   *  otherwise identical. */
  handle: string;
  /** Which sub-agent off the roster this is — built-in or project-declared. */
  name: string;
  task: string;
  /** The task list it is keeping for itself. Rides the card rather than being fetched
   *  per sub-agent: this list is already re-read while anything is live, and a thread
   *  with four sub-agents out would otherwise open four more polls to say the same
   *  thing. Empty for one that has not written a list. */
  tasks: TaskItem[];
  status: SubagentStatus;
  /** Its report once it has one; while it runs, its latest answer instead.
   *
   *  **The prose alone** — the backend strips the machine-readable block out before
   *  serving it, so a card cannot end in forty lines of JSON. That block arrives beside
   *  it as `findings`. */
  summary: string | null;
  /** The same report as data, when the sub-agent emitted a findings block and it
   *  parsed. `null` for one that did not, which is the ordinary case for every
   *  sub-agent whose brief does not ask for one — and is why nothing may treat its
   *  absence as a failed report. */
  findings: SubagentFindings | null;
  error: string | null;
  contextUsed: number | null;
  contextWindow: number | null;
  startedAt: string;
  endedAt: string | null;
}

/**
 * A sub-agent's report, read as data rather than as prose.
 *
 * A **mirror** of `services/subagents/report.ReportStructure`, and mirrored rather than
 * inferred for the same reason the citation shape is: the vocabulary here — what counts
 * as a conflict, how deep a topic was covered, how confident a finding is — belongs to
 * the backend that asked the sub-agent for it. The frontend renders these words and
 * coins none of them.
 *
 * **Every list may be empty, and an empty one is an answer.** A sub-agent that found
 * nothing, hit no contradiction and covered one topic is reporting honestly. Nothing
 * here may read an empty list as a failure.
 *
 * **This is a shape, not attribution.** A finding names the sources it rests on; it
 * does not link a sentence of the answer to a sentence of a source. Claim-level
 * attribution is an open design question, and nothing in this file has pre-empted it.
 */
export interface SubagentFindings {
  findings: Finding[];
  conflicts: Conflict[];
  coverage: TopicCoverage[];
  /** Questions the sub-agent could not settle, in its own words. */
  unresolved: string[];
}

/** Where a sub-agent read something — the same web/corpus split `Citation` carries,
 *  so a report naming its sources and the run stream naming them are talking about the
 *  same things. */
export interface ReportSource {
  url: string | null;
  /** The locator within a corpus source, for a passage out of the operator's own
   *  knowledge base — which has no address to open. */
  ref: string | null;
  title: string | null;
}

/** One thing the sub-agent established, and what it rests on. `sources` is what makes
 *  it a finding rather than an assertion. */
export interface Finding {
  statement: string;
  confidence: Confidence;
  sources: ReportSource[];
  /** Matched by name against `TopicCoverage.topic`. Free text — the topics are the
   *  launching agent's own words. `null` for a finding filed under none. */
  topic: string | null;
}

export type Confidence = "high" | "medium" | "low";

/** A question the sources answer differently, kept rather than synthesized away: a
 *  summary that picks a side silently is indistinguishable from sources that agreed. */
export interface Conflict {
  question: string;
  positions: ConflictPosition[];
  /** Which side the sub-agent finds more credible, and why. It may take a side — the
   *  point is that the taking is visible. */
  assessment: string | null;
}

export interface ConflictPosition {
  claim: string;
  sources: ReportSource[];
}

/** How far the investigation actually got on one topic. */
export interface TopicCoverage {
  topic: string;
  depth: Depth;
  sourceCount: number;
  /** What is missing, in the sub-agent's own words. */
  gaps: string[];
}

/** `none` is a real answer and the most useful row a coverage map can carry — a topic
 *  nobody reached is exactly what one exists to show. */
export type Depth = "none" | "thin" | "adequate" | "deep";

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
  handle: string;
  name: string;
  task: string;
  tasks: TaskItem[];
  status: SubagentStatus;
  summary: string | null;
  findings: FindingsDTO | null;
  error: string | null;
  context_used: number | null;
  context_window: number | null;
  started_at: string;
  ended_at: string | null;
}

/** The report block on the wire. One field differs in case (`source_count`), which is
 *  the whole reason this is mapped rather than passed through. */
interface FindingsDTO {
  findings?: Finding[];
  conflicts?: Conflict[];
  coverage?: {
    topic: string;
    depth: Depth;
    source_count?: number;
    gaps?: string[];
  }[];
  unresolved?: string[];
}

/** **Defensive about every list**, because the block's author is a model writing JSON
 *  by hand at the end of a long task and the backend parses it leniently on purpose: a
 *  field it omitted arrives absent rather than empty. A surface that has to guard each
 *  read would eventually forget one. */
function toFindings(dto: FindingsDTO): SubagentFindings {
  return {
    findings: (dto.findings ?? []).map((f) => ({
      ...f,
      sources: f.sources ?? [],
    })),
    conflicts: (dto.conflicts ?? []).map((c) => ({
      ...c,
      positions: (c.positions ?? []).map((p) => ({
        ...p,
        sources: p.sources ?? [],
      })),
    })),
    coverage: (dto.coverage ?? []).map((c) => ({
      topic: c.topic,
      depth: c.depth,
      sourceCount: c.source_count ?? 0,
      gaps: c.gaps ?? [],
    })),
    unresolved: dto.unresolved ?? [],
  };
}

function toSubagent(dto: SubagentDTO): Subagent {
  return {
    id: dto.id,
    conversationId: dto.conversation_id,
    runId: dto.run_id,
    // `?? dto.name` for a row written before handles existed — its migration backfilled
    // the spec name, and a card with no title is worse than one naming the roster twice.
    handle: dto.handle || dto.name,
    name: dto.name,
    task: dto.task,
    tasks: dto.tasks ?? [],
    status: dto.status,
    summary: dto.summary,
    findings: dto.findings ? toFindings(dto.findings) : null,
    error: dto.error,
    contextUsed: dto.context_used,
    contextWindow: dto.context_window,
    startedAt: dto.started_at,
    endedAt: dto.ended_at,
  };
}

/** One read of the list. `ok` is false when it could not be read at all, which is a
 *  different fact from an empty list and has to stay one — see the note at the top. */
export interface SubagentsRead {
  subagents: Subagent[];
  ok: boolean;
}

/** Every sub-agent this thread has launched, newest first. */
export async function fetchSubagents(
  conversationId: string,
): Promise<SubagentsRead> {
  try {
    const res = await api.get<{ subagents: SubagentDTO[] }>(
      `/conversations/${conversationId}/subagents`,
    );
    return { subagents: res.subagents.map(toSubagent), ok: true };
  } catch (err) {
    console.warn("sub-agents unavailable", err);
    return { subagents: [], ok: false };
  }
}
