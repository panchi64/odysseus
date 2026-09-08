/**
 * The answer reveal's DOM half — wrapping characters so they resolve in, and taking the
 * wrappers back out once they have.
 *
 * The scheduling math lives in `streamReveal.ts` and is pure; this is the part that
 * touches nodes. Two rules shape all of it:
 *
 * **Only the trailing block is ever wrapped.** `Markdown streamStable` re-renders the
 * block the delta landed in and leaves every earlier block's DOM alone, so walking the
 * whole answer per delta was O(answer) work for a bounded result — and worse, it
 * re-entered blocks that already held wrappers and nested a second span inside each one.
 * The walk is scoped to the last `[data-block-index]`, and a character's absolute index
 * is `base + local`, so `streamReveal`'s absolute-time schedule is untouched.
 *
 * **A settled block gets its wrappers taken back out.** Nothing did this before, so every
 * character that passed through the reveal window kept its span, its inline
 * `animation-delay`, and its filled animation for the life of the session. A finished
 * fade is invisible; the span it left behind is not — it is a permanent element in the
 * transcript, and one-character spans break text shaping into one-character runs, which
 * is paid again on every repaint of a scrolling transcript. Unwrapping is guarded on the
 * whole block having finished, so it can never cut a fade short.
 */

import {
  REVEAL_MS,
  extendSchedule,
  firstLiveIndex,
  revealDelay,
  settledUnits,
  unitBases,
} from "../streamReveal";

/** Subtrees the fade must not enter, because their contents are the machine's
 *  voice and the machine does not ease (§8). Code and samples are mono by
 *  element; `.katex` is neither voice, and threading spans through KaTeX's
 *  markup would be meddling with a layout we don't own. `.font-mono` catches
 *  anything that opted in by class.
 *
 *  `table` is here for three reasons that agree. A table is a dense data panel
 *  (§10) whose header band is already mono because a column header names a
 *  machine field — and it is mono by `font-family`, not by a class, so nothing
 *  else in this list would have caught it. Its cells are emitted values, which
 *  is the §2 test for the machine voice. And the eye reads a grid in two
 *  dimensions, so a reveal sweeping left-to-right through cells reads as
 *  flicker rather than as arrival — on top of the column widths still
 *  reflowing as rows stream in.
 *
 *  `.ody-open-path` is a file the answer pointed at (markdownLinks.ts). It is
 *  mono by rule rather than by the `.font-mono` class, so nothing above catches
 *  it, and it is machine voice by the same §2 test the table is: a path is a
 *  literal string the machine will act on, not a phrase being spoken. */
const MACHINE_VOICE =
  "code, pre, kbd, samp, table, .katex, .font-mono, .ody-open-path";

const SPAN_CLASS = "ody-token-in";

/** Animatable character counts for blocks that are no longer the trailing one, keyed by
 *  the element itself.
 *
 *  Keyed by identity rather than by index on purpose: `Markdown`'s `<For>` iterates raw
 *  block sources, so a block whose source changed is a *different element*, and a stale
 *  count can never be read back for it. A block whose source did not change keeps its
 *  node and its count, which is what makes the per-delta cost proportional to the number
 *  of blocks rather than to the length of the answer. */
const settledCounts = new WeakMap<Element, number>();

/** Every animatable text node under `root`, in document order, with the character index
 *  each one starts at *within `root`*. Machine-voice subtrees are rejected outright, so
 *  their characters are neither wrapped nor counted — the index space is *animatable*
 *  characters, which is what keeps it stable between passes, and it is what makes a code
 *  block land hard inside an answer that is easing in around it. Collected before any
 *  mutation, since splitting a node mid-walk would invalidate the walker. */
function animatableText(root: HTMLElement): {
  nodes: { node: Text; base: number }[];
  count: number;
} {
  const walker = document.createTreeWalker(
    root,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    {
      acceptNode: (node) => {
        if (node.nodeType !== Node.ELEMENT_NODE)
          return NodeFilter.FILTER_ACCEPT;
        // REJECT prunes the whole subtree; SKIP passes over the element itself
        // and keeps descending, which is what every other element wants.
        return (node as Element).matches(MACHINE_VOICE)
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_SKIP;
      },
    },
  );
  const nodes: { node: Text; base: number }[] = [];
  let count = 0;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const node = n as Text;
    nodes.push({ node, base: count });
    count += node.data.length;
  }
  return { nodes, count };
}

/** One character, wrapped so it resolves in on its own schedule. */
function revealSpan(char: string, delay: number): HTMLSpanElement {
  const span = document.createElement("span");
  span.className = SPAN_CLASS;
  // Duration comes from the same constant the schedule reasons about, so the
  // two can't drift; the delay is what carries this character's phase across a
  // re-render.
  span.style.setProperty("--reveal-ms", `${REVEAL_MS}ms`);
  span.style.animationDelay = `${delay}ms`;
  span.textContent = char;
  return span;
}

