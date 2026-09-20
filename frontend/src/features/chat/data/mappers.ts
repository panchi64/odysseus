/**
 * The wire, read as the transcript's own vocabulary.
 *
 * Every one of these is pure: a DTO (or a stream event carrying the same shape) in, a
 * seam type out. That is what makes them the single answer to "what does this payload
 * mean" for *both* readers of it — the cold conversation load and the live SSE fold. A
 * screenshot, a host command's exit code, or a version chip has to look identical whether
 * the operator watched it arrive or reloaded into it, and the only way to guarantee that
 * is for one function to produce both.
 *
 * Nothing here touches a store, a resource or the network. Ordering, deduping and
 * placement belong to whoever is folding — these only translate.
 */

import { asCompactionReason } from "../compactionReason";
import { describeToolArgs, describeToolResult } from "../toolSummary";
import { sessionMode } from "~/lib/modes";
import type {
  ActiveRun,
  AssistantBlock,
  ChatMessage,
  ChatSummary,
  Citation,
  CommandBoundaryFacts,
  ConversationStats,
  HostCommand,
  HostCommandPhase,
  ToolImage,
  ToolInvocation,
  ViewSnapshotRef,
  ViewVersionBlock,
} from "../model";
import { isTerminalTool } from "../toolPresentation";
import type {
  ActiveRunDTO,
  ConversationSummaryDTO,
  HostResult,
  MessageDTO,
  RunMetricsDTO,
  ToolCallDTO,
  ToolImageDTO,
  ViewSnapshotDTO,
} from "./wire";

export function toActiveRun(
  dto: ActiveRunDTO | null | undefined,
): ActiveRun | null {
  return dto ? { id: dto.id, status: dto.status, lastSeq: dto.last_seq } : null;
}

/** The composer's readout, from the backend's metrics payload.
 *
 *  One mapper for both sources on purpose: the live `run.metrics` frame and the
 *  conversation load's `stats` are the *same* shape server-side, so mapping them in
 *  one place is what guarantees a reload can't quietly report something different
 *  from what the stream reported a moment earlier.
 *
 *  A pure rename — no arithmetic. The averages, the rate and the ratio all arrive
 *  derived, because deriving them here would mean two implementations of the same
 *  formula and a second answer to a question the backend already answered. Nulls
 *  pass through untouched: they mean unmeasured, and coercing one to 0 would turn
 *  "nobody reported this" into a measurement. */
export function toStats(dto: RunMetricsDTO): ConversationStats {
  return {
    turns: dto.turns,
    steps: dto.steps,
    toolCalls: dto.tool_calls,
    inputTokens: dto.input_tokens,
    outputTokens: dto.output_tokens,
    cacheHitRatio: dto.cache_hit_ratio,
    llmMs: dto.llm_ms,
    toolMs: dto.tool_ms,
    ttftAvgMs: dto.ttft_avg_ms,
    tokensPerSecond: dto.output_tokens_per_second,
    lastRequest: dto.last_request
      ? {
          route: dto.last_request.route,
          inputTokens: dto.last_request.input_tokens,
          outputTokens: dto.last_request.output_tokens,
          cacheReadTokens: dto.last_request.cache_read_tokens,
          cacheWriteTokens: dto.last_request.cache_write_tokens,
        }
      : null,
  };
}

/** A readable one-line title for a thread that the operator hasn't named. */
export function deriveTitle(dto: ConversationSummaryDTO): string {
  if (dto.title) return dto.title;
  if (dto.preview) return dto.preview.slice(0, 60);
  return "Untitled conversation";
}

export function toSummary(dto: ConversationSummaryDTO): ChatSummary {
  return {
    id: dto.id,
    title: deriveTitle(dto),
    updatedAt: dto.updated_at,
    createdAt: dto.created_at,
    messageCount: dto.message_count,
    preview: dto.preview ?? undefined,
    model: dto.model ?? undefined,
    activity: dto.activity ?? undefined,
    lastOutcome: dto.last_outcome ?? undefined,
    mode: sessionMode(dto.mode ?? undefined),
    workspace: dto.workspace ?? undefined,
    projectId: dto.project_id ?? undefined,
  };
}

