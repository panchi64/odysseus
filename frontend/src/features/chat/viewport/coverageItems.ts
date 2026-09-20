/**
 * The shape of an investigation, folded out of the reports that have landed so far.
 *
 * A fan-out of researchers produces N reports, and the operator's questions are not "what
 * did each of them say" — that is the Agents panel, and it is a transcript each. The
 * questions are **how deep did this get, where are the holes, and where do the sources
 * disagree**, which are questions about the investigation rather than about any one
 * sub-agent. So the reports are merged by topic here, and the panel renders the merge.
 *
 * **Every number in here is provisional while anything is still out**, and that is the
 * fact the surface is most at risk of hiding. A coverage map assembled from two of four
 * reports looks exactly like a finished one; `arrival` is what stops it claiming to be,
 * and the panel leads with it rather than tucking it in a corner.
 *
 * **What "report-arrival state per topic" can honestly be.** A topic knows which
 * sub-agents have reported *on it*; it cannot know which of the ones still working will
 * turn out to cover it, because a sub-agent's topics arrive with its report. So a row
 * carries its reporters, and the band above carries who is still out. Inferring an
 * expected topic from an outstanding sub-agent's brief would be the frontend deciding
 * something, and the frontend decides nothing.
 *
 * **No claim-level attribution.** A finding names the sources it rests on, and that is
 * where the linkage stops. Nothing here ties a sentence of the launching agent's answer
 * to a sentence of a source; that is an open design question and this module has not
 * pre-empted it.
 */

import type {
  Conflict,
  Depth,
  Finding,
  ReportSource,
  Subagent,
} from "../data/subagents";
import { isLive } from "../data/subagents";

/** The ladder a merged topic keeps the top of. Mirrors `services/subagents/report.Depth`
 *  — which of two depths is the deeper is a fact about a vocabulary the backend owns. */
export const DEPTH_ORDER: Record<Depth, number> = {
  none: 0,
  thin: 1,
  adequate: 2,
  deep: 3,
};

/** One topic, as every report that touched it leaves it. */
export interface TopicRow {
  topic: string;
  /** **The deepest any reporter reached**, not an average. Two sub-agents on one topic
   *  is the case this exists for, and "one of them got deep into this" is the true
   *  statement about the investigation; averaging would report a thinner coverage than
   *  the thread actually has. */
  depth: Depth;
  /** Whether any report actually made a depth claim about this topic.
   *
   *  A topic can reach the map two ways — a coverage row, or a finding filed under a
   *  name no coverage row mentioned — and `depth` cannot tell them apart. `none` means
   *  "a sub-agent looked and got nowhere", which is a strong and useful claim; a topic
   *  that arrived only as a finding's label has made no claim at all, and printing
   *  `none` over it would put words in the report's mouth. */
  depthReported: boolean;
  /** Summed across reporters. Sources counted twice by two sub-agents are counted
   *  twice here — the reports name counts, not source lists, so there is nothing to
   *  deduplicate against and claiming otherwise would be worse than the overcount. */
  sourceCount: number;
  /** Every gap named, deduplicated on the exact words. */
  gaps: string[];
  /** The findings filed under this topic, across reports. */
  findings: Finding[];
  /** Which sub-agents reported on it — the per-topic arrival state, as far as it can
   *  honestly go. */
  reporters: string[];
}

/** A conflict, plus who found it. The handle matters: `assessment` is one sub-agent's
 *  judgement, and an unattributed judgement reads as the system's. */
export interface ConflictRow {
  conflict: Conflict;
  handle: string;
}

/** A question nobody settled, and who could not settle it. */
export interface UnresolvedRow {
  question: string;
  handle: string;
}

/** Who has reported and who has not — the honesty band above the map. */
export interface ArrivalState {
  /** Sub-agents that came back with a structured report. */
  reported: number;
  /** Still working or parked on the operator. Named, because "waiting on 2" is a
   *  different sentence from "waiting on `pricing-researcher` and `spec-reader`". */
  outstanding: string[];
  /** Finished, but with no structured block — its report is prose only, and its
   *  findings are in the Agents panel rather than in this map. Worth counting: a map
   *  missing a finished sub-agent's work is not the same as a complete one. */
  proseOnly: number;
}

export interface CoverageReport {
  arrival: ArrivalState;
  topics: TopicRow[];
  /** Findings no report filed under a topic. Kept rather than dropped — an unfiled
   *  finding is still something the investigation established. */
  untopiced: Finding[];
  conflicts: ConflictRow[];
  unresolved: UnresolvedRow[];
}

/** Where a topic sorts. A row that made no depth claim sits just past `none`: it is not
 *  a reported dead end, and it is not coverage either, so it belongs with the rows the
 *  operator is scanning for rather than among the ones that are done. */
function depthRank(row: TopicRow): number {
  return row.depthReported ? DEPTH_ORDER[row.depth] : 0.5;
}

