import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

export interface MetaActionProps extends Omit<
  JSX.ButtonHTMLAttributes<HTMLButtonElement>,
  "type"
> {
  /** Brightens the resting tone, for a segment whose value is pinned or live —
   *  brightness carries the state, never hue (§5.3). Pair with `aria-pressed`
   *  where it is genuinely a toggle. */
  active?: boolean;
  class?: string;
  children: JSX.Element;
}

/**
 * **A readout segment that can be clicked.** Mono, `micro`-sized, dim at rest and
 * bright on hover — a value in a run of machine text that happens to open
 * something, rather than a control parked in the middle of one.
 *
 * `Button` is the wrong shape for this and deliberately so: it is sans (the
 * interface's voice), it has a control height and padding, and a row of them
 * inside a line of telemetry reads as a toolbar. This is the same type as the
 * values beside it and sits on the same baseline; only the hover says it acts.
 *
 * It carries no transition, and that is not an oversight — mono is the machine
 * register (§8), so the tone change snaps. The global `.font-mono` rule in
 * theme.css enforces that anyway; the class here just makes it explicit.
 *
 * Because it is the *only* affordance, the hover tone is load-bearing — do not
 * use this for anything the operator must be able to find without pointing at
 * it. That is what `Button` is for.
 */
export function MetaAction(props: MetaActionProps): JSX.Element {
  const [local, rest] = splitProps(props, ["active", "class", "children"]);
  return (
    <button
      type="button"
      class={cx(
        "text-micro inline-flex items-center gap-1 font-mono whitespace-nowrap transition-none",
        "disabled:cursor-not-allowed disabled:opacity-40",
        local.active ? "text-bright" : "text-dim hover:text-bright",
        local.class,
      )}
      {...rest}
    >
      {local.children}
    </button>
  );
}
