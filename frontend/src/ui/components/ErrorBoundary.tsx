import {
  createEffect,
  ErrorBoundary as SolidErrorBoundary,
  on,
  type JSX,
} from "solid-js";
import { ErrorState } from "./ErrorState";

export interface ErrorBoundaryProps {
  /** Error headline (default "Something went wrong"); the reason is auto-filled. */
  message?: string;
  /** Extra work to run before Solid re-renders the subtree — e.g. refetch a
   *  resource whose failure threw, so RETRY has something new to render. */
  onReset?: () => void;
  /** Auto-reset when this value changes while the fallback is showing. Solid's
   *  boundary latches until reset, so without it a caught error outlives what
   *  caused it — pass the route path, or the id of whatever the subtree renders,
   *  so moving on clears the error instead of stranding the operator on it. */
  resetKey?: () => unknown;
  /** Layout glue for the fallback (the boundary itself renders no box). */
  class?: string;
  children: JSX.Element;
}

/** Catches a throw from anywhere in its subtree and renders `ErrorState` in its
 *  place, so one bad render degrades a region instead of blanking the screen.
 *  RETRY calls Solid's reset, which re-runs the subtree from scratch.
 *
 *  Wrap regions that can be lost independently — the routed content, a
 *  transcript — not individual leaves. This is the *last* line of defence: a
 *  resource that can fail should still be read through `.latest`/`.error` (or
 *  `Resource`) so its failure stays local and keeps its own retry. */
export function ErrorBoundary(props: ErrorBoundaryProps): JSX.Element {
  return (
    <SolidErrorBoundary
      fallback={(err: unknown, reset: () => void) => {
        const retry = () => {
          props.onReset?.();
          reset();
        };
        // Owned by the fallback, so it only tracks while an error is showing and
        // is disposed the moment the subtree comes back. `defer` skips the run
        // that would fire on mount and reset us straight back into the throw.
        createEffect(on(() => props.resetKey?.(), retry, { defer: true }));
        return (
          <ErrorState
            message={props.message}
            hint={err instanceof Error ? err.message : String(err)}
            class={props.class}
            onRetry={retry}
          />
        );
      }}
    >
      {props.children}
    </SolidErrorBoundary>
  );
}
