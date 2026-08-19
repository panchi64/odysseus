import { useSearchParams } from "@solidjs/router";
import type { Accessor } from "solid-js";

/** A tab/filter selection held in the URL instead of a local signal, so the view
 *  is linkable and the back button undoes a switch. The default is kept out of
 *  the query string, and an unknown value falls back to it rather than rendering
 *  an empty list from a hand-edited URL. */
export function useTabParam<T extends string>(
  key: string,
  values: readonly T[],
  fallback: T,
): [Accessor<T>, (next: T) => void] {
  const [params, setParams] = useSearchParams();
  const value = () => {
    const raw = params[key];
    return typeof raw === "string" &&
      (values as readonly string[]).includes(raw)
      ? (raw as T)
      : fallback;
  };
  const set = (next: T) =>
    setParams(
      { [key]: next === fallback ? undefined : next },
      // Flipping a filter isn't a navigation step worth stacking up.
      { replace: true, scroll: false },
    );
  return [value, set];
}