/** Format tool args as a compact `k=v` summary for the call card. */
export function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
}

export function stringifyResult(result: unknown): string | undefined {
  if (result == null) return undefined;
  return typeof result === "string" ? result : JSON.stringify(result, null, 2);
}

/** Pull the structured streams out of a host command's result, or null when the
 *  payload isn't that shape (e.g. a denial string) — callers leave the phase
 *  untouched in that case so a denied command stays denied. */
export function parseHostResult(result: unknown): HostResult | null {
  if (result == null || typeof result !== "object") return null;
  const r = result as Record<string, unknown>;
  const known =
    typeof r.ok === "boolean" ||
    typeof r.stdout === "string" ||
    typeof r.exit_code === "number" ||
    typeof r.error === "string";
  return known ? (r as HostResult) : null;
}

export function hostPhaseFromResult(r: HostResult): HostCommandPhase {
  return r.ok === false || r.error != null ? "error" : "ok";
}

/** The declaration and the fence's verdict off any result that carries them, or
 *  `undefined` for the overwhelming majority that do not.
 *
 *  Keyed on the presence of `reach` rather than on a tool name, because it is the tools
 *  that *run a command* that carry these and the client should not hold a second list of
 *  which those are — the backend attaches the pair to every executing command tool, and
 *  a new one would arrive here already understood. */
export function commandBoundary(
  result: unknown,
): CommandBoundaryFacts | undefined {
  const r = parseHostResult(result);
  return r ? boundaryOf(r) : undefined;
}

function boundaryOf(r: HostResult): CommandBoundaryFacts | undefined {
  if (!r.reach) return undefined;
  return {
    reach: r.reach,
    fenced: r.fenced,
    unfencedReason: r.unfenced_reason,
    fenceNote: r.fence_note,
  };
}

/**
 * A finished terminal's outcome, from whatever its tool returned — `null` when the
 * result carries no outcome at all.
 *
 * **An object means it executed; a string means it did not.** Both command tools
 * answer with a record when they actually run, and a guard refusal — the wrong mode,
 * a host that cannot fence — comes back as a plain sentence the model was handed.
 * That is the whole test, and it is one test rather than two because the worktree
 * shell stopped composing its own labelled transcript: it reports the streams, the
 * exit code, the duration and its fence verdict as fields, the same way the sandboxed
 * host command always has. The client used to pull that transcript back apart with a
 * parser that read a format the shell harness owned — see `toHostCommand` for what
 * the string now means instead.
 */
export function toTerminalOutcome(
  result: unknown,
): Partial<HostCommand> | null {
  const r = parseHostResult(result);
  return r
    ? {
        phase: hostPhaseFromResult(r),
        exitCode: r.exit_code,
        stdout: r.stdout,
        stderr: r.stderr,
        timedOut: r.timed_out,
        error: r.error,
        elapsedMs: r.duration_ms,
        ...boundaryOf(r),
      }
    : null;
}

/** Map a persisted terminal tool call (cold history) to the terminal model.
 *  A stored call has already run, so its phase comes from the recorded status. */
export function toHostCommand(dto: ToolCallDTO): HostCommand {
  const outcome = toTerminalOutcome(dto.result);
  // A command tool always returns a structured dict when it actually executes, so a
  // plain-string result means it never ran — it was refused, and the string is the
  // refusal the model was handed. Surface that instead of a green OK.
  const denial =
    !outcome && typeof dto.result === "string" && dto.result
      ? dto.result
      : undefined;
  const phase: HostCommandPhase = denial
    ? "denied"
    : dto.status === "running"
      ? "running"
      : dto.status === "error"
        ? "error"
        : (outcome?.phase ?? "ok");
  return {
    toolCallId: dto.id,
    name: dto.name,
    command: typeof dto.args.command === "string" ? dto.args.command : "",
    explanation:
      typeof dto.args.explanation === "string"
        ? dto.args.explanation
        : undefined,
    phase,
    exitCode: outcome?.exitCode,
    stdout: outcome?.stdout,
    stderr: outcome?.stderr,
    timedOut: outcome?.timedOut,
    elapsedMs: outcome?.elapsedMs,
    reach: outcome?.reach,
    fenced: outcome?.fenced,
    unfencedReason: outcome?.unfencedReason,
    fenceNote: outcome?.fenceNote,
    // Carry whatever diagnostic exists: the result hint, the denial message, or a
    // retry/validation error projected onto the tool call.
    error: outcome?.error ?? denial ?? dto.error ?? undefined,
  };
}

