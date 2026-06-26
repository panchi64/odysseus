/** Pure shaping of an assistant turn's ordered `blocks` for rendering and copy.
 *  No Solid/DOM here — just data → data, so the rules (grouping, compaction,
 *  transcript assembly) stay testable and live in one place. */

import type { AssistantBlock, BlockKind } from "./model";

/** A run of consecutive collapsible work only folds into a WORK LOG accordion
 *  once it reaches this many groups. Below it, the run stays inline — a lone
 *  tool call or a think→tool pair reads better on the rail than wrapped in a
 *  "WORK LOG · 1 STEP" fold. Each inline block is still independently
 *  collapsible via its own card, so nothing is buried. */
export const WORK_LOG_MIN_RUN = 3;

/** The answer the operator reads — every `text` block in order. */
export function answerText(blocks: AssistantBlock[] | undefined): string {
  return (blocks ?? [])
    .filter((b) => b.kind === "text")
    .map((b) => b.text)
    .join("\n\n");
}

/** Every reasoning passage in order (for COPY REASONING). */
export function reasoningText(blocks: AssistantBlock[] | undefined): string {
  return (blocks ?? [])
    .filter((b) => b.kind === "thinking")
    .map((b) => b.text)
    .join("\n\n");
}

export function hasReasoning(blocks: AssistantBlock[] | undefined): boolean {
  return (blocks ?? []).some((b) => b.kind === "thinking");
}

/** Whether a turn has any collapsible layer worth an expand-all control. */
export function hasLayers(blocks: AssistantBlock[] | undefined): boolean {
  return (blocks ?? []).some(
    (b) =>
      b.kind === "thinking" || b.kind === "tool" || b.kind === "host_command",
  );
}

/** Flatten a turn to one plain-text block for COPY MESSAGE — reasoning, each
 *  tool/host call as `name(args) -> outcome`, decisions, then the answer, all in
 *  the order they happened. */
export function assembleTranscript(
  blocks: AssistantBlock[] | undefined,
): string {
  const parts: string[] = [];
  for (const b of blocks ?? []) {
    switch (b.kind) {
      case "thinking":
        parts.push(`REASONING\n${b.text}`);
        break;
      case "text":
        parts.push(b.text);
        break;
      case "tool": {
        const t = b.tool;
        const outcome = t.error ? `error: ${t.error}` : (t.result ?? "");
        parts.push(`${t.name}(${t.args}) -> ${outcome}`);
        break;
      }
      case "host_command": {
        const c = b.command;
        const out = c.error ?? c.stdout ?? "";
        parts.push(`$ ${c.command}${out ? `\n${out}` : ""}`);
        break;
      }
      case "approval":
        parts.push(
          `APPROVAL REQUIRED: ${b.approval.name} — ${b.approval.summary}`,
        );
        break;
      case "artifact":
        parts.push(`[artifact: ${b.artifact.title}]`);
        break;
      case "preview":
        parts.push(`[preview: ${b.preview.url}]`);
        break;
    }
  }
  return parts.join("\n\n");
}

/* ── Grouping ─────────────────────────────────────────────────────────────────
   Approvals and host commands batch into one card (the parked run resumes only
   on a decision covering every pending call), so consecutive blocks of those
   kinds merge into a single group. Every other block stands alone.

   This assumes a park's pending calls arrive contiguously in the stream (true
   for a single park — the events for one step's gated calls are emitted back to
   back). If a future backend ever interleaves a non-gated block *between* two
   simultaneously-pending approvals, they'd split across cards and each would
   submit a partial decision — unify the cards then. */

export interface BlockGroup {
  id: string;
  kind: BlockKind;
  blocks: AssistantBlock[];
}

const AGGREGATED: ReadonlySet<BlockKind> = new Set([
  "approval",
  "host_command",
]);

