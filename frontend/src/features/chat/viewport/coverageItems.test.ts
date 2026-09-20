/** Merging N reports into one map.
 *
 *  The rules worth pinning are the ones where the wrong answer is still a plausible
 *  map: a depth that averaged instead of keeping the deepest understates an
 *  investigation that actually got somewhere, a topic row invented at `none` puts words
 *  in a report's mouth, and an arrival count that forgot the sub-agents still out lets a
 *  half-finished map present itself as complete.
 */

import { describe, expect, test } from "bun:test";
import {
  byConfidence,
  collectCoverage,
  contestedTokens,
  hasCoverage,
} from "./coverageItems";
import type { Subagent, SubagentFindings } from "../data/subagents";

const agent = (
  handle: string,
  status: Subagent["status"],
  findings: SubagentFindings | null,
): Subagent =>
  ({
    id: handle,
    conversationId: `c-${handle}`,
    runId: `r-${handle}`,
    handle,
    name: "explorer",
    task: "look into it",
    tasks: [],
    status,
    summary: null,
    findings,
    error: null,
    contextUsed: null,
    contextWindow: null,
    startedAt: "2026-09-19T09:00:00Z",
    endedAt: null,
  }) as Subagent;

const report = (over: Partial<SubagentFindings> = {}): SubagentFindings => ({
  findings: [],
  conflicts: [],
  coverage: [],
  unresolved: [],
  ...over,
});

describe("availability", () => {
  test("a thread whose sub-agents reported in prose has no map", () => {
    expect(hasCoverage([agent("a", "done", null)])).toBe(false);
  });
  test("one structured report is enough to draw one", () => {
    expect(
      hasCoverage([agent("a", "done", null), agent("b", "done", report())]),
    ).toBe(true);
  });
});

describe("merging topics", () => {
  test("the deepest reporter sets the depth, not the last or the average", () => {
    const map = collectCoverage([
      agent(
        "a",
        "done",
        report({
          coverage: [
            { topic: "pricing", depth: "deep", sourceCount: 6, gaps: [] },
          ],
        }),
      ),
      agent(
        "b",
        "done",
        report({
          coverage: [
            { topic: "pricing", depth: "thin", sourceCount: 1, gaps: [] },
          ],
        }),
      ),
    ]);
    expect(map.topics).toHaveLength(1);
    expect(map.topics[0].depth).toBe("deep");
    expect(map.topics[0].sourceCount).toBe(7);
    expect(map.topics[0].reporters).toEqual(["a", "b"]);
  });

  test("gaps merge without repeating the same words twice", () => {
    const map = collectCoverage([
      agent(
        "a",
        "done",
        report({
          coverage: [
            { topic: "t", depth: "thin", sourceCount: 0, gaps: ["no EU data"] },
          ],
        }),
      ),
      agent(
        "b",
        "done",
        report({
          coverage: [
            {
              topic: "t",
              depth: "thin",
              sourceCount: 0,
              gaps: ["no EU data", "nothing past 2024"],
            },
          ],
        }),
      ),
    ]);
    expect(map.topics[0].gaps).toEqual(["no EU data", "nothing past 2024"]);
  });

  test("shallowest first — the map is read for what is missing", () => {
    const map = collectCoverage([
      agent(
        "a",
        "done",
        report({
          coverage: [
            { topic: "deep-one", depth: "deep", sourceCount: 0, gaps: [] },
            { topic: "nothing", depth: "none", sourceCount: 0, gaps: [] },
            { topic: "some", depth: "adequate", sourceCount: 0, gaps: [] },
          ],
        }),
      ),
    ]);
    expect(map.topics.map((t) => t.topic)).toEqual([
      "nothing",
      "some",
      "deep-one",
    ]);
  });

  test("a topic that only a finding named makes no depth claim", () => {
    const map = collectCoverage([
      agent(
        "a",
        "done",
        report({
          findings: [
            {
              statement: "it costs more in the EU",
              confidence: "high",
              sources: [],
              topic: "pricing",
            },
          ],
        }),
      ),
    ]);
    // `none` would be the report saying it looked and got nowhere, which is a much
    // stronger claim than the one it made.
    expect(map.topics[0].depthReported).toBe(false);
    expect(map.topics[0].findings).toHaveLength(1);
  });

  test("a later coverage row upgrades a row a finding created", () => {
    const map = collectCoverage([
      agent(
        "a",
        "done",
        report({
          findings: [
            { statement: "x", confidence: "low", sources: [], topic: "t" },
          ],
        }),
      ),
      agent(
        "b",
        "done",
        report({
          coverage: [
            { topic: "t", depth: "adequate", sourceCount: 3, gaps: [] },
          ],
        }),
      ),
    ]);
    expect(map.topics[0]).toMatchObject({
      depth: "adequate",
      depthReported: true,
      sourceCount: 3,
    });
  });

  test("a finding with no topic is kept, not dropped", () => {
    const map = collectCoverage([
      agent(
        "a",
        "done",
        report({
          findings: [
            {
              statement: "loose fact",
              confidence: "medium",
              sources: [],
              topic: null,
            },
          ],
        }),
      ),
    ]);
    expect(map.topics).toHaveLength(0);
    expect(map.untopiced).toHaveLength(1);
  });
});

