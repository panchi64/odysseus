import {
  Show,
  type Accessor,
  type JSX,
  type Resource as SolidResource,
} from "solid-js";
import { LoadingText } from "./LoadingText";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";

export interface ResourceProps<T> {
  /** A SolidJS resource (from createResource). */
  data: SolidResource<T>;
  /** Loading label override (default "LOADING…"). */
  loadingLabel?: string;
  /** Replace the default loading affordance entirely. */
  loading?: JSX.Element;
  /** Error headline (default "SOMETHING WENT WRONG"); reason is auto-filled. */
  errorMessage?: string;
  /** Show a RETRY in the error state — typically `() => data.refetch()`. */
  onRetry?: () => void;
  /** Emptiness test, e.g. `(rows) => rows.length === 0`. */
  isEmpty?: (value: T) => boolean;
  emptyMessage?: string;
  emptyHint?: string;
  /** Replace the default empty affordance entirely. */
  empty?: JSX.Element;
  /** Rendered with the resolved, non-empty value. */
  children: (value: Accessor<NonNullable<T>>) => JSX.Element;
}

/** The one place loading / error / empty / content arms live for a resource, so
 *  screens stop hand-rolling the Suspense+Show+EmptyState triple (§6 states).
 *  `<Resource data={things} onRetry={things.refetch} isEmpty={(t) => !t.length}>
 *     {(things) => <List items={things()} />}
 *   </Resource>` */
export function Resource<T>(props: ResourceProps<T>): JSX.Element {
  // "ready"/"refreshing" mean the resource has resolved a value (which may be
  // falsy — 0, "", false). Use `state`, not truthiness, to tell loading apart.
  const resolved = () =>
    props.data.state === "ready" || props.data.state === "refreshing";
  return (
    <Show
      when={!props.data.error}
      fallback={
        <ErrorState
          message={props.errorMessage}
          hint={(props.data.error as Error | undefined)?.message}
          onRetry={props.onRetry}
        />
      }
    >
      <Show
        when={resolved()}
        fallback={props.loading ?? <LoadingText label={props.loadingLabel} />}
      >
        <Show
          when={!props.isEmpty?.(props.data() as T)}
          fallback={
            props.empty ?? (
              <EmptyState message={props.emptyMessage} hint={props.emptyHint} />
            )
          }
        >
          {props.children(() => props.data() as NonNullable<T>)}
        </Show>
      </Show>
    </Show>
  );
}
