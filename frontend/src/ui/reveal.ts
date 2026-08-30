/** The one way a control hides until it is reached for.
 *
 *  A secondary control that sits on every row of a long list — copy, delete, the
 *  overflow menu — is noise at rest and necessary on demand. Hiding it until the
 *  row is hovered is the resolution, and four surfaces do it, so they say it once
 *  here rather than four slightly different ways.
 *
 *  Three things it gets right that a hand-rolled version tends not to:
 *
 *  - **`opacity`, not `hidden`.** An element that leaves the layout on reveal
 *    reflows the row it is in at the moment the pointer arrives, which is the one
 *    moment the operator is looking at it.
 *  - **`focus-within` / `focus-visible` keep it keyboard-reachable.** A control
 *    that exists only on hover cannot be tabbed to, which is an accessibility
 *    failure rather than a density decision.
 *  - **`no-hover` keeps it on touch.** A phone has no state between "not
 *    touching" and "tapped", so a hover reveal there does not hide the control —
 *    it deletes it. That is how the turn's overflow menu, and Expand all behind
 *    it, became unreachable on a narrow viewport.
 *
 *  **Why the touch case is written as an override rather than as a condition.**
 *  The obvious form is `can-hover:opacity-0` — hide it only where a pointer
 *  exists. It does not work: Tailwind emits media-query variants *after*
 *  pseudo-class ones, so `@media (hover:hover){opacity:0}` lands below
 *  `.group-hover\/tool\:opacity-100` and wins at equal specificity. The control
 *  would then never appear on any device. Inverting it puts the media query on
 *  the side that *wants* to come last, so the ordering works for the rule instead
 *  of against it, and the pointer path is left byte-for-byte as it was.
 *
 *  The caller supplies the group that triggers the reveal, because the group is
 *  often *named* (`group/tool`) — a turn wrapper is itself an unnamed `group`, so
 *  a nested reveal hanging off the unnamed one would fire for the whole turn. Use
 *  `REVEAL_ON_GROUP_HOVER` where the unnamed group is the right trigger, or pair
 *  `REVEAL_BASE` with your own `group-hover/<name>:opacity-100`. */
export const REVEAL_BASE =
  "opacity-0 transition-opacity focus-within:opacity-100 focus-visible:opacity-100 no-hover:opacity-100";

/** `REVEAL_BASE` wired to the nearest *unnamed* `group`. The common case. */
export const REVEAL_ON_GROUP_HOVER = `${REVEAL_BASE} group-hover:opacity-100`;
