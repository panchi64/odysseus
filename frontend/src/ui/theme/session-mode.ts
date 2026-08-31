import { isServer } from "solid-js/web";
import type { SessionMode } from "~/lib/modes";

/**
 * The second axis of the cascade: `document.documentElement.dataset.mode`.
 *
 * Sibling of `applyTheme` in `theme-store`, and deliberately as small: one
 * attribute write, no state of its own. The *value* is chat state — which thread
 * the operator is in — so it is owned by the chat store and pushed here, rather
 * than held here and read by chat. This module only knows how to say it to the
 * document.
 *
 * **The naming is not incidental.** In `ui/theme`, `mode` already means the theme
 * mode (`ThemeMode = "phosphor" | "paper"`), which is a different axis with a
 * different set of values. The CSS attribute `data-mode` is free and reads
 * correctly in a stylesheet; the TypeScript identifier is not, so everything in
 * this layer spells the new axis `sessionMode` in full. Two things called `mode`
 * in one module would be conflated within a week, and the failure — a paper theme
 * painting a code thread's accent — would look like a cascade bug.
 */
export function applySessionMode(sessionMode: SessionMode): void {
  if (isServer || typeof document === "undefined") return;
  document.documentElement.dataset.mode = sessionMode;
}
