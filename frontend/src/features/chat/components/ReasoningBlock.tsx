import {
  Show,
  createEffect,
  createMemo,
  createSignal,
  on,
  type JSX,
} from "solid-js";
import { Collapse, Text } from "~/ui";
import { ProcessRow, Sep } from "./ProcessRow";

/** The animation that plays when the stage clears. The component waits for this
 *  by name rather than holding a duration of its own — the timing lives in
 *  `--motion-stage`, and a copy here would be a second number to keep in sync
 *  with a token that exists precisely so there is only one. */
const CLEAR_ANIMATION = "ody-stage-clear";

/** The settled row's glyph. Reasoning is not a tool, so it has no registry entry
 *  to borrow; `cpu` is the machine doing its own work and is unclaimed by any
 *  tool category, so it can't be mistaken for one. Matches `WorkLogHeader`. */
const THINK_ICON = "cpu" as const;

/** How much of the trace the collapsed row shows. The same slot a tool row's
 *  `detail` fills — what this step was *about* — so a column of thinks and calls
 *  reads as one sequence rather than as two kinds of thing. */
const PEEK_CHARS = 90;

/** The reasoning stream (design §10.10) — the model's thought process, in the
 *  two states the machine voice implies.
 *
 *  **Live.** While tokens are arriving, the trace is not a message: it is the
 *  computer working *behind* the response area. It renders as a clipped
 *  background layer — mono, uniformly and barely tinted, with no gradient: a
 *  faded edge would make it a decorated panel, and this is meant to read as a
 *  flat wall of machine text. Bottom-anchored, so new tokens push older lines up
 *  and out of frame and the newest is always at the bottom. It never eases:
 *  this is the machine register (§8), so tokens land hard as they arrive.
 *
 *  **Resolved.** The layer fades out (the human register — the interface
 *  clearing the stage, not a control responding) and what remains is a collapsed
 *  disclosure holding the full trace, available but out of the way.
 *
 *  `open` (expand-all / collapse-all) wins over both when defined. */
export function ReasoningBlock(props: {
  reasoning: string;
  open?: boolean;
  /** This is the turn's trailing block and the run is still going. */
  active?: boolean;
  /** Tokens are still streaming in. */
  streaming?: boolean;
}): JSX.Element {
  const [open, setOpen] = createSignal(false);
  // True through the fade-out, after the stream has stopped — the live layer
  // stays mounted so it has something to animate from.
  const [fading, setFading] = createSignal(false);

  const live = (): boolean => Boolean(props.active && props.streaming);

  // Adopt an explicit expand-all/collapse-all; local toggles work between them.
  createEffect(() => {
    if (props.open !== undefined) setOpen(props.open);
  });

  // Clear the stage exactly on the live -> settled edge. The layer stays mounted
  // until the animation reports itself finished (see `onAnimationEnd` below).
  createEffect(
    on(live, (now, prev) => {
      if (!prev || now) return;
      setFading(true);
    }),
  );

  const toggle = (): void => {
    setOpen((v) => !v);
  };

  /* The trace's opening line, flattened — a trace is paragraphs of prose and the
     row is one line, so newlines have to go or the row's height follows the
     content.

     **Bounded before it is flattened, and that is the whole point.** A memo is
     eager: it recomputes on every delta while the trace is still streaming, even
     though the settled row it feeds is not on screen then. Flattening the whole
     string each time is O(n) per delta and so O(n²) over a run — on the main
     thread, inside the stream handler, to produce ninety characters nobody is
     looking at yet. A deep-research trace is large enough for that to be felt.
     Taking a fixed head first makes each pass constant-cost regardless of how
     long the trace grows. (Same reasoning as `lineCount` in `toolSummary.ts`.) */
  const peek = createMemo(() => {
    // Generous enough that collapsing runs of whitespace inside it still leaves
    // more than PEEK_CHARS of text in any realistic trace.
    const head = props.reasoning.slice(0, PEEK_CHARS * 4);
    const flat = head.replace(/\s+/g, " ").trim();
    if (flat.length > PEEK_CHARS) return `${flat.slice(0, PEEK_CHARS - 1)}…`;
    // The head was cut short, so there IS more trace even though the flattened
    // text came in under the limit — say so rather than implying this is all.
    return head.length < props.reasoning.length ? `${flat}…` : flat;
  });

  return (
    <Show
      when={live() || fading()}
      fallback={
        // The wall fades to the background, then the settled row fades in where
        // it stood — above the response — so the handoff reads as one movement
        // rather than as a block being swapped out.
        <div class="ody-fade-in">
          <ProcessRow
            open={open()}
            onToggle={toggle}
            icon={THINK_ICON}
            label="Reasoning"
          >
            {/* The same "what was this about" slot a tool row fills with its
                salient argument. Without it, a settled think was a bare word on
                a rail of rows that all carried a detail — the one row in the
                column that said nothing about itself. */}
            <Show when={peek()}>
              <Sep />
              <Text variant="micro" tone="dim" class="min-w-0 truncate">
                {peek()}
              </Text>
            </Show>
          </ProcessRow>
          <Collapse open={open()}>
            {/* The trace itself is machine output, so it keeps the mono voice
                even at rest — just dim, and no longer tinted or clipped. */}
            <Text
              variant="micro"
              tone="dim"
              class="block cursor-text whitespace-pre-wrap px-2 py-1.5"
            >
              {props.reasoning}
            </Text>
          </Collapse>
        </div>
      }
    >
      {/* A fixed-height stage, tall enough that the trace reads as a wall rather
          than a ticker. The height is deliberately constant so the transcript
          does not reflow line-by-line as tokens arrive — the text cascades
          *inside* the clip instead of growing the page.

          Nothing sits in the foreground. The wall is its own indicator: text
          arriving is the most direct signal there is that the model is working,
          and the live rail beside it already says so in light. A label and a
          throbber on top were both restating it. */}
      <div
        class="ody-reasoning-stage"
        data-clearing={fading() ? "" : undefined}
        aria-hidden="true"
        onAnimationEnd={(e) => {
          if (e.animationName === CLEAR_ANIMATION) setFading(false);
        }}
      >
        <div class="ody-reasoning">
          <div class="ody-reasoning-tail">{props.reasoning}</div>
        </div>
      </div>
      {/* The live layer is decorative texture, so it is aria-hidden above; the
          trace stays reachable to assistive tech through this live region. */}
      <span class="sr-only" aria-live="polite">
        Model is reasoning.
      </span>
    </Show>
  );
}
