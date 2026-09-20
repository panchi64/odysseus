import {
  createMemo,
  createSignal,
  For,
  Match,
  onCleanup,
  onMount,
  Show,
  Switch,
  type JSX,
} from "solid-js";
import { cx } from "../cx";
import { fontStepSize } from "./fontScale";

export interface DiffViewProps {
  /** Unified-diff text. */
  diff: string;
  class?: string;
  /** Force the single-column unified layout (a changed block's removed lines,
   *  then its added lines, in standard unified order) instead of the default
   *  two-column split. Also forced automatically below `STACK_BREAKPOINT`,
   *  regardless of this prop. */
  stacked?: boolean;
  /** Pick the layout outright, overriding both `stacked` and the width probe.
   *
   *  - `split` — two columns, removed | added.
   *  - `stacked` — one column, the flat unified stream.
   *  - `hunks` — one column, **grouped by hunk**: each `@@` range becomes a
   *    header carrying its own +/− tally and the section heading git put after
   *    the range, collapsible, over numbered lines.
   *
   *  Omit it and the view picks: `stacked` when that prop is set, otherwise
   *  `split` above `STACK_BREAKPOINT` and `hunks` below it. */
  layout?: "split" | "stacked" | "hunks";
  /** Render only the section of a multi-file patch that touches this path —
   *  either side of a rename resolves. The slice happens before any layout
   *  runs, so all three behave identically on it. An unmatched path renders
   *  nothing, which is the honest answer: the patch does not contain that file.
   *
   *  It exists so a caller listing a patch's files can expand one in place
   *  without a second patch parser of its own. */
  file?: string;
  /** Forwards the scrolling root element — lets a caller hook up scroll-position
   *  persistence (e.g. `rememberScroll`) without DiffView owning that concern. */
  ref?: (el: HTMLDivElement) => void;
  /** Zoom step (-2..+2), matching the View panel's font-size control. Default 0. */
  fontStep?: number;
  /** Wraps long lines inside their column instead of scrolling horizontally.
   *  **Defaults to `true`** — unlike `CodeBlock`, which is a single column and
   *  can scroll a long line harmlessly. A split diff cannot: two side-by-side
   *  columns of unwrapped text put the whole file behind a horizontal scroll and
   *  read badly. The View panel's wrap toggle turns it off. */
  softWrap?: boolean;
}

/** Below this width (px) the two-column split can't breathe, so the layout
 *  auto-forces a single column regardless of the `stacked` prop — the hunk
 *  layout, which is the one written for a column this narrow. */
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

/* ── The hunk layout ──────────────────────────────────────────────────────────
 *
 * The split view's answer to a narrow column was the flat unified stack, and a
 * flat stack is exactly the wrong shape there: the `@@` ranges — the only thing
 * in a patch that says *where you are* — render as one more dim line in a stream
 * of hundreds, and a fourteen-file branch becomes an undifferentiated scroll.
 *
 * So the narrow arm groups. A hunk gets a header band carrying its own tally and
 * the section heading git already puts after the range (the enclosing function,
 * usually), it collapses, and its lines carry a line-number gutter. One number
 * column, not two: the new-file number for a kept or added line and the old-file
 * number for a removed one, with the +/− marker telling them apart — two gutters
 * is what there is no room for at half-screen.
 */

/** `@@ -12,7 +12,9 @@ function name()`. The trailing heading is optional and is
 *  git's own context line, not something rendered from the content. */
const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$/;

/** One line inside a hunk, plus the single gutter number it shows. A note line
 *  (`\ No newline at end of file`) belongs to neither file and shows none. */
interface HunkLine {
  line: Line;
  no?: number;
}

interface Hunk {
  key: string;
  /** git's own after-the-range context, verbatim; "" when it gave none. */
  heading: string;
  newStart: number;
  oldStart: number;
  adds: number;
  dels: number;
  lines: HunkLine[];
}

interface DiffFile {
  key: string;
  /** The post-image path, as the patch names it; "" when it names none. */
  path: string;
  /** The pre-image path — differs from `path` on a rename, and is the only
   *  path a deletion has. */
  oldPath: string;
  /** Preamble git emits that is not part of any hunk: "Binary files … differ",
   *  a mode change, a pure rename. When a file has no hunks this *is* the
   *  change, so it has to render. */
  notes: string[];
  hunks: Hunk[];
}

/** Strip git's `a/` / `b/` prefix off a `---`/`+++` path, leaving `/dev/null`
 *  alone so an add/delete still reads as one. */
