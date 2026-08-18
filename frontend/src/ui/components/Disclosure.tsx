import { Show, createSignal, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";

export interface DisclosureProps {
  /** Uppercase label shown beside the chevron. */
  label: string;
  /** Controlled open state. Omit to let the component own it. */
  open?: boolean;
  /** Toggle handler. Required when `open` is supplied. */
  onToggle?: () => void;
  /** Initial state when uncontrolled. Defaults to closed. */
  defaultOpen?: boolean;
  /** Rendered inside the trigger after the label — a peek line, a status glyph. */
  trailing?: JSX.Element;
  /** Extra classes for the trigger row (e.g. `w-full` for a full-width header). */
  triggerClass?: string;
  /** Body wrapper classes. Replaces the default spacing rather than adding to it,
   *  so a caller can set its own margin without two competing utilities. */
  class?: string;
  children: JSX.Element;
}

/**
 * A labelled show/hide section — chevron, uppercase label, `Show`-gated body.
 *
 * The look is the one the chat surface's own collapsibles converged on: a size-12
 * chevron-right that turns chevron-down, a dim label that brightens on hover, and the
 * body beneath. Works controlled (pass `open` + `onToggle`) or uncontrolled.
 *
 * Two nearby collapsibles deliberately do *not* use this and should not be forced onto
 * it: the sidebar's section headers put the chevron on the right beside a status
 * indicator, and `ToolCallCard` shares its trigger row with a sibling copy button.
 * Covering those would mean prop-configuring chevron placement and arbitrary trigger
 * children, at which point the component stops being simpler than the markup it hides.
 */
export function Disclosure(props: DisclosureProps): JSX.Element {
  const [uncontrolled, setUncontrolled] = createSignal(
    props.defaultOpen ?? false,
  );
  const isOpen = (): boolean => props.open ?? uncontrolled();
  const toggle = (): void => {
    if (props.open === undefined) setUncontrolled((v) => !v);
    props.onToggle?.();
  };

  return (
    <div>
      <button
        type="button"
        aria-expanded={isOpen()}
        onClick={(e) => {
          // Trigger clicks stop here: a disclosure nested inside its own clickable
          // wrapper would otherwise toggle twice and appear inert.
          e.stopPropagation();
          toggle();
        }}
        class={cx(
          "flex items-center gap-1 text-left text-dim transition-colors hover:text-text",
          props.triggerClass,
        )}
      >
        <Icon name={isOpen() ? "chevron-down" : "chevron-right"} size={12} />
        <Text variant="label" tone="dim">
          {props.label}
        </Text>
        {props.trailing}
      </button>
      <Show when={isOpen()}>
        <div class={props.class ?? "mt-2"}>{props.children}</div>
      </Show>
    </div>
  );
}
