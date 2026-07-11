import { Show, createMemo, type JSX } from "solid-js";
import { Frames, Row, Text } from "~/ui";
import type { AssistantBlock } from "../model";
import { workCounts } from "../blocks";

/** What the agent is doing *right now* — derived from the trailing block, since
 *  that's the one currently receiving deltas/updates. */
function activeLabel(blocks: AssistantBlock[] | undefined): string {
  const last = blocks?.[blocks.length - 1];
  // No blocks yet = the run was created but nothing has streamed back: the backend
  // is still preparing (context assembly, model spin-up). Say so rather than
  // "WORKING", which implies the agent is already mid-task.
  if (!last) return "STARTING";
  switch (last.kind) {
    case "thinking":
      return "THINKING";
    case "text":
      return "WRITING";
    case "tool":
      return last.tool.status === "running"
        ? `RUNNING ${last.tool.name}`
        : "WORKING";
    case "host_command":
      return last.command.phase === "pending"
        ? "AWAITING APPROVAL"
        : last.command.phase === "running"
          ? "RUNNING ON HOST"
          : "WORKING";
    case "approval":
      return "AWAITING APPROVAL";
    case "view_version":
    case "view_document":
      return "UPDATING VIEW";
    case "view_live":
      return "STARTING LIVE VIEW";
  }
}

/** The turn's tempo line: while streaming, a hard-stepped throbber + a label for
 *  the live phase ("THINKING", "RUNNING web_search", "WRITING"). Once settled, a
 *  compact count of the work it took (the per-step rhythm lives in the block
 *  rail). Renders nothing for a plain turn with no work. */
export function TurnProgressRail(props: {
  blocks: AssistantBlock[] | undefined;
  streaming?: boolean;
  /** True until the run's first event arrives — waiting behind the backend's
   *  concurrency limit, not yet actually executing. Rendered as an explicit
   *  "QUEUED" state instead of the throbber, which would otherwise look
   *  identical to a model that's just slow to produce its first token. */
  queued?: boolean;
}): JSX.Element {
  const counts = createMemo(() => workCounts(props.blocks));
  const hasWork = () => counts().thinks > 0 || counts().tools > 0;

  return (
    <Show
      when={props.streaming}
      fallback={
        <Show when={hasWork()}>
          <Text variant="micro" tone="dim">
            {counts().tools} {counts().tools === 1 ? "TOOL" : "TOOLS"} ·{" "}
            {counts().thinks} {counts().thinks === 1 ? "THINK" : "THINKS"}
          </Text>
        </Show>
      }
    >
      <Row gap={2} align="center" aria-live="polite">
        <Show
          when={!props.queued}
          fallback={
            <Text variant="label" tone="dim">
              QUEUED
            </Text>
          }
        >
          <Frames class="text-info" />
          <Text variant="label" tone="info">
            {activeLabel(props.blocks)}
          </Text>
        </Show>
      </Row>
    </Show>
  );
}