function stripSide(path: string): string {
  const cut = path.replace(/\t.*$/, "");
  return /^[ab]\//.test(cut) ? cut.slice(2) : cut;
}

/** Group a unified diff into files → hunks → numbered lines.
 *
 *  Only `diff --git` and `@@` end a hunk. A `--- `/`+++ ` line *inside* one is
 *  content — a removed line whose own text began with dashes — and the patches
 *  this reads are git's, which always announce a new file with `diff --git`. */
function hunkFiles(diff: string): DiffFile[] {
  const lines = diff.replace(/\n$/, "").split("\n");
  const files: DiffFile[] = [];
  let file: DiffFile | undefined;
  let hunk: Hunk | undefined;
  let oldNo = 0;
  let newNo = 0;

  const openFile = (): DiffFile => {
    const next: DiffFile = {
      key: `f${files.length}`,
      path: "",
      oldPath: "",
      notes: [],
      hunks: [],
    };
    files.push(next);
    hunk = undefined;
    return next;
  };

  for (const raw of lines) {
    if (raw.startsWith("diff --git ") || raw.startsWith("diff -")) {
      file = openFile();
      // A pure rename and a binary change carry no `---`/`+++` pair at all, so
      // the header line is the only thing that ever names them.
      const named = GIT_HEADER_RE.exec(raw);
      if (named) {
        file.oldPath = named[1];
        file.path = named[2];
      }
      continue;
    }

    const range = HUNK_RE.exec(raw);
    if (range) {
      if (!file) file = openFile();
      oldNo = Number(range[1]);
      newNo = Number(range[2]);
      hunk = {
        key: `${file.key}h${file.hunks.length}`,
        heading: range[3].trim(),
        newStart: newNo,
        oldStart: oldNo,
        adds: 0,
        dels: 0,
        lines: [],
      };
      file.hunks.push(hunk);
      continue;
    }

    if (!hunk) {
      if (!file) file = openFile();
      if (raw.startsWith("--- ")) file.oldPath = stripSide(raw.slice(4));
      else if (raw.startsWith("+++ ")) file.path = stripSide(raw.slice(4));
      else if (raw.startsWith("index ") || !raw.trim()) {
        /* git's blob ids say nothing the operator can act on. */
      } else file.notes.push(raw);
      continue;
    }

    if (raw.startsWith("+")) {
      hunk.adds++;
      hunk.lines.push({
        line: { tone: "nominal", raw, marker: "+" },
        no: newNo++,
      });
    } else if (raw.startsWith("-")) {
      hunk.dels++;
      hunk.lines.push({
        line: { tone: "alert", raw, marker: "-" },
        no: oldNo++,
      });
    } else if (raw.startsWith("\\")) {
      hunk.lines.push({ line: { tone: "dim", raw } });
    } else {
      hunk.lines.push({ line: { tone: "text", raw }, no: newNo });
      oldNo++;
      newNo++;
    }
  }

  for (const f of files) for (const h of f.hunks) pairWords(h.lines);
  return files;
}

/** The same 1:1 removed↔replacement pairing `changedLines` does for the split
 *  and stacked layouts, applied in place to a hunk's own line list — so a
 *  changed line carries the identical word-level emphasis in all three. */
function pairWords(lines: HunkLine[]): void {
  let i = 0;
  while (i < lines.length) {
    if (lines[i].line.marker !== "-") {
      i++;
      continue;
    }
    let del = i;
    while (del < lines.length && lines[del].line.marker === "-") del++;
    let add = del;
    while (add < lines.length && lines[add].line.marker === "+") add++;
    const pairs = Math.min(del - i, add - del);
    for (let k = 0; k < pairs; k++) {
      const segs = wordDiff(
        tokenize(lines[i + k].line.raw.slice(1)),
        tokenize(lines[del + k].line.raw.slice(1)),
      );
      lines[i + k].line.segs = segs;
      lines[del + k].line.segs = segs;
    }
    i = Math.max(add, del, i + 1);
  }
}

/** The paths a `diff --git a/x b/y` header names, for the mode-only and pure-
 *  rename sections that carry no `---`/`+++` pair at all. */
const GIT_HEADER_RE = /^diff --git [ab]\/(.+) [ab]\/(.+)$/;

/** Cut a multi-file patch at its `diff --git` boundaries, tagging each section
 *  with every path it names. Deliberately text-in/text-out: `hunkFiles` answers
 *  "what changed", this answers "which bytes of the patch belong to this file",
 *  and one parser owning both boundaries is what keeps them from disagreeing. */
