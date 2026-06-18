/** Line-level diff for the version-history view — a presentation-only derivation
 *  (the backend owns the snapshots; this only decides how to render two of them
 *  side by side). LCS-based, which is enough at document scale. */

export type DiffKind = "context" | "add" | "del";

export interface DiffLine {
  kind: DiffKind;
  text: string;
  /** 1-based line number in the base (old) text; absent on added lines. */
  oldNo?: number;
  /** 1-based line number in the target (new) text; absent on removed lines. */
  newNo?: number;
}

export interface DiffResult {
  lines: DiffLine[];
  added: number;
  removed: number;
}

/** Diff `oldText` → `newText` line by line (git-style: `-` removed, `+` added). */
export function lineDiff(oldText: string, newText: string): DiffResult {
  const a = oldText.split("\n");
  const b = newText.split("\n");

  // Longest-common-subsequence table over lines.
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] =
        a[i] === b[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  // Walk the table forward, emitting context / del / add in order.
  const lines: DiffLine[] = [];
  let added = 0;
  let removed = 0;
  let i = 0;
  let j = 0;
  let oldNo = 0;
  let newNo = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      oldNo++;
      newNo++;
      lines.push({ kind: "context", text: a[i], oldNo, newNo });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      oldNo++;
      removed++;
      lines.push({ kind: "del", text: a[i], oldNo });
      i++;
    } else {
      newNo++;
      added++;
      lines.push({ kind: "add", text: b[j], newNo });
      j++;
    }
  }
  while (i < a.length) {
    oldNo++;
    removed++;
    lines.push({ kind: "del", text: a[i], oldNo });
    i++;
  }
  while (j < b.length) {
    newNo++;
    added++;
    lines.push({ kind: "add", text: b[j], newNo });
    j++;
  }

  return { lines, added, removed };
}
