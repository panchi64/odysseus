import { Show, createMemo, type JSX } from "solid-js";
import { Collapse, Frames, Reveal, Row, Text } from "~/ui";
import type { AssistantBlock } from "../model";
import { runningTools, workCounts } from "../blocks";

/** What the agent is doing *right now* — live tool calls first, then the trailing
 *  block, which is the one receiving deltas when no tool is out. Calls go out in
 *  parallel, so the tail is an arbitrary member of the batch: reading it alone would
 *  drop the others and fall back to "Working" the moment that one returned. */
function activeLabel(blocks: AssistantBlock[] | undefined): string {
  const running = runningTools(blocks);
  if (running.length > 1) return `RUNNING ${running.length} TOOLS`;
  if (running.length === 1) return `RUNNING ${running[0].name}`;
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
    // `runningTools` above claims every live call, so a tool block reaching here has
    // already returned.
    case "tool":
      return "Working";
    case "host_command":
      return last.command.phase === "pending"
        ? "Awaiting approval"
        : last.command.phase === "running"
          ? "Running on host"
          : "Working";
    case "approval":
      return "Awaiting approval";
    case "view_version":
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

  /* The line has something to say while the turn runs, and afterwards only if
     there was work worth counting. For a plain answer — the common case — that
     means it goes from "Thinking" to nothing at all, and everything below it
     jumps up by the height of the line plus its stack gap the instant the run
     ends. `Collapse` turns that into the region closing, which is a movement the
     eye can follow rather than a jump it has to recover from. */
  const showing = () =>
    Boolean(props.streaming) || (hasWork() && Boolean(props.collapsed));

  return (
    <Collapse open={showing()}>
      <Show
        when={props.streaming}
        fallback={
          /* The settled summary is machine output — counts a process emitted,
             not a sentence anyone wrote (§2) — so it stays mono and it
             materializes rather than replacing the live label in place. */
          <Reveal>
            <Text variant="micro" tone="dim">
              {counts().tools} {counts().tools === 1 ? "Tool" : "Tools"} ·{" "}
              {counts().thinks} {counts().thinks === 1 ? "Think" : "Thinks"}
            </Text>
          </Reveal>
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
    </Collapse>
  );
}
