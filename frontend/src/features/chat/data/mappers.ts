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

import { describeToolArgs, describeToolResult } from "../toolSummary";
import { sessionMode } from "~/lib/modes";
import type {
  ActiveRun,
  AssistantBlock,
  ChatMessage,
  ChatSummary,
  Citation,
  ConversationStats,
  HostCommand,
  HostCommandPhase,
  ToolImage,
  ToolInvocation,
  ViewSnapshotRef,
  ViewVersionBlock,
} from "../model";
import { HOST_COMMAND_TOOL } from "./constants";
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
    messageCount: dto.message_count,
    preview: dto.preview ?? undefined,
    model: dto.model ?? undefined,
    activity: dto.activity ?? undefined,
    mode: sessionMode(dto.mode ?? undefined),
    workspace: dto.workspace ?? undefined,
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
    typeof r.stdout === "string" ||
    typeof r.exit_code === "number" ||
    typeof r.error === "string";
  return known ? (r as HostResult) : null;
}

export function hostPhaseFromResult(r: HostResult): HostCommandPhase {
  return r.ok === false || r.error != null ? "error" : "ok";
}

/** Map a persisted host-command tool call (cold history) to the terminal model.
 *  A stored call has already run, so its phase comes from the recorded status. */
export function toHostCommand(dto: ToolCallDTO): HostCommand {
  const r = parseHostResult(dto.result);
  // The tool always returns a structured dict when it actually executes, so a
  // plain-string result means it never ran — i.e. it was denied, and the string
  // is the denial message the model was handed. Surface that instead of a green OK.
  const denial =
    !r && typeof dto.result === "string" && dto.result ? dto.result : undefined;
  const phase: HostCommandPhase = denial
    ? "denied"
    : dto.status === "running"
      ? "running"
      : dto.status === "error"
        ? "error"
        : r
          ? hostPhaseFromResult(r)
          : "ok";
  return {
    toolCallId: dto.id,
    command: typeof dto.args.command === "string" ? dto.args.command : "",
    explanation:
      typeof dto.args.explanation === "string"
        ? dto.args.explanation
        : undefined,
    phase,
    exitCode: r?.exit_code,
    stdout: r?.stdout,
    stderr: r?.stderr,
    timedOut: r?.timed_out,
    // Carry whatever diagnostic exists: the result hint, the denial message, or a
    // retry/validation error projected onto the tool call.
    error: r?.error ?? denial ?? dto.error ?? undefined,
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
    foldedMessages: dto.messages_compacted ?? undefined,
    tokensBefore: dto.tokens_before ?? undefined,
    tokensAfter: dto.tokens_after ?? undefined,
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
    if (t.name === HOST_COMMAND_TOOL)
      blocks.push({
        kind: "host_command",
        id: `${dto.id}-${t.id}`,
        command: toHostCommand(t),
      });
    else
      blocks.push({ kind: "tool", id: `${dto.id}-${t.id}`, tool: toTool(t) });
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