/**
 * The units the answer is walked in: `Markdown streamStable`'s top-level blocks, or the
 * host itself when there are none (the default render path, or an answer so short it has
 * yet to produce a block wrapper).
 *
 * A plain descendant query rather than a child combinator because `Markdown` puts its
 * blocks inside its own `.ody-prose` element, and an answer never nests a second
 * `Markdown` inside itself — the only way another `[data-block-index]` could appear here.
 */
function revealUnits(host: HTMLElement): HTMLElement[] {
  const blocks = host.querySelectorAll<HTMLElement>("[data-block-index]");
  return blocks.length ? Array.from(blocks) : [host];
}

/** Put every wrapper in `unit` back as plain text and re-join the runs it split.
 *  `normalize()` is the half that matters for paint: without it the block keeps one text
 *  node per character and is shaped one character at a time. */
export function unwrapReveal(unit: HTMLElement): void {
  const spans = unit.querySelectorAll<HTMLElement>(`.${SPAN_CLASS}`);
  if (!spans.length) return;
  spans.forEach((span) =>
    span.replaceWith(document.createTextNode(span.textContent ?? "")),
  );
  unit.normalize();
}

/** Unwrap every block, settled or not — the terminal flush, run once the last character's
 *  fade is over and no more text is coming. */
export function unwrapAll(host: HTMLElement): void {
  revealUnits(host).forEach(unwrapReveal);
}

/**
 * Apply `starts` to the answer's DOM: every character of the trailing block still inside
 * its reveal window becomes a span carrying its own delay, every settled block gives its
 * spans back, and everything else is left alone. Extends the schedule to cover any
 * newly-arrived characters and returns it.
 *
 * Rebuilding the trailing block's wrappers wholesale on each delta is deliberate — its
 * DOM is new anyway, and re-deriving each character's delay from its *absolute* start is
 * exactly what lets a fade continue across that rebuild rather than restarting.
 */
export function applyReveal(
  host: HTMLElement,
  starts: number[],
  now: number,
  interval: number,
): number[] {
  const units = revealUnits(host);
  const last = units.length - 1;
  // Walked ONCE, and the result is carried to `wrapUnit` rather than re-derived there.
  // This is the only unit that changes between deltas, so it is the only one whose walk
  // cannot be cached — which makes a second walk of it the most expensive thing this
  // function could redundantly do, and this function exists to stop doing exactly that.
  const tail = animatableText(units[last]);
  const counts = units.map((unit, i) => {
    if (i === last) {
      settledCounts.set(unit, tail.count);
      return tail.count;
    }
    // A settled block's count cannot change without its element changing with it, so a
    // hit here is always current — see `settledCounts`.
    const cached = settledCounts.get(unit);
    if (cached !== undefined) return cached;
    const count = animatableText(unit).count;
    settledCounts.set(unit, count);
    return count;
  });
  const bases = unitBases(counts);
  const total = bases[last] + counts[last];

  starts = extendSchedule(starts, total, now, interval);
  const from = firstLiveIndex(starts, now);

  // Settled blocks first: taking wrappers out cannot move an index, so the order only
  // matters for keeping the work off the trailing block's pass.
  for (const i of settledUnits(counts, from)) unwrapReveal(units[i]);

  if (from >= total) return starts;
  wrapUnit(tail.nodes, bases[last], starts, now, from);
  return starts;
}

/** Split at the reveal front and rebuild only what is still resolving.
 *
 *  Takes the walked nodes and the front rather than re-deriving either: both are already
 *  in hand at the one call site, and two places computing the same cut is two places to
 *  keep in agreement. */
function wrapUnit(
  nodes: { node: Text; base: number }[],
  unitBase: number,
  starts: number[],
  now: number,
  from: number,
): void {
  for (const { node, base } of nodes) {
    const abs = unitBase + base;
    const len = node.data.length;
    if (abs + len <= from || !node.parentNode) continue;
    // Split the node once into "settled" and "still resolving", then rebuild
    // only the second half a character at a time.
    const cut = Math.max(0, from - abs);
    const frag = document.createDocumentFragment();
    if (cut > 0)
      frag.appendChild(document.createTextNode(node.data.slice(0, cut)));
    for (let i = cut; i < len; i++) {
      const delay = revealDelay(starts[abs + i], now);
      frag.appendChild(
        delay === null
          ? document.createTextNode(node.data[i])
          : revealSpan(node.data[i], delay),
      );
    }
    node.parentNode.replaceChild(frag, node);
  }
}
