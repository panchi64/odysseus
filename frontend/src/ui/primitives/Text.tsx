import { splitProps, type JSX, type ValidComponent } from "solid-js";
import { Dynamic } from "solid-js/web";
import { cx } from "../cx";

export type TextVariant =
  | "micro"
  | "label"
  | "body"
  | "readout"
  | "readout-lg"
  | "display";

export type TextTone =
  | "dim"
  | "default"
  | "bright"
  | "nominal"
  | "warn"
  | "alert"
  | "info";

/* The ONLY place the type scale is written. Each variant pairs size +
   line-height (via the text-* utilities defined in theme.css). */
const variantClass: Record<TextVariant, string> = {
  micro: "text-micro font-mono",
  label: "text-label font-mono uppercase tracking-label",
  body: "text-body font-mono",
  readout: "text-readout font-mono font-medium",
  "readout-lg": "text-readout-lg font-mono font-bold",
  display: "text-display font-display font-bold",
};

const toneClass: Record<TextTone, string> = {
  dim: "text-dim",
  default: "text-text",
  bright: "text-bright",
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
