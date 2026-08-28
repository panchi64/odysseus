/** The View panel's zoom scale (-2..+2), shared by every renderer so the same
 *  step reads as the same size everywhere. Anchored to the app's real type-scale
 *  tokens (`theme.css` `--type-*`: micro 10/12, label 11/16, body 13/16, readout
 *  20/24, readout-lg 32/36) — both the class form (`fontStepClass`, for
 *  renderers that lay text out in normal flow) and the numeric-px form
 *  (`fontStepMetrics`, for renderers that need a number for an inline
 *  `font-size` or virtualization row-height math) resolve to the identical
 *  values, so switching between e.g. a JSON artifact and a raw log at the same
 *  zoom step never jumps size. */

const FONT_STEP_CLASS = [
  "text-micro",
  "text-label",
  "text-body",
  "text-readout",
  "text-readout-lg",
] as const;

const FONT_STEP_METRICS: ReadonlyArray<{ size: number; line: number }> = [
  { size: 10, line: 12 },
  { size: 11, line: 16 },
  { size: 13, line: 16 },
  { size: 20, line: 24 },
  { size: 32, line: 36 },
];

function clampStep(step: number | undefined): number {
  return Math.max(-2, Math.min(2, step ?? 0));
}

/** The token-backed Tailwind class for `step` (CsvTable, JsonTree — text laid
 *  out in normal flow). */
export function fontStepClass(step: number | undefined): string {
  return FONT_STEP_CLASS[clampStep(step) + 2];
}

/** The same scale as `fontStepClass`, as raw px `{size, line}` — for renderers
 *  that need a number rather than a class (RawTextViewer's inline style +
 *  virtualization row height, ViewDocumentContent's inline style). */
export function fontStepMetrics(step: number | undefined): {
  size: number;
  line: number;
} {
  return FONT_STEP_METRICS[clampStep(step) + 2];
}

/** The zoom factor for `step` applied to a whole framed page (`SandboxedFrame`).
 *  A sandboxed iframe is opaque-origin, so no class or font-size can reach the
 *  document inside — the only lever is scaling the page like browser zoom. Uses
 *  browser-zoom-style factors rather than the text metrics' ratios (10px→32px
 *  would swing a full page between 77% and 246%, far past useful). */
const FRAME_ZOOM: ReadonlyArray<number> = [0.67, 0.8, 1, 1.25, 1.5];

export function frameZoom(step: number | undefined): number {
  return FRAME_ZOOM[clampStep(step) + 2];
}
