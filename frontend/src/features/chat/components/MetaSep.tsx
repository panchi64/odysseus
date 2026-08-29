import type { JSX } from "solid-js";
import { Text } from "~/ui";

/** The rule between groups in the composer's readout line. A `·` separates values
 *  that measure the same thing (in/out tokens against the context percentage); this
 *  `|` separates the things themselves.
 *
 *  **A segment renders its own leading separator, from inside its own presence
 *  check.** That is the whole reason this is a component and not a character in a
 *  template: three of the segments decide whether they exist asynchronously — the
 *  grants and the fold state resolve from their own resources — so a separator
 *  emitted by the parent would hang in the line for as long as the fetch takes, and
 *  forever for a thread that has no grants at all. Presence and punctuation have to
 *  be the same decision. */
export function MetaSep(): JSX.Element {
  return (
    <Text variant="micro" tone="dim" class="opacity-50 select-none">
      |
    </Text>
  );
}
