/** Where a list's keyboard cursor goes for one key, or null when the key doesn't move
 *  it. Shared by every listbox that keeps focus somewhere else and points at its rows
 *  with `aria-activedescendant` — the composer's `/` menu, `Select`, `Combobox` — so
 *  the arrows mean the same thing in all of them.
 *
 *  The arrows wrap, because a short menu is faster to reach the end of by going up.
 *  `at` of -1 (nothing active yet) lands ArrowDown on the first row and ArrowUp on the
 *  last. */
export function cursorStep(
  key: string,
  at: number,
  count: number,
): number | null {
  if (count <= 0) return null;
  switch (key) {
    case "ArrowDown":
      return at < 0 ? 0 : (at + 1) % count;
    case "ArrowUp":
      return at < 0 ? count - 1 : (at - 1 + count) % count;
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return null;
  }
}