function fileSections(diff: string): { paths: string[]; text: string }[] {
  const sections: { paths: string[]; text: string[] }[] = [];
  let cur: { paths: string[]; text: string[] } | undefined;
  let inHunk = false;

  const note = (path: string): void => {
    if (path && path !== "/dev/null" && !cur?.paths.includes(path))
      cur?.paths.push(path);
  };

  for (const raw of diff.replace(/\n$/, "").split("\n")) {
    const header = raw.startsWith("diff --git ") || raw.startsWith("diff -");
    if (header || !cur) {
      cur = { paths: [], text: [] };
      sections.push(cur);
      inHunk = false;
    }
    if (header) {
      const named = GIT_HEADER_RE.exec(raw);
      if (named) {
        note(named[1]);
        note(named[2]);
      }
    } else if (HUNK_RE.test(raw)) {
      inHunk = true;
    } else if (!inHunk && (raw.startsWith("--- ") || raw.startsWith("+++ "))) {
      note(stripSide(raw.slice(4)));
    }
    cur.text.push(raw);
  }
  return sections.map((s) => ({ paths: s.paths, text: s.text.join("\n") }));
}

/** The one file's slice of a patch, or "" when the patch does not hold it. */
function sliceFile(diff: string, path: string): string {
  return fileSections(diff)
    .filter((s) => s.paths.includes(path))
    .map((s) => s.text)
    .join("\n");
}

/** A hunk's file label: the post-image path, or the pre-image one when the file
 *  was deleted (`/dev/null` on the other side), with a rename spelled out. */
