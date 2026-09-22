/**
 * Where a tool call sits among a turn's blocks — on the rail, or on a script's card.
 *
 * A `run_code` call runs a script, and the script makes tool calls of its own. Each of
 * those is a call with its own lifecycle, but it is not a step the model took: it is
 * part of the one step that ran the script, so it nests on that call's card instead of
 * landing on the rail beside it. The live fold and the cold read both place calls
 * through here, so a nested row watched live and one reloaded cannot end up in two
 * different places.
 *
 * Pure edits on a block list: callers inside a Solid `produce` hand in the draft.
 */

import type { AssistantBlock, ToolBlock, ToolInvocation } from "./model";

/** The only tool whose calls make calls of their own. Named here for the one case that
 *  has to guess a parent: a nested call that arrived before the call it came from. */
export const SCRIPT_TOOL = "run_code";

function findTopLevel(
  blocks: AssistantBlock[] | undefined,
  toolCallId: string,
): ToolBlock | undefined {
  return blocks?.find(
    (b): b is ToolBlock => b.kind === "tool" && b.tool.id === toolCallId,
  );
}

/** One call by id, wherever it sits — on the rail or nested on a script's card. */
export function findToolCall(
  blocks: AssistantBlock[] | undefined,
  toolCallId: string,
): ToolInvocation | undefined {
  for (const b of blocks ?? []) {
    if (b.kind !== "tool") continue;
    if (b.tool.id === toolCallId) return b.tool;
    const child = b.tool.children?.find((c) => c.id === toolCallId);
    if (child) return child;
  }
  return undefined;
}

/**
 * Put one call where it belongs, merging onto the row already there for its id.
 *
 * With no `parentId` the call is a block on the rail. With one, it joins that call's
 * `children` — and **never** the rail, even when the parent has not arrived yet: the
 * parent is seated as a bare running row the parent's own frame then fills in, keeping
 * the children it collected. A frame ordering that put a nested call first would
 * otherwise leave it stranded on the rail as a step the model never took.
 *
 * `blockId` names a new rail block from its call id — the live stream and the cold read
 * mint different ones, and that is their only difference here.
 */
export function placeToolCall(
  blocks: AssistantBlock[],
  blockId: (toolCallId: string) => string,
  call: ToolInvocation,
  parentId?: string | null,
): void {
  if (!parentId) {
    const existing = findTopLevel(blocks, call.id);
    if (existing)
      Object.assign(existing.tool, call, {
        children: call.children ?? existing.tool.children,
      });
    else blocks.push({ kind: "tool", id: blockId(call.id), tool: call });
    return;
  }
  let parent = findTopLevel(blocks, parentId)?.tool;
  if (!parent) {
    parent = { id: parentId, name: SCRIPT_TOOL, args: "", status: "running" };
    blocks.push({ kind: "tool", id: blockId(parentId), tool: parent });
    // Through the list, not the local: inside a store draft, the object pushed is not
    // the proxy the list now hands back, and only the proxy's writes are seen.
    parent = findTopLevel(blocks, parentId)!.tool;
  }
  const children = parent.children ?? (parent.children = []);
  const existing = children.find((c) => c.id === call.id);
  if (existing) Object.assign(existing, call);
  else children.push(call);
}
