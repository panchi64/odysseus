import {
  preference,
  resolveTheme,
  setTheme,
  toggleTheme,
  type ThemeMode,
  type ThemePreference,
} from "./theme-store";

/** Read/control the active theme from any component. */
export function useTheme() {
  return {
    /** The user's chosen mode: "phosphor" | "paper" | "system". */
    get preference(): ThemePreference {
      return preference();
    },
    /** The concrete palette currently applied. */
    get resolved(): ThemeMode {
      return resolveTheme(preference());
    },
    set: setTheme,
    toggle: toggleTheme,
  };
}
