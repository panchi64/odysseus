import {
  createMemo,
  createSignal,
  For,
  onCleanup,
  onMount,
  Show,
  type JSX,
} from "solid-js";
import { cx } from "../cx";

export interface DiffViewProps {
  /** Unified-diff text. */
  diff: string;
  class?: string;
  /** Force the single-column unified layout (a changed block's removed lines,
   *  then its added lines, in standard unified order) instead of the default
   *  two-column split. Also forced automatically below `STACK_BREAKPOINT`,
   *  regardless of this prop. */
  stacked?: boolean;
  /** Forwards the scrolling root element — lets a caller hook up scroll-position
   *  persistence (e.g. `rememberScroll`) without DiffView owning that concern. */
  ref?: (el: HTMLDivElement) => void;
}

/** Below this width (px) the two-column split can't breathe, so the layout
 *  auto-forces the single-column stack regardless of the `stacked` prop. */
const STACK_BREAKPOINT = 560;

/** "Compare vs · full code" sentinel — no diff selected. */

/** One rendered row's content + tone, already resolved from the raw diff line —
 *  `segs` is set only for a changed line paired with its replacement (word-level
 *  emphasis); everything else (meta, context, unpaired add/remove) renders `raw`
 *  verbatim, exactly as before. */
interface Line {
  tone: "alert" | "nominal" | "dim" | "text";
  /** The full source line, marker included — the plain-render fallback. */
  raw: string;
  /** "-" / "+" for a changed line (paired or not); absent for meta/context. */
  marker?: "-" | "+";
  /** Word-level diff segments vs. the paired line on the other side. Only set
   *  when this line was matched 1:1 with a replacement line in the same block. */
  segs?: WordSeg[];
}

const EMPTY_LINE: Line = { tone: "dim", raw: "" };

type Seg =
  | { kind: "meta"; text: string }
  | { kind: "context"; text: string }
  | { kind: "change"; removed: string[]; added: string[] };

interface WordSeg {
  kind: "same" | "del" | "add";
  text: string;
}

/** File/hunk headers, checked before the single-char +/- markers so they don't
 *  read as add/remove lines. */
function isMeta(line: string): boolean {
  return (
    line.startsWith("@@") ||
    line.startsWith("+++") ||
    line.startsWith("---") ||
    line.startsWith("diff ") ||
    line.startsWith("index ")
  );
}

/** Group unified-diff lines into meta / context / change segments. A change
 *  segment holds one hunk's contiguous removed run plus the added run that
 *  immediately follows it (if any) — the removed↔added pairing a replacement
 *  block's word-level emphasis diffs between. */
function segment(diff: string): Seg[] {
  const lines = diff.replace(/\n$/, "").split("\n");
  const segs: Seg[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (isMeta(line)) {
      segs.push({ kind: "meta", text: line });
      i++;
      continue;
    }
    if (line.startsWith("-")) {
      const removed: string[] = [];
      while (
        i < lines.length &&
        lines[i].startsWith("-") &&
        !isMeta(lines[i])
      ) {
        removed.push(lines[i].slice(1));
        i++;
      }
      const added: string[] = [];
      while (
        i < lines.length &&
        lines[i].startsWith("+") &&
        !isMeta(lines[i])
      ) {
        added.push(lines[i].slice(1));
        i++;
      }
      segs.push({ kind: "change", removed, added });
      continue;
    }
    if (line.startsWith("+")) {
      const added: string[] = [];
      while (
        i < lines.length &&
        lines[i].startsWith("+") &&
        !isMeta(lines[i])
      ) {
        added.push(lines[i].slice(1));
        i++;
      }
      segs.push({ kind: "change", removed: [], added });
      continue;
    }
    segs.push({ kind: "context", text: line });
    i++;
  }
  return segs;
}

/** Split a line into word/whitespace-run tokens, keeping every character so the
 *  tokens rejoin to the exact original text. */
function tokenize(line: string): string[] {
  return line.split(/(\s+)/).filter((t) => t.length > 0);
}

/** Word-level LCS between one changed line's before/after tokens — the same
 *  walk `lineDiff` does one level up, one token deeper. The result is reused
 *  for both sides of the pair: the removed line renders its `same`+`del`
 *  tokens, the added line its `same`+`add` tokens. */
function wordDiff(oldTokens: string[], newTokens: string[]): WordSeg[] {
  const a = oldTokens;
  const b = newTokens;
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      lcs[i][j] =
        a[i] === b[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);

  const segs: WordSeg[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      segs.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      segs.push({ kind: "del", text: a[i] });
      i++;
    } else {
      segs.push({ kind: "add", text: b[j] });
      j++;
    }
  }
  while (i < a.length) segs.push({ kind: "del", text: a[i++] });
  while (j < b.length) segs.push({ kind: "add", text: b[j++] });
  return segs;
}

/** A changed block's removed/added lines, word-diffed 1:1 by position up to
 *  the shorter side's length (the "pair" a removed line and its replacement
 *  form); any excess lines on the longer side are left unpaired, rendered
 *  plain — exactly as before. */
