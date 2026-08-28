import {
  Show,
  createEffect,
  createSignal,
  onCleanup,
  splitProps,
  untrack,
  type JSX,
} from "solid-js";
import { cx } from "../cx";

/** How the content arrives. `fade` is opacity alone — for something appearing
 *  in place, where movement would imply it came from somewhere. `rise` adds a
 *  short glide up, for something entering the screen. */
export type RevealMotion = "fade" | "rise";

const motionClass: Record<RevealMotion, string> = {
  fade: "ody-fade-in",
  rise: "ody-rise",
};

export interface RevealProps {
  /** Default `fade`. */
  motion?: RevealMotion;
  /** Glide distance in px for `rise`. Default 4 — an overlay settling. The
   *  transcript's turn arrival uses 10, which is about as far as this register
   *  goes before the movement starts reading as decoration. Ignored by `fade`. */
  distance?: number;
  /** Duration in ms. Defaults by kind: an **ungated** reveal is content arriving
   *  into a place that already exists, and paces at `--motion-base` (180ms); a
   *  **gated** one is a whole region being opened or closed, and paces at
   *  `--motion-stage` (320ms), which is what that token is for. A region moving
   *  at a control's speed reads as a flash — there is much more of it to take
   *  in, and nothing is waiting on it. */
  duration?: number;
  /** Starting blur in px. Default 3. This is what makes the arrival read as the
   *  content *materializing* rather than as a light being turned up on something
   *  that was already there. `0` opts out — worth doing for a very large surface,
   *  where blurring the whole raster for a frame or two can cost more than the
   *  effect is worth. */
  blur?: number;
  /** Gate the reveal. While false nothing is rendered; when it flips true the
   *  content mounts and animates in — and when it flips back, the content
   *  **dissolves the way it resolved** before unmounting, rather than being cut.
   *
   *  This is the only way to get an exit out of `Reveal`, and deliberately so:
   *  an ungated reveal is content arriving in a place that keeps it, where an
   *  exit animation would only delay the operator getting what they asked for.
   *  A gated one is a region the caller genuinely opens and closes, and there a
   *  hard cut is the jolt. */
  when?: boolean;
  /** Layout glue for the wrapper. */
  class?: string;
  children: JSX.Element;
}

/**
 * **The one way something in the human voice arrives.** Wraps its children in an
 * element that *materializes* — resolving out of a blur while it fades, and with
 * `rise`, settling the last few pixels into place as it does.
 *
 * The blur is the load-bearing part. Fading opacity alone reads as a light being
 * turned up on something that was already sitting there; coming out of a blur
 * reads as the thing arriving. It is the difference between revealed and made.
 *
 * Reach for it whenever the interface puts something on screen on the operator's
 * behalf: a panel revealing, a section expanding, a result landing. The register
 * is the point (§8) — anything the interface does eases, and anything the
 * *machine* does snaps, so a mono readout must never be wrapped in this. That
 * contrast is what lets the operator tell the two apart without reading a word.
 *
 * Two things about how it comes and goes:
 * - **Ungated, it never exits.** Content that simply arrives somewhere and stays
 *   should leave the instant it is no longer wanted; an exit animation there
 *   only delays the operator. Pass `when` and it gains one — see that prop.
 * - **It does not animate on every update.** The animation fires on mount. To
 *   replay it, change `when` — or key the subtree, if the content itself is what
 *   changed.
 *
 * For a case that cannot take a wrapper — a portal root, a node built by hand —
 * the underlying `.ody-fade-in` / `.ody-rise` classes are still there.
 */
export function Reveal(props: RevealProps): JSX.Element {
  const [local] = splitProps(props, [
    "motion",
    "distance",
    "duration",
    "blur",
    "when",
    "class",
    "children",
  ]);

  // The presets carry the defaults; only an explicit override is written, so a
  // Reveal with no props emits no inline style at all.
  const style = (): JSX.CSSProperties => ({
    ...(local.distance === undefined
      ? {}
      : { "--reveal-y": `${local.distance}px` }),
    // A gated reveal opens and closes a whole region, so it takes the stage
    // duration rather than a control's. Still a token, not a number — an
    // explicit `duration` overrides both.
    ...(local.duration !== undefined
      ? { "--reveal-ms": `${local.duration}ms` }
      : local.when !== undefined
        ? { "--reveal-ms": "var(--motion-stage)" }
        : {}),
    ...(local.blur === undefined ? {} : { "--reveal-blur": `${local.blur}px` }),
  });

  // A gated reveal stays mounted through its exit so the animation has something
  // to run on; an ungated one is simply always there.
  const gated = (): boolean => local.when !== undefined;
  const [mounted, setMounted] = createSignal(local.when ?? true);
  const closing = (): boolean => gated() && !local.when;

  /* Whether the entry animation may start. Ungated reveals start at mount, as
     they always have — they wrap content that is already cheap to render.
     A *gated* one waits a frame, because it is opening a whole region: if that
     region's first render is expensive (an iframe, a highlighter, a document
     viewer), the main thread can stay blocked for longer than the animation
     lasts, and the first frame to paint is the last one — the region simply
     appears. Waiting costs nothing, since an animation carries its own start and
     plays in full whenever it begins.

     Two frames, not one: the first lands in the same batch as the render that
     mounted us, so the work has not necessarily finished by then. */
  const [ready, setReady] = createSignal(!gated());
  let frame = 0;
  const start = (): void => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => setReady(true));
    });
  };
  createEffect(() => {
    if (!(local.when ?? true)) return;
    setMounted(true);
    if (!untrack(ready)) start();
  });
  onCleanup(() => cancelAnimationFrame(frame));

  return (
    <Show when={mounted()}>
      <div
        class={cx(
          // Held invisible until the tree has settled, then the motion class
          // arrives and its animation plays from there.
          ready() ? motionClass[local.motion ?? "fade"] : "ody-reveal-hold",
          local.class,
        )}
        style={style()}
        data-closed={closing() ? "" : undefined}
        onAnimationEnd={(e) => {
          // Only this element's own exit unmounts. Animations inside the revealed
          // content bubble up here too — a streamed token, a nested reveal — and
          // any of them would otherwise tear the region out mid-exit. `closing()`
          // is read as the event fires, so a region reopened part-way through
          // stays put.
          if (e.target !== e.currentTarget || !closing()) return;
          setMounted(false);
          // Re-arm, so reopening waits for its own settled frame rather than
          // animating against whatever the next mount is busy building.
          setReady(false);
        }}
      >
        {local.children}
      </div>
    </Show>
  );
}
