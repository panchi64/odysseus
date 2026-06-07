import { Show, splitProps, type JSX } from "solid-js";
import { Dynamic } from "solid-js/web";
import { cx } from "../cx";
import { Icon, type IconProps } from "../primitives/Icon";

export type ButtonVariant = "primary" | "default" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends Omit<
  JSX.ButtonHTMLAttributes<HTMLButtonElement>,
  "type"
> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  leading?: IconProps["name"];
  trailing?: IconProps["name"];
  /** Renders as an anchor when set (router intercepts for SPA nav). */
  href?: string;
  type?: "button" | "submit" | "reset";
  block?: boolean;
}

const variantClass: Record<ButtonVariant, string> = {
  primary: "border-2 border-bright text-bright hover:bg-raised",
  default: "border border-line text-text hover:bg-raised hover:text-bright",
  ghost: "border border-transparent text-dim hover:text-bright",
  danger: "border border-alert text-alert hover:bg-raised",
};

const sizeClass: Record<ButtonSize, string> = {
  sm: "h-6 px-2 gap-1",
  md: "h-8 px-3 gap-2",
};

/** Foundational control. Cosmetic differences are the `variant`/`size` props —
 *  never a forked component. */
export function Button(props: ButtonProps): JSX.Element {
  const [local, rest] = splitProps(props, [
    "variant",
    "size",
    "leading",
    "trailing",
    "href",
    "type",
    "block",
    "class",
    "children",
  ]);
  return (
    <Dynamic
      component={local.href ? "a" : "button"}
      href={local.href}
      type={local.href ? undefined : (local.type ?? "button")}
      class={cx(
        "inline-flex items-center justify-center rounded-ctl text-label uppercase tracking-label font-mono transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-40",
        variantClass[local.variant ?? "default"],
        sizeClass[local.size ?? "md"],
        local.block && "w-full",
        local.class,
      )}
      {...rest}
    >
      <Show when={local.leading}>
        <Icon name={local.leading!} size={12} />
      </Show>
      {local.children}
      <Show when={local.trailing}>
        <Icon name={local.trailing!} size={12} />
      </Show>
    </Dynamic>
  );
}