/** Map a View version DTO/event to the seam type. Shared by the cold read
 *  (conversation detail) and the warm stream (`view.snapshot`). */
export function toViewSnapshotRef(dto: ViewSnapshotDTO): ViewSnapshotRef {
  return {
    snapshotId: dto.snapshot_id,
    title: dto.title ?? undefined,
    createdAt: dto.created_at,
    filesChanged: dto.files_changed,
    summary: dto.summary,
    preview:
      dto.preview_artifact_id && dto.preview_kind
        ? { kind: dto.preview_kind, artifactId: dto.preview_artifact_id }
        : null,
    keeper: dto.keeper ?? false,
  };
}

/** The inline transcript chip for a version the agent `show`ed — references the
 *  conversation-scoped version by id. Shared by the cold read and the warm stream. */
export function toVersionChipBlock(
  messageId: string,
  ref: {
    snapshotId: string;
    title?: string;
    previewKind?: ViewVersionBlock["previewKind"];
  },
): ViewVersionBlock {
  return {
    kind: "view_version",
    id: `${messageId}-${ref.snapshotId}`,
    snapshotId: ref.snapshotId,
    title: ref.title,
    previewKind: ref.previewKind,
  };
}

/** Derive the citations a completed `web_search`/`web_fetch` tool call surfaced, in
 *  result order — the cold-reload counterpart to the live `citation.added` fold, so a
 *  reloaded transcript shows the same Sources row that streamed in. Cross-call dedup and
 *  the row numbering are the caller's concern (`toMessage` dedups by URL; the row numbers
 *  by position), so this neither dedups nor indexes. Anything else (a degraded-capability
 *  string, a still-running call, an unrecognized shape) yields none.
 *
 *  `web_search` now persists as a `SearchResults` object (`{ instruction, results }`), not
 *  a bare array — read `.results`. `web_fetch` persists as a single page object. */
export function citationsFromToolResult(
  name: string,
  result: unknown,
): Citation[] {
  if (name === "web_search") {
    const items = (result as { results?: unknown })?.results;
    if (!Array.isArray(items)) return [];
    const citations: Citation[] = [];
    for (const item of items) {
      if (
        !item ||
        typeof item !== "object" ||
        typeof (item as { url?: unknown }).url !== "string"
      )
        continue;
      const { url, title } = item as { url: string; title?: string };
      citations.push({ url, title });
    }
    return citations;
  }
  if (
    name === "web_fetch" &&
    result &&
    typeof result === "object" &&
    typeof (result as { url?: unknown }).url === "string"
  ) {
    const { url, title } = result as { url: string; title?: string };
    return [{ url, title }];
  }
  return [];
}

/** The wire's snake_case image list as the model's, or undefined when a call returned
 *  none — the same mapping for the live event and the cold DTO, since a screenshot has
 *  to look identical whether the operator watched it happen or reloaded into it. */
export function toolImages(
  images: ToolImageDTO[] | undefined,
): ToolImage[] | undefined {
  if (!images?.length) return undefined;
  return images.map((i) => ({ mediaType: i.media_type, data: i.data }));
}

