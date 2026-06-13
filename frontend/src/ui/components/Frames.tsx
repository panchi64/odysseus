import { createSignal, onCleanup, onMount, type JSX } from "solid-js";
import { cx } from "../cx";

/** The braille throbber — the canonical terminal "working" indicator. */
const BRAILLE = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
/** Block-element fallback for fonts that don't ship braille (guaranteed glyphs
 *  in JetBrains Mono's Block Elements range). */
const BLOCKS = ["▖", "▘", "▝", "▗", "▚", "▞"];

/** Whether the font stack actually draws braille (vs. tofu). Monospace defeats
 *  width-based detection — every advance is equal — so diff the rendered pixels
 *  of a braille glyph against the notdef box. Memoized; assumes support where a
 *  canvas isn't available (SSR/headless) since the live throbber is client-only. */
let brailleOk: boolean | null = null;
function brailleSupported(): boolean {
  if (brailleOk !== null) return brailleOk;
  if (typeof document === "undefined") return (brailleOk = true);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 16;
    canvas.height = 16;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return (brailleOk = true);
    ctx.font = '12px "JetBrains Mono", monospace';
    ctx.textBaseline = "top";
    const ink = (ch: string): string => {
      ctx.clearRect(0, 0, 16, 16);
      ctx.fillText(ch, 0, 0);
      const { data } = ctx.getImageData(0, 0, 16, 16);
      let s = "";
      for (let i = 3; i < data.length; i += 16) s += data[i] ? "1" : "0";
      return s;
    };
    // Braille is usable only if the cell draws *real* ink — different from both
    // a blank space (font lacks braille → renders nothing) and the notdef/tofu
    // box (￿ is an unassigned noncharacter → the font's placeholder). Matching
    // either means the throbber would render blank or as boxes, so fall back.
    const braille = ink("⠿");
    return (brailleOk = braille !== ink(" ") && braille !== ink("￿"));
  } catch {
    return (brailleOk = true);
  }
}

export interface FramesProps {
  /** Milliseconds per frame (hard cut, no easing). Default 90. */
  speed?: number;
  /** Override the glyph set. Defaults to the braille throbber, swapped for a
   *  block-element set when the font lacks braille. */
  frames?: string[];
  /** Layout/colour glue (e.g. `text-info`); merged after the base class. */
  class?: string;
}

/** A live "working now" indicator: a fixed set of monospace glyphs cycled with
 *  hard cuts — the same mechanical motion family as the block caret (design §8),
 *  never an eased/decorative spinner. Decorative, so hidden from assistive tech;
 *  pair it with a text label that carries the meaning. */
export function Frames(props: FramesProps): JSX.Element {
  const set = (): string[] =>
    props.frames ?? (brailleSupported() ? BRAILLE : BLOCKS);
  const [i, setI] = createSignal(0);

  onMount(() => {
    const id = setInterval(
      () => setI((n) => (n + 1) % set().length),
      props.speed ?? 90,
    );
    onCleanup(() => clearInterval(id));
  });

  return (
    <span class={cx("tabular-nums", props.class)} aria-hidden="true">
      {set()[i() % set().length]}
    </span>
  );
}