function fileLabel(file: DiffFile): string {
  const to = file.path && file.path !== "/dev/null" ? file.path : "";
  const from = file.oldPath && file.oldPath !== "/dev/null" ? file.oldPath : "";
  if (to && from && to !== from) return `${from} → ${to}`;
  return to || from;
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

function LineRow(props: {
  line?: Line;
  class?: string;
  wrap?: boolean;
}): JSX.Element {
  const line = () => props.line ?? EMPTY_LINE;
  return (
    <div
      class={cx(
        props.wrap ? "whitespace-pre-wrap break-words" : "whitespace-pre",
        "px-3",
        TONE_CLASS[line().tone],
        props.class,
      )}
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

function StackedBody(props: { segs: Seg[]; wrap?: boolean }): JSX.Element {
  const lines = createMemo(() => stackedLines(props.segs));
  return (
    <For each={lines()}>
      {(line) => <LineRow line={line} wrap={props.wrap} />}
    </For>
  );
}

/** Each side is clipped to its own track (`min-w-0 overflow-hidden`) so a long
 *  line can never paint across the divider onto the other column. That only
 *  works because the track sizing gives the line somewhere to go:
 *  - **wrapping** — two equal `1fr` tracks; the line folds inside its column and
 *    nothing scrolls horizontally at all.
 *  - **not wrapping** — each track is at least half the width but grows to its
 *    content, so both sides overflow *together* into the one root scroller
 *    (a full-width `col-span-2` meta/context line distributes its own
 *    max-content contribution across both tracks, so it widens them too). */
const SPLIT_COLS = {
  wrap: "grid-cols-2",
  scroll: "grid-cols-[minmax(50%,max-content)_minmax(50%,max-content)]",
} as const;

function SplitBody(props: { segs: Seg[]; wrap?: boolean }): JSX.Element {
  const rows = createMemo(() => splitRows(props.segs));
  return (
    <div class={cx("grid", SPLIT_COLS[props.wrap ? "wrap" : "scroll"])}>
      <For each={rows()}>
        {(row) => (
          <Show
            when={row.full}
            fallback={
              <>
                <LineRow
                  line={row.left}
                  wrap={props.wrap}
                  class="min-w-0 overflow-hidden"
                />
                <LineRow
                  line={row.right}
                  wrap={props.wrap}
                  class="min-w-0 overflow-hidden border-l border-line"
                />
              </>
            }
          >
            {(full) => (
              <div class="col-span-2 min-w-0">
                <LineRow line={full()} wrap={props.wrap} />
              </div>
            )}
          </Show>
        )}
      </For>
    </div>
  );
}

/** Wrapping keeps every line inside the column; not wrapping lets the content
 *  track grow to its longest line so the root scroller carries both it and the
 *  gutter sideways together. */
const HUNK_COLS = {
  wrap: "grid-cols-[auto_minmax(0,1fr)]",
  scroll: "grid-cols-[auto_max-content]",
} as const;

function HunksBody(props: {
  diff: string;
  wrap?: boolean;
  /** Drop the per-file band — the caller already named the file it asked for. */
  bare?: boolean;
}): JSX.Element {
  const files = createMemo(() => hunkFiles(props.diff));
  // View state, and only ever that: which hunks the operator has folded shut.
  const [shut, setShut] = createSignal<ReadonlySet<string>>(new Set());
  const toggle = (key: string): void => {
    setShut((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  };

  return (
    <For each={files()}>
      {(file) => (
        <div class={cx("grid", HUNK_COLS[props.wrap ? "wrap" : "scroll"])}>
          <Show when={props.bare ? "" : fileLabel(file)}>
            {(label) => (
              <div class="col-span-2 sticky top-0 z-20 min-w-0 border-b border-line bg-raised px-3 py-1">
                <div class="truncate text-meta font-medium uppercase tracking-label text-bright">
                  {label()}
                </div>
              </div>
            )}
          </Show>

          {/* A binary file or a pure rename has no hunks, and git's own note is
              the entire change — dropping it would render the file as empty. */}
          <For each={file.notes}>
            {(note) => (
              <div class="col-span-2 min-w-0 px-3 text-dim">{note}</div>
            )}
          </For>

          <For each={file.hunks}>
            {(hunk) => (
              <>
                <button
                  type="button"
                  onClick={() => toggle(hunk.key)}
                  aria-expanded={!shut().has(hunk.key)}
                  class="col-span-2 sticky top-0 z-10 flex min-w-0 items-center gap-2 border-y border-line bg-surface px-3 py-1 text-left hover:bg-raised"
                >
                  <span class="shrink-0 text-meta font-medium uppercase tracking-label text-dim">
                    {/* The new-side start, except on a deletion, which has no
                        new side and whose only honest anchor is the old one. */}
                    L{hunk.newStart || hunk.oldStart}
                  </span>
                  <span class="min-w-0 flex-1 truncate text-dim">
                    {hunk.heading}
                  </span>
                  <Show when={hunk.adds}>
                    <span class="shrink-0 text-nominal">+{hunk.adds}</span>
                  </Show>
                  <Show when={hunk.dels}>
                    <span class="shrink-0 text-alert">−{hunk.dels}</span>
                  </Show>
                  <span class="shrink-0 text-meta uppercase tracking-label text-dim">
                    {shut().has(hunk.key) ? "SHOW" : "HIDE"}
                  </span>
                </button>

                <Show when={!shut().has(hunk.key)}>
                  <For each={hunk.lines}>
                    {(hl) => (
                      <>
                        <div class="select-none px-2 text-right tabular-nums text-dim">
                          {hl.no ?? ""}
                        </div>
                        <LineRow
                          line={hl.line}
                          wrap={props.wrap}
                          class="min-w-0"
                        />
                      </>
                    )}
                  </For>
                </Show>
              </>
            )}
          </For>
        </div>
      )}
    </For>
  );
}

/** Renders unified-diff text as a two-column split (removed | added, meta and
 *  context spanning both) by default, a single-column unified stack when
 *  `stacked` is set, and the **hunk layout** — collapsible `@@` groups with a
 *  line-number gutter — when the panel is too narrow to split. Changed line pairs
 *  (a removed line matched 1:1 with its replacement) get word-level emphasis
 *  on top of the line-level tone; unpaired adds/removes render plain, as
 *  before. Long lines soft-wrap inside their column by default, so the resting
 *  state has no horizontal scroll; `softWrap={false}` trades that for content-
 *  sized columns both sides scroll through together. Fills its container and
 *  owns the one scroll root — callers must not nest it in another. */
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

  const source = createMemo(() =>
    props.file ? sliceFile(props.diff, props.file) : props.diff,
  );
  const segs = createMemo(() => segment(source()));
  const layout = createMemo<"split" | "stacked" | "hunks">(() => {
    if (props.layout) return props.layout;
    if (props.stacked) return "stacked";
    return width() < STACK_BREAKPOINT ? "hunks" : "split";
  });
  const size = createMemo(() => fontStepSize(props.fontStep));
  // Wrapping is the resting state (see `softWrap`), so an omitted prop means on.
  const wrap = createMemo(() => props.softWrap ?? true);

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
      style={{ "font-size": `${size()}px` }}
    >
      <Switch fallback={<SplitBody segs={segs()} wrap={wrap()} />}>
        <Match when={layout() === "stacked"}>
          <StackedBody segs={segs()} wrap={wrap()} />
        </Match>
        <Match when={layout() === "hunks"}>
          <HunksBody diff={source()} wrap={wrap()} bare={Boolean(props.file)} />
        </Match>
      </Switch>
    </div>
  );
}