describe("arrival state", () => {
  test("the ones still out are named, and the prose-only ones counted", () => {
    const map = collectCoverage([
      agent("reporter", "done", report()),
      agent("worker", "running", null),
      agent("parked", "blocked", null),
      agent("prose", "done", null),
    ]);
    expect(map.arrival).toEqual({
      reported: 1,
      outstanding: ["worker", "parked"],
      proseOnly: 1,
    });
  });

  test("a running sub-agent that has already reported counts both ways", () => {
    // It is still expected to report again, and what it has said already is real.
    const map = collectCoverage([agent("a", "running", report())]);
    expect(map.arrival.reported).toBe(1);
    expect(map.arrival.outstanding).toEqual(["a"]);
    expect(map.arrival.proseOnly).toBe(0);
  });
});

describe("conflicts", () => {
  const conflicted = report({
    conflicts: [
      {
        question: "does it scale?",
        positions: [
          {
            claim: "yes",
            sources: [{ url: "https://a.test/", ref: null, title: "A" }],
          },
          {
            claim: "no",
            sources: [{ url: null, ref: "chapter-4", title: "KB" }],
          },
        ],
        assessment: "the benchmark is newer",
      },
    ],
  });

  test("a conflict carries the sub-agent that judged it", () => {
    const map = collectCoverage([agent("judge", "done", conflicted)]);
    expect(map.conflicts[0].handle).toBe("judge");
    expect(map.conflicts[0].conflict.positions).toHaveLength(2);
  });

  test("contested tokens are urls and refs — never titles", () => {
    const tokens = contestedTokens(
      collectCoverage([agent("a", "done", conflicted)]),
    );
    expect([...tokens].sort()).toEqual(["chapter-4", "https://a.test/"]);
    // Two different pages share a title often enough that matching on one would mark
    // innocent sources as contested.
    expect(tokens.has("A")).toBe(false);
  });
});

describe("filtering findings", () => {
  test("strongest first, and nothing is hidden", () => {
    const findings = [
      { statement: "c", confidence: "low" as const, sources: [], topic: null },
      { statement: "a", confidence: "high" as const, sources: [], topic: null },
      {
        statement: "b",
        confidence: "medium" as const,
        sources: [],
        topic: null,
      },
    ];
    expect(byConfidence(findings).map((f) => f.statement)).toEqual([
      "a",
      "b",
      "c",
    ]);
    expect(byConfidence(findings)).toHaveLength(3);
  });

  test("it does not mutate what it was handed", () => {
    const findings = [
      { statement: "c", confidence: "low" as const, sources: [], topic: null },
      { statement: "a", confidence: "high" as const, sources: [], topic: null },
    ];
    byConfidence(findings);
    expect(findings[0].statement).toBe("c");
  });
});
