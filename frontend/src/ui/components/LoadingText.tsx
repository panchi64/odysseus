import { splitProps } from "solid-js";
import type { JSX } from "solid-js";
import { Text } from "../primitives/Text";

export interface LoadingTextProps {
  /** Defaults to "LOADING…". Use "UPDATING…", "SYNCING…", etc. as needed. */
  label?: string;
  class?: string;
}

/** The system's only loading affordance: dim text, never a spinner (§6 states,
 *  §8 motion). */
export function LoadingText(props: LoadingTextProps): JSX.Element {
  const [local] = splitProps(props, ["label", "class"]);
  return (
    <Text variant="label" tone="dim" class={local.class}>
      {local.label ?? "LOADING…"}
    </Text>
  );
}