export function toTool(dto: ToolCallDTO): ToolInvocation {
  return {
    id: dto.id,
    name: dto.name,
    args: formatArgs(dto.args),
    detail: describeToolArgs(dto.name, dto.args),
    status: dto.status,
    // Only a call that succeeded has an outcome to report; a failure's story is
    // its error, which the card shows in full.
    outcome:
      dto.status === "ok"
        ? describeToolResult(dto.name, dto.result)
        : undefined,
    result: stringifyResult(dto.result),
    error: dto.error ?? undefined,
    images: toolImages(dto.images),
    // A backgrounded command is still a command run on the operator's machine, and it
    // renders as an ordinary card rather than as a terminal — so this is the only place
    // its declaration and fence would otherwise be dropped.
    boundary: commandBoundary(dto.result),
  };
}

export function toMessage(dto: MessageDTO): ChatMessage {
  const base: ChatMessage = {
    id: dto.id,
    role: dto.role,
    content: dto.content,
    createdAt: dto.created_at ?? new Date().toISOString(),
    versionIndex: dto.version_index,
    versionCount: dto.version_count,
    pinned: dto.pinned,
    attachmentIds: dto.attachment_ids,
    fileRefs: dto.file_refs,
    foldedMessages: dto.messages_compacted ?? undefined,
    tokensBefore: dto.tokens_before ?? undefined,
    tokensAfter: dto.tokens_after ?? undefined,
    compactionReason: asCompactionReason(dto.compaction_reason),
    // Length, not `??`: the backend defaults this to `[]` on *every* row, and an empty
    // array is not nullish — so `?? undefined` would hang a useless empty list off every
    // user and assistant turn. Absent-not-empty, the same rule the fields above follow.
    summarySections: dto.sections?.length ? dto.sections : undefined,
  };
  if (dto.role !== "assistant") return base;
  // Cold history is still flat (no recorded emission order), so reconstruct the
  // turn's blocks in the legacy lane order — reasoning, the tool/host calls, the
  // version chips, then the answer. (Once the backend persists ordered blocks, map
  // them straight through here; the live stream already carries true order.)
  const blocks: AssistantBlock[] = [];
  const citations: Citation[] = [];
  if (dto.reasoning)
    blocks.push({
      kind: "thinking",
      id: `${dto.id}-reasoning`,
      text: dto.reasoning,
    });
  for (const t of dto.tools) {
    // The same question the live fold asks, off the same table — so a reload cannot
    // turn a terminal back into a generic tool card.
    if (isTerminalTool(t.name))
      blocks.push({
        kind: "host_command",
        id: `${dto.id}-${t.id}`,
        command: toHostCommand(t),
      });
    else
      blocks.push({ kind: "tool", id: `${dto.id}-${t.id}`, tool: toTool(t) });
    // A settled `ask_user` carries what it asked and what it was told. Rebuilt as the
    // same answered question block the live `question.answered` fold produces, so a
    // reload renders the exchange rather than leaving it as prose inside a tool row.
    // Placed after its own call for the same reason the live one sits on the turn it
    // belongs to.
    if (t.answers?.length)
      blocks.push({
        kind: "question",
        id: `${dto.id}-${t.id}-answers`,
        question: {
          toolCallId: t.id,
          questions: [],
          answers: t.answers.map((a) => ({
            question: a.question,
            selections: a.selections ?? [],
            text: a.text ?? undefined,
          })),
        },
      });
    for (const c of citationsFromToolResult(t.name, t.result))
      if (!citations.some((existing) => existing.url === c.url))
        citations.push(c);
  }
  for (const v of dto.versions ?? [])
    blocks.push(
      toVersionChipBlock(dto.id, {
        snapshotId: v.snapshot_id,
        title: v.title ?? undefined,
        previewKind: v.preview_kind,
      }),
    );
  if (dto.content)
    blocks.push({ kind: "text", id: `${dto.id}-text`, text: dto.content });
  // The answer lives in the text block(s); keep `content` empty for assistant
  // turns so it isn't a second, divergent copy of the same text.
  return {
    ...base,
    content: "",
    blocks,
    citations: citations.length ? citations : undefined,
    blocked: dto.blocked_reason != null,
    blockedDetail: dto.blocked_reason ?? undefined,
    model: dto.model ?? undefined,
  };
}
