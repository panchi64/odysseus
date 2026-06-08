import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Icon } from "../primitives/Icon";
import { Tooltip } from "./Tooltip";

export interface InfoHintProps {
  /** The explanation revealed on hover/focus. */
  label: string;
  /** Edge to place the tip. Default top. */
  side?: "top" | "bottom" | "left" | "right";
  /** Glyph size in px. Default 13. */
  size?: number;
  class?: string;
}

/**
 * A dim ⓘ glyph that reveals an explanatory tooltip on hover/focus — the
 * reusable way to annotate domain jargon (token scopes, MCP transports,
 * suitability flags, privilege names…) inline without cluttering the layout.
 * Uses the floating tooltip so the text wraps and escapes overflow-clipping.
 */
export function InfoHint(props: InfoHintProps): JSX.Element {
  const [local] = splitProps(props, ["label", "side", "size", "class"]);
  return (
    <Tooltip
      label={local.label}
      side={local.side ?? "top"}
      float
      prose
      delay={80}
    >
      <span
        tabindex="0"
        role="img"
        aria-label={local.label}
        class={cx(
          "inline-flex cursor-help text-dim outline-none transition-colors hover:text-bright focus-visible:text-bright",
          local.class,
        )}
      >
        <Icon name="info" size={local.size ?? 13} />
      </span>
    </Tooltip>
  );
}
