import { onCleanup, onMount, type JSX } from "solid-js";
import { applyTheme, preference, syncSystemTheme } from "./theme-store";

/**
 * Reconciles the `data-theme` attribute with the stored preference on mount.
 * In SPA mode the no-flash inline script in entry-server.tsx sets the
 * attribute before first paint; this keeps it authoritative after hydration
 * and, while the preference is "system", re-resolves it when the OS palette
 * changes.
 */
export function ThemeProvider(props: { children: JSX.Element }): JSX.Element {
  onMount(() => {
    applyTheme(preference());
    if (typeof matchMedia === "undefined") return;
    const mq = matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      syncSystemTheme();
      if (preference() === "system") applyTheme("system");
    };
    mq.addEventListener("change", onChange);
    onCleanup(() => mq.removeEventListener("change", onChange));
  });
  return props.children;
}
