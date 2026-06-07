import { createSignal } from "solid-js";
import { isServer } from "solid-js/web";

/**
 * Central theme store. Theme is UI-owned state, so it lives here in `ui/theme`
 * rather than in `lib/stores`. The selected mode is written to
 * `document.documentElement.dataset.theme`, which drives every color token in
 * tokens.css; nothing else needs to know the mode.
 */
export type ThemeMode = "phosphor" | "paper";

export const THEME_STORAGE_KEY = "odysseus:theme";
export const DEFAULT_THEME: ThemeMode = "phosphor";

function readStored(): ThemeMode {
  if (isServer || typeof localStorage === "undefined") return DEFAULT_THEME;
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  return stored === "phosphor" || stored === "paper" ? stored : DEFAULT_THEME;
}

const [theme, setThemeSignal] = createSignal<ThemeMode>(readStored());

/** Reflect the mode onto <html data-theme>; the single source of cascade truth. */
export function applyTheme(mode: ThemeMode): void {
  if (isServer) return;
  document.documentElement.dataset.theme = mode;
}

export function setTheme(mode: ThemeMode): void {
  setThemeSignal(mode);
  if (!isServer && typeof localStorage !== "undefined") {
    localStorage.setItem(THEME_STORAGE_KEY, mode);
  }
  applyTheme(mode);
}

export function toggleTheme(): void {
  setTheme(theme() === "phosphor" ? "paper" : "phosphor");
}

export { theme };
