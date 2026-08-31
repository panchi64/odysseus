/**
 * The small mutations the fold performs on one assistant message.
 *
 * Every one of these takes a message and edits it in place — they are meant to be called
 * from inside a Solid `produce`, where the draft is already a mutable proxy. Keeping them
 * out of the fold's switch is what stops that switch from being an argument about *how* a
 * block is found or created while it is trying to say *which* block an event belongs to.
 *
 * The identity counter lives here too, because the same rule governs it: a live block and
 * a live message both need an id that no persisted row will ever collide with, and one
 * counter is the only way to be sure of that.
 */

import type {
  ChatMessage,
  HostCommand,
  HostCommandBlock,
  ReviewBlock,
  ToolBlock,
} from "../model";

let counter = 0;

/** A client-minted id for something the stream produced but the backend hasn't named
 *  yet — a live block, or an assistant bubble a `message.injected` boundary opened. */
export const nextId = (prefix: string) => `${prefix}-live-${++counter}`;

/** Append a streamed delta onto the trailing block of `kind`, starting a new
 *  block whenever the kind changes. This is what turns the flat delta stream
 *  into an ordered, interleaved sequence — and what gives a turn *multiple*
 *  thinking blocks (each resumption after a tool/text starts a fresh one). */
export function appendDelta(
  m: ChatMessage,
  kind: "thinking" | "text",
  text: string,
): void {
  const blocks = m.blocks ?? (m.blocks = []);
  const last = blocks[blocks.length - 1];
  if (last && last.kind === kind) last.text += text;
  else blocks.push({ kind, id: nextId(kind), text });
}

export function findTool(
  m: ChatMessage,
  toolCallId: string,
): ToolBlock | undefined {
  return m.blocks?.find(
    (b): b is ToolBlock => b.kind === "tool" && b.tool.id === toolCallId,
  );
}

/** The review row for one call, keyed by tool_call_id — `review.started` opens it and
 *  `review.completed` fills in the verdict on the same block, so the row the operator
 *  saw appear is the row that ends up carrying the answer. */
export function findReview(
  m: ChatMessage,
  toolCallId: string,
): ReviewBlock | undefined {
  return m.blocks?.find(
    (b): b is ReviewBlock =>
      b.kind === "review" && b.review.toolCallId === toolCallId,
  );
}

/** Upsert a host-command *block*, keyed by tool_call_id. The host call's
 *  `tool.started`, `approval.required`, and `tool.completed` events all land
 *  here, each filling in the part it carries onto the same terminal block. */
export function upsertHost(
  m: ChatMessage,
  toolCallId: string,
  patch: Partial<HostCommand>,
): void {
  const existing = m.blocks?.find(
    (b): b is HostCommandBlock =>
      b.kind === "host_command" && b.command.toolCallId === toolCallId,
  );
  if (existing) Object.assign(existing.command, patch);
  else
    (m.blocks ?? (m.blocks = [])).push({
      kind: "host_command",
      id: `host-${toolCallId}`,
      command: { toolCallId, command: "", phase: "pending", ...patch },
    });
}
