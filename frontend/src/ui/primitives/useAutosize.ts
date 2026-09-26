import { createEffect, onCleanup, onMount } from "solid-js";

export interface AutosizeOptions {
  /** The most lines the field grows to before it scrolls. */
  maxRows: number;
  /** The most of the window's height it may take, whichever cap is smaller. */
  maxViewportShare: number;
}

/**
 * Grow a textarea to fit its content, from one row up to the smaller of `maxRows`
 * and `maxViewportShare` of the window, then scroll. Re-measured whenever `value`
 * changes — typing, a draft load, a clear after send — and on window resize, since
 * one cap is a share of the window. A behavior hook: no styling of its own.
 */
export function useAutosize(
  field: () => HTMLTextAreaElement | undefined,
  value: () => string,
  options: AutosizeOptions,
): void {
  const autosize = () => {
    const el = field();
    if (!el) return;
    el.style.height = "auto";
    const cs = getComputedStyle(el);
    const line = parseFloat(cs.lineHeight) || 20;
    const padding = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const border =
      parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
    const max = Math.max(
      line + padding + border,
      Math.min(
        window.innerHeight * options.maxViewportShare,
        line * options.maxRows + padding + border,
      ),
    );
    // `scrollHeight` covers content + padding but not border; the field is
    // border-box, so add the border back or the set height clips by that much.
    const fit = el.scrollHeight + border;
    el.style.height = `${Math.min(fit, max)}px`;
    el.style.overflowY = fit > max ? "auto" : "hidden";
  };
  createEffect(() => {
    value();
    autosize();
  });
  onMount(() => {
    window.addEventListener("resize", autosize);
    onCleanup(() => window.removeEventListener("resize", autosize));
  });
}
