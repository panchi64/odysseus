import { theme, setTheme, toggleTheme, type ThemeMode } from "./theme-store";

/** Read/control the active theme mode from any component. */
export function useTheme() {
  return {
    get theme(): ThemeMode {
      return theme();
    },
    set: setTheme,
    toggle: toggleTheme,
  };
}
