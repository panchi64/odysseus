import type { JSX } from "solid-js";
import { cx } from "../cx";

/** Which edge of the scroll region the overlay sits on — and so which way the fade
 *  falls: strongest at that edge, gone one band into the content. */
export type ScrollFadeEdge = "top" | "bottom";

export interface ScrollFadeProps {
  edge: ScrollFadeEdge;
  class?: string;
}

/**
 * The band a scroll region dissolves into under an overlaid edge — a progressive
 * backdrop blur with a ground-colour tint on the same falloff (`.ody-scroll-fade`).
 *
 * **Mount it as the first child of the overlay, and give the overlay a position.** It
 * fills that parent and reaches one `--scroll-fade-band` past the side facing the
 * content; the overlay's own content has to be positioned too (`relative` is enough),
 * or this absolutely placed box paints over it. The scroll region keeps an inset of
 * that same band at the edge, so what rests there at the end of the scroll clears the
 * fade rather than sitting in it.
 *
 * Decoration only: hidden from assistive tech and transparent to the pointer, since it
 * lies over live content.
 */
export function ScrollFade(props: ScrollFadeProps): JSX.Element {
  return (
    <div
      aria-hidden="true"
      data-edge={props.edge}
      class={cx("ody-scroll-fade", props.class)}
    >
      <span class="ody-scroll-fade-blur-1" />
      <span class="ody-scroll-fade-blur-2" />
      <span class="ody-scroll-fade-blur-3" />
      <span class="ody-scroll-fade-tint" />
    </div>
  );
}
