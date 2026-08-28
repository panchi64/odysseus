import { Show, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { useGatedMount } from "./useGatedMount";

export interface ConstructionRevealProps {
  /** Open/close gate. Unlike `Reveal`, this is required — the whole component
   *  is a region the caller opens and closes, and there is no ungated form. */
  when: boolean;
  /** Which corner the single `+` starts from and returns to. Default
   *  `top-right`: the View opens from the right of the screen, so the gesture
   *  should read as coming *from* the edge the panel arrives at. */
  origin?: "top-right" | "top-left";
  /** Layout glue for the wrapper — how the region sits in its parent. */
  class?: string;
  /** Layout glue for the element that holds the children and carries the
   *  surface fade. Needed because that element sits between the wrapper and the
   *  content, so a caller laying its children out with flex has to put that
   *  flex *here*, not on `class`. */
  contentClass?: string;
  children: JSX.Element;
}

/** One corner mark: two hairlines crossing.
 *
 *  Spans rather than a glyph, so the stroke is exactly one device hairline at
 *  any zoom; and spans rather than SVG, because the panel's width is a runtime
 *  inline style and its height is `100%` — an SVG stretched to track that would
 *  need `preserveAspectRatio="none"`, which scales the two strokes by different
 *  factors and gives the `+` visibly unequal arms.
 *
 *  Offset by `-1` (4px) against a 9px mark, so it straddles the corner it names
 *  rather than sitting inside it. Positioning is by inset, never by
 *  `-translate-x-1/2`: the carriers below animate `transform`, and a centring
 *  transform here would be overwritten by the travel. */
function Mark(props: { class?: string }): JSX.Element {
  return (
    <span class={cx("absolute block h-[9px] w-[9px]", props.class)}>
      <span class="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 bg-line-strong" />
      <span class="absolute top-0 left-1/2 h-full w-px -translate-x-1/2 bg-line-strong" />
    </span>
  );
}

/**
 * **A region that draws its own frame before it fills.** The View panel's
 * arrival: a single `+` at the origin corner splits, one half travelling along
 * the top edge with a rule drawn between them, then both drop down the sides
 * with a rule closing the bottom — and the glass surface resolves inside the
 * frame that has just been described. Closing runs the gesture in reverse, so
 * the panel is taken apart rather than switched off.
 *
 * It is a sibling of `Reveal`, not a variant of it. `Reveal` says *content
 * materialized here*; this says *a place was made, and then filled*. That is
 * worth a second component only because the View is a region the operator
 * deliberately opens — a fade would say it had always been there and the light
 * had merely come up.
 *
 * **The budget is `--motion-stage` (320ms), and that is not a new exception.**
 * §8 grants the stage token to "a whole region arriving or leaving"; the View's
 * previous `Reveal` already ran at it, and this replaces that reveal. The phases
 * overlap by 20ms on purpose: two strictly sequential beats inside 320ms read as
 * a stutter, where an overlap reads as one continuous L-shaped gesture. The
 * timeline lives in `theme.css` under THE CONSTRUCTION REVEAL — this file owns
 * the geometry, that file owns the choreography.
 *
 * **The content is one fade, never a stagger.** §8 forbids staggered cascades,
 * and this is one region arriving rather than a list of things: the surface and
 * everything inside it resolve together, on a single animation.
 *
 * **Every moving part rides a full-size carrier, not the mark itself.** A
 * percentage `translate` resolves against the *animated element's own* border
 * box, so translating a 9px mark by 100% moves it 9px — not across the panel.
 * Each mark therefore sits at its destination inside an `inset-0` carrier, and
 * the carrier is what travels: 100% of the carrier is 100% of the panel, which
 * is the distance actually wanted, at any width the resize handle produces.
 */
export function ConstructionReveal(
  props: ConstructionRevealProps,
): JSX.Element {
  const [local] = splitProps(props, [
    "when",
    "origin",
    "class",
    "contentClass",
    "children",
  ]);
  const gate = useGatedMount(() => local.when);
  const leftOrigin = () => local.origin === "top-left";

  /* `--frame-from-x` is where the travelling carrier starts, signed by which
     corner the gesture comes from; `--frame-origin-x` is the `transform-origin`
     the horizontal rules unfurl from, so both grow away from that same corner.
     `--frame-from-y` is the drop, always downward from above. */
  const vars = (): JSX.CSSProperties => ({
    "--frame-from-x": leftOrigin() ? "-100%" : "100%",
    "--frame-origin-x": leftOrigin() ? "left" : "right",
    "--frame-from-y": "-100%",
  });

  /** The corner the gesture starts at, and the one it travels to. */
  const near = () => (leftOrigin() ? "-left-1" : "-right-1");
  const far = () => (leftOrigin() ? "-right-1" : "-left-1");

  return (
    <Show when={gate.mounted()}>
      <div
        class={cx("ody-frame relative isolate", local.class)}
        style={vars()}
        /* `data-ready` releases the whole timeline at once — every animation in
           theme.css is scoped under it, so until it appears nothing is running
           and the region is held invisible. Withholding the animations is what
           makes the wait work: the marks carry their classes statically, so
           anything not scoped would start on mount and could finish before the
           tree behind it had even settled. */
        data-ready={gate.ready() ? "" : undefined}
        data-closed={gate.closing() ? "" : undefined}
        /* `.ody-frame` carries a lifecycle span — an invisible animation lasting
           exactly as long as the whole sequence — so `animationend` fires on
           THIS element at the true end. `useGatedMount` ignores everything that
           merely bubbles up from the marks, the rules, or the content, which is
           what stops the region being torn out on whichever phase happens to
           finish first. See the note in theme.css. */
        onAnimationEnd={gate.onAnimationEnd}
      >
        {/* The frame. Decorative and never interactive, in the wrapper's own
            stacking context so it can overhang the panel's edge without
            escaping into the page or swallowing a click meant for the content. */}
        <div
          class="pointer-events-none absolute inset-0 z-10"
          aria-hidden="true"
        >
          {/* Phase 1 — the origin mark is simply there; its twin travels the
              top edge with a rule drawn between them. */}
          <Mark class={cx("-top-1", near())} />
          <div class="ody-frame-mark-a absolute inset-0">
            <Mark class={cx("-top-1", far())} />
          </div>
          <span class="ody-frame-rule-top absolute top-0 right-0 left-0 h-px bg-line" />

          {/* Phase 2 — both marks drop to the bottom edge, the sides close
              behind them, and the bottom rule completes the frame. */}
          <div class="ody-frame-mark-b absolute inset-0">
            <Mark class={cx("-bottom-1", near())} />
            <Mark class={cx("-bottom-1", far())} />
          </div>
          <span class="ody-frame-rule-side absolute top-0 bottom-0 left-0 w-px bg-line" />
          <span class="ody-frame-rule-side absolute top-0 right-0 bottom-0 w-px bg-line" />
          <span class="ody-frame-rule-bottom absolute right-0 bottom-0 left-0 h-px bg-line" />
        </div>

        <div class={cx("ody-frame-surface", local.contentClass)}>
          {local.children}
        </div>
      </div>
    </Show>
  );
}
