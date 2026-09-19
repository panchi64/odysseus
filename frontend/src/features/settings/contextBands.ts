/** Whether the operator's gauge bands and their fold point add up.
 *
 *  Split out of `ChatSection.tsx` for the reason every derivation in this codebase is:
 *  the screen renders a conclusion, it does not reach one, and the rule here has enough
 *  edges to be worth pinning without a DOM.
 *
 *  **The rule.** The gauge's two bands and auto-compaction's threshold are deliberately
 *  separate dials — a warning wants to be early enough to be useful and a fold wants to be
 *  late enough not to have been unnecessary, so one number for both would mean every
 *  adjustment to one silently retuned the other. What separate does not mean is
 *  unrelated: with folding **on**, the window is emptied at the fold point, so a band set
 *  *above* it describes a fullness the thread never reaches. That band is not wrong — it
 *  is what the operator will see the moment they pause folding — but it is inert, and an
 *  inert dial that looks live is worth one line of type.
 *
 *  Nothing here corrects anything. Which of the three numbers to move (or to leave alone)
 *  is a taste about how a thread should feel, and this only makes the arrangement legible.
 */

/** The red band, when a fold point has put it out of reach. */
export interface InertBand {
  /** The band's own percentage, 0–100, rounded for display. */
  at: number;
  /** The fold point's percentage, 0–100, rounded for display. */
  fold: number;
}

/** The band a fold point makes unreachable, or `null` when the arrangement is coherent.
 *
 *  **Only the red band can be the one reported, and that is a consequence rather than a
 *  choice.** `warn` strictly below `alert` is an invariant the backend enforces at the
 *  single construction path, so a warn band above the fold implies an alert band above it
 *  too — there is no arrangement in which amber is inert and red is not. A branch for it
 *  would be a branch nothing can reach.
 *
 *  `null` whenever folding is off (every band is reachable then — that is exactly the
 *  state the bands describe), and whenever the fold sits at or above the band, since a
 *  fold at the very top still lets the band light on the turn that reaches it.
 */
export function inertBand(args: {
  foldEnabled: boolean;
  /** Fractions, 0–1, as the wire and the settings store carry them. */
  foldThreshold: number;
  alert: number;
}): InertBand | null {
  if (!args.foldEnabled) return null;
  const fold = Math.round(args.foldThreshold * 100);
  const alert = Math.round(args.alert * 100);
  // Compared after rounding, so the line agrees with the numbers on screen rather than
  // firing on a difference the operator cannot see (a fold at 0.801 against an alert at
  // 0.80 is not something to tell anyone about).
  return alert > fold ? { at: alert, fold } : null;
}
