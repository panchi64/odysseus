import { type JSX } from "solid-js";
import { Text } from "~/ui";

/** One-line reminder that engines don't share model builds, so changing the engine means
 *  a different download. Lives alongside the download step (not inside the engine picker)
 *  so it reads as guidance for picking a repo, not fine print on the selector. */
export function EngineSwitchNote(): JSX.Element {
  return (
    <Text variant="micro" tone="dim">
      Each engine uses its own model build, so switching engines means a
      separate download.
    </Text>
  );
}
