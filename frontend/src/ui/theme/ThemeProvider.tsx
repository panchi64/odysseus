import { onMount, type JSX } from "solid-js";
import { applyTheme, theme } from "./theme-store";

/**
 * Reconciles the `data-theme` attribute with the stored signal on mount.
 * In SPA mode the no-flash inline script in entry-server.tsx sets the
 * attribute before first paint; this just keeps the signal authoritative
 * after hydration.
 */
export function ThemeProvider(props: { children: JSX.Element }): JSX.Element {
  onMount(() => applyTheme(theme()));
  return props.children;
}
