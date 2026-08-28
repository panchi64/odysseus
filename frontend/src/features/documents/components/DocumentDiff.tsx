import { For, Show, type JSX } from "solid-js";
import { cx, EmptyState, Text } from "~/ui";
import type { DiffLine, DiffResult } from "../diff";

/** A git-style line diff rendered in the terminal-HUD idiom: a single tabular
 *  line-number gutter, a `+`/`-`/space marker, then the line. Every column uses
 *  the same `body` size so the grid stays uniform; additions read `nominal`
 *  (green), removals `alert` (red) — the only two accents — context stays
 *  neutral. A 2px rail (transparent on context, to keep text aligned) bands the
 *  changed lines. */

const MARKER: Record<DiffLine["kind"], string> = {
  context: " ",
  add: "+",
  del: "-",
};

function rail(kind: DiffLine["kind"]): string {
  if (kind === "add") return "border-nominal";
  if (kind === "del") return "border-alert";
  return "border-transparent";
}

function tone(kind: DiffLine["kind"]): "nominal" | "alert" | "default" {
  if (kind === "add") return "nominal";
  if (kind === "del") return "alert";
  return "default";
}

function DiffRow(props: { line: DiffLine }): JSX.Element {
  // One line-number column so every number stacks in the same place: a removed
  // line shows its old number, an added/context line its new number.
  const num = (): number | undefined => props.line.newNo ?? props.line.oldNo;
  return (
    <div class={cx("flex items-start border-l-2", rail(props.line.kind))}>
      <Text
        variant="body"
        tone="dim"
        class="w-12 shrink-0 select-none px-2 text-right tabular-nums"
      >
        {num() ?? " "}
      </Text>
      <Text
        variant="body"
        tone={tone(props.line.kind)}
        class="w-5 shrink-0 select-none text-center"
      >
        {MARKER[props.line.kind]}
      </Text>
      <Text
        variant="body"
        tone={tone(props.line.kind)}
        class="min-w-0 flex-1 whitespace-pre-wrap break-words pr-2"
      >
        {props.line.text || " "}
      </Text>
    </div>
  );
}

export function DocumentDiff(props: { result: DiffResult }): JSX.Element {
  return (
    <Show
      when={props.result.added || props.result.removed}
      fallback={
        <EmptyState
          icon="check"
          message="NO CHANGES"
          hint="This version made no changes to the document body."
        />
      }
    >
      <div class="overflow-x-auto border border-line bg-surface py-1">
        <For each={props.result.lines}>{(line) => <DiffRow line={line} />}</For>
      </div>
    </Show>
  );
}
