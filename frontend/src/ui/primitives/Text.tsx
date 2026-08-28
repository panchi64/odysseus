import { splitProps, type JSX, type ValidComponent } from "solid-js";
import { Dynamic } from "solid-js/web";
import { cx } from "../cx";

export type TextVariant =
  "micro" | "meta" | "label" | "body" | "readout" | "readout-lg" | "display";

export type TextTone =
  | "dim"
  | "default"
  | "bright"
  | "accent"
  | "nominal"
  | "warn"
  | "alert"
  | "info";

/* The ONLY place the type scale is written, and the place the two voices (§2)
   are encoded.

   SANS is the interface speaking to the operator — labels, body, readouts,
   titles. Sentence case, no tracking, and it eases (the default register).

   MONO is the machine showing its work — ids, states, counters, durations,
   paths. Small, uppercase where it is a machine *label* (`meta`), and it snaps:
   `transition-none` plus the global `.font-mono` rule in theme.css put every
   mono element in the machine register, because a computer does not ease. */
const variantClass: Record<TextVariant, string> = {
  // ---- machine voice ----
  micro: "text-micro font-mono transition-none",
  meta: "text-meta font-mono font-medium uppercase tracking-label transition-none",
  // ---- interface voice ----
  label: "text-label font-sans font-medium",
  body: "text-body font-sans",
  readout: "text-readout font-sans font-medium",
  "readout-lg": "text-readout-lg font-sans font-medium",
  display: "text-display font-sans font-semibold tracking-tight",
};

const toneClass: Record<TextTone, string> = {
  dim: "text-dim",
  default: "text-text",
  bright: "text-bright",
  accent: "text-accent",
  nominal: "text-nominal",
  warn: "text-warn",
  alert: "text-alert",
  info: "text-info",
};

export interface TextProps {
  variant?: TextVariant;
  tone?: TextTone;
  /** Element to render. Defaults to <span>. */
  as?: ValidComponent;
  class?: string;
  children: JSX.Element;
}

/** Typographic primitive — the type-scale authority for the whole system. */
export function Text(props: TextProps): JSX.Element {
  const [local, rest] = splitProps(props, [
    "variant",
    "tone",
    "as",
    "class",
    "children",
  ]);
  return (
    <Dynamic
      component={local.as ?? "span"}
      class={cx(
        variantClass[local.variant ?? "body"],
        toneClass[local.tone ?? "default"],
        local.class,
      )}
      {...rest}
    >
      {local.children}
    </Dynamic>
  );
}
