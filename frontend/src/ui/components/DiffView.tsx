import { For, type JSX } from "solid-js";
import { cx } from "../cx";

export interface DiffViewProps {
  /** Unified-diff text. */
  diff: string;
  class?: string;
}

/** The tone for one unified-diff line, by its leading marker: additions read
 *  nominal, removals alert, file/hunk headers dim, context default. `+++`/`---`
 *  file markers are checked before the single-char +/- so they don't read as
 *  add/remove lines. */
function lineTone(line: string): string {
  if (
    line.startsWith("@@") ||
    line.startsWith("+++") ||
    line.startsWith("---") ||
    line.startsWith("diff ") ||
    line.startsWith("index ")
  )
    return "text-dim";
  if (line.startsWith("+")) return "text-nominal";
  if (line.startsWith("-")) return "text-alert";
  return "text-text";
}

/** Renders unified-diff text line-by-line in monospace, tinting additions,
 *  removals, and headers by semantic tone. Scrollable, fills its container. */
export function DiffView(props: DiffViewProps): JSX.Element {
  const lines = (): string[] => props.diff.replace(/\n$/, "").split("\n");
  return (
    <div
      class={cx(
        "h-full overflow-auto bg-surface font-mono text-body",
        props.class,
      )}
    >
      <For each={lines()}>
        {(line) => (
          <div class={cx("whitespace-pre px-3", lineTone(line))}>
            {line || " "}
          </div>
        )}
      </For>
    </div>
  );
}
