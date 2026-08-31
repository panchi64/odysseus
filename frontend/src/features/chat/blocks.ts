/** Pure shaping of an assistant turn's ordered `blocks` for rendering and copy.
 *  No Solid/DOM here — just data → data, so the rules (grouping, compaction,
 *  transcript assembly) stay testable and live in one place. */

import type { AssistantBlock, BlockKind, ToolInvocation } from "./model";

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
      b.kind === "thinking" ||
      b.kind === "tool" ||
      b.kind === "context" ||
      b.kind === "host_command",
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
      case "context":
        // Named as an injection rather than transcribed as a message, so a pasted
        // transcript can't read as something the operator or the model said.
        parts.push(
          `CONTEXT INJECTED (${b.injection.contributor})\n${b.injection.text}`,
        );
        break;
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
      case "view_version":
        parts.push(`[view version: ${b.title ?? "version"}]`);
        break;
      case "view_live":
        parts.push(`[live view: ${b.live.url}]`);
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
 *  (pending) or actively running on the host (live output). See `pinsRunInline`
 *  for the rest of what must not fold; this one is specifically about *live*. */
function hasLiveHost(group: BlockGroup): boolean {
  return group.blocks.some(
    (b) =>
      b.kind === "host_command" &&
      (b.command.phase === "pending" || b.command.phase === "running"),
  );
}

/** A tool call still running. Each tool block is its own group, so a parallel batch is
 *  a *run* of them — and a run of three is exactly what `WORK_LOG_MIN_RUN` folds away,
 *  hiding the spinners of calls still in flight. Same rule as `hasLiveHost`. */
function hasLiveTool(group: BlockGroup): boolean {
  return group.blocks.some(
    (b) => b.kind === "tool" && b.tool.status === "running",
  );
}

/** A call that failed — the tool returned an error, or a host command came back
 *  non-zero. A denied host command is not this: that is a decision the operator
 *  already made, and it may fold away like any other settled terminal. */
function hasFailure(group: BlockGroup): boolean {
  return group.blocks.some(
    (b) =>
      (b.kind === "tool" && b.tool.status === "error") ||
      (b.kind === "host_command" && b.command.phase === "error"),
  );
}

/** A call that came back with a picture — a browser screenshot. */
function hasImages(group: BlockGroup): boolean {
  return group.blocks.some((b) => b.kind === "tool" && b.tool.images?.length);
}

/** Work that must stay on screen whatever else folds: still in flight, waiting on
 *  a decision, failed, or carrying something to look at.
 *
 *  Failure is here and deliberately NOT in `hasLiveTool`, because the two mean
 *  different things and only one of them lights the rail. `liveToolGroupIds`
 *  drives the `LedEdge`, whose whole claim is "this is running *now*" — lighting
 *  it for a call that failed a minute ago would be a lie in the one place the
 *  interface speaks in light rather than words.
 *
 *  Without this, a failure was the single most hidden thing in a turn: the card
 *  auto-expands on error, but the work log folded shut around it, so the one
 *  event that should interrupt was the one event buried.
 *
 *  Images are here for the same reason and it bites hardest in the case that
 *  produced them: an agent that screenshots repeatedly makes a run of settled
 *  calls, which is exactly what folds — so without this the pictures would be
 *  hidden precisely when there are the most of them to see. A fold exists to hide
 *  undifferentiated process, and a picture of the page is not that. It costs the
 *  turn a strip of height per screenshot, knowingly. */
function pinsRunInline(group: BlockGroup): boolean {
  return (
    hasLiveTool(group) ||
    hasLiveHost(group) ||
    hasFailure(group) ||
    hasImages(group)
  );
}

/** Collapsible = process the operator doesn't have to read or act on inline:
 *  reasoning, tool calls that finished cleanly, host terminals that are settled
 *  and not failed, and the View chips (a version / the live head — the viewport
 *  surfaces those anyway).
 *
 *  Three things break a work log run: answer `text` (the model writing *to the
 *  operator* — the one thing that should segment the log), approvals, and
 *  anything `pinsRunInline` claims — a call in flight, a host command awaiting a
 *  decision, or a failure. The operator has to act before the run goes on, is
 *  watching it happen, or needs to know it went wrong. Everything else folds into
 *  one continuously growing log. */
function isCollapsible(group: BlockGroup): boolean {
  if (group.kind === "thinking") return true;
  if (group.kind === "view_version" || group.kind === "view_live") return true;
  // Injected context is the frame around the work, never the work — it has no state to
  // watch, nothing to act on, and it arrives in a clump at the head of every turn. If
  // anything in a turn should fold, it is this.
  if (group.kind === "context") return true;
  if (group.kind === "tool" || group.kind === "host_command")
    return !pinsRunInline(group);
  return false;
}

/** Every group with a call in flight. The trailing group is live by *position*; these
 *  are live by *state*, and with parallel calls the two are no longer the same set. */
export function liveToolGroupIds(groups: BlockGroup[]): Set<string> {
  return new Set(groups.filter(hasLiveTool).map((g) => g.id));
}

/** Every tool call in flight across a turn, in order — read across the whole turn
 *  because a parallel batch has no single trailing member that speaks for the rest. */
export function runningTools(
  blocks: AssistantBlock[] | undefined,
): ToolInvocation[] {
  return (blocks ?? []).flatMap((b) =>
    b.kind === "tool" && b.tool.status === "running" ? [b.tool] : [],
  );
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

/**
 * A stable identity for a layout item, across every recompute of the plan.
 *
 * `planTurnLayout` mints fresh objects each call, so a reference-keyed `<For>`
 * treats the whole turn as new every time the plan is rebuilt — on each new
 * block, and again when `streaming` flips at the end of a run. That tears down
 * and re-renders every row in the turn, which is a visible redraw at exactly the
 * moment the operator starts reading. Keying on this instead means a row is
 * created once and only genuinely new or regrouped rows move.
 *
 * The first block's id anchors both kinds: a group keeps its id as it grows, and
 * a work-log run is named by where it starts, so a run absorbing another group
 * stays the same item rather than becoming a different one.
 */
export function layoutItemKey(item: LayoutItem): string {
  return item.type === "worklog"
    ? `w:${item.groups[0]?.id ?? ""}`
    : `g:${item.group.id}`;
}

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

/* The collapsed work log's own summary lives in `workShape.ts` — what the run
   was made of, by tool, rather than the latest call or a bare step count. */
