import type { JSX } from "solid-js";
import { useTheme } from "../theme/useTheme";
import { Icon } from "../primitives/Icon";
import { Text } from "../primitives/Text";

/** Switches between Phosphor (dark) and Paper (light). */
export function ThemeToggle(): JSX.Element {
  const theme = useTheme();
  const isPaper = () => theme.theme === "paper";
  return (
    <button
      type="button"
      onClick={() => theme.toggle()}
      aria-label={
        isPaper() ? "Switch to Phosphor (dark)" : "Switch to Paper (light)"
      }
      class="inline-flex items-center gap-1 rounded-ctl border border-line px-2 h-6 text-dim transition-colors hover:text-bright hover:border-dim"
    >
      <Icon name={isPaper() ? "sun" : "moon"} size={12} />
      <Text variant="label" tone="dim">
        {isPaper() ? "PAPER" : "PHOSPHOR"}
      </Text>
    </button>
  );
}
