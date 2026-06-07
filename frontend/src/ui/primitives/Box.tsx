import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

/**
 * Bare styled <div>. The lowest-level layout anchor: it merges a `class` and
 * forwards everything else. Prefer Stack/Row for flex layout; reach for Box
 * when you need a plain block with token-backed utility classes.
 */
export function Box(props: JSX.HTMLAttributes<HTMLDivElement>): JSX.Element {
  const [local, rest] = splitProps(props, ["class"]);
  return <div class={cx(local.class)} {...rest} />;
}
