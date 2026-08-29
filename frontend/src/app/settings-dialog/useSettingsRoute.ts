import { useSearchParams } from "@solidjs/router";
import type { Accessor } from "solid-js";
import { categoryById, type SettingsCategory } from "./categories";
import { SETTINGS_PARAM } from "./legacy";

export { SETTINGS_PARAM };

export interface SettingsRoute {
  /** True while the dialog should be mounted. */
  open: Accessor<boolean>;
  /** The category on screen. Falls back to the first when the param names none,
   *  so a stale bookmark opens the dialog rather than an empty pane. */
  category: Accessor<SettingsCategory>;
  /** Open the dialog, optionally on a named category. */
  show: (id?: string) => void;
  select: (id: string) => void;
  close: () => void;
}

/**
 * The settings dialog's open state and current category, held in the URL.
 *
 * **Not `useTabParam`, and the difference is the whole point.** That helper keeps
 * the default value *out* of the query string, which is right for a filter — a
 * tab strip is visible whether or not a param is set. Here the param's presence
 * *is* the open state, so the default category has to be written like any other
 * or opening GENERAL would be indistinguishable from closed.
 *
 * The other difference is history. `useTabParam` replaces, because flipping a
 * filter is not a navigation step worth stacking up. Opening the dialog is:
 * `open` pushes, so the back button closes it — the gesture an overlay over a
 * page is expected to answer to. Switching category once inside replaces, since
 * a browse through six categories should not take six presses to back out of.
 */
export function useSettingsRoute(): SettingsRoute {
  const [params, setParams] = useSearchParams();
  const raw = (): string | undefined => {
    const v = params[SETTINGS_PARAM];
    return typeof v === "string" ? v : undefined;
  };

  return {
    open: () => raw() !== undefined,
    category: () => categoryById(raw()),
    show: (id) =>
      setParams(
        { [SETTINGS_PARAM]: id ?? categoryById(undefined).id },
        { scroll: false },
      ),
    select: (id) =>
      setParams({ [SETTINGS_PARAM]: id }, { replace: true, scroll: false }),
    // `undefined` removes the key rather than leaving `?settings=` behind.
    close: () => setParams({ [SETTINGS_PARAM]: undefined }, { scroll: false }),
  };
}