export function groupBlocks(
  blocks: AssistantBlock[] | undefined,
): BlockGroup[] {
  const groups: BlockGroup[] = [];
  for (const b of blocks ?? []) {
    const last = groups[groups.length - 1];
    if (last && last.kind === b.kind && AGGREGATED.has(b.kind)) {
      last.blocks.push(b);
    } else {
      groups.push({ id: b.id, kind: b.kind, blocks: [b] });
    }
  }
  return groups;
}

/** A host-command group the operator still needs eyes on — awaiting a decision
 *  (pending) or actively running on the host (live output) — must never be
 *  hidden. Only finished terminals (ok/error/denied) may fold away. */
function hasLiveHost(group: BlockGroup): boolean {
  return group.blocks.some(
    (b) =>
      b.kind === "host_command" &&
      (b.command.phase === "pending" || b.command.phase === "running"),
  );
}

/** Collapsible = pure process noise: reasoning, finished tool calls, and host
 *  terminals that are neither pending nor running. Answer text, approvals,
 *  artifacts and live previews are always shown. */
function isCollapsible(group: BlockGroup): boolean {
  if (group.kind === "thinking" || group.kind === "tool") return true;
  if (group.kind === "host_command") return !hasLiveHost(group);
  return false;
}

/* ── Compaction layout ────────────────────────────────────────────────────────
   Fold every maximal run of consecutive collapsible work that reaches
   WORK_LOG_MIN_RUN groups into its own WORK LOG accordion, always leaving the
   non-collapsible blocks (the answer, pending actions, outputs) and the
   active/streaming tail visible and in order. Shorter runs stay inline as
   individual rail blocks — so the turn's true think → tool → text → … narrative
   survives, long stretches of process recede into per-segment accordions, and a
   lone call or a think→tool pair isn't wrapped in a one-step fold. */

export type LayoutItem =
  | { type: "group"; group: BlockGroup }
  | { type: "worklog"; groups: BlockGroup[] };

export function planTurnLayout(
  groups: BlockGroup[],
  opts: { streaming?: boolean } = {},
): LayoutItem[] {
  // While streaming, the trailing group is "live" — keep it inline, never folded.
  const activeIndex = opts.streaming ? groups.length - 1 : -1;
  const items: LayoutItem[] = [];
  let run: BlockGroup[] = [];
  const flush = (): void => {
    if (run.length >= WORK_LOG_MIN_RUN) {
      items.push({ type: "worklog", groups: run });
    } else {
      for (const group of run) items.push({ type: "group", group });
    }
    run = [];
  };
  groups.forEach((group, i) => {
    if (i !== activeIndex && isCollapsible(group)) {
      run.push(group);
    } else {
      flush();
      items.push({ type: "group", group });
    }
  });
  flush();
  return items;
}

/** The latest tool/host call in a set of groups, with the reasoning that led to
 *  it — the peek the WORK LOG accordion shows while collapsed. */
export function peekLatestTool(
  groups: BlockGroup[],
): { name: string; rationale?: string } | null {
  const flat = groups.flatMap((g) => g.blocks);
  for (let i = flat.length - 1; i >= 0; i--) {
    const b = flat[i];
    const name =
      b.kind === "tool"
        ? b.tool.name
        : b.kind === "host_command"
          ? b.command.command
          : null;
    if (name == null) continue;
    // The reasoning that led to *this* call is the thinking block immediately
    // before it; condense to a line. If another block sits between (e.g. a prior
    // tool), there's no direct rationale — don't borrow an unrelated one.
    const prev = flat[i - 1];
    const rationale =
      prev?.kind === "thinking"
        ? prev.text.replace(/\s+/g, " ").trim()
        : undefined;
    return { name, rationale };
  }
  return null;
}

/** Count work blocks by kind for the settled progress summary. */
export function workCounts(blocks: AssistantBlock[] | undefined): {
  thinks: number;
  tools: number;
} {
  let thinks = 0;
  let tools = 0;
  for (const b of blocks ?? []) {
    if (b.kind === "thinking") thinks++;
    else if (b.kind === "tool" || b.kind === "host_command") tools++;
  }
  return { thinks, tools };
}
