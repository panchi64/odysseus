import { createSignal, onCleanup, onMount, type Accessor } from "solid-js";

function readQuery(query: string): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia(query).matches;
}

/** A CSS media query as a reactive accessor. Read synchronously at creation so
 *  the first render already renders the correct arm (no flash of the wrong
 *  layout), then kept live by a `change` listener. Falls back to `false` where
 *  `matchMedia` doesn't exist (the SSR shell render). Presentation only: a
 *  breakpoint is never a decision, just which arm of a layout is on screen. */
export function useMediaQuery(query: string): Accessor<boolean> {
  const [matches, setMatches] = createSignal(readQuery(query));
  onMount(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(query);
    const update = (): void => {
      setMatches(mq.matches);
    };
    update();
    mq.addEventListener("change", update);
    onCleanup(() => mq.removeEventListener("change", update));
  });
  return matches;
}

/** Tailwind's `lg` breakpoint, in one place — the width at/above which the app
 *  shows its side-by-side layouts (the chat workspace's viewport aside) and
 *  below which those same panels take over the whole screen instead. */
export const LG_QUERY = "(min-width: 64rem)";

/** True at/above `lg`. See `LG_QUERY`. */
export function useIsDesktop(): Accessor<boolean> {
  return useMediaQuery(LG_QUERY);
}
