import { Show, createEffect, createSignal, on, type JSX } from "solid-js";
import { Disclosure, Text } from "~/ui";

/** The animation that plays when the stage clears. The component waits for this
 *  by name rather than holding a duration of its own — the timing lives in
 *  `--motion-stage`, and a copy here would be a second number to keep in sync
 *  with a token that exists precisely so there is only one. */
const CLEAR_ANIMATION = "ody-stage-clear";

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

  return (
    <Show
      when={live() || fading()}
      fallback={
        // The wall fades to the background, then the accordion fades in where it
        // stood — above the response — so the handoff reads as one movement
        // rather than as a block being swapped out.
        <Disclosure
          label="Reasoning"
          open={open()}
          onToggle={toggle}
          class="mt-2"
          triggerClass="ody-fade-in"
        >
          {/* The trace itself is machine output, so it keeps the mono voice
              even at rest — just dim, and no longer tinted or clipped. */}
          <Text
            variant="micro"
            tone="dim"
            class="block cursor-text whitespace-pre-wrap"
          >
            {props.reasoning}
          </Text>
        </Disclosure>
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
