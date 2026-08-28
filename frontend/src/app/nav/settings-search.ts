/**
 * The settings index's pure derivations — search, formatting, and the two
 * value transforms the palette's inline controls need.
 *
 * Deliberately free of any runtime import from the registry itself
 * (`settings-index.ts` reaches the feature data seams, and importing it here
 * would drag `createResource` fetches into every consumer, tests included).
 * Types come across with `import type`, which erases. Everything below takes its
 * entries as an argument for exactly the reason `nav/index.ts` takes its areas:
 * so the rules can be exercised against a fixture rather than against whatever
 * the real registry happens to hold today.
 */

import type {
  ChoiceSetting,
  NumberSetting,
  SettingChoice,
  SettingEntry,
  SettingValue,
} from "./types";

/** Search the settings index — label first, then keywords, then the group name.
 *  The ranking is what makes typing a setting's own name surface *it* rather
 *  than some other row that merely mentions it: "offline" is a group and a
 *  keyword on several rows, and the row actually called Offline has to win.
 *  An entry is counted once, by its strongest field. */
export function searchSettings(
  query: string,
  entries: SettingEntry[],
): SettingEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const byLabel: SettingEntry[] = [];
  const byKeyword: SettingEntry[] = [];
  const byGroup: SettingEntry[] = [];
  for (const entry of entries) {
    if (entry.label.toLowerCase().includes(q)) byLabel.push(entry);
    else if (entry.keywords.some((k) => k.toLowerCase().includes(q)))
      byKeyword.push(entry);
    else if (entry.group.toLowerCase().includes(q)) byGroup.push(entry);
  }
  return [...byLabel, ...byKeyword, ...byGroup];
}

/** The value as the row shows it on the right. `undefined` — the seam hasn't
 *  loaded — reads as a dash rather than as a made-up default: a palette that
 *  guesses "OFF" while the fetch is in flight would be lying about state the
 *  operator is about to act on. */
export function formatSettingValue(
  entry: SettingEntry,
  value: SettingValue,
): string {
  if (value === undefined) return "—";
  switch (entry.kind) {
    case "toggle":
      return value ? "ON" : "OFF";
    case "number":
      return `${value}${entry.unit ?? ""}`;
    case "choice":
      // An unrecognized value still renders as itself — the seam is the
      // authority on what it holds, and hiding a value we don't have a label
      // for would show the operator the wrong state.
      return (
        entry.options.find((o) => o.value === value)?.label ?? String(value)
      );
  }
}

/** The next option in a choice's cycle. Wraps, and starts at the first option
 *  when the current value isn't one of them (`findIndex` → -1 → 0), so a row
 *  whose seam holds something unlisted is still actionable. */
export function nextChoiceValue(
  options: readonly SettingChoice[],
  current: string | undefined,
): string | undefined {
  if (options.length === 0) return undefined;
  const i = options.findIndex((o) => o.value === current);
  return options[(i + 1) % options.length]!.value;
}

/** Parse what was typed into an inline number field.
 *
 *  `null` means "don't send it" — nothing more. This is immediate UX feedback,
 *  not enforcement: the bounds mirror what the setting's own page already tells
 *  the operator, and the backend re-validates and can still reject a value that
 *  passes here. `Number("")` is 0, so a blanked field is rejected explicitly
 *  rather than silently saved as zero. */
export function parseSettingNumber(
  entry: NumberSetting,
  raw: string,
): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  if (!Number.isInteger(n)) return null;
  if (entry.min !== undefined && n < entry.min) return null;
  if (entry.max !== undefined && n > entry.max) return null;
  return n;
}

/** Narrowing helpers — the palette row switches on `kind` in JSX, where a
 *  `switch` doesn't narrow across `<Match>` arms. */
export function isNumberSetting(entry: SettingEntry): entry is NumberSetting {
  return entry.kind === "number";
}

export function isChoiceSetting(entry: SettingEntry): entry is ChoiceSetting {
  return entry.kind === "choice";
}
