import { Show, createEffect, createSignal, type JSX } from "solid-js";
import { Caret, Markdown } from "~/ui";
import {
  INTERVAL_SEED,
  REVEAL_MS,
  extendSchedule,
  firstLiveIndex,
  nextInterval,
  revealDelay,
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

/** Every animatable text node under `root`, in document order, with the absolute
 *  character index each one starts at. Machine-voice subtrees are rejected
 *  outright, so their characters are neither wrapped nor counted — the index
 *  space is *animatable* characters, which is what keeps it stable between
 *  passes, and it is what makes a code block land hard inside an answer that is
 *  easing in around it. Collected before any mutation, since splitting a node
 *  mid-walk would invalidate the walker. */
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
  span.className = "ody-token-in";
  // Duration comes from the same constant the schedule reasons about, so the
  // two can't drift; the delay is what carries this character's phase across a
  // re-render.
  span.style.setProperty("--reveal-ms", `${REVEAL_MS}ms`);
  span.style.animationDelay = `${delay}ms`;
  span.textContent = char;
  return span;
}

/**
 * Apply `starts` to the answer's DOM: every character still inside its reveal
 * window becomes a span carrying its own delay, and everything settled is left
 * as plain text. Extends the schedule to cover any newly-arrived characters and
 * returns it.
 *
 * Rebuilding the wrappers wholesale on each delta is deliberate — the trailing
 * block's DOM is new anyway, and re-deriving each character's delay from its
 * *absolute* start is exactly what lets a fade continue across that rebuild
 * rather than restarting. The work is bounded by the live window (roughly
 * `REVEAL_MS` worth of characters), not by the length of the answer.
 */
function applyReveal(
  root: HTMLElement,
  starts: number[],
  now: number,
  interval: number,
): number[] {
  const { nodes, count } = animatableText(root);
  starts = extendSchedule(starts, count, now, interval);
  const from = firstLiveIndex(starts, now);
  if (from >= count) return starts;

  for (const { node, base } of nodes) {
    const len = node.data.length;
    if (base + len <= from || !node.parentNode) continue;
    // Split the node once into "settled" and "still resolving", then rebuild
    // only the second half a character at a time.
    const cut = Math.max(0, from - base);
    const frag = document.createDocumentFragment();
    if (cut > 0)
      frag.appendChild(document.createTextNode(node.data.slice(0, cut)));
    for (let i = cut; i < len; i++) {
      const delay = revealDelay(starts[base + i], now);
      frag.appendChild(
        delay === null
          ? document.createTextNode(node.data[i])
          : revealSpan(node.data[i], delay),
      );
    }
    node.parentNode.replaceChild(frag, node);
  }
  return starts;
}

/** A passage of the answer — full-width and bright. The active, still-streaming
 *  passage carries the caret, resolves each arriving character in on its own
 *  schedule (§8, human register), and defers code-copy enhancement until it
 *  settles.
 *
 *  `streamStable` while live keeps the DOM of every settled block, so only the
 *  trailing block re-parses per delta — which is what stops KaTeX/markdown
 *  flicker. It is also why the reveal is scheduled in absolute time: that
 *  re-parse destroys anything mid-animation, and only a character that knows
 *  when it *started* can pick its fade back up rather than restarting it. See
 *  `streamReveal.ts`. */
export function AnswerText(props: {
  text: string;
  active?: boolean;
  streaming?: boolean;
}): JSX.Element {
  const live = () => Boolean(props.active && props.streaming);

  /* Latched, and this is what stops the screen flashing when a run finishes.
     `Markdown` renders a *different element* for `streamStable` than for its
     default path — it has to, since Solid's `innerHTML` prop can't coexist with
     rendered children on one node. Passing `live()` straight through therefore
     flipped that flag at the exact moment the answer completed, and Solid tore
     down the entire rendered answer and rebuilt it: a full re-parse, a fresh
     DOM, KaTeX re-rendered, every `pre` and `table` re-wrapped. On a long answer
     that is a visible flash at the worst possible moment — the instant the
     operator starts reading.

     Once a passage has streamed it keeps the block path forever. The two paths
     render the same content (the block path exists to replicate the prose
     cascade at the block-wrapper level), so there is nothing to switch back
     for. A message that never streamed — history, a settled turn — never takes
     the block path at all, which is the cheaper read for a long transcript. */
  const [streamStable, setStreamStable] = createSignal(live());
  createEffect(() => {
    if (live()) setStreamStable(true);
  });

  let host: HTMLDivElement | undefined;
  // Absolute start time per animatable character. Empty until the passage goes
  // live; a message that arrives complete (history, a settled turn) never
  // schedules anything and so renders without animating.
  let starts: number[] = [];
  // Running estimate of the gap between deltas, which is what the stagger is
  // paced against — see `streamReveal.ts`. Seeded rather than measured from the
  // first delta, since there is nothing to measure against yet.
  let interval = INTERVAL_SEED;
  let lastDelta = 0;

  createEffect(() => {
    // Read the source so this effect re-runs on every delta (the value itself
    // is not needed — the DOM Markdown just committed is what gets walked).
    void props.text;
    // A passage that never streamed (history, a settled turn) schedules nothing
    // and renders instantly. One that has streamed keeps going for a final pass
    // after `live()` drops: the run's last characters land in the same tick the
    // stream closes, and bailing here made them the one part of the answer that
    // appeared without resolving — a pop right at the end of an otherwise smooth
    // reveal.
    if (!host || (!live() && starts.length === 0)) return;
    // Let Markdown commit its own DOM for this delta first.
    queueMicrotask(() => {
      if (!host) return;
      const now = performance.now();
      // Attaching to a passage that already has text (a resumed stream): treat
      // what is on screen as settled rather than animating the whole thing in.
      if (starts.length === 0) {
        const existing = host.textContent?.length ?? 0;
        starts = Array.from({ length: existing }, () => now - REVEAL_MS);
      }
      if (lastDelta) interval = nextInterval(interval, now - lastDelta);
      lastDelta = now;
      starts = applyReveal(host, starts, now, interval);
    });
  });

  return (
    <div>
      <div ref={host} class="inline">
        {/* `copyCode` stays on THROUGHOUT, including while streaming. It used to
            be gated on `!live()` to save a DOM scan per delta, but that gate was
            paid for at the worst moment: flipping it on completion ran the
            enhancement pass over a finished answer, and that pass *physically
            moves* every `pre` and `table` — out of the tree and back inside a
            wrapper. Re-laying-out and re-rasterizing every code block the
            instant the answer settles is a redraw the operator sees.

            Enhancing as we go does the same work incrementally on the trailing
            block instead, and leaves nothing to do at the end. The buttons are
            hidden until their block is hovered, so nothing appears mid-stream
            either. */}
        <Markdown class="inline" streamStable={streamStable()}>
          {props.text}
        </Markdown>
      </div>
      <Show when={live()}>
        {" "}
        <Caret class="text-bright" />
      </Show>
    </div>
  );
}