function changedLines(seg: Extract<Seg, { kind: "change" }>): {
  removed: Line[];
  added: Line[];
} {
  const pairCount = Math.min(seg.removed.length, seg.added.length);
  const pairs = Array.from({ length: pairCount }, (_, i) =>
    wordDiff(tokenize(seg.removed[i]), tokenize(seg.added[i])),
  );
  const removed = seg.removed.map((text, i) => ({
    tone: "alert" as const,
    raw: `-${text}`,
    marker: "-" as const,
    segs: pairs[i],
  }));
  const added = seg.added.map((text, i) => ({
    tone: "nominal" as const,
    raw: `+${text}`,
    marker: "+" as const,
    segs: pairs[i],
  }));
  return { removed, added };
}

/** Flatten segments into the single-column unified order: meta/context as-is,
 *  each changed block's removed lines then its added lines. */
function stackedLines(segs: Seg[]): Line[] {
  const out: Line[] = [];
  for (const seg of segs) {
    if (seg.kind === "meta") out.push({ tone: "dim", raw: seg.text });
    else if (seg.kind === "context") out.push({ tone: "text", raw: seg.text });
    else {
      const { removed, added } = changedLines(seg);
      out.push(...removed, ...added);
    }
  }
  return out;
}

/** A split-view row: either one line spanning both columns (meta/context), or
 *  a left/right pair (either side may be blank when the other's run is
 *  longer). */
interface SplitRow {
  full?: Line;
  left?: Line;
  right?: Line;
}

function splitRows(segs: Seg[]): SplitRow[] {
  const out: SplitRow[] = [];
  for (const seg of segs) {
    if (seg.kind === "meta") out.push({ full: { tone: "dim", raw: seg.text } });
    else if (seg.kind === "context")
      out.push({ full: { tone: "text", raw: seg.text } });
    else {
      const { removed, added } = changedLines(seg);
      const rows = Math.max(removed.length, added.length);
      for (let i = 0; i < rows; i++)
        out.push({ left: removed[i], right: added[i] });
    }
  }
  return out;
}

const TONE_CLASS: Record<Line["tone"], string> = {
  alert: "text-alert",
  nominal: "text-nominal",
  dim: "text-dim",
  text: "text-text",
};

/** One side of a word-diffed pair: common tokens render plain (the line's own
 *  tone already carries them), differing tokens get a background wash in the
 *  same nominal/alert accent family at higher intensity — no new colors. */
function WordSpans(props: {
  segs: WordSeg[];
  side: "del" | "add";
}): JSX.Element {
  const emphasis =
    props.side === "del"
      ? "bg-alert/30 text-alert"
      : "bg-nominal/30 text-nominal";
  return (
    <For
      each={props.segs.filter(
        (s) => s.kind === "same" || s.kind === props.side,
      )}
    >
      {(s) =>
        s.kind === "same" ? (
          <>{s.text}</>
        ) : (
          <span class={emphasis}>{s.text}</span>
        )
      }
    </For>
  );
}

function LineRow(props: { line?: Line; class?: string }): JSX.Element {
  const line = () => props.line ?? EMPTY_LINE;
  return (
    <div
      class={cx("whitespace-pre px-3", TONE_CLASS[line().tone], props.class)}
    >
      <Show when={line().segs} fallback={<>{line().raw || " "}</>}>
        {(segs) => (
          <>
            {line().marker}
            <WordSpans
              segs={segs()}
              side={line().marker === "-" ? "del" : "add"}
            />
          </>
        )}
      </Show>
    </div>
  );
}

function StackedBody(props: { segs: Seg[] }): JSX.Element {
  const lines = createMemo(() => stackedLines(props.segs));
  return <For each={lines()}>{(line) => <LineRow line={line} />}</For>;
}

function SplitBody(props: { segs: Seg[] }): JSX.Element {
  const rows = createMemo(() => splitRows(props.segs));
  return (
    <div class="grid grid-cols-2">
      <For each={rows()}>
        {(row) => (
          <Show
            when={row.full}
            fallback={
              <>
                <LineRow line={row.left} />
                <LineRow line={row.right} class="border-l border-line" />
              </>
            }
          >
            {(full) => (
              <div class="col-span-2">
                <LineRow line={full()} />
              </div>
            )}
          </Show>
        )}
      </For>
    </div>
  );
}

/** Renders unified-diff text as a two-column split (removed | added, meta and
 *  context spanning both) by default, or a single-column unified stack when
 *  `stacked` is set or the panel is too narrow to split. Changed line pairs
 *  (a removed line matched 1:1 with its replacement) get word-level emphasis
 *  on top of the line-level tone; unpaired adds/removes render plain, as
 *  before. Scrollable, fills its container. */
export function DiffView(props: DiffViewProps): JSX.Element {
  let root: HTMLDivElement | undefined;
  const [width, setWidth] = createSignal(Infinity);

  onMount(() => {
    if (!root) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w !== undefined) setWidth(w);
    });
    ro.observe(root);
    onCleanup(() => ro.disconnect());
  });

  const segs = createMemo(() => segment(props.diff));
  const stacked = createMemo(
    () => Boolean(props.stacked) || width() < STACK_BREAKPOINT,
  );

  return (
    <div
      ref={(el) => {
        root = el;
        props.ref?.(el);
      }}
      class={cx(
        "h-full overflow-auto bg-surface font-mono text-body",
        props.class,
      )}
    >
      <Show when={stacked()} fallback={<SplitBody segs={segs()} />}>
        <StackedBody segs={segs()} />
      </Show>
    </div>
  );
}
