import { Show, splitProps, type JSX } from "solid-js";
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
  /** Duration in ms. Defaults to `--motion-base` (180ms). Never exceed 240 —
   *  that is the human register's ceiling (§8). */
  duration?: number;
  /** Starting blur in px. Default 3. This is what makes the arrival read as the
   *  content *materializing* rather than as a light being turned up on something
   *  that was already there. `0` opts out — worth doing for a very large surface,
   *  where blurring the whole raster for a frame or two can cost more than the
   *  effect is worth. */
  blur?: number;
  /** Gate the reveal. While false nothing is rendered; when it flips true the
   *  content mounts and animates in. Omit to reveal once, on mount.
   *
   *  Because this mounts rather than hides, flipping it back and forth replays
   *  the animation — which is what a panel opening and closing wants. */
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
 * Two things it deliberately does not do:
 * - **It never exits.** An exit animation delays the operator getting what they
 *   asked for, and a `Show` that has to wait for one is a class of bug (stale
 *   content, double-mount) with nothing to show for it. Things arrive gently and
 *   leave immediately.
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
    ...(local.duration === undefined
      ? {}
      : { "--reveal-ms": `${local.duration}ms` }),
    ...(local.blur === undefined ? {} : { "--reveal-blur": `${local.blur}px` }),
  });

  return (
    <Show when={local.when ?? true}>
      <div
        class={cx(motionClass[local.motion ?? "fade"], local.class)}
        style={style()}
      >
        {local.children}
      </div>
    </Show>
  );
}
