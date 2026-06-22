import { type JSX } from "solid-js";
import { cx } from "../cx";
import { type TextTone } from "../primitives/Text";

/** Semantic status. Each maps to exactly one accent (§4 color discipline). */
export type Status = "idle" | "live" | "nominal" | "warn" | "alert" | "info";

/** The one Status → accent mapping. Every status indicator (the StatusFlag chip,
 *  the system strip, fallback-chain rows) reads from here so the color of a state
 *  never forks across surfaces. */
export const statusTone: Record<Status, TextTone> = {
  idle: "dim",
  live: "nominal",
  nominal: "nominal",
  warn: "warn",
  alert: "alert",
  info: "info",
};

export interface StatusDotProps {
  /** Drives the accent. Defaults to idle (neutral, at rest). */
  status?: Status;
  /** Hard-stepped pulse to signal live activity (cursor-blink family, §8). */
  pulse?: boolean;
  class?: string;
}

/** The shared state dot: a bare 6px disc carrying one semantic accent. The single
 *  source for every health/status indicator so the state→color mapping never
 *  forks — `bg-current` over the tone's text color keeps dot and label in sync. */
export function StatusDot(props: StatusDotProps): JSX.Element {
  return (
    <span
      class={cx(
        "inline-block size-1.5 shrink-0 rounded-full bg-current",
        `text-${statusTone[props.status ?? "idle"]}`,
        props.pulse && "ody-pulse",
        props.class,
      )}
      aria-hidden="true"
    />
  );
}
