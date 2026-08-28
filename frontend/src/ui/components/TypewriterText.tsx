import { createEffect, createSignal, onCleanup, type JSX } from "solid-js";
import { Text, type TextProps } from "../primitives/Text";
import { Caret } from "./Caret";

export interface TypewriterTextProps {
  /** The full string to reveal. Restarts the reveal whenever it changes. */
  text: string;
  variant?: TextProps["variant"];
  tone?: TextProps["tone"];
  /** Milliseconds per character. A linear, mechanical cadence (design §8 — a
   *  sequence of permitted value tick-overs, not an eased flourish). */
  speed?: number;
  class?: string;
}

/** Reveals text one character at a time behind the terminal block caret, then
 *  drops the caret when complete. The single moving piece in the otherwise static
 *  interface — used to "type out" a value the backend just produced (e.g. an
 *  auto-generated conversation title). The reveal's lifetime is owned by whoever
 *  supplies `text`; this component only animates what it's given. */
export function TypewriterText(props: TypewriterTextProps): JSX.Element {
  const [count, setCount] = createSignal(0);

  // (Re)start on every text change. `count` is the single source of truth for
  // how much has been revealed; the interval is its only writer and self-clears
  // at the end, so there's no second counter to drift.
  createEffect(() => {
    const full = props.text;
    setCount(0);
    if (!full) return;
    const timer = setInterval(() => {
      setCount((c) => {
        if (c + 1 >= full.length) clearInterval(timer);
        return c + 1;
      });
    }, props.speed ?? 30);
    onCleanup(() => clearInterval(timer));
  });

  return (
    <Text variant={props.variant} tone={props.tone} class={props.class}>
      {props.text.slice(0, count())}
      {count() < props.text.length && <Caret />}
    </Text>
  );
}
