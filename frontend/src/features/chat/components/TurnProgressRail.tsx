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
  // "Working", which implies the agent is already mid-task.
  if (!last) return "Starting";
  switch (last.kind) {
    case "thinking":
      return "Thinking";
    case "text":
      return "Writing";
    case "tool":
      return last.tool.status === "running"
        ? `RUNNING ${last.tool.name}`
        : "Working";
    case "host_command":
      return last.command.phase === "pending"
        ? "Awaiting approval"
        : last.command.phase === "running"
          ? "Running on host"
          : "Working";
    case "approval":
      return "Awaiting approval";
    case "view_version":
    case "view_document":
      return "Updating view";
    case "view_live":
      return "Starting live view";
  }
}

/** The turn's tempo line: while streaming, a hard-stepped throbber + a label for
 *  the live phase ("Thinking", "RUNNING web_search", "Writing"). Once settled, a
 *  compact count of the work it took (the per-step rhythm lives in the block
 *  rail). Renders nothing for a plain turn with no work. */
export function TurnProgressRail(props: {
  blocks: AssistantBlock[] | undefined;
  streaming?: boolean;
  /** Whether the turn's work log is folded away. The settled "N TOOLS · M THINKS"
   *  line stands in for the log; with the log open it restates what is already on
   *  screen directly beneath it, so it is withheld. */
  collapsed?: boolean;
  /** True until the run's first event arrives — waiting behind the backend's
   *  concurrency limit, not yet actually executing. Rendered as an explicit
   *  "Queued" state instead of the throbber, which would otherwise look
   *  identical to a model that's just slow to produce its first token. */
  queued?: boolean;
}): JSX.Element {
  const counts = createMemo(() => workCounts(props.blocks));
  const hasWork = () => counts().thinks > 0 || counts().tools > 0;

  return (
    <Show
      when={props.streaming}
      fallback={
        <Show when={hasWork() && props.collapsed}>
          <Text variant="micro" tone="dim">
            {counts().tools} {counts().tools === 1 ? "Tool" : "Tools"} ·{" "}
            {counts().thinks} {counts().thinks === 1 ? "Think" : "Thinks"}
          </Text>
        </Show>
      }
    >
      <Row gap={2} align="center" aria-live="polite">
        <Show
          when={!props.queued}
          fallback={
            <Text variant="label" tone="dim">
              Queued
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
