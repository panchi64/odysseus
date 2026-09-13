import type { Resource } from "solid-js";

/**
 * A resource's value, read **without suspending**.
 *
 * Calling a resource (`data()`) inside a tracked scope while a fetch is in flight
 * registers with the nearest `Suspense` boundary and pulls everything inside that
 * boundary off screen behind its fallback. That is rarely what a component wants:
 * it has already written its own loading arm, sized to its own box, and the
 * boundary it actually lands on is somewhere up the tree — a pane, or a whole
 * route — which then blanks for as long as one small request takes.
 *
 * `state` and `latest` are plain reads. Once the resource has resolved even once,
 * `latest` keeps handing back the value it has while the next one is fetched, so a
 * refetch behind rendered content leaves that content on screen; before the first
 * resolution it reads `undefined`, which is the case a local fallback is for.
 *
 * It is also the only safe read of a resource whose fetcher can reject: bare
 * `latest` calls through to the resource while unresolved, which re-throws the
 * error at the read site — blanking whatever `ErrorBoundary` is above it over a
 * secondary fetch. Guarding on `state` first means an errored resource reads
 * `undefined` and the caller's own error arm decides what to say.
 *
 * The rule this encodes: **suspend where the operator is looking, never above it.**
 */
export function settled<T>(resource: Resource<T>): T | undefined {
  return resource.state === "ready" || resource.state === "refreshing"
    ? resource.latest
    : undefined;
}
