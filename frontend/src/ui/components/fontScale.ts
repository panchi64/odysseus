/** Internal helper shared by `CodeBlock` and `DiffView` — not part of the public
 *  surface (not re-exported from `index.ts`). Maps a `fontStep` (-2..+2) to a
 *  font-size in px, anchored to the same type-scale token values
 *  (`theme.css` `--type-*-size`) the View panel's renderers use for the
 *  identical prop, so a zoom step reads as the same size everywhere — kept
 *  local here (rather than imported) since `~/ui` doesn't depend on feature
 *  code. */
const FONT_STEP_SIZE: readonly number[] = [10, 11, 13, 20, 32];

export function fontStepSize(step: number | undefined): number {
  const clamped = Math.max(-2, Math.min(2, step ?? 0));
  return FONT_STEP_SIZE[clamped + 2];
}
