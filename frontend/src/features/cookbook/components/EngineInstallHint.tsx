import { type JSX } from "solid-js";
import { Text } from "~/ui";

/** One-line hint about whether an engine's runtime is already present, so the operator
 *  knows a first serve will download it. Shared by the engine list and the guided setup
 *  form so the wording stays in one place. */
export function EngineInstallHint(props: { installed: boolean }): JSX.Element {
  return (
    <Text variant="micro" tone="dim">
      {props.installed
        ? "Ready — engine runtime is installed."
        : "Downloads engine (~once) on first serve."}
    </Text>
  );
}
