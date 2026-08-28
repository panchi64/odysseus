import { Show, createEffect, createSignal, type JSX } from "solid-js";
import { cx } from "../cx";

export interface CollapseProps {
  /** Whether the region is open. Changing it animates; mounting does not. */
  open: boolean;
  /** Layout glue for the collapsing container. */
  class?: string;
  children: JSX.Element;
}

/**
 * **A region that opens and closes over its own height**, without the caller
 * knowing what that height is.
 *
 * Use it wherever content genuinely comes and goes — a status line that has
 * something to say only while work is running, a panel revealing, a summary that
 * appears once there is something to summarize. The alternative is content
 * vanishing, which takes everything below it with it: a jump the reader has to
 * re-find their place after, and the single most common reason a screen "feels
 * like it redrew".
 *
 * Two details it gets right that a naive version does not:
 *
 * - **It leaves nothing behind.** Once closed, it unmounts — but only *after*
 *   the closing transition ends. A collapsed element that stays mounted is
 *   invisible and still consumes its parent's `gap`, so a spaced stack keeps a
 *   hole exactly where the thing used to be.
 * - **It does not animate on mount.** Transitions never run on initial render,
 *   so a region that mounts open simply is open. That is what keeps a long
 *   transcript still on load instead of unfolding a hundred regions at once
 *   (§8 — nothing animates that the operator is not watching).
 *
 * `Reveal` is the counterpart for content that *arrives* into space it already
 * has; this is for content that has to make the space first.
 */
export function Collapse(props: CollapseProps): JSX.Element {
  // Mount on first open and stay mounted through the close, so the closing
  // animation has something to run on.
  const [mounted, setMounted] = createSignal(props.open);
  createEffect(() => {
    if (props.open) setMounted(true);
  });

  return (
    <Show when={mounted()}>
      <div
        class={cx("ody-collapse", props.class)}
        data-closed={props.open ? undefined : ""}
        onTransitionEnd={(e) => {
          // Guard on the property: a child's own transition bubbles up here too,
          // and unmounting on one of those would cut the region while it is
          // still open.
          if (e.propertyName === "grid-template-rows" && !props.open)
            setMounted(false);
        }}
      >
        <div>{props.children}</div>
      </div>
    </Show>
  );
}
