import { createEffect, createSignal, onCleanup, untrack } from "solid-js";

export interface GatedMount {
  /** Whether to render at all. Stays true through the exit animation. */
  mounted: () => boolean;
  /** True while the exit is playing — drives `data-closed`. */
  closing: () => boolean;
  /** False until the tree has settled; hold the content invisible until then. */
  ready: () => boolean;
  /** Wire to the animated element's `onAnimationEnd`. Unmounts after the exit. */
  onAnimationEnd: (e: AnimationEvent) => void;
}

/**
 * The mount/exit lifecycle behind every animation in the system that has to
 * survive its own disappearance. Extracted from `Reveal` when
 * `ConstructionReveal` needed the same four behaviours; it is subtle enough that
 * a second copy would have drifted.
 *
 * Four things it does, each of which was a bug once:
 *
 * - **Stays mounted through the exit.** A gated region has to keep existing for
 *   the length of its closing animation, or there is nothing for the animation
 *   to run on and the region is simply cut.
 * - **Waits two frames before starting the entry.** A region whose first render
 *   is expensive — an iframe, a syntax highlighter, a document viewer — can
 *   block the main thread for longer than the animation lasts, and the first
 *   frame to paint would then be the last one: the region appears fully formed
 *   instead of arriving. Two, not one, because the first lands in the same batch
 *   as the render that mounted us, so the work has not necessarily finished by
 *   then. Waiting costs nothing, since an animation carries its own start and
 *   plays in full whenever it begins.
 * - **Only unmounts on its OWN animation ending.** Animations inside the
 *   revealed content bubble to the same handler — a streamed token, a nested
 *   reveal, a frame mark — and any of them would otherwise tear the region out
 *   mid-exit. Hence the `target !== currentTarget` guard, which is why the
 *   element you attach this to must itself carry the longest animation.
 * - **Re-arms on close**, so reopening waits for its own settled frame rather
 *   than animating against whatever the next mount is busy building.
 *
 * `when` undefined means ungated: always mounted, never closing, ready at once.
 */
export function useGatedMount(when: () => boolean | undefined): GatedMount {
  const gated = (): boolean => when() !== undefined;
  const open = (): boolean => when() ?? true;

  const [mounted, setMounted] = createSignal(open());
  const [ready, setReady] = createSignal(!untrack(gated));
  const closing = (): boolean => gated() && !open();

  let frame = 0;
  const start = (): void => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => setReady(true));
    });
  };

  createEffect(() => {
    if (!open()) return;
    setMounted(true);
    if (!untrack(ready)) start();
  });
  onCleanup(() => cancelAnimationFrame(frame));

  return {
    mounted,
    closing,
    ready,
    onAnimationEnd: (e: AnimationEvent) => {
      // `closing()` is read as the event fires, so a region reopened part-way
      // through its exit stays put rather than vanishing on the stale decision.
      if (e.target !== e.currentTarget || !closing()) return;
      setMounted(false);
      setReady(false);
    },
  };
}