/** Whether there is a map to draw at all. A thread whose sub-agents have all reported
 *  in prose has nothing structured to show, and an empty coverage panel is worse than
 *  no coverage panel. */
export function hasCoverage(subagents: Subagent[]): boolean {
  return subagents.some((s) => s.findings !== null);
}

/** Everything the landed reports say about the shape of the work. */
export function collectCoverage(subagents: Subagent[]): CoverageReport {
  const topics = new Map<string, TopicRow>();
  const untopiced: Finding[] = [];
  const conflicts: ConflictRow[] = [];
  const unresolved: UnresolvedRow[] = [];
  const outstanding: string[] = [];
  let reported = 0;
  let proseOnly = 0;

  for (const agent of subagents) {
    if (isLive(agent)) {
      outstanding.push(agent.handle);
      // A sub-agent can be both still working and already holding a partial report, so
      // it is counted as outstanding and its findings are still read below.
    }
    const report = agent.findings;
    if (report === null) {
      if (!isLive(agent)) proseOnly += 1;
      continue;
    }
    reported += 1;

    for (const row of report.coverage) {
      const existing = topics.get(row.topic);
      if (existing) {
        if (
          !existing.depthReported ||
          DEPTH_ORDER[row.depth] > DEPTH_ORDER[existing.depth]
        )
          existing.depth = row.depth;
        existing.depthReported = true;
        existing.sourceCount += row.sourceCount;
        for (const gap of row.gaps)
          if (!existing.gaps.includes(gap)) existing.gaps.push(gap);
        if (!existing.reporters.includes(agent.handle))
          existing.reporters.push(agent.handle);
      } else {
        topics.set(row.topic, {
          topic: row.topic,
          depth: row.depth,
          depthReported: true,
          sourceCount: row.sourceCount,
          gaps: [...row.gaps],
          findings: [],
          reporters: [agent.handle],
        });
      }
    }

    for (const finding of report.findings) {
      // A finding whose topic no coverage row named still belongs to that topic — the
      // two are matched by the launching agent's own words, and a sub-agent that filed
      // a finding under a topic it forgot to report coverage for has told us something
      // about that topic all the same. So the row is created rather than the finding
      // dropped, and it is marked as carrying no depth claim: `none` would be the
      // report saying it got nowhere, which is not what happened.
      const topic = finding.topic;
      if (topic === null || topic === "") {
        untopiced.push(finding);
        continue;
      }
      let row = topics.get(topic);
      if (!row) {
        row = {
          topic,
          depth: "none",
          depthReported: false,
          sourceCount: 0,
          gaps: [],
          findings: [],
          reporters: [],
        };
        topics.set(topic, row);
      }
      row.findings.push(finding);
      if (!row.reporters.includes(agent.handle))
        row.reporters.push(agent.handle);
    }

    for (const conflict of report.conflicts)
      conflicts.push({ conflict, handle: agent.handle });
    for (const question of report.unresolved)
      unresolved.push({ question, handle: agent.handle });
  }

  return {
    arrival: { reported, outstanding, proseOnly },
    // **Shallowest first.** The map is read to find what is missing, and a list that
    // opens with the topic already covered deeply buries its own point. Ties keep
    // insertion order, which is the order the reports named them in.
    topics: [...topics.values()].sort((a, b) => depthRank(a) - depthRank(b)),
    untopiced,
    conflicts,
    unresolved,
  };
}

/** Every source named on a side of some conflict, as the bare tokens the Sources panel
 *  can match a citation against — urls, and corpus refs.
 *
 *  A **lenient join** on purpose: a report names sources as `{url, ref, title}` while a
 *  citation is keyed by url or by `source_id:ref`, so the two meet only on the halves
 *  they share. A title is deliberately not a token — two different pages share a title
 *  often enough that matching on one would mark innocent sources as contested. */
export function contestedTokens(report: CoverageReport): Set<string> {
  const tokens = new Set<string>();
  const add = (sources: ReportSource[]): void => {
    for (const s of sources) {
      if (s.url) tokens.add(s.url);
      if (s.ref) tokens.add(s.ref);
    }
  };
  for (const { conflict } of report.conflicts)
    for (const position of conflict.positions) add(position.sources);
  return tokens;
}

/** How a finding's confidence is ranked when the panel sorts by it — highest first.
 *  A low-confidence finding is still a finding and is never hidden; it just does not
 *  lead. */
export const CONFIDENCE_ORDER: Record<Finding["confidence"], number> = {
  high: 0,
  medium: 1,
  low: 2,
};

/** Findings strongest first. The filter the requirement asks for — "filtered sub-agent
 *  findings, not the full transcript" — is this plus the topic grouping above: what
 *  reaches the operator is the report's own claims, ranked by the report's own
 *  confidence, rather than N essays to read end to end. */
export function byConfidence(findings: Finding[]): Finding[] {
  return [...findings].sort(
    (a, b) => CONFIDENCE_ORDER[a.confidence] - CONFIDENCE_ORDER[b.confidence],
  );
}
